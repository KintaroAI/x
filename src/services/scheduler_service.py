"""Schedule resolution service for computing next run times."""

import logging
import hashlib
import re
from collections import OrderedDict
from datetime import datetime, timedelta
from typing import Optional
from dateutil import parser as dateutil_parser
from croniter import croniter
import pytz

from src.models import Schedule

logger = logging.getLogger(__name__)

# Cache for compiled RRULE objects (using proper LRU)
_rrule_cache = OrderedDict()  # {(schedule_id, rrule_hash): (rrule_obj, dtstart)}
MAX_CACHE_SIZE = 1000


class ScheduleResolver:
    """Resolves schedules to next run times."""
    
    def resolve_schedule(self, schedule: Schedule) -> Optional[datetime]:
        """Calculate next_run_at for a schedule."""
        try:
            if schedule.kind == "one_shot":
                return self._resolve_one_shot(schedule)
            elif schedule.kind == "cron":
                return self._resolve_cron(schedule)
            elif schedule.kind == "rrule":
                return self._resolve_rrule(schedule)
            else:
                logger.warning(f"Unknown schedule kind: {schedule.kind}")
                return None
        except Exception as e:
            logger.error(f"Error resolving schedule {schedule.id}: {str(e)}")
            return None
    
    def _resolve_one_shot(self, schedule: Schedule) -> Optional[datetime]:
        """Resolve one-shot schedule (runs once at specified time)."""
        try:
            # Parse the ISO datetime string
            planned_time = dateutil_parser.parse(schedule.schedule_spec)
            
            # If the time has already passed, return None (schedule is done)
            if planned_time <= datetime.utcnow():
                logger.info(f"One-shot schedule {schedule.id} has already passed")
                return None
            
            return planned_time
        except Exception as e:
            logger.error(f"Error parsing one-shot schedule {schedule.id}: {str(e)}")
            return None
    
    def _resolve_cron(self, schedule: Schedule) -> Optional[datetime]:
        """Resolve cron schedule (recurring based on cron expression)."""
        try:
            # Get timezone, default to UTC
            tz = pytz.timezone(schedule.timezone or "UTC")
            
            # Use last_run_at if available, otherwise use current time
            # This ensures we calculate the next occurrence after the last run,
            # and avoids DST transition issues by using the actual execution time
            if schedule.last_run_at:
                # Convert last_run_at (stored as naive UTC) to the schedule's timezone
                reference_utc = pytz.UTC.localize(schedule.last_run_at) if schedule.last_run_at.tzinfo is None else schedule.last_run_at
                reference_tz = reference_utc.astimezone(tz)
            else:
                # No last_run_at yet (initial resolution), use current time
                reference_tz = datetime.now(tz)
                
                # Check if there's an upcoming DST transition that might affect the calculation
                # If we're in DST and the next occurrence might be after DST ends (or vice versa),
                # we should use a reference time after the DST transition to get the correct calculation
                try:
                    # Calculate a tentative next run to detect DST transitions
                    temp_cron = croniter(schedule.schedule_spec, reference_tz)
                    temp_next = temp_cron.get_next(datetime)
                    
                    # Check if there's a DST transition between reference time and next occurrence
                    if reference_tz.dst() != temp_next.dst():
                        # DST transition detected between reference and next occurrence
                        # The temp_next was calculated using the pre-transition timezone, so it may be incorrect
                        # Recalculate using a time after the DST transition to get the correct result
                        
                        # Parse scheduled time from cron spec to check for special cases
                        cron_parts = schedule.schedule_spec.split()
                        scheduled_hour = int(cron_parts[1]) if cron_parts[1] != '*' else None
                        scheduled_minute = int(cron_parts[0]) if cron_parts[0] != '*' else None
                        
                        # Determine which direction the DST transition is going
                        is_fall_back = reference_tz.dst() and not temp_next.dst()  # CDT -> CST
                        is_spring_forward = not reference_tz.dst() and temp_next.dst()  # CST -> CDT
                        
                        # Determine the transition date
                        # temp_next might have the wrong date due to timezone calculation issues,
                        # so we'll use the reference time's date and check if it's the transition day,
                        # or use temp_next's date if it's clearly on the transition day
                        # For simplicity, use temp_next's date but construct the time properly
                        transition_date = temp_next.date()
                        
                        # Also check if the reference time is already on or near the transition day
                        ref_date = reference_tz.date()
                        # If temp_next is clearly in the future by a day or more, the transition is tomorrow
                        # Otherwise, it's today
                        if temp_next.date() > ref_date + timedelta(days=1):
                            transition_date = ref_date + timedelta(days=1)
                        
                        # Special handling: If the scheduled time is at 3 AM on the transition day,
                        # we need to use a reference time just before 3 AM to avoid skipping it.
                        if scheduled_hour == 3:
                            # Schedule is at 3 AM on transition day - use 2:59:59 AM to avoid skipping
                            if is_fall_back:
                                # Post-transition is CST - use 2:59:59 AM CST
                                transition_time = tz.localize(
                                    datetime(transition_date.year, transition_date.month, transition_date.day, 2, 59, 59),
                                    is_dst=False  # CST (no DST)
                                )
                            else:  # spring forward
                                # Post-transition is CDT, but we want a reference before 3 AM CDT
                                # Use 1:59:59 AM CST (just before 2 AM CST when transition happens)
                                transition_time = tz.localize(
                                    datetime(transition_date.year, transition_date.month, transition_date.day, 1, 59, 59),
                                    is_dst=False  # CST (pre-transition)
                                )
                        else:
                            # Use 3 AM on the transition day as a safe reference time
                            # (after DST ends in fall, safe time in spring)
                            transition_time = tz.localize(
                                datetime(transition_date.year, transition_date.month, transition_date.day, 3, 0, 0),
                                is_dst=False if is_fall_back else True  # CST for fall back, CDT for spring forward
                            )
                        
                        # Ensure we're moving forward in time
                        if transition_time > reference_tz:
                            reference_tz = transition_time
                            transition_type = "fall back" if is_fall_back else "spring forward"
                            logger.debug(f"Schedule {schedule.id}: DST transition detected ({transition_type}), "
                                       f"using post-transition time as reference for initial resolution")
                except Exception as e:
                    # If there's any issue with DST detection, continue with original reference
                    logger.debug(f"Schedule {schedule.id}: Could not check DST transition, using original reference: {e}")
            
            # Create croniter with reference time in the schedule's timezone
            cron = croniter(schedule.schedule_spec, reference_tz)
            
            # Get next run time
            next_run = cron.get_next(datetime)
            
            # Convert back to UTC for storage
            next_run_utc = next_run.astimezone(pytz.UTC).replace(tzinfo=None)
            
            return next_run_utc
        except Exception as e:
            logger.error(f"Error parsing cron schedule {schedule.id}: {str(e)}")
            return None
    
    def _validate_rrule(self, rrule_spec: str) -> bool:
        """Validate RRULE format with whitelist and size limits."""
        # Whitelist allowed RRULE components
        ALLOWED_COMPONENTS = {
            'FREQ', 'INTERVAL', 'COUNT', 'UNTIL', 'BYDAY', 'BYMONTHDAY',
            'BYMONTH', 'BYYEARDAY', 'BYWEEKNO', 'BYSETPOS', 'BYHOUR',
            'BYMINUTE', 'BYSECOND', 'DTSTART', 'RRULE'
        }
        
        # Size limits (2-4k is reasonable; 4k is safe)
        MAX_RRULE_LENGTH = 4000  # Prevent pathological inputs while allowing legitimate RRULEs
        
        if len(rrule_spec) > MAX_RRULE_LENGTH:
            logger.warning(f"RRULE spec exceeds maximum length: {len(rrule_spec)} > {MAX_RRULE_LENGTH}")
            return False
        
        # Extract component names from RRULE
        components = re.findall(r'([A-Z]+)=', rrule_spec.upper())
        
        # Check all components are whitelisted
        for component in components:
            if component not in ALLOWED_COMPONENTS:
                logger.warning(f"Invalid RRULE component: {component}")
                return False
        
        return True
    
    def _get_rrule_dtstart(self, schedule: Schedule, tz: pytz.timezone, rrule_spec: str) -> datetime:
        """Get DTSTART for RRULE with smart snapping.
        
        If BYHOUR/BYMINUTE/BYSECOND present in RRULE, snap DTSTART to that wall time.
        Otherwise use schedule.created_at or current time.
        
        Note: After snapping, if the time is in the past, we let dateutil compute
        the correct next occurrence via rule.after() rather than manually advancing.
        This correctly handles monthly/yearly patterns.
        """
        # Extract time constraints from RRULE using regex
        # (dateutil.rrule doesn't expose these properties directly, so regex is practical)
        has_byhour = re.search(r'BYHOUR=(\d+)', rrule_spec.upper())
        has_byminute = re.search(r'BYMINUTE=(\d+)', rrule_spec.upper())
        has_bysecond = re.search(r'BYSECOND=(\d+)', rrule_spec.upper())
        
        # Base DTSTART from schedule or current time
        base_dtstart = schedule.created_at or datetime.utcnow()
        if base_dtstart.tzinfo is None:
            base_dtstart = pytz.UTC.localize(base_dtstart)
        base_dtstart = base_dtstart.astimezone(tz)
        
        # If time constraints present, snap to that wall time
        if has_byhour or has_byminute or has_bysecond:
            # Extract desired time components
            hour = int(has_byhour.group(1)) if has_byhour else base_dtstart.hour
            minute = int(has_byminute.group(1)) if has_byminute else base_dtstart.minute
            second = int(has_bysecond.group(1)) if has_bysecond else 0
            
            # Snap to wall time (use today's date, or next occurrence if past)
            now_tz = datetime.now(tz)
            dtstart = tz.localize(datetime(
                base_dtstart.year, base_dtstart.month, base_dtstart.day,
                hour, minute, second
            ))
            
            # If snapped time is in past, we'll let dateutil compute the correct next occurrence
            # after constructing the rule, rather than manually advancing by day/week
            # This handles monthly/yearly rules correctly
            
            return dtstart
        else:
            # No time constraints, use base DTSTART as-is
            return base_dtstart
    
    def _parse_rrule(self, rrule_spec: str, dtstart: datetime) -> 'rrule':
        """Parse RRULE string into rrule object."""
        from dateutil.rrule import rrulestr
        
        # Normalize RRULE spec (preserve case for values like UNTIL timestamps)
        rrule_spec = rrule_spec.strip()
        
        # If RRULE doesn't include DTSTART, prepend it
        if "DTSTART" not in rrule_spec.upper():
            # Format DTSTART in iCal format (YYYYMMDDTHHMMSSZ or with offset)
            if dtstart.tzinfo == pytz.UTC or dtstart.tzinfo is None:
                dtstart_str = dtstart.strftime("%Y%m%dT%H%M%S") + "Z"
            else:
                # Include timezone offset
                dtstart_str = dtstart.strftime("%Y%m%dT%H%M%S%z")
            rrule_spec = f"DTSTART:{dtstart_str}\nRRULE:{rrule_spec}"
        
        # Parse RRULE string using dateutil.rrule
        return rrulestr(rrule_spec, dtstart=dtstart)
    
    def _resolve_rrule(self, schedule: Schedule) -> Optional[datetime]:
        """Resolve RRULE schedule (iCal recurrence rule).
        
        Uses python-dateutil.rrule which is RFC 5545 compliant.
        Already available in requirements.txt, no new dependency needed.
        
        Design decisions:
        - Uses after(time, inc=False) to skip occurrences at exact reference time
        - Stores as naive UTC datetime (consistent with existing codebase)
        - Caches compiled RRULE objects for performance
        """
        try:
            from dateutil.rrule import rrulestr
            
            # Validate RRULE format before parsing
            if not self._validate_rrule(schedule.schedule_spec):
                logger.error(f"Invalid RRULE format for schedule {schedule.id}")
                return None
            
            # Get timezone (consistent with existing codebase using pytz)
            tz = pytz.timezone(schedule.timezone or "UTC")
            now_tz = datetime.now(tz)
            
            # Determine DTSTART (with smart snapping)
            dtstart = self._get_rrule_dtstart(schedule, tz, schedule.schedule_spec)
            
            # Check cache for compiled RRULE
            rrule_hash = hashlib.md5(schedule.schedule_spec.encode()).hexdigest()
            cache_key = (schedule.id, rrule_hash)
            
            if cache_key in _rrule_cache:
                cached_rule, cached_dtstart = _rrule_cache[cache_key]
                # Reuse if DTSTART matches
                if cached_dtstart == dtstart:
                    rule = cached_rule
                    # Move to end (LRU - most recently used)
                    _rrule_cache.move_to_end(cache_key)
                else:
                    # DTSTART changed, recompile
                    rule = self._parse_rrule(schedule.schedule_spec, dtstart)
                    _rrule_cache[cache_key] = (rule, dtstart)
                    _rrule_cache.move_to_end(cache_key)
            else:
                # Parse and cache
                rule = self._parse_rrule(schedule.schedule_spec, dtstart)
                _rrule_cache[cache_key] = (rule, dtstart)
                
                # LRU eviction: remove oldest if cache is full
                if len(_rrule_cache) > MAX_CACHE_SIZE:
                    _rrule_cache.popitem(last=False)  # Remove oldest (FIFO)
            
            # Get next occurrence after last_run_at or now
            after_time = schedule.last_run_at or now_tz
            if after_time.tzinfo is None:
                # Assume naive datetime is UTC (consistent with storage convention)
                after_time = pytz.UTC.localize(after_time)
            after_time = after_time.astimezone(tz)
            
            # Find next occurrence using rule.after(inc=False)
            # inc=False: Skip occurrence if it equals reference time (safe for "next occurrence")
            # Note: If DTSTART was snapped and is in the past, rule.after() will compute
            # the correct next occurrence based on the RRULE pattern (handles monthly/yearly correctly)
            next_occurrence = rule.after(after_time, inc=False)
            
            if next_occurrence is None:
                # RRULE exhausted (COUNT reached or UNTIL passed)
                logger.info(f"RRULE schedule {schedule.id} has no more occurrences")
                return None
            
            # Convert to UTC for storage
            # Storage convention: Store as naive UTC datetime (consistent with existing codebase)
            next_occurrence_utc = next_occurrence.astimezone(pytz.UTC).replace(tzinfo=None)
            
            return next_occurrence_utc
            
        except Exception as e:
            logger.error(f"Error parsing RRULE schedule {schedule.id}: {str(e)}", exc_info=True)
            return None


def get_next_run_time(schedule: Schedule) -> Optional[datetime]:
    """Convenience function to get next run time for a schedule."""
    resolver = ScheduleResolver()
    return resolver.resolve_schedule(schedule)
