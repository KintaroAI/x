"""Unit tests for calendar API endpoint."""

import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
import pytz

from src.api.posts import get_weekly_schedule
from src.models import Schedule, Post


@pytest.mark.unit
@pytest.mark.asyncio
class TestGetWeeklyScheduleAPI:
    """Test cases for get_weekly_schedule API endpoint."""
    
    @patch('src.api.posts.get_db')
    @patch('src.api.posts.get_week_boundaries')
    @patch('src.api.posts.generate_week_occurrences')
    @patch('src.api.posts.format_occurrence_for_calendar')
    async def test_get_weekly_schedule_basic(self, mock_format, mock_generate, mock_boundaries, mock_get_db):
        """Test basic weekly schedule retrieval."""
        # Mock database session
        mock_db = MagicMock()
        mock_get_db.return_value.__enter__.return_value = mock_db
        
        # Mock schedules
        post = Post(
            id=1,
            text="Test post",
            media_refs=None,
            deleted=False,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        
        schedule = Schedule(
            id=1,
            post_id=1,
            kind="cron",
            schedule_spec="0 9 * * *",
            timezone="UTC",
            enabled=True,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        schedule.post = post
        
        mock_db.query.return_value.filter.return_value.join.return_value.filter.return_value.all.return_value = [schedule]
        
        # Mock week boundaries
        week_start = datetime(2024, 1, 15, 0, 0, 0, tzinfo=pytz.UTC)
        week_end = datetime(2024, 1, 21, 23, 59, 59, tzinfo=pytz.UTC)
        mock_boundaries.return_value = (week_start, week_end)
        
        # Mock occurrence generation
        occurrences = [
            datetime(2024, 1, 15, 9, 0, 0, tzinfo=pytz.UTC),
            datetime(2024, 1, 16, 9, 0, 0, tzinfo=pytz.UTC),
        ]
        mock_generate.return_value = occurrences
        
        # Mock formatting
        mock_format.side_effect = [
            {
                "occurrence_id": "test1",
                "post_id": 1,
                "post_text_preview": "Test post",
                "schedule_id": 1,
                "schedule_kind": "cron",
                "source": "cron",
                "scheduled_time": "2024-01-15T09:00:00+00:00",
                "scheduled_time_local": "2024-01-15T09:00:00+00:00",
                "duration_minutes": 30,
                "status": "planned",
                "color_hint": "#3B82F6",
                "stack_index": 0
            },
            {
                "occurrence_id": "test2",
                "post_id": 1,
                "post_text_preview": "Test post",
                "schedule_id": 1,
                "schedule_kind": "cron",
                "source": "cron",
                "scheduled_time": "2024-01-16T09:00:00+00:00",
                "scheduled_time_local": "2024-01-16T09:00:00+00:00",
                "duration_minutes": 30,
                "status": "planned",
                "color_hint": "#3B82F6",
                "stack_index": 0
            }
        ]
        
        # Call API
        result = await get_weekly_schedule(
            week_start="2024-01-15",
            timezone="UTC",
            locale="monday"
        )
        
        # Verify response structure
        assert 'week_start' in result
        assert 'week_end' in result
        assert 'timezone' in result
        assert 'locale' in result
        assert 'occurrences' in result
        assert result['timezone'] == 'UTC'
        assert result['locale'] == 'monday'
        assert len(result['occurrences']) == 2
    
    @patch('src.api.posts.get_db')
    async def test_get_weekly_schedule_defaults(self, mock_get_db):
        """Test weekly schedule with default parameters."""
        # Mock database session
        mock_db = MagicMock()
        mock_get_db.return_value.__enter__.return_value = mock_db
        
        # Mock empty schedules
        mock_db.query.return_value.filter.return_value.join.return_value.filter.return_value.all.return_value = []
        
        # Mock week boundaries
        with patch('src.api.posts.get_week_boundaries') as mock_boundaries:
            week_start = datetime.now(pytz.UTC).replace(hour=0, minute=0, second=0)
            week_end = week_start + timedelta(days=6, hours=23, minutes=59)
            mock_boundaries.return_value = (week_start, week_end)
            
            # Call API with defaults
            result = await get_weekly_schedule()
            
            # Verify response
            assert 'week_start' in result
            assert 'week_end' in result
            assert 'occurrences' in result
            assert result['occurrences'] == []
    
    @patch('src.api.posts.get_db')
    async def test_get_weekly_schedule_response_fields(self, mock_get_db):
        """Test that API response includes all required fields."""
        # Mock database session
        mock_db = MagicMock()
        mock_get_db.return_value.__enter__.return_value = mock_db
        
        post = Post(id=1, text="Test", media_refs=None, deleted=False, created_at=datetime.utcnow(), updated_at=datetime.utcnow())
        schedule = Schedule(id=1, post_id=1, kind="one_shot", schedule_spec="", timezone="UTC", enabled=True, created_at=datetime.utcnow())
        schedule.post = post
        
        mock_db.query.return_value.filter.return_value.join.return_value.filter.return_value.all.return_value = [schedule]
        
        with patch('src.api.posts.get_week_boundaries') as mock_boundaries, \
             patch('src.api.posts.generate_week_occurrences') as mock_generate, \
             patch('src.api.posts.format_occurrence_for_calendar') as mock_format:
            
            week_start = datetime(2024, 1, 15, 0, 0, 0, tzinfo=pytz.UTC)
            week_end = datetime(2024, 1, 21, 23, 59, 59, tzinfo=pytz.UTC)
            mock_boundaries.return_value = (week_start, week_end)
            mock_generate.return_value = [datetime(2024, 1, 18, 12, 0, 0, tzinfo=pytz.UTC)]
            
            occurrence_data = {
                "occurrence_id": "test1",
                "post_id": 1,
                "post_text_preview": "Test",
                "schedule_id": 1,
                "schedule_kind": "one_shot",
                "source": "one_shot",
                "scheduled_time": "2024-01-18T12:00:00+00:00",
                "scheduled_time_local": "2024-01-18T12:00:00+00:00",
                "duration_minutes": 30,
                "status": "planned",
                "color_hint": "#3B82F6",
                "stack_index": 0
            }
            mock_format.return_value = occurrence_data
            
            result = await get_weekly_schedule()
            
            # Verify all required fields in response
            assert 'week_start' in result
            assert 'week_end' in result
            assert 'timezone' in result
            assert 'locale' in result
            assert 'occurrences' in result
            
            if result['occurrences']:
                occ = result['occurrences'][0]
                required_fields = [
                    'occurrence_id', 'post_id', 'post_text_preview', 'schedule_id',
                    'schedule_kind', 'source', 'scheduled_time', 'scheduled_time_local',
                    'duration_minutes', 'status', 'color_hint', 'stack_index'
                ]
                for field in required_fields:
                    assert field in occ, f"Missing required field: {field}"
    
    @patch('src.api.posts.get_db')
    async def test_get_weekly_schedule_locale_parameter(self, mock_get_db):
        """Test weekly schedule with different locale parameters."""
        # Mock database session
        mock_db = MagicMock()
        mock_get_db.return_value.__enter__.return_value = mock_db
        mock_db.query.return_value.filter.return_value.join.return_value.filter.return_value.all.return_value = []
        
        with patch('src.api.posts.get_week_boundaries') as mock_boundaries:
            week_start = datetime(2024, 1, 15, 0, 0, 0, tzinfo=pytz.UTC)
            week_end = datetime(2024, 1, 21, 23, 59, 59, tzinfo=pytz.UTC)
            mock_boundaries.return_value = (week_start, week_end)
            
            # Test with 'sunday' locale
            result_sunday = await get_weekly_schedule(locale='sunday')
            assert result_sunday['locale'] == 'sunday'
            
            # Test with 'monday' locale
            result_monday = await get_weekly_schedule(locale='monday')
            assert result_monday['locale'] == 'monday'
            
            # Test default (should be 'monday')
            result_default = await get_weekly_schedule()
            assert result_default['locale'] == 'monday'
    
    @patch('src.api.posts.get_db')
    async def test_get_weekly_schedule_timezone_parameter(self, mock_get_db):
        """Test weekly schedule with different timezone parameters."""
        # Mock database session
        mock_db = MagicMock()
        mock_get_db.return_value.__enter__.return_value = mock_db
        mock_db.query.return_value.filter.return_value.join.return_value.filter.return_value.all.return_value = []
        
        with patch('src.api.posts.get_week_boundaries') as mock_boundaries:
            week_start = datetime(2024, 1, 15, 0, 0, 0, tzinfo=pytz.UTC)
            week_end = datetime(2024, 1, 21, 23, 59, 59, tzinfo=pytz.UTC)
            mock_boundaries.return_value = (week_start, week_end)
            
            # Test with America/Chicago timezone
            result = await get_weekly_schedule(timezone='America/Chicago')
            assert result['timezone'] == 'America/Chicago'
            
            # Test with UTC timezone
            result = await get_weekly_schedule(timezone='UTC')
            assert result['timezone'] == 'UTC'
    
    @patch('src.api.posts.get_db')
    async def test_get_weekly_schedule_sorts_occurrences(self, mock_get_db):
        """Test that occurrences are sorted by scheduled_time."""
        # Mock database session
        mock_db = MagicMock()
        mock_get_db.return_value.__enter__.return_value = mock_db
        
        post = Post(id=1, text="Test", media_refs=None, deleted=False, created_at=datetime.utcnow(), updated_at=datetime.utcnow())
        schedule = Schedule(id=1, post_id=1, kind="cron", schedule_spec="0 9 * * *", timezone="UTC", enabled=True, created_at=datetime.utcnow())
        schedule.post = post
        
        mock_db.query.return_value.filter.return_value.join.return_value.filter.return_value.all.return_value = [schedule]
        
        with patch('src.api.posts.get_week_boundaries') as mock_boundaries, \
             patch('src.api.posts.generate_week_occurrences') as mock_generate, \
             patch('src.api.posts.format_occurrence_for_calendar') as mock_format:
            
            week_start = datetime(2024, 1, 15, 0, 0, 0, tzinfo=pytz.UTC)
            week_end = datetime(2024, 1, 21, 23, 59, 59, tzinfo=pytz.UTC)
            mock_boundaries.return_value = (week_start, week_end)
            
            # Generate occurrences in random order
            occurrences = [
                datetime(2024, 1, 20, 9, 0, 0, tzinfo=pytz.UTC),  # Friday
                datetime(2024, 1, 15, 9, 0, 0, tzinfo=pytz.UTC),  # Monday
                datetime(2024, 1, 18, 9, 0, 0, tzinfo=pytz.UTC),  # Thursday
            ]
            mock_generate.return_value = occurrences
            
            # Mock formatting
            def format_side_effect(occ, post, schedule, stack_idx, tz):
                return {
                    "occurrence_id": f"test_{occ.isoformat()}",
                    "post_id": 1,
                    "post_text_preview": "Test",
                    "schedule_id": 1,
                    "schedule_kind": "cron",
                    "source": "cron",
                    "scheduled_time": occ.isoformat(),
                    "scheduled_time_local": occ.isoformat(),
                    "duration_minutes": 30,
                    "status": "planned",
                    "color_hint": "#3B82F6",
                    "stack_index": 0
                }
            
            mock_format.side_effect = format_side_effect
            
            result = await get_weekly_schedule()
            
            # Verify occurrences are sorted by scheduled_time
            if len(result['occurrences']) > 1:
                for i in range(len(result['occurrences']) - 1):
                    current = result['occurrences'][i]['scheduled_time']
                    next_occ = result['occurrences'][i + 1]['scheduled_time']
                    assert current <= next_occ, "Occurrences should be sorted by scheduled_time"

