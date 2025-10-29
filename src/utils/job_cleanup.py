"""Utilities for cleaning up orphaned jobs and re-enqueuing them."""

import logging
from datetime import datetime, timedelta
from typing import List

from src.database import get_db
from src.models import PublishJob
from src.utils.state_machine import PublishJobStatus, update_job_status
from src.tasks.publish import publish_post

logger = logging.getLogger(__name__)


def find_orphaned_enqueued_jobs(timeout_minutes: int = 5) -> List[PublishJob]:
    """
    Find jobs stuck in 'enqueued' state for longer than timeout_minutes.
    
    These are likely orphaned jobs that were created when Celery wasn't running,
    so the task was never actually enqueued to Redis.
    
    Args:
        timeout_minutes: How long a job can be enqueued before being considered orphaned
    
    Returns:
        List of orphaned PublishJob instances
    """
    cutoff_time = datetime.utcnow() - timedelta(minutes=timeout_minutes)
    
    with get_db() as db:
        orphaned_jobs = (
            db.query(PublishJob)
            .filter(
                PublishJob.status == PublishJobStatus.ENQUEUED.value,
                PublishJob.enqueued_at < cutoff_time,
                PublishJob.started_at.is_(None)  # Never started
            )
            .all()
        )
        
        return orphaned_jobs


def re_enqueue_orphaned_job(job: PublishJob) -> bool:
    """
    Re-enqueue an orphaned job to Celery.
    
    Args:
        job: The orphaned PublishJob instance
    
    Returns:
        True if successfully re-enqueued, False otherwise
    """
    try:
        logger.info(f"Re-enqueuing orphaned job {job.id}")
        
        # Re-enqueue the task
        publish_post.apply_async(kwargs={"job_id": str(job.id)})
        
        # Update enqueued_at timestamp
        with get_db() as db:
            job.enqueued_at = datetime.utcnow()
            job.updated_at = datetime.utcnow()
            db.commit()
        
        logger.info(f"Successfully re-enqueued orphaned job {job.id}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to re-enqueue job {job.id}: {str(e)}", exc_info=True)
        return False


def cleanup_orphaned_jobs(timeout_minutes: int = 5) -> dict:
    """
    Find and re-enqueue all orphaned jobs.
    
    Args:
        timeout_minutes: How long a job can be enqueued before being considered orphaned
    
    Returns:
        Dictionary with cleanup statistics
    """
    logger.info(f"Starting cleanup of orphaned jobs (timeout: {timeout_minutes} minutes)")
    
    orphaned_jobs = find_orphaned_enqueued_jobs(timeout_minutes)
    
    stats = {
        "found": len(orphaned_jobs),
        "re_enqueued": 0,
        "failed": 0,
        "job_ids": []
    }
    
    for job in orphaned_jobs:
        stats["job_ids"].append(job.id)
        if re_enqueue_orphaned_job(job):
            stats["re_enqueued"] += 1
        else:
            stats["failed"] += 1
    
    logger.info(
        f"Cleanup completed: found {stats['found']} orphaned jobs, "
        f"re-enqueued {stats['re_enqueued']}, failed {stats['failed']}"
    )
    
    return stats

