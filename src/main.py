"""FastAPI application entry point."""

from fastapi import FastAPI, Form, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from src.api import routes, posts, twitter, audit

app = FastAPI(
    title="X Scheduler",
    description="Scheduled posting and metrics tracking for X (Twitter)",
    version="0.1.0",
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Template/Page Routes
@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    """Root endpoint - serve UI."""
    return await routes.root(request)


@app.get("/audit-log", response_class=HTMLResponse)
async def audit_log_page(request: Request):
    """Audit log page."""
    return await routes.audit_log_page(request)


@app.get("/health-ux", response_class=HTMLResponse)
async def health_page(request: Request):
    """Health and status page."""
    return await routes.health_page(request)


@app.get("/create-post", response_class=HTMLResponse)
async def create_post_page(request: Request):
    """Post creation page."""
    return await routes.create_post_page(request)


@app.get("/edit-post/{post_id}", response_class=HTMLResponse)
async def edit_post_page(request: Request, post_id: int):
    """Post editing page."""
    return await routes.edit_post_page(request, post_id)


@app.get("/view-post/{post_id}", response_class=HTMLResponse)
async def view_post_page(request: Request, post_id: int):
    """Post view page showing post details, jobs, and published posts."""
    return await routes.view_post_page(request, post_id)


# Health Check Endpoints
@app.get("/api/health")
async def health():
    """Health check endpoint (JSON)."""
    return await routes.health()


@app.get("/api/hello")
async def hello():
    """Hello world API endpoint."""
    return await routes.hello()


@app.get("/health", response_class=HTMLResponse)
async def health_html():
    """Health check endpoint for HTMX."""
    return await routes.health_html()


# Audit Log Endpoints
@app.get("/api/audit-log")
async def get_audit_log():
    """Get the latest 10 audit log records."""
    return await audit.get_audit_log()


@app.get("/api/audit-log/html", response_class=HTMLResponse)
async def get_audit_log_html():
    """Get the latest 10 audit log records as HTML."""
    return await audit.get_audit_log_html()


@app.post("/api/audit-log/test")
async def create_test_audit_log():
    """Create a dummy audit log record for testing."""
    return await audit.create_test_audit_log()


# Twitter/X API Endpoints
@app.post("/api/twitter/profile")
async def get_twitter_profile(username: str = Form(...)):
    """Load a Twitter profile by username with caching."""
    return await twitter.get_twitter_profile(username)


# Post CRUD Endpoints
@app.get("/api/posts")
async def get_posts(include_deleted: bool = False):
    """Get all posts. Optionally include deleted posts."""
    return await posts.get_posts(include_deleted)


@app.post("/api/posts")
async def create_post(text: str = Form(...), media_refs: str = Form(None)):
    """Create a new post (draft)."""
    return await posts.create_post(text, media_refs)


@app.post("/api/posts/{post_id}")
async def update_post(post_id: int, text: str = Form(...), media_refs: str = Form(None)):
    """Update an existing post."""
    return await posts.update_post(post_id, text, media_refs)


@app.delete("/api/posts/{post_id}")
async def delete_post(post_id: int):
    """Soft delete a post by marking it as deleted."""
    return await posts.delete_post(post_id)


@app.post("/api/posts/{post_id}/restore")
async def restore_post(post_id: int):
    """Restore a deleted post by marking it as not deleted."""
    return await posts.restore_post(post_id)


@app.post("/api/posts/{post_id}/instant-publish")
async def instant_publish(post_id: int):
    """Create an instant publish job for a post."""
    return await posts.instant_publish(post_id)


@app.get("/api/posts/{post_id}")
async def get_post(post_id: int):
    """Get a single post with all related data."""
    return await posts.get_post(post_id)


@app.post("/api/jobs/cleanup-orphaned")
async def cleanup_orphaned_jobs_api():
    """Cleanup and re-enqueue orphaned jobs stuck in 'enqueued' state."""
    from src.utils.job_cleanup import cleanup_orphaned_jobs
    return cleanup_orphaned_jobs(timeout_minutes=5)


def main():
    """Main function."""
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
