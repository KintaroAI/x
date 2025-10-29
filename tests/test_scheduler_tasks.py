"""Tests for scheduler tasks."""

import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

from src.tasks.scheduler import scheduler_tick, initialize_schedules, scheduler_health_check
from src.models import Schedule, PublishJob


@pytest.mark.unit
class TestSchedulerTick:
    """Test cases for scheduler_tick task."""
    
    @patch('src.tasks.scheduler.get_db')
    @patch('src.tasks.scheduler.acquire_dedupe_lock')
    @patch('src.tasks.publish.publish_post')
    def test_scheduler_tick_no_due_schedules(self, mock_publish, mock_lock, mock_get_db):
        """Test scheduler_tick with no due schedules."""
        # Mock database session
        mock_db = MagicMock()
        mock_get_db.return_value.__enter__.return_value = mock_db
        
        # Mock query result - no due schedules
        mock_db.query.return_value.filter.return_value.with_for_update.return_value.all.return_value = []
        
        # Run scheduler tick
        scheduler_tick()
        
        # Verify no jobs were created
        mock_db.add.assert_not_called()
        mock_db.commit.assert_called_once()
    
    @patch('src.tasks.scheduler.get_db')
    @patch('src.tasks.scheduler.acquire_dedupe_lock')
    @patch('src.tasks.publish.publish_post')
    def test_scheduler_tick_with_due_schedule(self, mock_publish, mock_lock, mock_get_db):
        """Test scheduler_tick with a due schedule."""
        # Mock database session
        mock_db = MagicMock()
        mock_get_db.return_value.__enter__.return_value = mock_db
        
        # Create a mock schedule
        mock_schedule = MagicMock()
        mock_schedule.id = 1
        mock_schedule.next_run_at = datetime.utcnow()
        
        # Mock query result - one due schedule
        mock_db.query.return_value.filter.return_value.with_for_update.return_value.all.return_value = [mock_schedule]
        
        # Mock dedupe lock acquisition
        mock_lock.return_value = True
        
        # Mock job creation
        mock_job = MagicMock()
        mock_job.id = 123
        mock_db.add.return_value = None
        mock_db.flush.return_value = None
        
        # Mock publish_post.apply_async
        mock_publish.apply_async.return_value = None
        
        # Run scheduler tick
        scheduler_tick()
        
        # Verify job was created and published
        mock_db.add.assert_called_once()
        mock_publish.apply_async.assert_called_once()
        mock_db.commit.assert_called_once()
    
    @patch('src.tasks.scheduler.get_db')
    @patch('src.tasks.scheduler.acquire_dedupe_lock')
    def test_scheduler_tick_dedupe_lock_fails(self, mock_lock, mock_get_db):
        """Test scheduler_tick when dedupe lock acquisition fails."""
        # Mock database session
        mock_db = MagicMock()
        mock_get_db.return_value.__enter__.return_value = mock_db
        
        # Create a mock schedule
        mock_schedule = MagicMock()
        mock_schedule.id = 1
        mock_schedule.next_run_at = datetime.utcnow()
        
        # Mock query result - one due schedule
        mock_db.query.return_value.filter.return_value.with_for_update.return_value.all.return_value = [mock_schedule]
        
        # Mock dedupe lock acquisition failure
        mock_lock.return_value = False
        
        # Run scheduler tick
        scheduler_tick()
        
        # Verify no job was created
        mock_db.add.assert_not_called()
        mock_db.commit.assert_called_once()


@pytest.mark.unit
class TestInitializeSchedules:
    """Test cases for initialize_schedules task."""
    
    @patch('src.tasks.scheduler.get_db')
    def test_initialize_schedules_no_schedules(self, mock_get_db):
        """Test initialize_schedules with no schedules to initialize."""
        # Mock database session
        mock_db = MagicMock()
        mock_get_db.return_value.__enter__.return_value = mock_db
        
        # Mock query result - no schedules to initialize
        mock_db.query.return_value.filter.return_value.all.return_value = []
        
        # Run initialize schedules
        initialize_schedules()
        
        # Verify commit was called
        mock_db.commit.assert_called_once()
    
    @patch('src.tasks.scheduler.get_db')
    @patch('src.tasks.scheduler.ScheduleResolver')
    def test_initialize_schedules_with_schedules(self, mock_resolver_class, mock_get_db):
        """Test initialize_schedules with schedules to initialize."""
        # Mock database session
        mock_db = MagicMock()
        mock_get_db.return_value.__enter__.return_value = mock_db
        
        # Create mock schedules
        mock_schedule1 = MagicMock()
        mock_schedule1.id = 1
        mock_schedule2 = MagicMock()
        mock_schedule2.id = 2
        
        # Mock query result - two schedules to initialize
        mock_db.query.return_value.filter.return_value.all.return_value = [mock_schedule1, mock_schedule2]
        
        # Mock resolver
        mock_resolver = MagicMock()
        mock_resolver_class.return_value = mock_resolver
        mock_resolver.resolve_schedule.return_value = datetime.utcnow() + timedelta(hours=1)
        
        # Run initialize schedules
        initialize_schedules()
        
        # Verify schedules were processed
        assert mock_resolver.resolve_schedule.call_count == 2
        mock_db.commit.assert_called_once()


@pytest.mark.unit
class TestSchedulerHealthCheck:
    """Test cases for scheduler_health_check task."""
    
    @patch('src.tasks.scheduler.get_db')
    def test_scheduler_health_check(self, mock_get_db):
        """Test scheduler health check."""
        # Mock database session
        mock_db = MagicMock()
        mock_get_db.return_value.__enter__.return_value = mock_db
        
        # Mock query results
        mock_db.query.return_value.filter.return_value.count.return_value = 0
        
        # Run health check
        scheduler_health_check()
        
        # Verify queries were made
        assert mock_db.query.return_value.filter.return_value.count.call_count == 2
