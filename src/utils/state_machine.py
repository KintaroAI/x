"""State machine for managing PublishJob state transitions."""

import logging
from datetime import datetime
from typing import Dict, List, Optional, Any
from enum import Enum

from src.database import get_db
from src.models import PublishJob

logger = logging.getLogger(__name__)


class PublishJobStatus(Enum):
    """Enum for PublishJob status values."""
    PLANNED = "planned"
    ENQUEUED = "enqueued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    DEAD_LETTER = "dead_letter"


class PublishJobStateMachine:
    """Manages state transitions for publish jobs with atomic updates."""
    
    # Define valid state transitions
    VALID_TRANSITIONS: Dict[str, List[str]] = {
        PublishJobStatus.PLANNED.value: [
            PublishJobStatus.ENQUEUED.value,
            PublishJobStatus.CANCELLED.value
        ],
        PublishJobStatus.ENQUEUED.value: [
            PublishJobStatus.RUNNING.value,
            PublishJobStatus.CANCELLED.value
        ],
        PublishJobStatus.RUNNING.value: [
            PublishJobStatus.SUCCEEDED.value,
            PublishJobStatus.FAILED.value
        ],
        PublishJobStatus.FAILED.value: [
            PublishJobStatus.RUNNING.value,  # retry
            PublishJobStatus.DEAD_LETTER.value  # give up
        ],
        PublishJobStatus.SUCCEEDED.value: [],  # terminal state
        PublishJobStatus.DEAD_LETTER.value: [],  # terminal state
        PublishJobStatus.CANCELLED.value: [],  # terminal state
    }
    
    # Terminal states (no further transitions allowed)
    TERMINAL_STATES = {
        PublishJobStatus.SUCCEEDED.value,
        PublishJobStatus.DEAD_LETTER.value,
        PublishJobStatus.CANCELLED.value
    }
    
    @classmethod
    def is_valid_transition(cls, from_status: str, to_status: str) -> bool:
        """Check if a state transition is valid."""
        if from_status not in cls.VALID_TRANSITIONS:
            logger.warning(f"Unknown from_status: {from_status}")
            return False
        
        return to_status in cls.VALID_TRANSITIONS[from_status]
    
    @classmethod
    def is_terminal_state(cls, status: str) -> bool:
        """Check if a status is a terminal state."""
        return status in cls.TERMINAL_STATES
    
    @classmethod
    def get_valid_transitions(cls, from_status: str) -> List[str]:
        """Get list of valid transitions from a given status."""
        return cls.VALID_TRANSITIONS.get(from_status, [])
    
    @classmethod
    def validate_transition(cls, from_status: str, to_status: str) -> None:
        """Validate a state transition and raise exception if invalid."""
        if not cls.is_valid_transition(from_status, to_status):
            valid_transitions = cls.get_valid_transitions(from_status)
            raise ValueError(
                f"Invalid state transition: {from_status} -> {to_status}. "
                f"Valid transitions from {from_status}: {valid_transitions}"
            )


def update_job_status(
    job_id: int, 
    new_status: str, 
    **kwargs: Any
) -> PublishJob:
    """
    Atomically update job status with database lock and state validation.
    
    Args:
        job_id: ID of the job to update
        new_status: New status to transition to
        **kwargs: Additional fields to update (e.g., error, finished_at)
    
    Returns:
        Updated PublishJob instance
        
    Raises:
        ValueError: If job not found or invalid transition
        Exception: If database operation fails
    """
    logger.info(f"Updating job {job_id} status: {new_status}")
    
    with get_db() as db:
        # Use SELECT FOR UPDATE to prevent race conditions
        job = db.query(PublishJob).filter(
            PublishJob.id == job_id
        ).with_for_update().first()
        
        if not job:
            raise ValueError(f"Job {job_id} not found")
        
        # Store old status for logging
        old_status = job.status
        
        # Validate the transition
        PublishJobStateMachine.validate_transition(old_status, new_status)
        
        # Update status and additional fields
        job.status = new_status
        job.updated_at = datetime.utcnow()
        
        # Update additional fields if provided
        for key, value in kwargs.items():
            if hasattr(job, key):
                setattr(job, key, value)
                logger.debug(f"Updated job {job_id} field {key}: {value}")
            else:
                logger.warning(f"Job {job_id} has no field {key}, skipping")
        
        # Commit the transaction
        db.commit()
        
        logger.info(f"Successfully updated job {job_id}: {old_status} -> {new_status}")
        return job


def get_job_status(job_id: int) -> Optional[str]:
    """
    Get the current status of a job.
    
    Args:
        job_id: ID of the job
        
    Returns:
        Current status string or None if job not found
    """
    with get_db() as db:
        job = db.query(PublishJob).filter(PublishJob.id == job_id).first()
        return job.status if job else None


def is_job_terminal(job_id: int) -> bool:
    """
    Check if a job is in a terminal state.
    
    Args:
        job_id: ID of the job
        
    Returns:
        True if job is in terminal state, False otherwise
    """
    status = get_job_status(job_id)
    if not status:
        return False
    
    return PublishJobStateMachine.is_terminal_state(status)


def cancel_job(job_id: int, reason: str = "Manual cancellation") -> PublishJob:
    """
    Cancel a job if it's in a cancellable state.
    
    Args:
        job_id: ID of the job to cancel
        reason: Reason for cancellation
        
    Returns:
        Updated PublishJob instance
        
    Raises:
        ValueError: If job not found or not cancellable
    """
    logger.info(f"Cancelling job {job_id}: {reason}")
    
    with get_db() as db:
        job = db.query(PublishJob).filter(
            PublishJob.id == job_id
        ).with_for_update().first()
        
        if not job:
            raise ValueError(f"Job {job_id} not found")
        
        # Check if job can be cancelled
        if not PublishJobStateMachine.is_valid_transition(job.status, PublishJobStatus.CANCELLED.value):
            raise ValueError(f"Job {job_id} in status {job.status} cannot be cancelled")
        
        # Update to cancelled status
        job.status = PublishJobStatus.CANCELLED.value
        job.error = reason
        job.finished_at = datetime.utcnow()
        job.updated_at = datetime.utcnow()
        
        db.commit()
        
        logger.info(f"Successfully cancelled job {job_id}")
        return job


def retry_job(job_id: int, max_attempts: int = 5) -> Optional[PublishJob]:
    """
    Retry a failed job if it hasn't exceeded max attempts.
    
    Args:
        job_id: ID of the job to retry
        max_attempts: Maximum number of attempts allowed
        
    Returns:
        Updated PublishJob instance or None if retry not possible
        
    Raises:
        ValueError: If job not found or not retryable
    """
    logger.info(f"Retrying job {job_id} (max attempts: {max_attempts})")
    
    with get_db() as db:
        job = db.query(PublishJob).filter(
            PublishJob.id == job_id
        ).with_for_update().first()
        
        if not job:
            raise ValueError(f"Job {job_id} not found")
        
        # Check if job can be retried
        if job.status != PublishJobStatus.FAILED.value:
            raise ValueError(f"Job {job_id} in status {job.status} cannot be retried")
        
        # Check if max attempts exceeded
        if job.attempt >= max_attempts:
            logger.warning(f"Job {job_id} exceeded max attempts ({job.attempt}/{max_attempts})")
            # Move to dead letter queue
            job.status = PublishJobStatus.DEAD_LETTER.value
            job.error = f"Exceeded max attempts ({job.attempt}/{max_attempts})"
            job.finished_at = datetime.utcnow()
            job.updated_at = datetime.utcnow()
            db.commit()
            return job
        
        # Reset for retry
        job.status = PublishJobStatus.RUNNING.value
        job.started_at = datetime.utcnow()
        job.finished_at = None  # Clear finished_at for retry
        job.error = None  # Clear previous error
        job.updated_at = datetime.utcnow()
        
        db.commit()
        
        logger.info(f"Successfully retried job {job_id} (attempt {job.attempt + 1})")
        return job


def get_jobs_by_status(status: str, limit: int = 100) -> List[PublishJob]:
    """
    Get jobs by status for monitoring and debugging.
    
    Args:
        status: Status to filter by
        limit: Maximum number of jobs to return
        
    Returns:
        List of PublishJob instances
    """
    with get_db() as db:
        return db.query(PublishJob).filter(
            PublishJob.status == status
        ).limit(limit).all()


def get_job_statistics() -> Dict[str, int]:
    """
    Get statistics about job statuses for monitoring.
    
    Returns:
        Dictionary with status counts
    """
    with get_db() as db:
        stats = {}
        for status in PublishJobStatus:
            count = db.query(PublishJob).filter(
                PublishJob.status == status.value
            ).count()
            stats[status.value] = count
        
        return stats
