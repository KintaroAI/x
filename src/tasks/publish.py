"""Celery tasks for publishing posts."""

import logging
import os
from datetime import datetime
from typing import Optional
import asyncio

from src.celery_app import app
from src.database import get_db
from src.models import PublishJob, Schedule, Post, PublishedPost
from src.api.twitter import create_twitter_post
from src.utils.redis_utils import acquire_dedupe_lock, release_dedupe_lock
from src.utils.state_machine import (
    update_job_status, 
    is_job_terminal, 
    get_job_status,
    PublishJobStatus,
    PublishJobStateMachine
)

logger = logging.getLogger(__name__)


@app.task(
    name="publish.post",
    queue="publish",
    acks_late=True,
    max_retries=5,
    retry_backoff=True,
    retry_jitter=True,
    rate_limit="5/m",  # Adjust based on X API limits
    task_ignore_result=True,
)
def publish_post(job_id: str):
    """Publish a post to X/Twitter."""
    logger.info(f"Starting publish job {job_id}")
    
    # CRITICAL: Early-exit idempotency check using state machine
    # If job is already in terminal state, skip processing to make retries harmless
    if is_job_terminal(int(job_id)):
        current_status = get_job_status(int(job_id))
        logger.info(f"Job {job_id} already completed with status: {current_status}")
        return {"status": "already_completed", "result": current_status}
    
    try:
        # Get the job first to access its attempt count
        with get_db() as db:
            job = db.query(PublishJob).filter(PublishJob.id == int(job_id)).first()
            if not job:
                logger.error(f"Job {job_id} not found")
                return {"status": "error", "message": "Job not found"}
        
        # Transition to running state atomically
        job = update_job_status(
            int(job_id), 
            PublishJobStatus.RUNNING.value,
            started_at=datetime.utcnow(),
            attempt=job.attempt + 1
        )
        
        # Get schedule and post data
        with get_db() as db:
            schedule = db.query(Schedule).filter(Schedule.id == job.schedule_id).first()
            if not schedule:
                raise ValueError(f"Schedule {job.schedule_id} not found")
            
            post = db.query(Post).filter(Post.id == schedule.post_id).first()
            if not post:
                raise ValueError(f"Post {schedule.post_id} not found")
            
            if post.deleted:
                raise ValueError(f"Post {post.id} is deleted")
            
            logger.info(f"Publishing post {post.id}: {post.text[:50]}...")
            
            # Check if we're in dry run mode
            dry_run = os.getenv("DRY_RUN", "false").lower() == "true"
            
            # Parse media_refs if present
            media_ids = None
            if post.media_refs:
                try:
                    import json
                    media_refs = json.loads(post.media_refs)
                    # For now, just log media refs - actual media upload will be handled later
                    logger.info(f"Media refs found: {media_refs}")
                except Exception as e:
                    logger.warning(f"Failed to parse media_refs: {e}")
            
            # Publish to X using the new twitter API
            result = asyncio.run(create_twitter_post(post.text, media_ids, dry_run))
            
            if result.get("data", {}).get("id"):
                x_post_id = result["data"]["id"]
                
                # Create published_post record
                published_post = PublishedPost(
                    post_id=post.id,
                    x_post_id=x_post_id,
                    published_at=datetime.utcnow(),
                    url=f"https://x.com/i/web/status/{x_post_id}"
                )
                db.add(published_post)
                db.commit()
                
                # Transition to succeeded state atomically
                update_job_status(
                    int(job_id),
                    PublishJobStatus.SUCCEEDED.value,
                    finished_at=datetime.utcnow()
                )
                
                logger.info(f"Successfully published post {post.id} as X post {x_post_id}")
                
                # Schedule metrics collection
                # TODO: Implement metrics task
                # from src.tasks.metrics import capture_metrics
                # capture_metrics.apply_async(
                #     kwargs={"x_post_id": x_post_id, "stage": "fast"},
                #     countdown=60  # Start collecting metrics after 1 minute
                # )
                
            else:
                raise ValueError("No post ID returned from X API")
            
    except Exception as e:
        logger.error(f"Failed to publish job {job_id}: {str(e)}")
        
        # Transition to failed state atomically
        try:
            update_job_status(
                int(job_id),
                PublishJobStatus.FAILED.value,
                error=str(e),
                finished_at=datetime.utcnow()
            )
        except Exception as state_error:
            logger.error(f"Failed to update job status to failed: {state_error}")
        
        # Re-raise to trigger Celery retry
        raise
    
    finally:
        # Release dedupe lock
        try:
            with get_db() as db:
                job = db.query(PublishJob).filter(PublishJob.id == job_id).first()
                if job:
                    release_dedupe_lock(job.schedule_id, job.planned_at)
        except Exception as e:
            logger.warning(f"Failed to release dedupe lock: {e}")
    
    return {"status": "success", "job_id": job_id}

