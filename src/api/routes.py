"""Page and template routes."""

import logging
from datetime import datetime
from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from src.utils.timezone_utils import format_datetime_with_timezone, get_default_timezone

logger = logging.getLogger(__name__)

# Create templates instance - this will be used by all route functions
templates = Jinja2Templates(directory="templates")


def datetime_filter(dt, timezone=None, format_str=None):
    """
    Jinja2 filter to format datetime with timezone support.
    
    Args:
        dt: datetime object (or None)
        timezone: Optional timezone string (defaults to DEFAULT_TIMEZONE)
        format_str: Optional format string (not used currently, kept for future use)
    
    Returns:
        Formatted datetime string, or '-' if dt is None
    """
    if dt is None:
        return '-'
    
    # Use provided timezone or default
    if timezone is None:
        timezone = get_default_timezone()
    
    # Format with timezone
    try:
        # Use the already-imported function
        return format_datetime_with_timezone(dt, timezone)
    except Exception as e:
        logger.warning(f"Error formatting datetime with timezone: {e}")
        # Fallback to simple formatting
        if isinstance(dt, datetime):
            return dt.strftime('%Y-%m-%d %H:%M:%S UTC')
        return str(dt)


# Register the filter with Jinja2 templates
templates.env.filters["datetime_tz"] = datetime_filter


async def root(request: Request):
    """Root endpoint - serve UI."""
    return templates.TemplateResponse("index.html", {"request": request})


async def audit_log_page(request: Request):
    """Audit log page."""
    return templates.TemplateResponse("audit_log.html", {"request": request})


async def health_page(request: Request):
    """Health and status page."""
    return templates.TemplateResponse("health.html", {"request": request})


async def create_post_page(request: Request):
    """Post creation page."""
    from src.utils.timezone_utils import get_default_timezone
    default_timezone = get_default_timezone()
    return templates.TemplateResponse(
        "create_post.html", 
        {
            "request": request, 
            "post": None, 
            "is_edit": False,
            "default_timezone": default_timezone
        }
    )


async def edit_post_page(request: Request, post_id: int):
    """Post editing page."""
    try:
        from src.models import Post
        from src.database import get_db
        
        with get_db() as db:
            post = db.query(Post).filter(Post.id == post_id, Post.deleted == False).first()
            
            if not post:
                # Post not found or deleted - redirect to index
                return RedirectResponse(url="/", status_code=302)
            
            from src.utils.timezone_utils import get_default_timezone
            default_timezone = get_default_timezone()
            return templates.TemplateResponse(
                "create_post.html", 
                {
                    "request": request, 
                    "post": post, 
                    "is_edit": True,
                    "default_timezone": default_timezone
                }
            )
    except Exception as e:
        logger.error(f"Error loading edit post page: {str(e)}", exc_info=True)
        return RedirectResponse(url="/", status_code=302)


async def view_post_page(request: Request, post_id: int):
    """Post view page showing post details, jobs, and published posts."""
    try:
        from src.models import Post, Schedule, PublishJob, PublishedPost
        from src.database import get_db
        
        with get_db() as db:
            post = db.query(Post).filter(Post.id == post_id).first()
            
            if not post:
                # Post not found - redirect to index
                return RedirectResponse(url="/", status_code=302)
            
            # Get schedules for this post
            schedules = db.query(Schedule).filter(Schedule.post_id == post_id).all()
            
            # Get all publish jobs for these schedules
            schedule_ids = [s.id for s in schedules]
            jobs = []
            if schedule_ids:
                jobs = db.query(PublishJob).filter(PublishJob.schedule_id.in_(schedule_ids)).order_by(PublishJob.planned_at.desc()).all()
            
            # Get all published posts
            published_posts = db.query(PublishedPost).filter(PublishedPost.post_id == post_id).order_by(PublishedPost.published_at.desc()).all()
            
            return templates.TemplateResponse(
                "view_post.html",
                {
                    "request": request,
                    "post": post,
                    "jobs": jobs,
                    "published_posts": published_posts
                }
            )
    except Exception as e:
        logger.error(f"Error loading view post page: {str(e)}", exc_info=True)
        return RedirectResponse(url="/", status_code=302)


async def health():
    """Health check endpoint (JSON)."""
    return {"status": "healthy"}


async def hello():
    """Hello world API endpoint."""
    from datetime import datetime
    return {
        "message": "Hello from the API!",
        "timestamp": datetime.now().isoformat(),
        "server": "X Scheduler",
        "status": "running"
    }


async def health_html():
    """Health check endpoint for HTMX."""
    return HTMLResponse("<p class='text-green-600 font-semibold'>✓ Server is healthy</p>")


async def tasks_page(request: Request):
    """Celery tasks monitoring page."""
    from src.celery_app import app
    from src.database import get_db
    from src.models import PublishJob, Schedule, Post
    from src.utils.state_machine import get_job_statistics
    
    tasks_data = {
        "active": [],
        "reserved": [],
        "scheduled": [],
        "registered": [],
        "stats": {},
        "jobs": [],
        "worker_info": {},
        "error": None
    }
    
    try:
        # Get Celery inspection API
        inspect = app.control.inspect()
        
        # Get active tasks (currently running)
        active_tasks = inspect.active() or {}
        for worker, tasks in active_tasks.items():
            for task in tasks:
                tasks_data["active"].append({
                    "worker": worker,
                    "id": task.get("id", "unknown"),
                    "name": task.get("name", "unknown"),
                    "args": task.get("args", []),
                    "kwargs": task.get("kwargs", {}),
                    "time_start": task.get("time_start"),
                    "hostname": task.get("hostname", "unknown"),
                })
        
        # Get reserved tasks (waiting to be executed)
        reserved_tasks = inspect.reserved() or {}
        for worker, tasks in reserved_tasks.items():
            for task in tasks:
                tasks_data["reserved"].append({
                    "worker": worker,
                    "id": task.get("id", "unknown"),
                    "name": task.get("name", "unknown"),
                    "args": task.get("args", []),
                    "kwargs": task.get("kwargs", {}),
                    "hostname": task.get("hostname", "unknown"),
                })
        
        # Get scheduled tasks (with ETA)
        scheduled_tasks = inspect.scheduled() or {}
        for worker, tasks in scheduled_tasks.items():
            for task in tasks:
                tasks_data["scheduled"].append({
                    "worker": worker,
                    "id": task.get("request", {}).get("id", "unknown"),
                    "name": task.get("request", {}).get("task", "unknown"),
                    "args": task.get("request", {}).get("args", []),
                    "kwargs": task.get("request", {}).get("kwargs", {}),
                    "eta": task.get("eta"),
                    "expires": task.get("expires"),
                })
        
        # Get registered tasks (all available task types)
        registered_tasks = inspect.registered() or {}
        for worker, tasks in registered_tasks.items():
            for task_name in tasks:
                if task_name not in [t["name"] for t in tasks_data["registered"]]:
                    tasks_data["registered"].append({
                        "name": task_name,
                        "worker": worker,
                    })
        
        # Get worker stats
        stats = inspect.stats() or {}
        tasks_data["worker_info"] = {
            worker: {
                "status": stats.get(worker, {}).get("status", "unknown"),
                "pool": stats.get(worker, {}).get("pool", {}),
                "total_tasks": stats.get(worker, {}).get("total", {}),
            }
            for worker in stats.keys()
        }
        
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error querying Celery inspection API: {str(e)}", exc_info=True)
        tasks_data["error"] = f"Error querying Celery: {str(e)}"
    
    # Get database job statistics
    try:
        tasks_data["stats"] = get_job_statistics()
        
        # Get recent jobs from database
        from sqlalchemy.orm import joinedload
        
        with get_db() as db:
            jobs = (
                db.query(PublishJob)
                .options(joinedload(PublishJob.schedule).joinedload(Schedule.post))
                .order_by(PublishJob.created_at.desc())
                .limit(50)
                .all()
            )
            
            for job in jobs:
                schedule = job.schedule
                post = schedule.post if schedule else None
                
                tasks_data["jobs"].append({
                    "id": job.id,
                    "status": job.status,
                    "planned_at": job.planned_at.isoformat() if job.planned_at else None,
                    "started_at": job.started_at.isoformat() if job.started_at else None,
                    "finished_at": job.finished_at.isoformat() if job.finished_at else None,
                    "attempt": job.attempt,
                    "error": job.error,
                    "post_id": post.id if post else None,
                    "post_text": post.text[:50] + "..." if post and post.text else None,
                })
    
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error querying database: {str(e)}", exc_info=True)
        if not tasks_data["error"]:
            tasks_data["error"] = f"Error querying database: {str(e)}"
    
    return templates.TemplateResponse(
        "tasks.html",
        {
            "request": request,
            "tasks_data": tasks_data,
        }
    )

