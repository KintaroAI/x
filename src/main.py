"""FastAPI application entry point."""

from fastapi import FastAPI, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi import Request
from datetime import datetime
import os
import base64
import httpx
import tweepy
from src.models import AuditLog
from src.database import get_db

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


@app.get("/api/audit-log")
async def get_audit_log():
    """Get the latest 10 audit log records."""
    with get_db() as db:
        records = db.query(AuditLog).order_by(AuditLog.timestamp.desc()).limit(10).all()
        
        return [
            {
                "id": record.id,
                "timestamp": record.timestamp.isoformat(),
                "level": record.level,
                "component": record.component,
                "action": record.action,
                "message": record.message,
                "extra_data": record.extra_data,
                "user_id": record.user_id,
                "ip_address": record.ip_address,
            }
            for record in records
        ]


@app.get("/api/audit-log/html", response_class=HTMLResponse)
async def get_audit_log_html():
    """Get the latest 10 audit log records as HTML."""
    with get_db() as db:
        records = db.query(AuditLog).order_by(AuditLog.timestamp.desc()).limit(10).all()
        
        def get_level_color(level):
            colors = {
                "INFO": "text-blue-600",
                "WARNING": "text-yellow-600",
                "ERROR": "text-red-600",
                "CRITICAL": "text-red-800 font-bold"
            }
            return colors.get(level, "text-gray-600")
        
        if not records:
            return HTMLResponse(
                "<p class='text-gray-600 p-4 text-center'>No audit log records found.</p>"
            )
        
        html_rows = ""
        for record in records:
            level_color = get_level_color(record.level)
            timestamp = record.timestamp.strftime("%Y-%m-%d %H:%M:%S")
            html_rows += f"""
            <tr class="hover:bg-gray-50">
                <td class="border border-gray-300 px-4 py-2 text-sm">{record.id}</td>
                <td class="border border-gray-300 px-4 py-2 text-sm text-gray-700">{timestamp}</td>
                <td class="border border-gray-300 px-4 py-2 text-sm {level_color}">{record.level}</td>
                <td class="border border-gray-300 px-4 py-2 text-sm">{record.component or '-'}</td>
                <td class="border border-gray-300 px-4 py-2 text-sm">{record.action}</td>
                <td class="border border-gray-300 px-4 py-2 text-sm">{record.message}</td>
            </tr>
            """
        
        html = f"""
        <div class="overflow-x-auto">
            <table class="min-w-full border-collapse border border-gray-300">
                <thead class="bg-gray-100">
                    <tr>
                        <th class="border border-gray-300 px-4 py-2 text-left text-sm font-semibold">ID</th>
                        <th class="border border-gray-300 px-4 py-2 text-left text-sm font-semibold">Timestamp</th>
                        <th class="border border-gray-300 px-4 py-2 text-left text-sm font-semibold">Level</th>
                        <th class="border border-gray-300 px-4 py-2 text-left text-sm font-semibold">Component</th>
                        <th class="border border-gray-300 px-4 py-2 text-left text-sm font-semibold">Action</th>
                        <th class="border border-gray-300 px-4 py-2 text-left text-sm font-semibold">Message</th>
                    </tr>
                </thead>
                <tbody>
                    {html_rows}
                </tbody>
            </table>
        </div>
        """
        
        return HTMLResponse(html)


@app.post("/api/audit-log/test")
async def create_test_audit_log():
    """Create a dummy audit log record for testing."""
    import random
    
    levels = ["INFO", "WARNING", "ERROR"]
    actions = ["test_action", "dummy_action", "sample_action", "check_action"]
    components = ["ui", "api", "test", "frontend"]
    messages = [
        "Testing audit log functionality",
        "Dummy record created from UI",
        "Test audit entry created successfully",
        "Sample audit log for testing",
    ]
    
    with get_db() as db:
        audit_entry = AuditLog(
            timestamp=datetime.utcnow(),
            level=random.choice(levels),
            component=random.choice(components),
            action=random.choice(actions),
            message=random.choice(messages),
            extra_data='{"test": true, "source": "ui"}',
            user_id="test_user",
            ip_address="127.0.0.1",
            created_at=datetime.utcnow(),
        )
        db.add(audit_entry)
        db.commit()
        db.refresh(audit_entry)
        
        return {
            "id": audit_entry.id,
            "timestamp": audit_entry.timestamp.isoformat(),
            "level": audit_entry.level,
            "component": audit_entry.component,
            "action": audit_entry.action,
            "message": audit_entry.message,
        }


@app.post("/api/twitter/profile")
async def get_twitter_profile(username: str = Form(...)):
    """Load a Twitter profile by username."""
    try:
        if not username:
            return JSONResponse(
                status_code=400,
                content={"error": "Username is required"}
            )
        
        # Get OAuth2 credentials from environment
        client_id = os.getenv("X_CLIENT_ID")
        client_secret = os.getenv("X_CLIENT_SECRET")
        
        if not client_id or not client_secret:
            return JSONResponse(
                status_code=500,
                content={"error": "Twitter OAuth2 credentials not configured (X_CLIENT_ID and X_CLIENT_SECRET required)"}
            )
        
        # Remove @ if present
        username = username.lstrip('@')
        
        # For OAuth2 App-Only authentication, we need to obtain an access token first
        # Encode credentials for OAuth2 App-Only flow
        credentials = base64.b64encode(
            f"{client_id}:{client_secret}".encode('utf-8')
        ).decode('utf-8')
        
        # Request access token
        async with httpx.AsyncClient() as client_http:
            auth_response = await client_http.post(
                'https://api.twitter.com/oauth2/token',
                headers={
                    'Authorization': f'Basic {credentials}',
                    'Content-Type': 'application/x-www-form-urlencoded'
                },
                data='grant_type=client_credentials'
            )
            
            if auth_response.status_code != 200:
                return JSONResponse(
                    status_code=500,
                    content={"error": f"Failed to authenticate with Twitter API (status {auth_response.status_code}): {auth_response.text}"}
                )
            
            try:
                auth_data = auth_response.json()
                access_token = auth_data.get('access_token') if auth_data else None
            except Exception as e:
                return JSONResponse(
                    status_code=500,
                    content={"error": f"Failed to parse Twitter auth response: {str(e)}"}
                )
        
        if not access_token:
            return JSONResponse(
                status_code=500,
                content={"error": "Failed to obtain Twitter access token from response"}
            )
        
        # Initialize Tweepy client with access token
        client = tweepy.Client(bearer_token=access_token)
        
        # Fetch user information
        try:
            user = client.get_user(username=username, user_fields=["profile_image_url", "description"])
            
            if not user.data:
                return JSONResponse(
                    status_code=404,
                    content={"error": "User not found"}
                )
            
            profile_data = user.data
            
            return {
                "username": profile_data.username,
                "name": profile_data.name,
                "bio": profile_data.description or "",
                "profile_image_url": profile_data.profile_image_url or "",
                "profile_url": f"https://twitter.com/{profile_data.username}",
                "verified": getattr(profile_data, 'verified', False),
                "followers_count": getattr(profile_data, 'public_metrics', {}).get('followers_count', 0) if hasattr(profile_data, 'public_metrics') else 0,
            }
        except tweepy.TooManyRequests:
            return JSONResponse(
                status_code=429,
                content={"error": "Rate limit exceeded. Please try again later."}
            )
        except tweepy.NotFound:
            return JSONResponse(
                status_code=404,
                content={"error": "User not found"}
            )
        except tweepy.Unauthorized:
            return JSONResponse(
                status_code=401,
                content={"error": "Invalid Twitter credentials"}
            )
        except Exception as e:
            return JSONResponse(
                status_code=500,
                content={"error": f"Failed to fetch profile: {str(e)}"}
            )
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )


def main():
    """Main function."""
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
