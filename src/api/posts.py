"""Post CRUD API endpoints."""

import json
import logging
from datetime import datetime, timedelta
from fastapi import Form
from fastapi.responses import HTMLResponse, JSONResponse

from src.models import Post
from src.database import get_db
from src.audit import log_info, log_error

logger = logging.getLogger(__name__)


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


async def create_post(text: str = Form(...), media_refs: str = Form(None)):
    """Create a new post (draft)."""
    try:
        logger.debug(f"create_post called with text length: {len(text)}")
        
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
            db.commit()
            db.refresh(post)
            
            logger.info(f"Created new post with id: {post.id}")
            log_info(
                action="post_created",
                message=f"Created new post with id {post.id}",
                component="api",
                extra_data=json.dumps({
                    "post_id": post.id,
                    "text_length": len(text),
                    "has_media": media_data is not None
                })
            )
            
            # Return success response
            return HTMLResponse(
                f"""
                <div class="bg-green-50 border border-green-200 text-green-800 px-4 py-3 rounded-lg">
                    <h3 class="font-semibold mb-2">✓ Post Created Successfully</h3>
                    <p class="text-sm">Post ID: {post.id}</p>
                    <p class="text-sm">Created at: {post.created_at.strftime('%Y-%m-%d %H:%M:%S')}</p>
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


async def update_post(post_id: int, text: str = Form(...), media_refs: str = Form(None)):
    """Update an existing post."""
    try:
        logger.debug(f"update_post called with post_id: {post_id}, text length: {len(text)}")
        
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
            db.commit()
            
            logger.info(f"Updated post with id: {post_id}")
            log_info(
                action="post_updated",
                message=f"Updated post with id {post_id}",
                component="api",
                extra_data=json.dumps({
                    "post_id": post_id,
                    "text_length": len(text),
                    "has_media": media_data is not None
                })
            )
            
            # Return success response
            return HTMLResponse(
                f"""
                <div class="bg-green-50 border border-green-200 text-green-800 px-4 py-3 rounded-lg">
                    <h3 class="font-semibold mb-2">✓ Post Updated Successfully</h3>
                    <p class="text-sm">Post ID: {post.id}</p>
                    <p class="text-sm">Updated at: {post.updated_at.strftime('%Y-%m-%d %H:%M:%S')}</p>
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
            
            # Cancel all pending jobs related to this post
            schedules = db.query(Schedule).filter(Schedule.post_id == post_id).all()
            cancelled_count = 0
            
            for schedule in schedules:
                # Update all pending publish jobs to cancelled
                pending_jobs = db.query(PublishJob).filter(
                    PublishJob.schedule_id == schedule.id,
                    PublishJob.status == "pending"
                ).all()
                
                for job in pending_jobs:
                    job.status = "cancelled"
                    job.updated_at = datetime.utcnow()
                    cancelled_count += 1
                    logger.info(f"Cancelled publish job {job.id} for deleted post {post_id}")
            
            db.commit()
            
            extra_data = {"post_id": post_id, "cancelled_jobs": cancelled_count}
            logger.info(f"Soft deleted post with id: {post_id}, cancelled {cancelled_count} pending jobs")
            
            log_info(
                action="post_deleted",
                message=f"Soft deleted post with id {post_id}, cancelled {cancelled_count} pending jobs",
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
    """Create an instant publish job for a post."""
    try:
        logger.debug(f"instant_publish called with post_id: {post_id}")
        
        from src.models import Schedule, PublishJob
        
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
            
            # Check if there's already a publish job within the last 30 minutes
            now = datetime.utcnow()
            thirty_minutes_ago = now - timedelta(minutes=30)
            
            recent_job = db.query(PublishJob).filter(
                PublishJob.schedule_id == schedule.id,
                PublishJob.planned_at >= thirty_minutes_ago
            ).order_by(PublishJob.planned_at.desc()).first()
            
            if recent_job:
                # Job already exists
                logger.info(f"Publish job already exists for post {post_id}, status: {recent_job.status}")
                return {
                    "message": f"Job already planned. Status: {recent_job.status}",
                    "job_id": recent_job.id,
                    "status": recent_job.status,
                    "planned_at": recent_job.planned_at.isoformat(),
                    "already_exists": True
                }
            
            # Create a new instant publish job
            publish_job = PublishJob(
                schedule_id=schedule.id,
                planned_at=datetime.utcnow(),
                status="pending",
                dedupe_key=f"{schedule.id}_{datetime.utcnow().isoformat()}"
            )
            db.add(publish_job)
            db.commit()
            db.refresh(publish_job)
            
            logger.info(f"Created instant publish job {publish_job.id} for post {post_id}")
            log_info(
                action="instant_publish_job_created",
                message=f"Created instant publish job {publish_job.id} for post {post_id}",
                component="api",
                extra_data=json.dumps({
                    "post_id": post_id,
                    "job_id": publish_job.id,
                    "schedule_id": schedule.id
                })
            )
            
            return {
                "message": "Publish job created successfully",
                "job_id": publish_job.id,
                "status": publish_job.status,
                "planned_at": publish_job.planned_at.isoformat(),
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

