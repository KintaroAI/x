"""Post CRUD API endpoints."""

import json
import logging
from datetime import datetime, timedelta
from typing import Optional
import pytz

from fastapi import Form
from fastapi.responses import HTMLResponse, JSONResponse

from src.models import Post, Schedule
from src.database import get_db
from src.audit import log_info, log_error
from src.services.scheduler_service import ScheduleResolver
from src.utils.timezone_utils import get_default_timezone, format_datetime_with_timezone

logger = logging.getLogger(__name__)


def create_or_update_schedule(
    db,
    post_id: int,
    schedule_type: Optional[str] = None,
    cron_expression: Optional[str] = None,
    one_shot_datetime: Optional[str] = None,
    rrule_expression: Optional[str] = None,
    timezone: Optional[str] = None
) -> Optional[Schedule]:
    """
    Create or update a schedule for a post.
    
    Args:
        db: Database session
        post_id: ID of the post
        schedule_type: 'none', 'one_shot', 'cron', or 'rrule'
        cron_expression: Cron expression string (for cron type)
        one_shot_datetime: ISO datetime string (for one_shot type)
        rrule_expression: RRULE string (for rrule type, e.g., "FREQ=DAILY;INTERVAL=1")
        timezone: Timezone string (for cron and rrule types)
    
    Returns:
        Schedule instance if created/updated, None if cleared
    """
    # Get existing schedule for this post
    existing_schedule = db.query(Schedule).filter(Schedule.post_id == post_id).first()
    
    # If schedule_type is 'none', clear/disable the schedule
    if schedule_type == "none" or not schedule_type:
        if existing_schedule:
            # Clear next_run_at and disable schedule
            existing_schedule.next_run_at = None
            existing_schedule.enabled = False
            existing_schedule.updated_at = datetime.utcnow()
            logger.info(f"Cleared schedule {existing_schedule.id} for post {post_id}")
            return existing_schedule
        return None
    
    # Validate schedule type
    if schedule_type not in ["one_shot", "cron", "rrule"]:
        raise ValueError(f"Invalid schedule_type: {schedule_type}")
    
    resolver = ScheduleResolver()
    
    # Prepare schedule data
    if schedule_type == "one_shot":
        if not one_shot_datetime:
            raise ValueError("one_shot_datetime is required for one_shot schedule")
        
        # Parse datetime string from form (datetime-local format: YYYY-MM-DDTHH:MM)
        # datetime-local doesn't include timezone, so we interpret it in the default timezone
        try:
            # Get default timezone
            default_tz = get_default_timezone()
            
            # Parse datetime-local format (YYYY-MM-DDTHH:MM) - this is naive
            dt_naive = datetime.fromisoformat(one_shot_datetime)
            if dt_naive.tzinfo is not None:
                # Shouldn't happen with datetime-local, but handle it
                dt_naive = dt_naive.replace(tzinfo=None)
            
            # Interpret the datetime in the default timezone
            tz = pytz.timezone(default_tz)
            dt_local = tz.localize(dt_naive)
            
            # Convert to UTC for storage (as naive UTC datetime)
            dt_utc = dt_local.astimezone(pytz.UTC).replace(tzinfo=None)
            
            # Store as ISO string (in UTC) but remember the timezone
            schedule_spec = dt_utc.isoformat()
            schedule_timezone = default_tz
        except ValueError as e:
            raise ValueError(f"Invalid datetime format: {e}. Expected format: YYYY-MM-DDTHH:MM")
    
    elif schedule_type == "cron":
        if not cron_expression:
            raise ValueError("cron_expression is required for cron schedule")
        
        schedule_spec = cron_expression.strip()
        schedule_timezone = timezone or get_default_timezone()
    
    elif schedule_type == "rrule":
        if not rrule_expression:
            raise ValueError("rrule_expression is required for rrule schedule")
        
        schedule_spec = rrule_expression.strip()
        schedule_timezone = timezone or get_default_timezone()
    
    # Create or update schedule
    if existing_schedule:
        # Update existing schedule
        existing_schedule.kind = schedule_type
        existing_schedule.schedule_spec = schedule_spec
        existing_schedule.timezone = schedule_timezone
        existing_schedule.enabled = True
        existing_schedule.updated_at = datetime.utcnow()
        
        # Recalculate next_run_at using ScheduleResolver
        # Create a temporary schedule object with updated values for resolution
        temp_schedule = Schedule(
            kind=schedule_type,
            schedule_spec=schedule_spec,
            timezone=schedule_timezone
        )
        next_run_at = resolver.resolve_schedule(temp_schedule)
        
        if next_run_at:
            existing_schedule.next_run_at = next_run_at
            logger.info(f"Updated schedule {existing_schedule.id} for post {post_id}, next_run_at: {next_run_at}")
        else:
            # If resolution fails, clear next_run_at and disable
            existing_schedule.next_run_at = None
            existing_schedule.enabled = False
            logger.warning(f"Could not resolve schedule {existing_schedule.id} for post {post_id}, disabled")
        
        return existing_schedule
    else:
        # Create new schedule
        new_schedule = Schedule(
            post_id=post_id,
            kind=schedule_type,
            schedule_spec=schedule_spec,
            timezone=schedule_timezone,
            enabled=True,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        
        # Calculate next_run_at
        next_run_at = resolver.resolve_schedule(new_schedule)
        
        if next_run_at:
            new_schedule.next_run_at = next_run_at
            logger.info(f"Created schedule for post {post_id}, next_run_at: {next_run_at}")
        else:
            # If resolution fails, disable schedule
            new_schedule.enabled = False
            logger.warning(f"Could not resolve schedule for post {post_id}, created disabled")
        
        db.add(new_schedule)
        return new_schedule


async def get_posts(include_deleted: bool = False):
    """Get all posts. Optionally include deleted posts."""
    try:
        logger.debug(f"get_posts called, include_deleted={include_deleted}")
        
        with get_db() as db:
            query = db.query(Post)
            
            if not include_deleted:
                query = query.filter(Post.deleted == False)
            
            posts = query.order_by(Post.created_at.desc()).all()
            
            result = [
                {
                    "id": post.id,
                    "text": post.text,
                    "media_refs": post.media_refs,
                    "deleted": post.deleted,
                    "created_at": post.created_at.isoformat(),
                    "updated_at": post.updated_at.isoformat(),
                }
                for post in posts
            ]
            
            logger.info(f"Retrieved {len(result)} posts (include_deleted={include_deleted})")
            return result
    
    except Exception as e:
        logger.error(f"Unexpected error in get_posts: {str(e)}", exc_info=True)
        log_error(
            action="posts_fetch_exception",
            message=f"Exception while fetching posts",
            component="api",
            extra_data=json.dumps({"error": str(e), "error_type": type(e).__name__})
        )
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )


async def create_post(
    text: str = Form(...),
    media_refs: str = Form(None),
    schedule_type: str = Form("none"),
    cron_expression: str = Form(None),
    one_shot_datetime: str = Form(None),
    rrule_expression: str = Form(None),
    schedule_timezone: str = Form(None)
):
    """Create a new post (draft) with optional schedule."""
    try:
        logger.debug(f"create_post called with text length: {len(text)}, schedule_type: {schedule_type}")
        
        # Validate text
        if not text or len(text.strip()) == 0:
            log_error(
                action="post_create_empty",
                message="Attempted to create post with empty text",
                component="api",
                extra_data=json.dumps({"text_length": len(text) if text else 0})
            )
            return JSONResponse(
                status_code=400,
                content={"error": "Post text cannot be empty"}
            )
        
        # Parse media_refs if provided
        media_data = None
        if media_refs:
            try:
                media_data = json.loads(media_refs)
                if not isinstance(media_data, list):
                    raise ValueError("media_refs must be a JSON array")
            except json.JSONDecodeError as e:
                log_error(
                    action="post_create_invalid_media",
                    message="Failed to parse media_refs JSON",
                    component="api",
                    extra_data=json.dumps({"error": str(e)})
                )
                return JSONResponse(
                    status_code=400,
                    content={"error": "media_refs must be a valid JSON array"}
                )
        
        # Create post in database
        with get_db() as db:
            post = Post(
                text=text.strip(),
                media_refs=json.dumps(media_data) if media_data else None,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            db.add(post)
            db.flush()  # Get post.id before creating schedule
            
            # Create or update schedule if provided
            schedule_created = False
            schedule_info = ""
            try:
                if schedule_type and schedule_type != "none":
                    schedule = create_or_update_schedule(
                        db=db,
                        post_id=post.id,
                        schedule_type=schedule_type,
                        cron_expression=cron_expression if cron_expression else None,
                        one_shot_datetime=one_shot_datetime if one_shot_datetime else None,
                        rrule_expression=rrule_expression if rrule_expression else None,
                        timezone=schedule_timezone if schedule_timezone else None
                    )
                    if schedule:
                        schedule_created = True
                        if schedule.next_run_at:
                            next_run_str = format_datetime_with_timezone(schedule.next_run_at, schedule.timezone)
                        else:
                            next_run_str = "N/A"
                        schedule_info = f"<p class='text-sm'>Schedule: {schedule.kind}, Next run: {next_run_str}</p>"
            except Exception as schedule_error:
                logger.warning(f"Error creating schedule: {schedule_error}")
                # Don't fail post creation if schedule creation fails
                schedule_info = f"<p class='text-sm text-orange-600'>Warning: Could not create schedule: {schedule_error}</p>"
            
            db.commit()
            db.refresh(post)
            
            logger.info(f"Created new post with id: {post.id}, schedule_created: {schedule_created}")
            log_info(
                action="post_created",
                message=f"Created new post with id {post.id}",
                component="api",
                extra_data=json.dumps({
                    "post_id": post.id,
                    "text_length": len(text),
                    "has_media": media_data is not None,
                    "schedule_type": schedule_type if schedule_type != "none" else None
                })
            )
            
            # Return success response
            return HTMLResponse(
                f"""
                <div class="bg-green-50 border border-green-200 text-green-800 px-4 py-3 rounded-lg">
                    <h3 class="font-semibold mb-2">✓ Post Created Successfully</h3>
                    <p class="text-sm">Post ID: {post.id}</p>
                    <p class="text-sm">Created at: {post.created_at.strftime('%Y-%m-%d %H:%M:%S')}</p>
                    {schedule_info}
                </div>
                """
            )
    
    except Exception as e:
        logger.error(f"Unexpected error in create_post: {str(e)}", exc_info=True)
        log_error(
            action="post_create_exception",
            message=f"Exception while creating post",
            component="api",
            extra_data=json.dumps({"error": str(e), "error_type": type(e).__name__})
        )
        return HTMLResponse(
            f"""
            <div class="bg-red-50 border border-red-200 text-red-800 px-4 py-3 rounded-lg">
                <h3 class="font-semibold mb-2">✗ Error Creating Post</h3>
                <p class="text-sm">{str(e)}</p>
            </div>
            """
        )


async def update_post(
    post_id: int,
    text: str = Form(...),
    media_refs: str = Form(None),
    schedule_type: str = Form("none"),
    cron_expression: str = Form(None),
    one_shot_datetime: str = Form(None),
    rrule_expression: str = Form(None),
    schedule_timezone: str = Form(None)
):
    """Update an existing post and its schedule."""
    try:
        logger.debug(f"update_post called with post_id: {post_id}, text length: {len(text)}, schedule_type: {schedule_type}")
        
        # Validate text
        if not text or len(text.strip()) == 0:
            log_error(
                action="post_update_empty",
                message="Attempted to update post with empty text",
                component="api",
                extra_data=json.dumps({"post_id": post_id, "text_length": len(text) if text else 0})
            )
            return HTMLResponse(
                """
                <div class="bg-red-50 border border-red-200 text-red-800 px-4 py-3 rounded-lg">
                    <h3 class="font-semibold mb-2">✗ Error Updating Post</h3>
                    <p class="text-sm">Post text cannot be empty</p>
                </div>
                """
            )
        
        # Parse media_refs if provided
        media_data = None
        if media_refs:
            try:
                media_data = json.loads(media_refs)
                if not isinstance(media_data, list):
                    raise ValueError("media_refs must be a JSON array")
            except json.JSONDecodeError as e:
                log_error(
                    action="post_update_invalid_media",
                    message="Failed to parse media_refs JSON",
                    component="api",
                    extra_data=json.dumps({"post_id": post_id, "error": str(e)})
                )
                return HTMLResponse(
                    """
                    <div class="bg-red-50 border border-red-200 text-red-800 px-4 py-3 rounded-lg">
                        <h3 class="font-semibold mb-2">✗ Error Updating Post</h3>
                        <p class="text-sm">media_refs must be a valid JSON array</p>
                    </div>
                    """
                )
        
        with get_db() as db:
            post = db.query(Post).filter(Post.id == post_id, Post.deleted == False).first()
            
            if not post:
                log_error(
                    action="post_update_not_found",
                    message=f"Attempted to update non-existent post {post_id}",
                    component="api",
                    extra_data=json.dumps({"post_id": post_id})
                )
                return HTMLResponse(
                    """
                    <div class="bg-red-50 border border-red-200 text-red-800 px-4 py-3 rounded-lg">
                        <h3 class="font-semibold mb-2">✗ Error Updating Post</h3>
                        <p class="text-sm">Post not found</p>
                    </div>
                    """
                )
            
            # Update post
            post.text = text.strip()
            post.media_refs = json.dumps(media_data) if media_data else None
            post.updated_at = datetime.utcnow()
            
            # Update schedule if provided
            schedule_updated = False
            schedule_info = ""
            try:
                schedule = create_or_update_schedule(
                    db=db,
                    post_id=post_id,
                    schedule_type=schedule_type,
                    cron_expression=cron_expression if cron_expression else None,
                    one_shot_datetime=one_shot_datetime if one_shot_datetime else None,
                    rrule_expression=rrule_expression if rrule_expression else None,
                    timezone=schedule_timezone if schedule_timezone else None
                )
                if schedule:
                    schedule_updated = True
                    if schedule_type == "none":
                        schedule_info = f"<p class='text-sm'>Schedule cleared (disabled)</p>"
                    else:
                        if schedule.next_run_at:
                            next_run_str = format_datetime_with_timezone(schedule.next_run_at, schedule.timezone)
                        else:
                            next_run_str = "N/A"
                        schedule_info = f"<p class='text-sm'>Schedule: {schedule.kind}, Next run: {next_run_str}</p>"
            except Exception as schedule_error:
                logger.warning(f"Error updating schedule: {schedule_error}")
                # Don't fail post update if schedule update fails
                schedule_info = f"<p class='text-sm text-orange-600'>Warning: Could not update schedule: {schedule_error}</p>"
            
            db.commit()
            
            logger.info(f"Updated post with id: {post_id}, schedule_updated: {schedule_updated}")
            log_info(
                action="post_updated",
                message=f"Updated post with id {post_id}",
                component="api",
                extra_data=json.dumps({
                    "post_id": post_id,
                    "text_length": len(text),
                    "has_media": media_data is not None,
                    "schedule_type": schedule_type if schedule_type != "none" else None
                })
            )
            
            # Return success response
            return HTMLResponse(
                f"""
                <div class="bg-green-50 border border-green-200 text-green-800 px-4 py-3 rounded-lg">
                    <h3 class="font-semibold mb-2">✓ Post Updated Successfully</h3>
                    <p class="text-sm">Post ID: {post.id}</p>
                    <p class="text-sm">Updated at: {post.updated_at.strftime('%Y-%m-%d %H:%M:%S')}</p>
                    {schedule_info}
                </div>
                """
            )
    
    except Exception as e:
        logger.error(f"Unexpected error in update_post: {str(e)}", exc_info=True)
        log_error(
            action="post_update_exception",
            message=f"Exception while updating post",
            component="api",
            extra_data=json.dumps({"post_id": post_id, "error": str(e), "error_type": type(e).__name__})
        )
        return HTMLResponse(
            f"""
            <div class="bg-red-50 border border-red-200 text-red-800 px-4 py-3 rounded-lg">
                <h3 class="font-semibold mb-2">✗ Error Updating Post</h3>
                <p class="text-sm">{str(e)}</p>
            </div>
            """
        )


async def delete_post(post_id: int):
    """Soft delete a post by marking it as deleted."""
    try:
        logger.debug(f"delete_post called with post_id: {post_id}")
        
        from src.models import Schedule, PublishJob
        
        with get_db() as db:
            post = db.query(Post).filter(Post.id == post_id).first()
            
            if not post:
                logger.warning(f"Post not found: {post_id}")
                log_error(
                    action="post_delete_not_found",
                    message=f"Attempted to delete non-existent post {post_id}",
                    component="api",
                    extra_data=json.dumps({"post_id": post_id})
                )
                return JSONResponse(
                    status_code=404,
                    content={"error": "Post not found"}
                )
            
            # Soft delete - just mark as deleted
            post.deleted = True
            post.updated_at = datetime.utcnow()
            
            # Cancel all non-terminal jobs related to this post
            schedules = db.query(Schedule).filter(Schedule.post_id == post_id).all()
            cancelled_count = 0
            
            # Terminal states are: succeeded, failed, cancelled, dead_letter
            terminal_states = {"succeeded", "failed", "cancelled", "dead_letter"}
            
            for schedule in schedules:
                # Update all non-terminal publish jobs to cancelled
                # Only cancel jobs that are: planned, enqueued, or running
                cancellable_jobs = db.query(PublishJob).filter(
                    PublishJob.schedule_id == schedule.id,
                    ~PublishJob.status.in_(terminal_states)
                ).all()
                
                for job in cancellable_jobs:
                    job.status = "cancelled"
                    job.updated_at = datetime.utcnow()
                    job.finished_at = datetime.utcnow()
                    cancelled_count += 1
                    logger.info(f"Cancelled publish job {job.id} for deleted post {post_id}")
            
            db.commit()
            
            extra_data = {"post_id": post_id, "cancelled_jobs": cancelled_count}
            logger.info(f"Soft deleted post with id: {post_id}, cancelled {cancelled_count} active jobs")
            
            log_info(
                action="post_deleted",
                message=f"Soft deleted post with id {post_id}, cancelled {cancelled_count} active jobs",
                component="api",
                extra_data=json.dumps(extra_data)
            )
            
            return {
                "id": post.id,
                "deleted": True,
                "cancelled_jobs": cancelled_count,
                "message": "Post deleted successfully"
            }
    
    except Exception as e:
        logger.error(f"Unexpected error in delete_post: {str(e)}", exc_info=True)
        log_error(
            action="post_delete_exception",
            message=f"Exception while deleting post",
            component="api",
            extra_data=json.dumps({"post_id": post_id, "error": str(e), "error_type": type(e).__name__})
        )
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )


async def restore_post(post_id: int):
    """Restore a deleted post by marking it as not deleted."""
    try:
        logger.debug(f"restore_post called with post_id: {post_id}")
        
        with get_db() as db:
            post = db.query(Post).filter(Post.id == post_id).first()
            
            if not post:
                logger.warning(f"Post not found: {post_id}")
                log_error(
                    action="post_restore_not_found",
                    message=f"Attempted to restore non-existent post {post_id}",
                    component="api",
                    extra_data=json.dumps({"post_id": post_id})
                )
                return JSONResponse(
                    status_code=404,
                    content={"error": "Post not found"}
                )
            
            # Restore post - mark as not deleted
            post.deleted = False
            post.updated_at = datetime.utcnow()
            db.commit()
            
            logger.info(f"Restored post with id: {post_id}")
            log_info(
                action="post_restored",
                message=f"Restored post with id {post_id}",
                component="api",
                extra_data=json.dumps({"post_id": post_id})
            )
            
            return {
                "id": post.id,
                "deleted": False,
                "message": "Post restored successfully"
            }
    
    except Exception as e:
        logger.error(f"Unexpected error in restore_post: {str(e)}", exc_info=True)
        log_error(
            action="post_restore_exception",
            message=f"Exception while restoring post",
            component="api",
            extra_data=json.dumps({"post_id": post_id, "error": str(e), "error_type": type(e).__name__})
        )
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )


async def instant_publish(post_id: int):
    """Create an instant publish job for a post and enqueue it immediately."""
    try:
        logger.debug(f"instant_publish called with post_id: {post_id}")
        
        from src.models import Schedule, PublishJob
        from src.tasks.publish import publish_post
        from src.utils.state_machine import PublishJobStatus
        
        with get_db() as db:
            # Get the post
            post = db.query(Post).filter(Post.id == post_id, Post.deleted == False).first()
            
            if not post:
                logger.warning(f"Post not found: {post_id}")
                log_error(
                    action="instant_publish_post_not_found",
                    message=f"Attempted to publish non-existent post {post_id}",
                    component="api",
                    extra_data=json.dumps({"post_id": post_id})
                )
                return JSONResponse(
                    status_code=404,
                    content={"error": "Post not found"}
                )
            
            # Get or create a schedule for this post
            schedule = db.query(Schedule).filter(Schedule.post_id == post_id).first()
            
            if not schedule:
                # Create an instant schedule
                schedule = Schedule(
                    post_id=post_id,
                    kind="one_shot",
                    schedule_spec=datetime.utcnow().isoformat(),
                    timezone="UTC",
                    next_run_at=datetime.utcnow(),
                    enabled=True
                )
                db.add(schedule)
                db.commit()
                db.refresh(schedule)
                logger.info(f"Created new schedule for post {post_id}")
            
            # Block if ANY non-terminal job exists for this schedule (no time window)
            terminal_states = {"cancelled", "succeeded", "failed", "dead_letter"}
            existing_active_job = (
                db.query(PublishJob)
                .filter(
                    PublishJob.schedule_id == schedule.id,
                    ~PublishJob.status.in_(terminal_states)
                )
                .order_by(PublishJob.planned_at.desc())
                .first()
            )
            
            if existing_active_job:
                logger.info(
                    f"Active publish job already exists for post {post_id}, status: {existing_active_job.status}"
                )
                return {
                    "message": f"Job already planned. Status: {existing_active_job.status}",
                    "job_id": existing_active_job.id,
                    "status": existing_active_job.status,
                    "planned_at": existing_active_job.planned_at.isoformat(),
                    "already_exists": True
                }
            
            # Create a new instant publish job with status "planned"
            publish_job = PublishJob(
                schedule_id=schedule.id,
                planned_at=datetime.utcnow(),
                status=PublishJobStatus.PLANNED.value,  # Use correct status from state machine
                dedupe_key=f"{schedule.id}_{datetime.utcnow().isoformat()}"
            )
            db.add(publish_job)
            db.commit()  # Commit first so job is visible to worker before task executes
            db.refresh(publish_job)
            
            # Extract job ID while session is active (avoid detached instance errors)
            job_id = publish_job.id
            
            # Immediately enqueue to Celery and update status to "enqueued"
            # If enqueuing fails, we'll keep status as "planned" so it can be picked up by cleanup
            try:
                from src.utils.job_queue import enqueue_publish_job
                if enqueue_publish_job(job_id):
                    logger.info(f"Successfully enqueued job {job_id} to Celery")
                else:
                    raise RuntimeError("enqueue helper returned False")
            except Exception as e:
                # If enqueuing fails (e.g., Celery not running), keep status as "planned"
                # The job will be picked up by the cleanup mechanism or can be manually re-enqueued
                logger.error(f"Failed to enqueue job {job_id} to Celery: {str(e)}", exc_info=True)
                # Keep status as "planned" - cleanup can pick it up later
                # Don't update enqueued_at
                log_error(
                    action="instant_publish_enqueue_failed",
                    message=f"Failed to enqueue job {job_id} to Celery",
                    component="api",
                    extra_data=json.dumps({
                        "post_id": post_id,
                        "job_id": job_id,
                        "error": str(e)
                    })
                )
            
            # Get final job status for response (using a fresh query to avoid detached instance)
            with get_db() as db_final:
                final_job = db_final.query(PublishJob).filter(PublishJob.id == job_id).first()
                if final_job:
                    final_status = final_job.status
                    final_planned_at = final_job.planned_at
                    final_job_id = final_job.id
                else:
                    # Fallback if job somehow disappeared (shouldn't happen, but handle gracefully)
                    logger.warning(f"Job {job_id} not found when building response - using defaults")
                    final_status = "enqueued" if "Successfully enqueued" in locals() else "planned"
                    final_planned_at = datetime.utcnow()  # Use current time as fallback
                    final_job_id = job_id
            
            logger.info(f"Created and enqueued instant publish job {final_job_id} for post {post_id}")
            log_info(
                action="instant_publish_job_created",
                message=f"Created and enqueued instant publish job {final_job_id} for post {post_id}",
                component="api",
                extra_data=json.dumps({
                    "post_id": post_id,
                    "job_id": final_job_id,
                    "schedule_id": schedule.id,
                    "status": final_status
                })
            )
            
            return {
                "message": "Publish job created and enqueued successfully",
                "job_id": final_job_id,
                "status": final_status,
                "planned_at": final_planned_at.isoformat(),
                "already_exists": False
            }
    
    except Exception as e:
        logger.error(f"Unexpected error in instant_publish: {str(e)}", exc_info=True)
        log_error(
            action="instant_publish_exception",
            message=f"Exception while creating instant publish job",
            component="api",
            extra_data=json.dumps({"post_id": post_id, "error": str(e), "error_type": type(e).__name__})
        )
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )


async def get_post(post_id: int):
    """Get a single post with all related data (schedules, jobs, published posts)."""
    try:
        logger.debug(f"get_post called with post_id: {post_id}")
        
        from src.models import Schedule, PublishJob, PublishedPost
        
        with get_db() as db:
            post = db.query(Post).filter(Post.id == post_id).first()
            
            if not post:
                logger.warning(f"Post not found: {post_id}")
                return JSONResponse(
                    status_code=404,
                    content={"error": "Post not found"}
                )
            
            # Get schedules for this post
            schedules = db.query(Schedule).filter(Schedule.post_id == post_id).all()
            
            # Get all publish jobs for these schedules
            schedule_ids = [s.id for s in schedules]
            jobs = []
            if schedule_ids:
                jobs = db.query(PublishJob).filter(PublishJob.schedule_id.in_(schedule_ids)).order_by(PublishJob.planned_at.desc()).all()
            
            # Get all published posts
            published_posts = db.query(PublishedPost).filter(PublishedPost.post_id == post_id).order_by(PublishedPost.published_at.desc()).all()
            
            # Build result
            result = {
                "id": post.id,
                "text": post.text,
                "media_refs": post.media_refs,
                "deleted": post.deleted,
                "created_at": post.created_at.isoformat(),
                "updated_at": post.updated_at.isoformat(),
                "schedules": [
                    {
                        "id": s.id,
                        "kind": s.kind,
                        "schedule_spec": s.schedule_spec,
                        "timezone": s.timezone,
                        "next_run_at": s.next_run_at.isoformat() if s.next_run_at else None,
                        "enabled": s.enabled,
                        "created_at": s.created_at.isoformat(),
                        "updated_at": s.updated_at.isoformat(),
                    }
                    for s in schedules
                ],
                "jobs": [
                    {
                        "id": j.id,
                        "schedule_id": j.schedule_id,
                        "planned_at": j.planned_at.isoformat(),
                        "started_at": j.started_at.isoformat() if j.started_at else None,
                        "finished_at": j.finished_at.isoformat() if j.finished_at else None,
                        "status": j.status,
                        "error": j.error,
                        "created_at": j.created_at.isoformat(),
                        "updated_at": j.updated_at.isoformat(),
                    }
                    for j in jobs
                ],
                "published_posts": [
                    {
                        "id": pp.id,
                        "x_post_id": pp.x_post_id,
                        "published_at": pp.published_at.isoformat(),
                        "url": pp.url,
                    }
                    for pp in published_posts
                ]
            }
            
            logger.info(f"Retrieved post {post_id} with {len(schedules)} schedules, {len(jobs)} jobs, {len(published_posts)} published posts")
            return result
    
    except Exception as e:
        logger.error(f"Unexpected error in get_post: {str(e)}", exc_info=True)
        log_error(
            action="post_get_exception",
            message=f"Exception while getting post",
            component="api",
            extra_data=json.dumps({"post_id": post_id, "error": str(e), "error_type": type(e).__name__})
        )
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )

