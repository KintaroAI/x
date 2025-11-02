"""Tests for scheduler service."""

import pytest
from datetime import datetime, timedelta
from unittest.mock import patch

from src.services.scheduler_service import ScheduleResolver, get_next_run_time
from src.models import Schedule


@pytest.mark.unit
class TestScheduleResolver:
    """Test cases for ScheduleResolver class."""
    
    def test_resolve_one_shot_future(self):
        """Test resolving a one-shot schedule in the future."""
        resolver = ScheduleResolver()
        
        future_time = datetime.utcnow() + timedelta(minutes=10)
        schedule = Schedule(
            id=1,
            kind="one_shot",
            schedule_spec=future_time.isoformat(),
            timezone="UTC"
        )
        
        result = resolver.resolve_schedule(schedule)
        assert result is not None
        assert result == future_time
    
    def test_resolve_one_shot_past(self):
        """Test resolving a one-shot schedule in the past."""
        resolver = ScheduleResolver()
        
        past_time = datetime.utcnow() - timedelta(minutes=10)
        schedule = Schedule(
            id=1,
            kind="one_shot",
            schedule_spec=past_time.isoformat(),
            timezone="UTC"
        )
        
        result = resolver.resolve_schedule(schedule)
        assert result is None
    
    def test_resolve_cron_schedule(self):
        """Test resolving a cron schedule."""
        resolver = ScheduleResolver()
        
        schedule = Schedule(
            id=1,
            kind="cron",
            schedule_spec="0 */2 * * *",  # Every 2 hours
            timezone="UTC"
        )
        
        result = resolver.resolve_schedule(schedule)
        assert result is not None
        assert isinstance(result, datetime)
        assert result > datetime.utcnow()
    
    def test_resolve_cron_with_timezone(self):
        """Test resolving a cron schedule with timezone."""
        resolver = ScheduleResolver()
        
        schedule = Schedule(
            id=1,
            kind="cron",
            schedule_spec="0 9 * * *",  # 9 AM daily
            timezone="America/New_York"
        )
        
        result = resolver.resolve_schedule(schedule)
        assert result is not None
        assert isinstance(result, datetime)
        assert result > datetime.utcnow()
    
    def test_resolve_rrule_daily(self):
        """Test resolving a daily RRULE schedule."""
        resolver = ScheduleResolver()
        
        schedule = Schedule(
            id=1,
            kind="rrule",
            schedule_spec="FREQ=DAILY;INTERVAL=1",
            timezone="UTC",
            created_at=datetime.utcnow() - timedelta(days=1)
        )
        
        result = resolver.resolve_schedule(schedule)
        assert result is not None
        assert isinstance(result, datetime)
        assert result > datetime.utcnow()
        # Should be within 24 hours
        assert result <= datetime.utcnow() + timedelta(days=1)
    
    def test_resolve_rrule_weekly(self):
        """Test resolving a weekly RRULE schedule."""
        resolver = ScheduleResolver()
        
        schedule = Schedule(
            id=2,
            kind="rrule",
            schedule_spec="FREQ=WEEKLY;BYDAY=MO,WE,FR",
            timezone="UTC",
            created_at=datetime.utcnow() - timedelta(days=7)
        )
        
        result = resolver.resolve_schedule(schedule)
        assert result is not None
        assert isinstance(result, datetime)
        assert result > datetime.utcnow()
    
    def test_resolve_rrule_monthly(self):
        """Test resolving a monthly RRULE schedule."""
        resolver = ScheduleResolver()
        
        schedule = Schedule(
            id=3,
            kind="rrule",
            schedule_spec="FREQ=MONTHLY;BYMONTHDAY=1",
            timezone="UTC",
            created_at=datetime.utcnow() - timedelta(days=30)
        )
        
        result = resolver.resolve_schedule(schedule)
        assert result is not None
        assert isinstance(result, datetime)
        assert result > datetime.utcnow()
    
    def test_resolve_rrule_with_bysetpos(self):
        """Test resolving RRULE with BYSETPOS (last Friday of month)."""
        resolver = ScheduleResolver()
        
        schedule = Schedule(
            id=4,
            kind="rrule",
            schedule_spec="FREQ=MONTHLY;BYDAY=FR;BYSETPOS=-1",
            timezone="UTC",
            created_at=datetime.utcnow() - timedelta(days=30)
        )
        
        result = resolver.resolve_schedule(schedule)
        assert result is not None
        assert isinstance(result, datetime)
        assert result > datetime.utcnow()
    
    def test_resolve_rrule_with_time_constraints(self):
        """Test resolving RRULE with BYHOUR/BYMINUTE."""
        resolver = ScheduleResolver()
        
        # Schedule for 9 AM daily
        schedule = Schedule(
            id=5,
            kind="rrule",
            schedule_spec="FREQ=DAILY;BYHOUR=9;BYMINUTE=0",
            timezone="UTC",
            created_at=datetime.utcnow() - timedelta(days=1)
        )
        
        result = resolver.resolve_schedule(schedule)
        assert result is not None
        assert isinstance(result, datetime)
        assert result > datetime.utcnow()
        # Check hour is 9 (in UTC)
        assert result.hour == 9
    
    def test_resolve_rrule_with_timezone(self):
        """Test resolving RRULE with timezone."""
        resolver = ScheduleResolver()
        
        schedule = Schedule(
            id=6,
            kind="rrule",
            schedule_spec="FREQ=DAILY;BYHOUR=9;BYMINUTE=0",
            timezone="America/New_York",
            created_at=datetime.utcnow() - timedelta(days=1)
        )
        
        result = resolver.resolve_schedule(schedule)
        assert result is not None
        assert isinstance(result, datetime)
        assert result > datetime.utcnow()
    
    def test_resolve_rrule_with_count(self):
        """Test resolving RRULE with COUNT limit."""
        resolver = ScheduleResolver()
        
        # Create a schedule that runs 5 times
        schedule = Schedule(
            id=7,
            kind="rrule",
            schedule_spec="FREQ=DAILY;INTERVAL=1;COUNT=5",
            timezone="UTC",
            created_at=datetime.utcnow() - timedelta(days=10)  # 10 days ago
        )
        
        # First few calls should work
        for i in range(5):
            result = resolver.resolve_schedule(schedule)
            if result:
                # Update last_run_at to simulate execution
                schedule.last_run_at = result
            else:
                # Should return None after COUNT is exhausted
                break
        
        # After COUNT is exhausted, should return None
        result = resolver.resolve_schedule(schedule)
        assert result is None
    
    def test_resolve_rrule_invalid_format(self):
        """Test resolving an invalid RRULE format."""
        resolver = ScheduleResolver()
        
        schedule = Schedule(
            id=8,
            kind="rrule",
            schedule_spec="INVALID_RRULE_FORMAT",
            timezone="UTC"
        )
        
        result = resolver.resolve_schedule(schedule)
        assert result is None
    
    def test_resolve_rrule_invalid_component(self):
        """Test resolving RRULE with invalid component."""
        resolver = ScheduleResolver()
        
        schedule = Schedule(
            id=9,
            kind="rrule",
            schedule_spec="FREQ=DAILY;INVALIDCOMPONENT=123",
            timezone="UTC"
        )
        
        result = resolver.resolve_schedule(schedule)
        assert result is None
    
    def test_resolve_rrule_too_large(self):
        """Test resolving RRULE that exceeds size limit."""
        resolver = ScheduleResolver()
        
        # Create an RRULE string that's too large
        large_spec = "FREQ=DAILY;" + "A" * 5000
        schedule = Schedule(
            id=10,
            kind="rrule",
            schedule_spec=large_spec,
            timezone="UTC"
        )
        
        result = resolver.resolve_schedule(schedule)
        assert result is None
    
    def test_resolve_unknown_kind(self):
        """Test resolving an unknown schedule kind."""
        resolver = ScheduleResolver()
        
        schedule = Schedule(
            id=1,
            kind="unknown",
            schedule_spec="some spec",
            timezone="UTC"
        )
        
        result = resolver.resolve_schedule(schedule)
        assert result is None
    
    def test_resolve_invalid_one_shot(self):
        """Test resolving an invalid one-shot schedule."""
        resolver = ScheduleResolver()
        
        schedule = Schedule(
            id=1,
            kind="one_shot",
            schedule_spec="invalid datetime",
            timezone="UTC"
        )
        
        result = resolver.resolve_schedule(schedule)
        assert result is None
    
    def test_resolve_invalid_cron(self):
        """Test resolving an invalid cron schedule."""
        resolver = ScheduleResolver()
        
        schedule = Schedule(
            id=1,
            kind="cron",
            schedule_spec="invalid cron",
            timezone="UTC"
        )
        
        result = resolver.resolve_schedule(schedule)
        assert result is None


@pytest.mark.unit
class TestGetNextRunTime:
    """Test cases for get_next_run_time convenience function."""
    
    def test_get_next_run_time_one_shot(self):
        """Test get_next_run_time with one-shot schedule."""
        future_time = datetime.utcnow() + timedelta(minutes=5)
        schedule = Schedule(
            id=1,
            kind="one_shot",
            schedule_spec=future_time.isoformat(),
            timezone="UTC"
        )
        
        result = get_next_run_time(schedule)
        assert result == future_time
    
    def test_get_next_run_time_cron(self):
        """Test get_next_run_time with cron schedule."""
        schedule = Schedule(
            id=1,
            kind="cron",
            schedule_spec="0 */1 * * *",  # Every hour
            timezone="UTC"
        )
        
        result = get_next_run_time(schedule)
        assert result is not None
        assert isinstance(result, datetime)
        assert result > datetime.utcnow()
