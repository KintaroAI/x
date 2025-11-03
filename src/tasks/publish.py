"""Celery tasks for publishing posts."""

import logging
import os
from datetime import datetime
from typing import Optional
import asyncio

from src.celery_app import app
from src.database import get_db
from src.models import PublishJob, Schedule, Post, PublishedPost, PostVariant
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
        # Get the job first to access its attempt count and schedule_id
        # Extract values while session is active to avoid detached instance error
        current_attempt = 0
        schedule_id = None
        with get_db() as db:
            job = db.query(PublishJob).filter(PublishJob.id == int(job_id)).first()
            if not job:
                logger.error(f"Job {job_id} not found")
                return {"status": "error", "message": "Job not found"}
            current_attempt = job.attempt  # Extract attempt while session is active
            schedule_id = job.schedule_id  # Extract schedule_id while session is active
        
        # Transition to running state atomically
        update_job_status(
            int(job_id), 
            PublishJobStatus.RUNNING.value,
            started_at=datetime.utcnow(),
            attempt=current_attempt + 1
        )
        
        # Get schedule and determine post content
        with get_db() as db:
            schedule = db.query(Schedule).filter(Schedule.id == schedule_id).first()
            if not schedule:
                raise ValueError(f"Schedule {schedule_id} not found")
            
            # Get job again to access variant_id
            job = db.query(PublishJob).filter(PublishJob.id == int(job_id)).first()
            if not job:
                raise ValueError(f"Job {job_id} not found")
            
            # VARIANT-BASED OR LEGACY POST-BASED (NEW)
            post_text = None
            media_refs = None
            variant_id = None
            post_id = None
            
            if job.variant_id:
                # New variant-based job
                variant = db.query(PostVariant).filter(
                    PostVariant.id == job.variant_id
                ).first()
                
                if not variant:
                    raise ValueError(
                        f"Variant {job.variant_id} not found for job {job_id}"
                    )
                
                post_text = variant.text
                media_refs = variant.media_refs
                variant_id = variant.id
                
                # Note: History is already created in scheduler_tick() with job_id,
                # so no need to update it here
                
                logger.info(f"Publishing variant {variant.id}: {post_text[:50]}...")
                
            elif schedule.post_id:
                # Legacy post-based schedule
                post = db.query(Post).filter(Post.id == schedule.post_id).first()
                if not post:
                    raise ValueError(f"Post {schedule.post_id} not found")
                
                if post.deleted:
                    raise ValueError(f"Post {post.id} is deleted")
                
                post_text = post.text
                media_refs = post.media_refs
                post_id = post.id
                
                logger.info(f"Publishing post {post.id}: {post_text[:50]}...")
            else:
                raise ValueError(
                    f"Schedule {schedule_id} has neither template_id nor post_id"
                )
            
            # Check if we're in dry run mode
            dry_run = os.getenv("DRY_RUN", "false").lower() == "true"
            
            # Parse media_refs if present
            media_ids = None
            if media_refs:
                try:
                    import json
                    media_refs_parsed = json.loads(media_refs)
                    # For now, just log media refs - actual media upload will be handled later
                    logger.info(f"Media refs found: {media_refs_parsed}")
                except Exception as e:
                    logger.warning(f"Failed to parse media_refs: {e}")
            
            # Publish to X using the new twitter API
            result = asyncio.run(create_twitter_post(post_text, media_ids, dry_run))
            
            if result.get("data", {}).get("id"):
                x_post_id = result["data"]["id"]
                
                # Check if PublishedPost already exists (idempotent - handles retries/re-enqueues)
                existing_published = db.query(PublishedPost).filter(
                    PublishedPost.x_post_id == x_post_id
                ).first()
                
                if existing_published:
                    logger.info(f"PublishedPost with x_post_id {x_post_id} already exists - skipping creation (idempotent)")
                else:
                    # Create published_post record only if it doesn't exist
                    # For variant-based posts: PublishedPost.variant_id tracks which variant was published
                    # This enables metrics/analytics per variant
                    # post_id is kept for backwards compatibility (may be NULL for variant-only posts)
                    published_post = PublishedPost(
                        post_id=post_id,
                        variant_id=variant_id,
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
                
                logger.info(f"Successfully published {'variant' if variant_id else 'post'} {variant_id or post_id} as X post {x_post_id}")
                
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
        
        # Try to transition to failed state atomically
        # Note: Can only transition to failed from "running" state
        # If error occurred before reaching "running", status is still "enqueued"
        # In that case, let Celery retry (will transition to "running" on retry)
        try:
            # Get current status to see if we can transition to failed
            with get_db() as db:
                job = db.query(PublishJob).filter(PublishJob.id == int(job_id)).first()
                if job and job.status == PublishJobStatus.RUNNING.value:
                    # We were in "running" state, can transition to "failed"
                    update_job_status(
                        int(job_id),
                        PublishJobStatus.FAILED.value,
                        error=str(e),
                        finished_at=datetime.utcnow()
                    )
                elif job and job.status == PublishJobStatus.ENQUEUED.value:
                    # Error happened before we transitioned to "running"
                    # Log error but don't change status - let Celery retry
                    logger.info(f"Error occurred while job {job_id} still enqueued - will retry via Celery")
                else:
                    # Job might be in terminal state already, or status is unexpected
                    logger.warning(f"Job {job_id} in unexpected status {job.status if job else 'not found'} - cannot update to failed")
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

