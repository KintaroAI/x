"""Page and template routes."""

import logging
from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

logger = logging.getLogger(__name__)

# Create templates instance - this will be used by all route functions
templates = Jinja2Templates(directory="templates")


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
    return templates.TemplateResponse("create_post.html", {"request": request, "post": None, "is_edit": False})


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
            
            return templates.TemplateResponse(
                "create_post.html", 
                {"request": request, "post": post, "is_edit": True}
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

