"""Integration tests for scheduler functionality."""

import pytest
from datetime import datetime, timedelta
from src.database import get_db
from src.models import Schedule, Post, PublishJob
from src.services.scheduler_service import ScheduleResolver


@pytest.mark.integration
class TestSchedulerIntegration:
    """Integration tests for scheduler functionality."""
    
    def test_schedule_resolver_with_real_db(self, test_db):
        """Test schedule resolver with real database."""
        resolver = ScheduleResolver()
        
        # Create a test post
        post = Post(
            text="Integration test post",
            media_refs=None,
            deleted=False,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        test_db.add(post)
        test_db.flush()
        
        # Create a one-shot schedule
        future_time = datetime.utcnow() + timedelta(minutes=10)
        schedule = Schedule(
            post_id=post.id,
            kind="one_shot",
            schedule_spec=future_time.isoformat(),
            timezone="UTC",
            next_run_at=None,
            enabled=True,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        test_db.add(schedule)
        test_db.flush()
        
        # Test resolver
        result = resolver.resolve_schedule(schedule)
        assert result is not None
        assert result == future_time
        
        # Clean up
        test_db.delete(schedule)
        test_db.delete(post)
        test_db.commit()
    
    def test_schedule_resolver_cron_with_real_db(self, test_db):
        """Test cron schedule resolver with real database."""
        resolver = ScheduleResolver()
        
        # Create a test post
        post = Post(
            text="Cron integration test post",
            media_refs=None,
            deleted=False,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        test_db.add(post)
        test_db.flush()
        
        # Create a cron schedule
        schedule = Schedule(
            post_id=post.id,
            kind="cron",
            schedule_spec="0 */1 * * *",  # Every hour
            timezone="UTC",
            next_run_at=None,
            enabled=True,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        test_db.add(schedule)
        test_db.flush()
        
        # Test resolver
        result = resolver.resolve_schedule(schedule)
        assert result is not None
        assert isinstance(result, datetime)
        assert result > datetime.utcnow()
        
        # Clean up
        test_db.delete(schedule)
        test_db.delete(post)
        test_db.commit()
    
    def test_publish_job_creation(self, test_db):
        """Test creating a publish job."""
        # Create a test post
        post = Post(
            text="Publish job test post",
            media_refs=None,
            deleted=False,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        test_db.add(post)
        test_db.flush()
        
        # Create a schedule
        schedule = Schedule(
            post_id=post.id,
            kind="one_shot",
            schedule_spec=(datetime.utcnow() + timedelta(minutes=5)).isoformat(),
            timezone="UTC",
            next_run_at=datetime.utcnow() + timedelta(minutes=5),
            enabled=True,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        test_db.add(schedule)
        test_db.flush()
        
        # Create a publish job
        job = PublishJob(
            schedule_id=schedule.id,
            planned_at=schedule.next_run_at,
            status="planned",
            dedupe_key=f"{schedule.id}:{schedule.next_run_at.isoformat()}",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        test_db.add(job)
        test_db.commit()
        
        # Verify job was created
        assert job.id is not None
        assert job.status == "planned"
        assert job.schedule_id == schedule.id
        
        # Clean up
        test_db.delete(job)
        test_db.delete(schedule)
        test_db.delete(post)
        test_db.commit()
    
    def test_schedule_resolver_rrule_with_real_db(self, test_db):
        """Test RRULE schedule resolver with real database."""
        resolver = ScheduleResolver()
        
        # Create a test post
        post = Post(
            text="RRULE integration test post",
            media_refs=None,
            deleted=False,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        test_db.add(post)
        test_db.flush()
        
        # Create a daily RRULE schedule
        schedule = Schedule(
            post_id=post.id,
            kind="rrule",
            schedule_spec="FREQ=DAILY;INTERVAL=1",
            timezone="UTC",
            next_run_at=None,
            enabled=True,
            created_at=datetime.utcnow() - timedelta(days=1),
            updated_at=datetime.utcnow()
        )
        test_db.add(schedule)
        test_db.flush()
        
        # Test resolver
        result = resolver.resolve_schedule(schedule)
        assert result is not None
        assert isinstance(result, datetime)
        assert result > datetime.utcnow()
        assert result <= datetime.utcnow() + timedelta(days=1)
        
        # Clean up
        test_db.delete(schedule)
        test_db.delete(post)
        test_db.commit()
    
    def test_schedule_resolver_rrule_weekly_with_real_db(self, test_db):
        """Test weekly RRULE schedule resolver with real database."""
        resolver = ScheduleResolver()
        
        # Create a test post
        post = Post(
            text="Weekly RRULE integration test post",
            media_refs=None,
            deleted=False,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        test_db.add(post)
        test_db.flush()
        
        # Create a weekly RRULE schedule (Monday, Wednesday, Friday)
        schedule = Schedule(
            post_id=post.id,
            kind="rrule",
            schedule_spec="FREQ=WEEKLY;BYDAY=MO,WE,FR",
            timezone="UTC",
            next_run_at=None,
            enabled=True,
            created_at=datetime.utcnow() - timedelta(days=7),
            updated_at=datetime.utcnow()
        )
        test_db.add(schedule)
        test_db.flush()
        
        # Test resolver
        result = resolver.resolve_schedule(schedule)
        assert result is not None
        assert isinstance(result, datetime)
        assert result > datetime.utcnow()
        
        # Clean up
        test_db.delete(schedule)
        test_db.delete(post)
        test_db.commit()
    
    def test_schedule_resolver_rrule_with_time_constraints(self, test_db):
        """Test RRULE schedule with time constraints (BYHOUR/BYMINUTE) with real database."""
        resolver = ScheduleResolver()
        
        # Create a test post
        post = Post(
            text="RRULE time constraints test post",
            media_refs=None,
            deleted=False,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        test_db.add(post)
        test_db.flush()
        
        # Create a daily RRULE schedule at 9 AM
        schedule = Schedule(
            post_id=post.id,
            kind="rrule",
            schedule_spec="FREQ=DAILY;BYHOUR=9;BYMINUTE=0",
            timezone="UTC",
            next_run_at=None,
            enabled=True,
            created_at=datetime.utcnow() - timedelta(days=1),
            updated_at=datetime.utcnow()
        )
        test_db.add(schedule)
        test_db.flush()
        
        # Test resolver
        result = resolver.resolve_schedule(schedule)
        assert result is not None
        assert isinstance(result, datetime)
        assert result > datetime.utcnow()
        # Verify hour is 9 (in UTC)
        assert result.hour == 9
        assert result.minute == 0
        
        # Clean up
        test_db.delete(schedule)
        test_db.delete(post)
        test_db.commit()
    
    def test_schedule_resolver_rrule_with_count_limit(self, test_db):
        """Test RRULE schedule with COUNT limit with real database."""
        resolver = ScheduleResolver()
        
        # Create a test post
        post = Post(
            text="RRULE COUNT limit test post",
            media_refs=None,
            deleted=False,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        test_db.add(post)
        test_db.flush()
        
        # Create a daily RRULE schedule with COUNT=3
        schedule = Schedule(
            post_id=post.id,
            kind="rrule",
            schedule_spec="FREQ=DAILY;INTERVAL=1;COUNT=3",
            timezone="UTC",
            next_run_at=None,
            enabled=True,
            created_at=datetime.utcnow() - timedelta(days=5),  # 5 days ago
            updated_at=datetime.utcnow()
        )
        test_db.add(schedule)
        test_db.flush()
        
        # Get first 3 occurrences (should work)
        for i in range(3):
            result = resolver.resolve_schedule(schedule)
            if result:
                # Update last_run_at to simulate execution
                schedule.last_run_at = result
                test_db.commit()
            else:
                break
        
        # After COUNT is exhausted, should return None
        result = resolver.resolve_schedule(schedule)
        assert result is None
        
        # Clean up
        test_db.delete(schedule)
        test_db.delete(post)
        test_db.commit()