"""Utilities for cleaning up orphaned jobs and re-enqueuing them."""

import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any

from src.database import get_db
from src.models import PublishJob
from src.utils.state_machine import PublishJobStatus
from src.tasks.publish import publish_post

logger = logging.getLogger(__name__)


def find_orphaned_enqueued_jobs(timeout_minutes: int = 5) -> List[int]:
    """
    Find job IDs stuck in 'enqueued' state for longer than timeout_minutes.
    
    These are likely orphaned jobs that were created when Celery wasn't running,
    so the task was never actually enqueued to Redis.
    
    Args:
        timeout_minutes: How long a job can be enqueued before being considered orphaned
    
    Returns:
        List of orphaned job IDs
    """
    cutoff_time = datetime.utcnow() - timedelta(minutes=timeout_minutes)
    
    with get_db() as db:
        # Query only IDs to avoid detached instance issues
        result = db.query(PublishJob.id).filter(
            PublishJob.status == PublishJobStatus.ENQUEUED.value,
            PublishJob.enqueued_at < cutoff_time,
            PublishJob.started_at.is_(None)  # Never started
        ).all()
        
        # Extract IDs from tuples - result is list of tuples like [(id1,), (id2,), ...]
        return [row[0] for row in result]


def re_enqueue_orphaned_job(job_id: int) -> bool:
    """
    Re-enqueue an orphaned job to Celery.
    
    Args:
        job_id: The ID of the orphaned job
    
    Returns:
        True if successfully re-enqueued, False otherwise
    """
    try:
        logger.info(f"Re-enqueuing orphaned job {job_id}")
        
        # Re-enqueue the task
        publish_post.apply_async(kwargs={"job_id": str(job_id)})
        
        # Update enqueued_at timestamp
        with get_db() as db:
            job = db.query(PublishJob).filter(PublishJob.id == job_id).first()
            if job:
                job.enqueued_at = datetime.utcnow()
                job.updated_at = datetime.utcnow()
                db.commit()
                logger.info(f"Successfully re-enqueued orphaned job {job_id}")
                return True
            else:
                logger.warning(f"Job {job_id} not found when trying to re-enqueue")
                return False
        
    except Exception as e:
        logger.error(f"Failed to re-enqueue job {job_id}: {str(e)}", exc_info=True)
        return False


def cleanup_orphaned_jobs(timeout_minutes: int = 5) -> Dict[str, Any]:
    """
    Find and re-enqueue all orphaned jobs.
    
    Args:
        timeout_minutes: How long a job can be enqueued before being considered orphaned
    
    Returns:
        Dictionary with cleanup statistics
    """
    logger.info(f"Starting cleanup of orphaned jobs (timeout: {timeout_minutes} minutes)")
    
    orphaned_job_ids = find_orphaned_enqueued_jobs(timeout_minutes)
    
    stats = {
        "found": len(orphaned_job_ids),
        "re_enqueued": 0,
        "failed": 0,
        "job_ids": []
    }
    
    # Process each job by ID (re-enqueue will create its own session)
    for job_id in orphaned_job_ids:
        stats["job_ids"].append(job_id)
        if re_enqueue_orphaned_job(job_id):
            stats["re_enqueued"] += 1
        else:
            stats["failed"] += 1
    
    logger.info(
        f"Cleanup completed: found {stats['found']} orphaned jobs, "
        f"re-enqueued {stats['re_enqueued']}, failed {stats['failed']}"
    )
    
    return stats

