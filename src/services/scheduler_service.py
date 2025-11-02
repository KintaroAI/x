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
            
            # Create croniter with current time in the schedule's timezone
            now_tz = datetime.now(tz)
            cron = croniter(schedule.schedule_spec, now_tz)
            
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
