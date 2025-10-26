"""FastAPI application entry point."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi import Request

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

# Setup templates
templates = Jinja2Templates(directory="templates")


@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    """Root endpoint - serve UI."""
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/api/health")
async def health():
    """Health check endpoint (JSON)."""
    return {"status": "healthy"}


@app.get("/api/hello")
async def hello():
    """Hello world API endpoint."""
    from datetime import datetime
    return {
        "message": "Hello from the API!",
        "timestamp": datetime.now().isoformat(),
        "server": "X Scheduler",
        "status": "running"
    }


@app.get("/health", response_class=HTMLResponse)
async def health_html():
    """Health check endpoint for HTMX."""
    return HTMLResponse("<p class='text-green-600 font-semibold'>✓ Server is healthy</p>")


def main():
    """Main function."""
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
