"""Tests for state machine functionality."""

import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

from src.utils.state_machine import (
    PublishJobStateMachine,
    PublishJobStatus,
    update_job_status,
    get_job_status,
    is_job_terminal,
    cancel_job,
    retry_job,
    get_jobs_by_status,
    get_job_statistics
)
from src.models import PublishJob


@pytest.mark.unit
class TestPublishJobStateMachine:
    """Test cases for PublishJobStateMachine class."""
    
    def test_valid_transitions(self):
        """Test that valid transitions are correctly identified."""
        # Test valid transitions
        assert PublishJobStateMachine.is_valid_transition("planned", "enqueued")
        assert PublishJobStateMachine.is_valid_transition("planned", "cancelled")
        assert PublishJobStateMachine.is_valid_transition("enqueued", "running")
        assert PublishJobStateMachine.is_valid_transition("enqueued", "cancelled")
        assert PublishJobStateMachine.is_valid_transition("running", "succeeded")
        assert PublishJobStateMachine.is_valid_transition("running", "failed")
        assert PublishJobStateMachine.is_valid_transition("failed", "running")
        assert PublishJobStateMachine.is_valid_transition("failed", "dead_letter")
    
    def test_invalid_transitions(self):
        """Test that invalid transitions are correctly identified."""
        # Test invalid transitions
        assert not PublishJobStateMachine.is_valid_transition("planned", "running")
        assert not PublishJobStateMachine.is_valid_transition("enqueued", "succeeded")
        assert not PublishJobStateMachine.is_valid_transition("succeeded", "running")
        assert not PublishJobStateMachine.is_valid_transition("dead_letter", "running")
        assert not PublishJobStateMachine.is_valid_transition("cancelled", "running")
    
    def test_terminal_states(self):
        """Test terminal state identification."""
        assert PublishJobStateMachine.is_terminal_state("succeeded")
        assert PublishJobStateMachine.is_terminal_state("dead_letter")
        assert PublishJobStateMachine.is_terminal_state("cancelled")
        
        assert not PublishJobStateMachine.is_terminal_state("planned")
        assert not PublishJobStateMachine.is_terminal_state("enqueued")
        assert not PublishJobStateMachine.is_terminal_state("running")
        assert not PublishJobStateMachine.is_terminal_state("failed")
    
    def test_get_valid_transitions(self):
        """Test getting valid transitions from a state."""
        planned_transitions = PublishJobStateMachine.get_valid_transitions("planned")
        assert "enqueued" in planned_transitions
        assert "cancelled" in planned_transitions
        assert len(planned_transitions) == 2
        
        succeeded_transitions = PublishJobStateMachine.get_valid_transitions("succeeded")
        assert len(succeeded_transitions) == 0
        
        failed_transitions = PublishJobStateMachine.get_valid_transitions("failed")
        assert "running" in failed_transitions
        assert "dead_letter" in failed_transitions
        assert len(failed_transitions) == 2
    
    def test_validate_transition_valid(self):
        """Test validation of valid transitions."""
        # Should not raise exception
        PublishJobStateMachine.validate_transition("planned", "enqueued")
        PublishJobStateMachine.validate_transition("running", "succeeded")
        PublishJobStateMachine.validate_transition("failed", "dead_letter")
    
    def test_validate_transition_invalid(self):
        """Test validation of invalid transitions."""
        with pytest.raises(ValueError, match="Invalid state transition"):
            PublishJobStateMachine.validate_transition("planned", "running")
        
        with pytest.raises(ValueError, match="Invalid state transition"):
            PublishJobStateMachine.validate_transition("succeeded", "running")
        
        with pytest.raises(ValueError, match="Invalid state transition"):
            PublishJobStateMachine.validate_transition("dead_letter", "running")


@pytest.mark.unit
class TestUpdateJobStatus:
    """Test cases for update_job_status function."""
    
    @patch('src.utils.state_machine.get_db')
    def test_update_job_status_success(self, mock_get_db):
        """Test successful job status update."""
        # Mock database session
        mock_db = MagicMock()
        mock_get_db.return_value.__enter__.return_value = mock_db
        
        # Mock job
        mock_job = MagicMock()
        mock_job.id = 1
        mock_job.status = "planned"
        mock_job.updated_at = datetime.utcnow()
        
        # Mock query result
        mock_db.query.return_value.filter.return_value.with_for_update.return_value.first.return_value = mock_job
        
        # Update job status
        result = update_job_status(1, "enqueued", enqueued_at=datetime.utcnow())
        
        # Verify job was updated
        assert mock_job.status == "enqueued"
        assert mock_job.enqueued_at is not None
        mock_db.commit.assert_called_once()
        assert result == mock_job
    
    @patch('src.utils.state_machine.get_db')
    def test_update_job_status_job_not_found(self, mock_get_db):
        """Test update_job_status when job is not found."""
        # Mock database session
        mock_db = MagicMock()
        mock_get_db.return_value.__enter__.return_value = mock_db
        
        # Mock query result - job not found
        mock_db.query.return_value.filter.return_value.with_for_update.return_value.first.return_value = None
        
        # Should raise ValueError
        with pytest.raises(ValueError, match="Job 1 not found"):
            update_job_status(1, "enqueued")
    
    @patch('src.utils.state_machine.get_db')
    def test_update_job_status_invalid_transition(self, mock_get_db):
        """Test update_job_status with invalid transition."""
        # Mock database session
        mock_db = MagicMock()
        mock_get_db.return_value.__enter__.return_value = mock_db
        
        # Mock job
        mock_job = MagicMock()
        mock_job.id = 1
        mock_job.status = "planned"
        
        # Mock query result
        mock_db.query.return_value.filter.return_value.with_for_update.return_value.first.return_value = mock_job
        
        # Should raise ValueError for invalid transition
        with pytest.raises(ValueError, match="Invalid state transition"):
            update_job_status(1, "running")  # planned -> running is invalid
    
    @patch('src.utils.state_machine.get_db')
    def test_update_job_status_with_additional_fields(self, mock_get_db):
        """Test update_job_status with additional fields."""
        # Mock database session
        mock_db = MagicMock()
        mock_get_db.return_value.__enter__.return_value = mock_db
        
        # Mock job
        mock_job = MagicMock()
        mock_job.id = 1
        mock_job.status = "running"
        mock_job.updated_at = datetime.utcnow()
        
        # Mock query result
        mock_db.query.return_value.filter.return_value.with_for_update.return_value.first.return_value = mock_job
        
        # Update job status with additional fields
        test_time = datetime.utcnow()
        result = update_job_status(
            1, 
            "succeeded", 
            finished_at=test_time,
            x_post_id="12345"
        )
        
        # Verify job was updated
        assert mock_job.status == "succeeded"
        assert mock_job.finished_at == test_time
        assert mock_job.x_post_id == "12345"
        mock_db.commit.assert_called_once()


@pytest.mark.unit
class TestGetJobStatus:
    """Test cases for get_job_status function."""
    
    @patch('src.utils.state_machine.get_db')
    def test_get_job_status_found(self, mock_get_db):
        """Test get_job_status when job is found."""
        # Mock database session
        mock_db = MagicMock()
        mock_get_db.return_value.__enter__.return_value = mock_db
        
        # Mock job
        mock_job = MagicMock()
        mock_job.status = "running"
        
        # Mock query result
        mock_db.query.return_value.filter.return_value.first.return_value = mock_job
        
        # Get job status
        status = get_job_status(1)
        
        assert status == "running"
    
    @patch('src.utils.state_machine.get_db')
    def test_get_job_status_not_found(self, mock_get_db):
        """Test get_job_status when job is not found."""
        # Mock database session
        mock_db = MagicMock()
        mock_get_db.return_value.__enter__.return_value = mock_db
        
        # Mock query result - job not found
        mock_db.query.return_value.filter.return_value.first.return_value = None
        
        # Get job status
        status = get_job_status(1)
        
        assert status is None


@pytest.mark.unit
class TestIsJobTerminal:
    """Test cases for is_job_terminal function."""
    
    @patch('src.utils.state_machine.get_job_status')
    def test_is_job_terminal_true(self, mock_get_status):
        """Test is_job_terminal returns True for terminal states."""
        mock_get_status.return_value = "succeeded"
        assert is_job_terminal(1)
        
        mock_get_status.return_value = "dead_letter"
        assert is_job_terminal(1)
        
        mock_get_status.return_value = "cancelled"
        assert is_job_terminal(1)
    
    @patch('src.utils.state_machine.get_job_status')
    def test_is_job_terminal_false(self, mock_get_status):
        """Test is_job_terminal returns False for non-terminal states."""
        mock_get_status.return_value = "planned"
        assert not is_job_terminal(1)
        
        mock_get_status.return_value = "enqueued"
        assert not is_job_terminal(1)
        
        mock_get_status.return_value = "running"
        assert not is_job_terminal(1)
        
        mock_get_status.return_value = "failed"
        assert not is_job_terminal(1)
    
    @patch('src.utils.state_machine.get_job_status')
    def test_is_job_terminal_job_not_found(self, mock_get_status):
        """Test is_job_terminal when job is not found."""
        mock_get_status.return_value = None
        assert not is_job_terminal(1)


@pytest.mark.unit
class TestCancelJob:
    """Test cases for cancel_job function."""
    
    @patch('src.utils.state_machine.get_db')
    def test_cancel_job_success(self, mock_get_db):
        """Test successful job cancellation."""
        # Mock database session
        mock_db = MagicMock()
        mock_get_db.return_value.__enter__.return_value = mock_db
        
        # Mock job
        mock_job = MagicMock()
        mock_job.id = 1
        mock_job.status = "planned"
        
        # Mock query result
        mock_db.query.return_value.filter.return_value.with_for_update.return_value.first.return_value = mock_job
        
        # Cancel job
        result = cancel_job(1, "Test cancellation")
        
        # Verify job was cancelled
        assert mock_job.status == "cancelled"
        assert mock_job.error == "Test cancellation"
        assert mock_job.finished_at is not None
        mock_db.commit.assert_called_once()
        assert result == mock_job
    
    @patch('src.utils.state_machine.get_db')
    def test_cancel_job_not_cancellable(self, mock_get_db):
        """Test cancel_job when job is not cancellable."""
        # Mock database session
        mock_db = MagicMock()
        mock_get_db.return_value.__enter__.return_value = mock_db
        
        # Mock job in terminal state
        mock_job = MagicMock()
        mock_job.id = 1
        mock_job.status = "succeeded"
        
        # Mock query result
        mock_db.query.return_value.filter.return_value.with_for_update.return_value.first.return_value = mock_job
        
        # Should raise ValueError
        with pytest.raises(ValueError, match="cannot be cancelled"):
            cancel_job(1)


@pytest.mark.unit
class TestRetryJob:
    """Test cases for retry_job function."""
    
    @patch('src.utils.state_machine.get_db')
    def test_retry_job_success(self, mock_get_db):
        """Test successful job retry."""
        # Mock database session
        mock_db = MagicMock()
        mock_get_db.return_value.__enter__.return_value = mock_db
        
        # Mock job
        mock_job = MagicMock()
        mock_job.id = 1
        mock_job.status = "failed"
        mock_job.attempt = 2
        
        # Mock query result
        mock_db.query.return_value.filter.return_value.with_for_update.return_value.first.return_value = mock_job
        
        # Retry job
        result = retry_job(1, max_attempts=5)
        
        # Verify job was retried
        assert mock_job.status == "running"
        assert mock_job.started_at is not None
        assert mock_job.finished_at is None
        assert mock_job.error is None
        mock_db.commit.assert_called_once()
        assert result == mock_job
    
    @patch('src.utils.state_machine.get_db')
    def test_retry_job_max_attempts_exceeded(self, mock_get_db):
        """Test retry_job when max attempts exceeded."""
        # Mock database session
        mock_db = MagicMock()
        mock_get_db.return_value.__enter__.return_value = mock_db
        
        # Mock job with max attempts exceeded
        mock_job = MagicMock()
        mock_job.id = 1
        mock_job.status = "failed"
        mock_job.attempt = 5
        
        # Mock query result
        mock_db.query.return_value.filter.return_value.with_for_update.return_value.first.return_value = mock_job
        
        # Retry job
        result = retry_job(1, max_attempts=5)
        
        # Verify job moved to dead letter
        assert mock_job.status == "dead_letter"
        assert "Exceeded max attempts" in mock_job.error
        assert mock_job.finished_at is not None
        mock_db.commit.assert_called_once()
        assert result == mock_job
    
    @patch('src.utils.state_machine.get_db')
    def test_retry_job_not_retryable(self, mock_get_db):
        """Test retry_job when job is not retryable."""
        # Mock database session
        mock_db = MagicMock()
        mock_get_db.return_value.__enter__.return_value = mock_db
        
        # Mock job not in failed state
        mock_job = MagicMock()
        mock_job.id = 1
        mock_job.status = "running"
        
        # Mock query result
        mock_db.query.return_value.filter.return_value.with_for_update.return_value.first.return_value = mock_job
        
        # Should raise ValueError
        with pytest.raises(ValueError, match="cannot be retried"):
            retry_job(1)


@pytest.mark.unit
class TestGetJobsByStatus:
    """Test cases for get_jobs_by_status function."""
    
    @patch('src.utils.state_machine.get_db')
    def test_get_jobs_by_status(self, mock_get_db):
        """Test get_jobs_by_status function."""
        # Mock database session
        mock_db = MagicMock()
        mock_get_db.return_value.__enter__.return_value = mock_db
        
        # Mock jobs
        mock_jobs = [MagicMock(), MagicMock()]
        
        # Mock query result
        mock_db.query.return_value.filter.return_value.limit.return_value.all.return_value = mock_jobs
        
        # Get jobs by status
        result = get_jobs_by_status("running", limit=10)
        
        assert result == mock_jobs
        mock_db.query.return_value.filter.assert_called_once()
        mock_db.query.return_value.filter.return_value.limit.assert_called_once_with(10)


@pytest.mark.unit
class TestGetJobStatistics:
    """Test cases for get_job_statistics function."""
    
    @patch('src.utils.state_machine.get_db')
    def test_get_job_statistics(self, mock_get_db):
        """Test get_job_statistics function."""
        # Mock database session
        mock_db = MagicMock()
        mock_get_db.return_value.__enter__.return_value = mock_db
        
        # Mock query results for each status
        mock_db.query.return_value.filter.return_value.count.side_effect = [5, 3, 2, 1, 0, 0, 0]
        
        # Get job statistics
        result = get_job_statistics()
        
        # Verify statistics
        assert result["planned"] == 5
        assert result["enqueued"] == 3
        assert result["running"] == 2
        assert result["succeeded"] == 1
        assert result["failed"] == 0
        assert result["cancelled"] == 0
        assert result["dead_letter"] == 0
