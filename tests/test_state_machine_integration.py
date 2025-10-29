"""Integration tests for state machine with publish task."""

import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

from src.tasks.publish import publish_post
from src.utils.state_machine import (
    PublishJobStatus,
    get_job_status,
    is_job_terminal,
    update_job_status
)
from src.models import PublishJob, Schedule, Post


@pytest.mark.integration
class TestPublishTaskStateMachineIntegration:
    """Integration tests for publish task with state machine."""
    
    @patch('src.tasks.publish.create_twitter_post')
    @patch('src.tasks.publish.get_db')
    @patch('src.tasks.publish.acquire_dedupe_lock')
    @patch('src.tasks.publish.release_dedupe_lock')
    @patch('src.tasks.publish.is_job_terminal')
    @patch('src.tasks.publish.update_job_status')
    def test_publish_task_state_transitions_success(self, mock_update_status, mock_is_terminal, mock_release_lock, mock_acquire_lock, mock_get_db, mock_create_post):
        """Test successful state transitions in publish task."""
        # Mock successful Twitter API response
        mock_create_post.return_value = {"data": {"id": "12345"}}
        
        # Mock terminal state check - job is not terminal
        mock_is_terminal.return_value = False
        
        # Mock database session
        mock_db = MagicMock()
        mock_get_db.return_value.__enter__.return_value = mock_db
        
        # Mock job
        mock_job = MagicMock()
        mock_job.id = 1
        mock_job.schedule_id = 1
        mock_job.planned_at = datetime.utcnow()
        mock_job.attempt = 0
        
        # Mock schedule
        mock_schedule = MagicMock()
        mock_schedule.id = 1
        mock_schedule.post_id = 1
        
        # Mock post
        mock_post = MagicMock()
        mock_post.id = 1
        mock_post.text = "Test post"
        mock_post.deleted = False
        mock_post.media_refs = None
        
        # Mock query results
        mock_db.query.return_value.filter.return_value.first.side_effect = [
            mock_job,  # First call for job lookup
            mock_schedule,  # Second call for schedule lookup
            mock_post,  # Third call for post lookup
            mock_job  # Fourth call for dedupe lock release
        ]
        
        # Mock dedupe lock operations
        mock_acquire_lock.return_value = True
        mock_release_lock.return_value = True
        
        # Mock state machine updates
        mock_update_status.return_value = mock_job
        
        # Run publish task
        result = publish_post("1")
        
        # Verify successful result
        assert result["status"] == "success"
        assert result["job_id"] == "1"
        
        # Verify state machine was called
        assert mock_update_status.call_count >= 2  # At least running and succeeded
    
    @patch('src.tasks.publish.create_twitter_post')
    @patch('src.tasks.publish.get_db')
    @patch('src.tasks.publish.acquire_dedupe_lock')
    @patch('src.tasks.publish.release_dedupe_lock')
    @patch('src.tasks.publish.is_job_terminal')
    @patch('src.tasks.publish.update_job_status')
    def test_publish_task_state_transitions_failure(self, mock_update_status, mock_is_terminal, mock_release_lock, mock_acquire_lock, mock_get_db, mock_create_post):
        """Test state transitions when publish task fails."""
        # Mock failed Twitter API response
        mock_create_post.side_effect = Exception("API Error")
        
        # Mock terminal state check - job is not terminal
        mock_is_terminal.return_value = False
        
        # Mock database session
        mock_db = MagicMock()
        mock_get_db.return_value.__enter__.return_value = mock_db
        
        # Mock job
        mock_job = MagicMock()
        mock_job.id = 1
        mock_job.schedule_id = 1
        mock_job.planned_at = datetime.utcnow()
        mock_job.attempt = 0
        
        # Mock schedule
        mock_schedule = MagicMock()
        mock_schedule.id = 1
        mock_schedule.post_id = 1
        
        # Mock post
        mock_post = MagicMock()
        mock_post.id = 1
        mock_post.text = "Test post"
        mock_post.deleted = False
        mock_post.media_refs = None
        
        # Mock query results
        mock_db.query.return_value.filter.return_value.first.side_effect = [
            mock_job,  # First call for job lookup
            mock_schedule,  # Second call for schedule lookup
            mock_post,  # Third call for post lookup
            mock_job  # Fourth call for dedupe lock release
        ]
        
        # Mock dedupe lock operations
        mock_acquire_lock.return_value = True
        mock_release_lock.return_value = True
        
        # Mock state machine updates
        mock_update_status.return_value = mock_job
        
        # Run publish task - should raise exception
        with pytest.raises(Exception, match="API Error"):
            publish_post("1")
        
        # Verify state machine was called for running state
        assert mock_update_status.call_count >= 1
    
    @patch('src.tasks.publish.get_db')
    @patch('src.tasks.publish.is_job_terminal')
    @patch('src.tasks.publish.get_job_status')
    def test_publish_task_terminal_state_early_exit(self, mock_get_status, mock_is_terminal, mock_get_db):
        """Test that publish task exits early for terminal states."""
        # Mock terminal state check - job is terminal
        mock_is_terminal.return_value = True
        mock_get_status.return_value = "succeeded"
        
        # Mock database session
        mock_db = MagicMock()
        mock_get_db.return_value.__enter__.return_value = mock_db
        
        # Mock job in terminal state
        mock_job = MagicMock()
        mock_job.id = 1
        mock_job.status = "succeeded"
        
        # Mock query result
        mock_db.query.return_value.filter.return_value.first.return_value = mock_job
        
        # Run publish task
        result = publish_post("1")
        
        # Verify early exit
        assert result["status"] == "already_completed"
        assert result["result"] == "succeeded"
    
    @patch('src.tasks.publish.get_db')
    def test_publish_task_job_not_found(self, mock_get_db):
        """Test publish task when job is not found."""
        # Mock database session
        mock_db = MagicMock()
        mock_get_db.return_value.__enter__.return_value = mock_db
        
        # Mock job not found
        mock_db.query.return_value.filter.return_value.first.return_value = None
        
        # Run publish task
        result = publish_post("999")
        
        # Verify error result
        assert result["status"] == "error"
        assert result["message"] == "Job not found"


@pytest.mark.integration
class TestStateMachineDatabaseIntegration:
    """Integration tests for state machine with real database operations."""
    
    def test_state_machine_basic_functionality(self, test_db):
        """Test basic state machine functionality with real database."""
        # Create a test post
        post = Post(
            text="State machine integration test post",
            media_refs=None,
            deleted=False,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        test_db.add(post)
        test_db.flush()
        
        # Create a test schedule
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
        
        # Create a test job
        job = PublishJob(
            schedule_id=schedule.id,
            planned_at=datetime.utcnow(),
            status="planned",
            dedupe_key=f"{schedule.id}:{datetime.utcnow().isoformat()}",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        test_db.add(job)
        test_db.commit()
        
        # Test basic state machine functionality
        # Test terminal state check
        assert not is_job_terminal(job.id)
        
        # Test getting job status
        status = get_job_status(job.id)
        assert status == "planned"
        
        # Test invalid transition (should fail)
        with pytest.raises(ValueError, match="Invalid state transition"):
            update_job_status(job.id, PublishJobStatus.RUNNING.value)
        
        # Clean up
        test_db.delete(job)
        test_db.delete(schedule)
        test_db.delete(post)
        test_db.commit()
