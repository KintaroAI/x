"""Unit tests for calendar service functions."""

import pytest
from datetime import datetime, timedelta
import pytz

from src.services.calendar_service import (
    get_week_boundaries,
    generate_week_occurrences,
    format_occurrence_for_calendar,
    MAX_OCCURRENCES_PER_SCHEDULE
)
from src.models import Schedule, Post


@pytest.mark.unit
class TestGetWeekBoundaries:
    """Test cases for get_week_boundaries function."""
    
    def test_week_boundaries_monday_locale(self):
        """Test week boundaries with Monday locale."""
        tz = pytz.UTC
        date = datetime(2024, 1, 15, 12, 0, 0, tzinfo=tz)  # Monday, Jan 15
        
        week_start, week_end = get_week_boundaries(date, tz, 'monday')
        
        # Monday Jan 15 should be the start of the week
        assert week_start.date() == datetime(2024, 1, 15).date()
        assert week_end.date() == datetime(2024, 1, 21).date()
        assert week_start.hour == 0
        assert week_start.minute == 0
        assert week_end.hour == 23
        assert week_end.minute == 59
    
    def test_week_boundaries_sunday_locale(self):
        """Test week boundaries with Sunday locale."""
        tz = pytz.UTC
        date = datetime(2024, 1, 15, 12, 0, 0, tzinfo=tz)  # Monday, Jan 15
        
        week_start, week_end = get_week_boundaries(date, tz, 'sunday')
        
        # Sunday Jan 14 should be the start of the week
        assert week_start.date() == datetime(2024, 1, 14).date()
        assert week_end.date() == datetime(2024, 1, 20).date()
    
    def test_week_boundaries_sunday_day(self):
        """Test week boundaries when date is a Sunday."""
        tz = pytz.UTC
        date = datetime(2024, 1, 14, 12, 0, 0, tzinfo=tz)  # Sunday, Jan 14
        
        # With Sunday locale, Sunday should be week start
        week_start, week_end = get_week_boundaries(date, tz, 'sunday')
        assert week_start.date() == datetime(2024, 1, 14).date()
        assert week_end.date() == datetime(2024, 1, 20).date()
        
        # With Monday locale, week starts on Monday Jan 8
        week_start, week_end = get_week_boundaries(date, tz, 'monday')
        assert week_start.date() == datetime(2024, 1, 8).date()
        assert week_end.date() == datetime(2024, 1, 14).date()
    
    def test_week_boundaries_default_current_week(self):
        """Test week boundaries with default (current week)."""
        tz = pytz.UTC
        week_start, week_end = get_week_boundaries(None, tz, 'monday')
        
        # Should return current week boundaries
        assert week_start < week_end
        assert (week_end - week_start).days == 6
        assert week_start.hour == 0
        assert week_end.hour == 23
    
    def test_week_boundaries_timezone_conversion(self):
        """Test week boundaries with different timezone."""
        tz = pytz.timezone('America/Chicago')
        date = datetime(2024, 1, 15, 12, 0, 0, tzinfo=pytz.UTC)
        
        week_start, week_end = get_week_boundaries(date, tz, 'monday')
        
        # Week start should be in Chicago timezone (check by string comparison)
        assert str(week_start.tzinfo) == str(tz) or week_start.tzinfo.zone == tz.zone
        assert str(week_end.tzinfo) == str(tz) or week_end.tzinfo.zone == tz.zone


@pytest.mark.unit
class TestGenerateWeekOccurrences:
    """Test cases for generate_week_occurrences function."""
    
    def test_one_shot_within_week(self):
        """Test one_shot schedule with next_run_at within week."""
        tz = pytz.UTC
        week_start = datetime(2024, 1, 15, 0, 0, 0, tzinfo=tz)
        week_end = datetime(2024, 1, 21, 23, 59, 59, tzinfo=tz)
        
        next_run = datetime(2024, 1, 18, 12, 0, 0)  # Naive UTC
        schedule = Schedule(
            id=1,
            kind="one_shot",
            schedule_spec=next_run.isoformat(),
            timezone="UTC",
            next_run_at=next_run,
            enabled=True,
            created_at=datetime.utcnow()
        )
        
        occurrences = generate_week_occurrences(schedule, week_start, week_end, tz)
        
        assert len(occurrences) == 1
        assert occurrences[0].date() == next_run.date()
        assert occurrences[0].hour == 12
    
    def test_one_shot_outside_week(self):
        """Test one_shot schedule with next_run_at outside week."""
        tz = pytz.UTC
        week_start = datetime(2024, 1, 15, 0, 0, 0, tzinfo=tz)
        week_end = datetime(2024, 1, 21, 23, 59, 59, tzinfo=tz)
        
        next_run = datetime(2024, 1, 22, 12, 0, 0)  # After week_end
        schedule = Schedule(
            id=1,
            kind="one_shot",
            schedule_spec=next_run.isoformat(),
            timezone="UTC",
            next_run_at=next_run,
            enabled=True,
            created_at=datetime.utcnow()
        )
        
        occurrences = generate_week_occurrences(schedule, week_start, week_end, tz)
        
        assert len(occurrences) == 0
    
    def test_cron_daily_within_week(self):
        """Test cron schedule generating daily occurrences."""
        tz = pytz.UTC
        week_start = datetime(2024, 1, 15, 0, 0, 0, tzinfo=tz)  # Monday
        week_end = datetime(2024, 1, 21, 23, 59, 59, tzinfo=tz)  # Sunday
        
        schedule = Schedule(
            id=1,
            kind="cron",
            schedule_spec="0 9 * * *",  # Daily at 9 AM
            timezone="UTC",
            enabled=True,
            created_at=datetime.utcnow()
        )
        
        occurrences = generate_week_occurrences(schedule, week_start, week_end, tz)
        
        # Should generate 7 occurrences (one per day)
        assert len(occurrences) == 7
        assert all(occ.hour == 9 for occ in occurrences)
        assert all(occ.minute == 0 for occ in occurrences)
        # Check all occurrences are within week
        assert all(week_start <= occ <= week_end for occ in occurrences)
    
    def test_cron_hourly_capped(self):
        """Test cron schedule that would exceed 300 occurrences cap."""
        tz = pytz.UTC
        week_start = datetime(2024, 1, 15, 0, 0, 0, tzinfo=tz)
        week_end = datetime(2024, 1, 21, 23, 59, 59, tzinfo=tz)
        
        schedule = Schedule(
            id=1,
            kind="cron",
            schedule_spec="*/5 * * * *",  # Every 5 minutes
            timezone="UTC",
            enabled=True,
            created_at=datetime.utcnow()
        )
        
        occurrences = generate_week_occurrences(schedule, week_start, week_end, tz)
        
        # Should be capped at 300 occurrences
        assert len(occurrences) <= MAX_OCCURRENCES_PER_SCHEDULE
        assert len(occurrences) == MAX_OCCURRENCES_PER_SCHEDULE
    
    def test_rrule_daily_within_week(self):
        """Test RRULE schedule generating daily occurrences."""
        tz = pytz.UTC
        week_start = datetime(2024, 1, 15, 0, 0, 0, tzinfo=tz)
        week_end = datetime(2024, 1, 21, 23, 59, 59, tzinfo=tz)
        
        # Set created_at to before week_start so RRULE can generate occurrences
        schedule = Schedule(
            id=1,
            kind="rrule",
            schedule_spec="FREQ=DAILY;BYHOUR=10;BYMINUTE=30",
            timezone="UTC",
            enabled=True,
            created_at=datetime(2024, 1, 1, 0, 0, 0)  # Before week_start
        )
        
        occurrences = generate_week_occurrences(schedule, week_start, week_end, tz)
        
        # Should generate 7 occurrences (one per day)
        assert len(occurrences) >= 7
        # Check occurrences are within week
        assert all(week_start <= occ <= week_end for occ in occurrences)
    
    def test_rrule_with_count(self):
        """Test RRULE schedule with COUNT limit."""
        tz = pytz.UTC
        week_start = datetime(2024, 1, 15, 0, 0, 0, tzinfo=tz)
        week_end = datetime(2024, 1, 21, 23, 59, 59, tzinfo=tz)
        
        schedule = Schedule(
            id=1,
            kind="rrule",
            schedule_spec="FREQ=HOURLY;COUNT=5",  # Only 5 occurrences
            timezone="UTC",
            enabled=True,
            created_at=datetime.utcnow()
        )
        
        occurrences = generate_week_occurrences(schedule, week_start, week_end, tz)
        
        # Should generate at most 5 occurrences (limited by COUNT)
        assert len(occurrences) <= 5
    
    def test_rrule_capped_at_300(self):
        """Test RRULE that would exceed 300 occurrences cap."""
        tz = pytz.UTC
        week_start = datetime(2024, 1, 15, 0, 0, 0, tzinfo=tz)
        week_end = datetime(2024, 1, 21, 23, 59, 59, tzinfo=tz)
        
        # Set created_at to before week_start so RRULE can generate occurrences
        schedule = Schedule(
            id=1,
            kind="rrule",
            schedule_spec="FREQ=MINUTELY;INTERVAL=5",  # Every 5 minutes
            timezone="UTC",
            enabled=True,
            created_at=datetime(2024, 1, 1, 0, 0, 0)  # Before week_start
        )
        
        occurrences = generate_week_occurrences(schedule, week_start, week_end, tz)
        
        # Should be capped at 300 occurrences
        assert len(occurrences) <= MAX_OCCURRENCES_PER_SCHEDULE
        assert len(occurrences) == MAX_OCCURRENCES_PER_SCHEDULE


@pytest.mark.unit
class TestFormatOccurrenceForCalendar:
    """Test cases for format_occurrence_for_calendar function."""
    
    def test_format_occurrence_basic(self):
        """Test basic occurrence formatting."""
        tz = pytz.UTC
        occurrence = datetime(2024, 1, 18, 12, 30, 0, tzinfo=pytz.UTC)
        
        post = Post(
            id=1,
            text="Test post content that is longer than 50 characters so we can test truncation",
            media_refs=None,
            deleted=False,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        
        schedule = Schedule(
            id=5,
            kind="cron",
            schedule_spec="0 12 * * *",
            timezone="UTC",
            enabled=True,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        
        result = format_occurrence_for_calendar(occurrence, post, schedule, 0, tz)
        
        assert result['occurrence_id'] is not None
        assert result['post_id'] == 1
        assert len(result['post_text_preview']) <= 53  # 50 chars + "..."
        assert result['schedule_id'] == 5
        assert result['schedule_kind'] == 'cron'
        assert result['source'] == 'cron'
        assert result['duration_minutes'] == 30
        assert result['status'] == 'planned'
        assert result['color_hint'] is not None
        assert result['stack_index'] == 0
    
    def test_format_occurrence_text_truncation(self):
        """Test text truncation for long posts."""
        tz = pytz.UTC
        occurrence = datetime(2024, 1, 18, 12, 0, 0, tzinfo=pytz.UTC)
        
        # Short text (should not truncate)
        post_short = Post(
            id=1,
            text="Short text",
            media_refs=None,
            deleted=False,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        
        schedule = Schedule(id=1, kind="one_shot", schedule_spec="", timezone="UTC", enabled=True, created_at=datetime.utcnow())
        
        result_short = format_occurrence_for_calendar(occurrence, post_short, schedule, 0, tz)
        assert result_short['post_text_preview'] == "Short text"
        
        # Long text (should truncate)
        post_long = Post(
            id=2,
            text="A" * 100,  # 100 characters
            media_refs=None,
            deleted=False,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        
        result_long = format_occurrence_for_calendar(occurrence, post_long, schedule, 0, tz)
        assert len(result_long['post_text_preview']) == 53  # 50 + "..."
        assert result_long['post_text_preview'].endswith("...")


@pytest.mark.unit
class TestDSTHandling:
    """Test cases for DST transition handling."""
    
    def test_week_boundaries_dst_spring_forward(self):
        """Test week boundaries during spring forward DST transition."""
        # Spring forward in America/Chicago is typically 2 AM on second Sunday in March
        # In 2024, it's March 10
        tz = pytz.timezone('America/Chicago')
        date = datetime(2024, 3, 12, 12, 0, 0)  # Tuesday after spring forward
        date = tz.localize(date)
        
        week_start, week_end = get_week_boundaries(date, tz, 'monday')
        
        # Week should span March 11-17 (Monday-Sunday)
        assert week_start.date() == datetime(2024, 3, 11).date()
        assert week_end.date() == datetime(2024, 3, 17).date()
    
    def test_week_boundaries_dst_fall_back(self):
        """Test week boundaries during fall back DST transition."""
        # Fall back in America/Chicago is typically 2 AM on first Sunday in November
        # In 2024, it's November 3
        tz = pytz.timezone('America/Chicago')
        date = datetime(2024, 11, 5, 12, 0, 0)  # Tuesday after fall back
        date = tz.localize(date)
        
        week_start, week_end = get_week_boundaries(date, tz, 'monday')
        
        # Week should span November 4-10 (Monday-Sunday)
        assert week_start.date() == datetime(2024, 11, 4).date()
        assert week_end.date() == datetime(2024, 11, 10).date()
    
    def test_cron_during_dst_transition(self):
        """Test cron schedule during DST transition."""
        tz = pytz.timezone('America/Chicago')
        # Week that includes spring forward (March 10, 2024)
        week_start = tz.localize(datetime(2024, 3, 11, 0, 0, 0))  # Monday
        week_end = tz.localize(datetime(2024, 3, 17, 23, 59, 59))  # Sunday
        
        schedule = Schedule(
            id=1,
            kind="cron",
            schedule_spec="0 9 * * *",  # Daily at 9 AM
            timezone="America/Chicago",
            enabled=True,
            created_at=datetime.utcnow()
        )
        
        occurrences = generate_week_occurrences(schedule, week_start, week_end, tz)
        
        # Should generate occurrences despite DST transition
        assert len(occurrences) >= 6  # At least 6 days (some may be skipped)
        # All occurrences should be in Chicago timezone
        assert all(occ.tzinfo == pytz.UTC for occ in occurrences)  # Stored as UTC


@pytest.mark.unit
class TestTimezoneConversions:
    """Test cases for timezone conversions."""
    
    def test_occurrence_timezone_conversion(self):
        """Test occurrence generation with different timezone."""
        tz = pytz.timezone('America/New_York')
        week_start = datetime(2024, 1, 15, 0, 0, 0, tzinfo=pytz.UTC)
        week_end = datetime(2024, 1, 21, 23, 59, 59, tzinfo=pytz.UTC)
        
        schedule = Schedule(
            id=1,
            kind="cron",
            schedule_spec="0 9 * * *",  # 9 AM daily
            timezone="America/New_York",
            enabled=True,
            created_at=datetime.utcnow()
        )
        
        occurrences = generate_week_occurrences(schedule, week_start, week_end, tz)
        
        # All occurrences should be stored as UTC
        assert all(occ.tzinfo == pytz.UTC or occ.tzinfo is None for occ in occurrences)
        # Should generate 7 occurrences
        assert len(occurrences) == 7

