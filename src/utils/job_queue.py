"""Shared helpers for enqueuing publish jobs consistently."""

import logging
from datetime import datetime
from typing import Optional

from src.celery_app import app
from src.database import get_db
from src.models import PublishJob
from src.utils.state_machine import PublishJobStatus
from src.tasks.publish import publish_post

logger = logging.getLogger(__name__)


def enqueue_publish_job(job_id: int, eta: Optional[datetime] = None) -> bool:
    """
    Enqueue the publish task for the given job and mark it enqueued.
    If eta is provided, schedule for that time; otherwise enqueue immediately.

    Returns True if enqueued and DB updated, False otherwise.
    """
    try:
        # Enqueue task
        if eta is not None:
            publish_post.apply_async(kwargs={"job_id": str(job_id)}, eta=eta)
        else:
            publish_post.apply_async(kwargs={"job_id": str(job_id)})

        # Update DB: set status=enqueued and enqueued_at
        with get_db() as db:
            job = db.query(PublishJob).filter(PublishJob.id == job_id).first()
            if not job:
                logger.warning(f"enqueue_publish_job: job {job_id} not found after enqueue")
                return False
            # Only transition from planned to enqueued
            if job.status == PublishJobStatus.PLANNED.value:
                job.status = PublishJobStatus.ENQUEUED.value
                job.enqueued_at = datetime.utcnow()
                job.updated_at = datetime.utcnow()
                db.commit()
                logger.info(f"Enqueued job {job_id} (eta={eta})")
                return True
            # If already enqueued/running/etc., don't overwrite
            logger.info(f"enqueue_publish_job: job {job_id} status is {job.status} - no update")
            return True
    except Exception as e:
        logger.error(f"enqueue_publish_job failed for job {job_id}: {e}", exc_info=True)
        return False


