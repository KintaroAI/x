"""Schedule resolution service for computing next run times."""

import logging
from datetime import datetime, timedelta
from typing import Optional
from dateutil import parser as dateutil_parser
from croniter import croniter
import pytz

from src.models import Schedule

logger = logging.getLogger(__name__)


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
    
    def _resolve_rrule(self, schedule: Schedule) -> Optional[datetime]:
        """Resolve RRULE schedule (iCal recurrence rule)."""
        try:
            # For now, we'll implement a basic RRULE parser
            # In a full implementation, you'd use a library like `rrule`
            # This is a simplified version that handles basic cases
            
            logger.warning(f"RRULE parsing not fully implemented for schedule {schedule.id}")
            logger.info(f"RRULE spec: {schedule.schedule_spec}")
            
            # For now, return None to disable RRULE schedules
            # TODO: Implement proper RRULE parsing with python-dateutil or rrule library
            return None
            
        except Exception as e:
            logger.error(f"Error parsing RRULE schedule {schedule.id}: {str(e)}")
            return None


def get_next_run_time(schedule: Schedule) -> Optional[datetime]:
    """Convenience function to get next run time for a schedule."""
    resolver = ScheduleResolver()
    return resolver.resolve_schedule(schedule)
