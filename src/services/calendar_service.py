"""Calendar service for generating weekly schedule occurrences."""

import hashlib
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
import pytz
from croniter import croniter
from dateutil.rrule import rrulestr

from src.models import Schedule, Post

logger = logging.getLogger(__name__)

# Maximum occurrences to generate per schedule per week (hard cap)
MAX_OCCURRENCES_PER_SCHEDULE = 300


def get_week_boundaries(date: Optional[datetime] = None, tz: pytz.timezone = None, locale: str = 'monday') -> Tuple[datetime, datetime]:
    """
    Calculate week start and end dates based on locale.
    
    Args:
        date: Reference date (defaults to current date in timezone)
        tz: Timezone object (defaults to UTC)
        locale: Week start day ('sunday' or 'monday'), defaults to 'monday'
    
    Returns:
        Tuple of (week_start, week_end) as timezone-aware datetimes
    """
    if tz is None:
        tz = pytz.UTC
    
    if date is None:
        date = datetime.now(tz)
    elif date.tzinfo is None:
        # Assume UTC if naive
        date = pytz.UTC.localize(date)
    else:
        # Ensure date is in target timezone
        date = date.astimezone(tz)
    
    # Get the date part in local timezone
    local_date = date.date()
    
    # Calculate days from week start
    if locale == 'sunday':
        days_from_sunday = local_date.weekday() + 1  # Monday=0, so +1 to get Sunday=0
        if days_from_sunday == 7:
            days_from_sunday = 0
    else:  # monday
        days_from_sunday = local_date.weekday()  # Monday=0, Sunday=6
    
    # Calculate week start (Sunday or Monday at 00:00:00 in local timezone)
    week_start_date = local_date - timedelta(days=days_from_sunday)
    week_start = tz.localize(datetime.combine(week_start_date, datetime.min.time()))
    
    # Week end is 6 days later at 23:59:59.999999
    week_end_date = week_start_date + timedelta(days=6)
    week_end = tz.localize(datetime.combine(week_end_date, datetime.max.time().replace(microsecond=999999)))
    
    return week_start, week_end


def generate_week_occurrences(
    schedule: Schedule,
    week_start: datetime,
    week_end: datetime,
    tz: pytz.timezone,
    max_occurrences: int = MAX_OCCURRENCES_PER_SCHEDULE
) -> List[datetime]:
    """
    Generate all occurrences for a schedule within a week.
    
    Args:
        schedule: Schedule object
        week_start: Week start datetime (timezone-aware)
        week_end: Week end datetime (timezone-aware)
        tz: Target timezone for conversions
        max_occurrences: Maximum occurrences to generate (hard cap)
    
    Returns:
        List of occurrence datetimes (timezone-aware, converted to UTC for storage)
    """
    occurrences = []
    
    if schedule.kind == 'one_shot':
        # Single occurrence check
        if schedule.next_run_at:
            # Convert next_run_at (stored as naive UTC) to timezone-aware
            if schedule.next_run_at.tzinfo is None:
                next_run_utc = pytz.UTC.localize(schedule.next_run_at)
            else:
                next_run_utc = schedule.next_run_at
            
            # Check if within week bounds
            if week_start <= next_run_utc <= week_end:
                occurrences.append(next_run_utc)
    
    elif schedule.kind == 'cron':
        # Generate cron occurrences
        try:
            schedule_tz = pytz.timezone(schedule.timezone or 'UTC')
            
            # Convert week boundaries to schedule timezone
            week_start_tz = week_start.astimezone(schedule_tz)
            week_end_tz = week_end.astimezone(schedule_tz)
            
            # Create croniter starting from week_start
            cron = croniter(schedule.schedule_spec, week_start_tz)
            
            # Generate occurrences until week_end or max_occurrences
            current = cron.get_next(datetime)
            count = 0
            while current <= week_end_tz and count < max_occurrences:
                # Convert back to UTC for storage
                if current.tzinfo is None:
                    current_utc = schedule_tz.localize(current).astimezone(pytz.UTC)
                else:
                    current_utc = current.astimezone(pytz.UTC)
                
                occurrences.append(current_utc)
                count += 1
                
                # Get next occurrence if not at max
                if count < max_occurrences:
                    current = cron.get_next(datetime)
                else:
                    logger.warning(f"Schedule {schedule.id} hit max_occurrences limit ({max_occurrences}) in week {week_start} to {week_end}")
                    break
                
        except Exception as e:
            logger.error(f"Error generating cron occurrences for schedule {schedule.id}: {str(e)}")
    
    elif schedule.kind == 'rrule':
        # Generate RRULE occurrences
        try:
            schedule_tz = pytz.timezone(schedule.timezone or 'UTC')
            
            # Convert week boundaries to schedule timezone
            week_start_tz = week_start.astimezone(schedule_tz)
            week_end_tz = week_end.astimezone(schedule_tz)
            
            # Parse RRULE (similar to ScheduleResolver._parse_rrule)
            rrule_spec = schedule.schedule_spec.strip()
            
            # Get DTSTART (use created_at or current time)
            base_dtstart = schedule.created_at or datetime.utcnow()
            if base_dtstart.tzinfo is None:
                base_dtstart = pytz.UTC.localize(base_dtstart)
            base_dtstart = base_dtstart.astimezone(schedule_tz)
            
            # If RRULE doesn't include DTSTART, prepend it
            if "DTSTART" not in rrule_spec.upper():
                if base_dtstart.tzinfo == pytz.UTC or base_dtstart.tzinfo is None:
                    dtstart_str = base_dtstart.strftime("%Y%m%dT%H%M%S") + "Z"
                else:
                    dtstart_str = base_dtstart.strftime("%Y%m%dT%H%M%S%z")
                rrule_spec = f"DTSTART:{dtstart_str}\nRRULE:{rrule_spec}"
            
            # Parse RRULE
            rule = rrulestr(rrule_spec, dtstart=base_dtstart)
            
            # Generate occurrences using after() method
            current = rule.after(week_start_tz, inc=False)
            count = 0
            
            while current is not None and current <= week_end_tz and count < max_occurrences:
                # Convert back to UTC for storage
                if current.tzinfo is None:
                    current_utc = schedule_tz.localize(current).astimezone(pytz.UTC)
                else:
                    current_utc = current.astimezone(pytz.UTC)
                
                occurrences.append(current_utc)
                count += 1
                
                # Get next occurrence if not at max
                if count < max_occurrences:
                    current = rule.after(current, inc=False)
                else:
                    logger.warning(f"Schedule {schedule.id} hit max_occurrences limit ({max_occurrences}) in week {week_start} to {week_end}")
                    break
                
        except Exception as e:
            logger.error(f"Error generating rrule occurrences for schedule {schedule.id}: {str(e)}", exc_info=True)
    
    else:
        logger.warning(f"Unknown schedule kind: {schedule.kind}")
    
    return occurrences


def format_occurrence_for_calendar(
    occurrence: datetime,
    post: Post,
    schedule: Schedule,
    stack_index: int,
    display_tz: pytz.timezone
) -> Dict:
    """
    Format occurrence data for frontend calendar display.
    
    Args:
        occurrence: Occurrence datetime (UTC, timezone-aware)
        post: Post object
        schedule: Schedule object
        stack_index: Stack index for overlap handling
        display_tz: Timezone for display
    
    Returns:
        Dictionary with occurrence metadata
    """
    # Convert occurrence to display timezone
    occurrence_local = occurrence.astimezone(display_tz)
    
    # Generate occurrence_id (hash of schedule_id + scheduled_time in UTC)
    occurrence_str = f"{schedule.id}_{occurrence.isoformat()}"
    occurrence_id = hashlib.md5(occurrence_str.encode()).hexdigest()
    
    # Truncate post text for preview (first 50 characters)
    post_text_preview = post.text[:50] + ("..." if len(post.text) > 50 else "")
    
    # Default duration (30 minutes)
    duration_minutes = 30
    
    # Default status
    status = "planned"
    
    # Generate color hint (simple hash-based color)
    color_hash = hash(schedule.id) % 360
    color_hint = f"hsl({color_hash}, 70%, 50%)"
    
    return {
        "occurrence_id": occurrence_id,
        "post_id": post.id,
        "post_text_preview": post_text_preview,
        "schedule_id": schedule.id,
        "schedule_kind": schedule.kind,
        "source": schedule.kind,  # Explicit source field
        "scheduled_time": occurrence.isoformat(),  # UTC
        "scheduled_time_local": occurrence_local.isoformat(),  # Local timezone
        "duration_minutes": duration_minutes,
        "status": status,
        "color_hint": color_hint,
        "stack_index": stack_index
    }

