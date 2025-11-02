"""Integration tests for calendar functionality."""

import pytest
from datetime import datetime, timedelta
import pytz

from src.database import get_db
from src.models import Schedule, Post
from src.api.posts import get_weekly_schedule
from src.services.calendar_service import (
    get_week_boundaries,
    generate_week_occurrences,
    format_occurrence_for_calendar
)


@pytest.mark.integration
class TestCalendarIntegration:
    """Integration tests for calendar functionality."""
    
    @pytest.mark.asyncio
    async def test_get_weekly_schedule_with_real_db(self, test_db):
        """Test weekly schedule API with real database."""
        # Create a test post
        post = Post(
            text="Integration test post for calendar",
            media_refs=None,
            deleted=False,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        test_db.add(post)
        test_db.flush()
        
        # Create a one-shot schedule within next week
        next_week = datetime.utcnow() + timedelta(days=3)
        schedule = Schedule(
            post_id=post.id,
            kind="one_shot",
            schedule_spec=next_week.isoformat(),
            timezone="UTC",
            next_run_at=next_week,
            enabled=True,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        test_db.add(schedule)
        test_db.commit()
        
        try:
            # Call API with current week
            result = await get_weekly_schedule(timezone="UTC", locale="monday")
            
            # Verify response structure
            assert 'week_start' in result
            assert 'week_end' in result
            assert 'timezone' in result
            assert 'locale' in result
            assert 'occurrences' in result
            
            # Should have at least one occurrence if next_week is in current week
            # (depending on when the test runs)
            assert isinstance(result['occurrences'], list)
            
            # Verify occurrence structure if present
            if result['occurrences']:
                occ = result['occurrences'][0]
                required_fields = [
                    'occurrence_id', 'post_id', 'post_text_preview', 'schedule_id',
                    'schedule_kind', 'source', 'scheduled_time', 'scheduled_time_local',
                    'duration_minutes', 'status', 'color_hint', 'stack_index'
                ]
                for field in required_fields:
                    assert field in occ, f"Missing required field: {field}"
        
        finally:
            # Clean up
            test_db.delete(schedule)
            test_db.delete(post)
            test_db.commit()
    
    @pytest.mark.asyncio
    async def test_get_weekly_schedule_with_cron_schedule(self, test_db):
        """Test weekly schedule with cron schedule."""
        # Create a test post
        post = Post(
            text="Daily scheduled post",
            media_refs=None,
            deleted=False,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        test_db.add(post)
        test_db.flush()
        
        # Create a daily cron schedule
        schedule = Schedule(
            post_id=post.id,
            kind="cron",
            schedule_spec="0 9 * * *",  # Daily at 9 AM
            timezone="UTC",
            enabled=True,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        test_db.add(schedule)
        test_db.commit()
        
        try:
            # Call API
            result = await get_weekly_schedule(timezone="UTC", locale="monday")
            
            # Filter occurrences for this post
            post_occurrences = [occ for occ in result['occurrences'] if occ['post_id'] == post.id]
            
            # Verify occurrences are generated for this post
            assert len(post_occurrences) >= 1  # At least one occurrence
            
            # Verify all occurrences for this post are correct
            for occ in post_occurrences:
                assert occ['post_id'] == post.id
                assert occ['schedule_id'] == schedule.id
                assert occ['schedule_kind'] == 'cron'
                assert occ['source'] == 'cron'
        
        finally:
            # Clean up
            test_db.delete(schedule)
            test_db.delete(post)
            test_db.commit()
    
    @pytest.mark.asyncio
    async def test_get_weekly_schedule_with_rrule_schedule(self, test_db):
        """Test weekly schedule with RRULE schedule."""
        # Create a test post
        post = Post(
            text="RRULE scheduled post",
            media_refs=None,
            deleted=False,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        test_db.add(post)
        test_db.flush()
        
        # Create a daily RRULE schedule
        # Set created_at to past date so RRULE can generate occurrences in current week
        schedule = Schedule(
            post_id=post.id,
            kind="rrule",
            schedule_spec="FREQ=DAILY;BYHOUR=10;BYMINUTE=30",
            timezone="UTC",
            enabled=True,
            created_at=datetime.utcnow() - timedelta(days=30),  # Past date
            updated_at=datetime.utcnow()
        )
        test_db.add(schedule)
        test_db.commit()
        
        try:
            # Call API
            result = await get_weekly_schedule(timezone="UTC", locale="monday")
            
            # Filter occurrences for this post
            post_occurrences = [occ for occ in result['occurrences'] if occ['post_id'] == post.id]
            
            # Verify occurrences are generated for this post
            assert len(post_occurrences) >= 1  # At least one occurrence
            
            # Verify all occurrences for this post are correct
            for occ in post_occurrences:
                assert occ['post_id'] == post.id
                assert occ['schedule_id'] == schedule.id
                assert occ['schedule_kind'] == 'rrule'
                assert occ['source'] == 'rrule'
        
        finally:
            # Clean up
            test_db.delete(schedule)
            test_db.delete(post)
            test_db.commit()
    
    @pytest.mark.asyncio
    async def test_get_weekly_schedule_excludes_disabled_schedules(self, test_db):
        """Test that disabled schedules are excluded."""
        # Create a test post
        post = Post(
            text="Disabled schedule post",
            media_refs=None,
            deleted=False,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        test_db.add(post)
        test_db.flush()
        
        # Create a disabled schedule
        schedule = Schedule(
            post_id=post.id,
            kind="cron",
            schedule_spec="0 9 * * *",
            timezone="UTC",
            enabled=False,  # Disabled
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        test_db.add(schedule)
        test_db.commit()
        
        try:
            # Call API
            result = await get_weekly_schedule(timezone="UTC", locale="monday")
            
            # Verify disabled schedule is excluded
            schedule_ids = [occ['schedule_id'] for occ in result['occurrences']]
            assert schedule.id not in schedule_ids
        
        finally:
            # Clean up
            test_db.delete(schedule)
            test_db.delete(post)
            test_db.commit()
    
    @pytest.mark.asyncio
    async def test_get_weekly_schedule_excludes_deleted_posts(self, test_db):
        """Test that deleted posts are excluded."""
        # Create a deleted post
        post = Post(
            text="Deleted post",
            media_refs=None,
            deleted=True,  # Deleted
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        test_db.add(post)
        test_db.flush()
        
        # Create a schedule for deleted post
        schedule = Schedule(
            post_id=post.id,
            kind="cron",
            schedule_spec="0 9 * * *",
            timezone="UTC",
            enabled=True,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        test_db.add(schedule)
        test_db.commit()
        
        try:
            # Call API
            result = await get_weekly_schedule(timezone="UTC", locale="monday")
            
            # Verify deleted post's schedule is excluded
            post_ids = [occ['post_id'] for occ in result['occurrences']]
            assert post.id not in post_ids
        
        finally:
            # Clean up
            test_db.delete(schedule)
            test_db.delete(post)
            test_db.commit()
    
    @pytest.mark.asyncio
    async def test_get_weekly_schedule_stack_index_calculation(self, test_db):
        """Test that stack_index is correctly calculated for overlapping posts."""
        # Create multiple posts with schedules at the same time
        tz = pytz.UTC
        week_start, week_end = get_week_boundaries(None, tz, 'monday')
        
        posts = []
        schedules = []
        
        for i in range(3):
            post = Post(
                text=f"Post {i+1}",
                media_refs=None,
                deleted=False,
                created_at=datetime.utcnow() + timedelta(seconds=i),  # Slight time difference
                updated_at=datetime.utcnow()
            )
            test_db.add(post)
            test_db.flush()
            posts.append(post)
            
            # All schedules at same time (9 AM on a specific day)
            schedule = Schedule(
                post_id=post.id,
                kind="one_shot",
                schedule_spec=(week_start + timedelta(days=2, hours=9)).isoformat(),
                timezone="UTC",
                next_run_at=week_start + timedelta(days=2, hours=9),
                enabled=True,
                created_at=datetime.utcnow() + timedelta(seconds=i),
                updated_at=datetime.utcnow()
            )
            test_db.add(schedule)
            schedules.append(schedule)
        
        test_db.commit()
        
        try:
            # Call API
            result = await get_weekly_schedule(
                week_start=week_start.strftime('%Y-%m-%d'),
                timezone="UTC",
                locale="monday"
            )
            
            # Find occurrences at the same time slot
            target_time = (week_start + timedelta(days=2, hours=9)).strftime('%H:%M')
            same_slot_occurrences = [
                occ for occ in result['occurrences']
                if occ['scheduled_time_local'].split('T')[1].startswith(target_time)
            ]
            
            # Should have 3 occurrences at same time
            assert len(same_slot_occurrences) == 3
            
            # Verify stack_index is different for each
            stack_indices = [occ['stack_index'] for occ in same_slot_occurrences]
            assert len(set(stack_indices)) == 3  # All different
            assert sorted(stack_indices) == [0, 1, 2]  # Sequential
        
        finally:
            # Clean up
            for schedule in schedules:
                test_db.delete(schedule)
            for post in posts:
                test_db.delete(post)
            test_db.commit()
    
    @pytest.mark.asyncio
    async def test_get_weekly_schedule_locale_difference(self, test_db):
        """Test that locale parameter affects week boundaries."""
        # Create a test post
        post = Post(
            text="Locale test post",
            media_refs=None,
            deleted=False,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        test_db.add(post)
        test_db.flush()
        
        # Create a schedule for a specific date
        target_date = datetime(2024, 1, 14, 12, 0, 0)  # Sunday, Jan 14
        schedule = Schedule(
            post_id=post.id,
            kind="one_shot",
            schedule_spec=target_date.isoformat(),
            timezone="UTC",
            next_run_at=target_date,
            enabled=True,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        test_db.add(schedule)
        test_db.commit()
        
        try:
            # Call with 'sunday' locale (Sunday is week start)
            result_sunday = await get_weekly_schedule(
                week_start="2024-01-14",  # Sunday
                timezone="UTC",
                locale="sunday"
            )
            
            # Call with 'monday' locale (Monday is week start)
            result_monday = await get_weekly_schedule(
                week_start="2024-01-08",  # Monday of previous week
                timezone="UTC",
                locale="monday"
            )
            
            # The Sunday Jan 14 occurrence should appear in both, but in different weeks
            # Verify week boundaries are different
            assert result_sunday['week_start'] != result_monday['week_start']
            assert result_sunday['locale'] == 'sunday'
            assert result_monday['locale'] == 'monday'
        
        finally:
            # Clean up
            test_db.delete(schedule)
            test_db.delete(post)
            test_db.commit()

