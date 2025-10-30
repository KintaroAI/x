"""Utilities for cleaning up orphaned jobs and re-enqueuing them."""

import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any

from src.database import get_db
from src.models import PublishJob
from src.utils.state_machine import PublishJobStatus
from src.tasks.publish import publish_post
from src.utils.job_queue import enqueue_publish_job
from src.utils.redis_utils import get_redis_client

logger = logging.getLogger(__name__)


def find_orphaned_enqueued_jobs(timeout_minutes: int = 5, re_enqueue_cooldown_minutes: int = 1) -> List[int]:
    """
    Find job IDs stuck in 'enqueued' state for longer than timeout_minutes.
    
    These are likely orphaned jobs that were created when Celery wasn't running,
    so the task was never actually enqueued to Redis.
    
    Args:
        timeout_minutes: How long a job can be enqueued before being considered orphaned
        re_enqueue_cooldown_minutes: Don't re-enqueue if enqueued_at was updated recently (to prevent duplicates)
    
    Returns:
        List of orphaned job IDs
    """
    cutoff_time = datetime.utcnow() - timedelta(minutes=timeout_minutes)
    cooldown_time = datetime.utcnow() - timedelta(minutes=re_enqueue_cooldown_minutes)
    
    with get_db() as db:
        # Query only IDs to avoid detached instance issues
        # Additional check: enqueued_at must be OLD (before cutoff) but not TOO RECENTLY updated
        # This prevents re-enqueuing jobs that were just re-enqueued by another cleanup run
        result = db.query(PublishJob.id).filter(
            PublishJob.status == PublishJobStatus.ENQUEUED.value,
            PublishJob.enqueued_at < cutoff_time,  # Stuck for > timeout_minutes
            PublishJob.enqueued_at < cooldown_time,  # Not updated in last cooldown period (prevents race)
            PublishJob.started_at.is_(None),  # Never started
            PublishJob.updated_at < cooldown_time  # Also check updated_at to prevent recent cleanup
        ).all()
        
        # Extract IDs from tuples - result is list of tuples like [(id1,), (id2,), ...]
        return [row[0] for row in result]


def re_enqueue_orphaned_job(job_id: int) -> bool:
    """
    Re-enqueue an orphaned job to Celery with deduplication guards.
    
    Uses Redis lock to prevent multiple cleanup tasks from re-enqueuing the same job.
    Also double-checks job status before re-enqueuing.
    
    Args:
        job_id: The ID of the orphaned job
    
    Returns:
        True if successfully re-enqueued, False otherwise
    """
    redis_client = get_redis_client()
    lock_key = f"cleanup_lock:job:{job_id}"
    lock_ttl = 300  # 5 minutes lock to prevent concurrent re-enqueues
    
    try:
        # Acquire Redis lock to prevent duplicate re-enqueues
        if not redis_client.set(lock_key, "1", nx=True, ex=lock_ttl):
            logger.warning(f"Job {job_id} already has cleanup lock - skipping re-enqueue")
            return False
        
        # Double-check job is still orphaned before re-enqueuing
        with get_db() as db:
            job = db.query(PublishJob).filter(PublishJob.id == job_id).first()
            if not job:
                logger.warning(f"Job {job_id} not found when trying to re-enqueue")
                redis_client.delete(lock_key)
                return False
            
            # Check if job is still in enqueued state and hasn't started
            if job.status != PublishJobStatus.ENQUEUED.value:
                logger.info(f"Job {job_id} is no longer enqueued (status: {job.status}) - skipping")
                redis_client.delete(lock_key)
                return False
            
            if job.started_at is not None:
                logger.info(f"Job {job_id} has started_at set - already processing - skipping")
                redis_client.delete(lock_key)
                return False
            
            # Check if enqueued_at was updated recently (within last minute) - another cleanup might have done it
            one_minute_ago = datetime.utcnow() - timedelta(minutes=1)
            if job.enqueued_at and job.enqueued_at > one_minute_ago:
                logger.info(f"Job {job_id} was recently enqueued (at {job.enqueued_at}) - skipping to prevent duplicate")
                redis_client.delete(lock_key)
                return False
        
        logger.info(f"Re-enqueuing orphaned job {job_id}")
        
        # Re-enqueue via helper (updates status and enqueued_at)
        success = enqueue_publish_job(job_id)
        if success:
            logger.info(f"Successfully re-enqueued orphaned job {job_id}")
        else:
            logger.warning(f"Failed to re-enqueue orphaned job {job_id}")
        # Release lock after attempt
        redis_client.delete(lock_key)
        return success
        
    except Exception as e:
        logger.error(f"Failed to re-enqueue job {job_id}: {str(e)}", exc_info=True)
        # Release lock on error
        try:
            redis_client.delete(lock_key)
        except:
            pass
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

    # NEW: Also find planned jobs whose planned_at is due (<= now)
    due_planned_job_ids = find_due_planned_jobs()

    stats = {
        "found": len(orphaned_job_ids),
        "re_enqueued": 0,
        "failed": 0,
        "job_ids": [],
        # Extended stats
        "planned_found": len(due_planned_job_ids),
        "planned_enqueued": 0,
        "planned_failed": 0,
        "planned_job_ids": [],
    }

    # Process orphaned enqueued jobs
    for job_id in orphaned_job_ids:
        stats["job_ids"].append(job_id)
        if re_enqueue_orphaned_job(job_id):
            stats["re_enqueued"] += 1
        else:
            stats["failed"] += 1

    # Process due planned jobs: enqueue and mark enqueued
    for job_id in due_planned_job_ids:
        stats["planned_job_ids"].append(job_id)
        if enqueue_planned_job(job_id):
            stats["planned_enqueued"] += 1
        else:
            stats["planned_failed"] += 1

    logger.info(
        (
            f"Cleanup completed: found {stats['found']} orphaned jobs, "
            f"re-enqueued {stats['re_enqueued']}, failed {stats['failed']}; "
            f"planned due: {stats['planned_found']}, "
            f"planned enqueued: {stats['planned_enqueued']}, planned failed: {stats['planned_failed']}"
        )
    )

    return stats


def find_due_planned_jobs() -> List[int]:
    """Return IDs of PublishJobs with status 'planned' and planned_at <= now."""
    now = datetime.utcnow()
    with get_db() as db:
        result = db.query(PublishJob.id).filter(
            PublishJob.status == PublishJobStatus.PLANNED.value,
            PublishJob.planned_at <= now,
        ).all()
        return [row[0] for row in result]


def enqueue_planned_job(job_id: int) -> bool:
    """
    Enqueue a planned job that is due, and mark it as enqueued.

    Returns True on success, False otherwise.
    """
    try:
        # Double-check status before enqueue
        with get_db() as db:
            job = db.query(PublishJob).filter(PublishJob.id == job_id).first()
            if not job:
                logger.warning(f"Planned job {job_id} not found")
                return False
            if job.status != PublishJobStatus.PLANNED.value:
                logger.info(
                    f"Job {job_id} no longer planned (status: {job.status}) - skipping"
                )
                return False

        # Enqueue immediately (planned time already due) using helper
        if enqueue_publish_job(job_id):
            logger.info(f"Enqueued planned job {job_id}")
            return True
        else:
            logger.warning(f"Failed to enqueue planned job {job_id}")
            return False
    except Exception as e:
        logger.error(f"Failed to enqueue planned job {job_id}: {str(e)}", exc_info=True)
        return False

