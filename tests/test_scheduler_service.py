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
    
    def test_resolve_rrule_stub(self):
        """Test resolving an RRULE schedule (currently returns None)."""
        resolver = ScheduleResolver()
        
        schedule = Schedule(
            id=1,
            kind="rrule",
            schedule_spec="FREQ=DAILY;INTERVAL=1",
            timezone="UTC"
        )
        
        result = resolver.resolve_schedule(schedule)
        assert result is None  # RRULE not implemented yet
    
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
