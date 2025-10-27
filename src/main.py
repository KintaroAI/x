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
import logging
import json
from src.models import AuditLog, TokenManagement
from src.database import get_db
from src.audit import log_info, log_error, log_warning

# Configure logging
logger = logging.getLogger(__name__)

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


async def get_or_refresh_token(service_name: str, client_id: str, client_secret: str) -> str:
    """Get existing token from database or fetch a new one from Twitter API."""
    from datetime import timedelta
    
    logger.debug(f"get_or_refresh_token called for service: {service_name}")
    
    with get_db() as db:
        # Check if we have a valid token in the database
        existing_token = db.query(TokenManagement).filter(
            TokenManagement.service_name == service_name,
            TokenManagement.token_type == 'access_token'
        ).first()
        
        # If token exists and hasn't expired (or doesn't have expiry), use it
        if existing_token:
            if existing_token.expires_at is None or existing_token.expires_at > datetime.utcnow():
                logger.debug(f"Using existing valid token for service: {service_name}")
                log_info(
                    action="token_reused",
                    message=f"Using existing valid token for {service_name}",
                    component="twitter_api",
                    extra_data=json.dumps({"service_name": service_name, "expires_at": existing_token.expires_at.isoformat() if existing_token.expires_at else None})
                )
                return existing_token.token
            # Token expired, update it instead of deleting
            logger.info(f"Token expired for service: {service_name}, refreshing token")
            log_info(
                action="token_refresh_initiated",
                message=f"Token expired for {service_name}, initiating refresh",
                component="twitter_api",
                extra_data=json.dumps({"service_name": service_name, "expires_at": existing_token.expires_at.isoformat() if existing_token.expires_at else None})
            )
            token_record_to_update = existing_token
        else:
            logger.debug(f"No existing token found for service: {service_name}, fetching new token")
            log_info(
                action="token_fetch_initiated",
                message=f"No existing token found for {service_name}, fetching new token",
                component="twitter_api",
                extra_data=json.dumps({"service_name": service_name})
            )
            token_record_to_update = None
        
        # No valid token, fetch a new one
        logger.debug(f"Fetching new access token from Twitter API for service: {service_name}")
        credentials = base64.b64encode(
            f"{client_id}:{client_secret}".encode('utf-8')
        ).decode('utf-8')
        
        try:
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
                    error_message = f"Twitter API authentication failed (status {auth_response.status_code})"
                    logger.error(f"{error_message}: {auth_response.text}")
                    log_error(
                        action="token_fetch_failed",
                        message=error_message,
                        component="twitter_api",
                        extra_data=json.dumps({"service_name": service_name, "status_code": auth_response.status_code, "response": auth_response.text})
                    )
                    raise Exception(f"Failed to authenticate with Twitter API (status {auth_response.status_code}): {auth_response.text}")
                
                auth_data = auth_response.json()
                access_token = auth_data.get('access_token')
                
                if not access_token:
                    error_message = "Failed to obtain Twitter access token from response"
                    logger.error(error_message)
                    log_error(
                        action="token_parse_failed",
                        message=error_message,
                        component="twitter_api",
                        extra_data=json.dumps({"service_name": service_name, "response_keys": list(auth_data.keys())})
                    )
                    raise Exception("Failed to obtain Twitter access token from response")
                
                logger.debug("Successfully obtained new access token from Twitter API")
                
                # Store the new token in database
                expires_in = auth_data.get('expires_in')  # Usually 7200 seconds (2 hours)
                expires_at = None
                if expires_in:
                    expires_at = datetime.utcnow() + timedelta(seconds=expires_in)
                
                # Update existing record or create new one
                if token_record_to_update:
                    logger.debug(f"Updating existing token record for service: {service_name}")
                    token_record_to_update.token = access_token
                    token_record_to_update.expires_at = expires_at
                    token_record_to_update.updated_at = datetime.utcnow()
                else:
                    logger.debug(f"Creating new token record for service: {service_name}")
                    token_record = TokenManagement(
                        service_name=service_name,
                        token_type='access_token',
                        token=access_token,
                        expires_at=expires_at,
                        created_at=datetime.utcnow(),
                        updated_at=datetime.utcnow()
                    )
                    db.add(token_record)
                
                db.commit()
                logger.info(f"Token saved to database for service: {service_name} (expires at: {expires_at})")
                
                log_info(
                    action="token_fetched",
                    message=f"Successfully fetched and stored token for {service_name}",
                    component="twitter_api",
                    extra_data=json.dumps({"service_name": service_name, "expires_at": expires_at.isoformat() if expires_at else None, "expires_in": expires_in})
                )
                
                return access_token
        except Exception as e:
            log_error(
                action="token_fetch_exception",
                message=f"Exception while fetching token for {service_name}: {str(e)}",
                component="twitter_api",
                extra_data=json.dumps({"service_name": service_name, "error": str(e)})
            )
            raise


@app.post("/api/twitter/profile")
async def get_twitter_profile(username: str = Form(...)):
    """Load a Twitter profile by username."""
    logger.debug(f"get_twitter_profile called with username: {username}")
    
    try:
        if not username:
            logger.error("get_twitter_profile: Username is required")
            log_error(
                action="profile_fetch_invalid_request",
                message="Username is required",
                component="twitter_api",
                extra_data=json.dumps({"username": username})
            )
            return JSONResponse(
                status_code=400,
                content={"error": "Username is required"}
            )
        
        # Get OAuth2 credentials from environment
        client_id = os.getenv("X_CLIENT_ID")
        client_secret = os.getenv("X_CLIENT_SECRET")
        
        if not client_id or not client_secret:
            logger.error("get_twitter_profile: Twitter OAuth2 credentials not configured")
            log_error(
                action="profile_fetch_missing_credentials",
                message="Twitter OAuth2 credentials not configured",
                component="twitter_api",
                extra_data=json.dumps({"username": username})
            )
            return JSONResponse(
                status_code=500,
                content={"error": "Twitter OAuth2 credentials not configured (X_CLIENT_ID and X_CLIENT_SECRET required)"}
            )
        
        logger.debug(f"Twitter OAuth2 credentials configured (client_id exists: {bool(client_id)})")
        
        # Remove @ if present
        username_original = username
        username = username.lstrip('@')
        if username != username_original:
            logger.debug(f"Removed @ from username: {username_original} -> {username}")
        
        log_info(
            action="profile_fetch_initiated",
            message=f"Initiating profile fetch for username: {username}",
            component="twitter_api",
            extra_data=json.dumps({"username": username, "original_username": username_original})
        )
        
        # Get or refresh access token (will reuse if it exists and is valid)
        try:
            logger.debug("Retrieving or refreshing Twitter access token")
            access_token = await get_or_refresh_token("twitter", client_id, client_secret)
            logger.debug("Successfully obtained access token")
        except Exception as e:
            logger.error(f"Failed to get/refresh Twitter access token: {str(e)}", exc_info=True)
            log_error(
                action="profile_fetch_token_error",
                message=f"Failed to get/refresh Twitter access token for {username}",
                component="twitter_api",
                extra_data=json.dumps({"username": username, "error": str(e)})
            )
            return JSONResponse(
                status_code=500,
                content={"error": str(e)}
            )
        
        # Initialize Tweepy client with access token
        logger.debug(f"Initializing Tweepy client for username: {username}")
        client = tweepy.Client(bearer_token=access_token)
        
        # Fetch user information
        try:
            logger.debug(f"Fetching user profile for: {username}")
            user = client.get_user(username=username, user_fields=["profile_image_url", "description"])
            
            if not user.data:
                logger.warning(f"User not found: {username}")
                log_warning(
                    action="profile_fetch_not_found",
                    message=f"User not found: {username}",
                    component="twitter_api",
                    extra_data=json.dumps({"username": username})
                )
                return JSONResponse(
                    status_code=404,
                    content={"error": "User not found"}
                )
            
            profile_data = user.data
            logger.info(f"Successfully fetched profile for user: {username} (name: {profile_data.name})")
            
            result = {
                "username": profile_data.username,
                "name": profile_data.name,
                "bio": profile_data.description or "",
                "profile_image_url": profile_data.profile_image_url or "",
                "profile_url": f"https://twitter.com/{profile_data.username}",
                "verified": getattr(profile_data, 'verified', False),
                "followers_count": getattr(profile_data, 'public_metrics', {}).get('followers_count', 0) if hasattr(profile_data, 'public_metrics') else 0,
            }
            
            log_info(
                action="profile_fetch_success",
                message=f"Successfully fetched profile for {username}",
                component="twitter_api",
                extra_data=json.dumps({"username": username, "name": profile_data.name, "verified": result["verified"]})
            )
            
            logger.debug(f"Returning profile data for user: {username}")
            return result
        except tweepy.TooManyRequests as e:
            logger.error(f"Rate limit exceeded while fetching profile for {username}: {str(e)}")
            log_error(
                action="profile_fetch_rate_limit",
                message=f"Rate limit exceeded while fetching profile for {username}",
                component="twitter_api",
                extra_data=json.dumps({"username": username, "error": str(e)})
            )
            return JSONResponse(
                status_code=429,
                content={"error": "Rate limit exceeded. Please try again later."}
            )
        except tweepy.NotFound as e:
            logger.warning(f"User not found: {username} - {str(e)}")
            log_error(
                action="profile_fetch_not_found",
                message=f"User not found: {username}",
                component="twitter_api",
                extra_data=json.dumps({"username": username, "error": str(e)})
            )
            return JSONResponse(
                status_code=404,
                content={"error": "User not found"}
            )
        except tweepy.Unauthorized as e:
            logger.error(f"Unauthorized access while fetching profile for {username}: {str(e)}")
            log_error(
                action="profile_fetch_unauthorized",
                message=f"Unauthorized access while fetching profile for {username}",
                component="twitter_api",
                extra_data=json.dumps({"username": username, "error": str(e)})
            )
            return JSONResponse(
                status_code=401,
                content={"error": "Invalid Twitter credentials"}
            )
        except Exception as e:
            logger.error(f"Failed to fetch profile for {username}: {str(e)}", exc_info=True)
            log_error(
                action="profile_fetch_failed",
                message=f"Failed to fetch profile for {username}",
                component="twitter_api",
                extra_data=json.dumps({"username": username, "error": str(e), "error_type": type(e).__name__})
            )
            return JSONResponse(
                status_code=500,
                content={"error": f"Failed to fetch profile: {str(e)}"}
            )
    except Exception as e:
        logger.error(f"Unexpected error in get_twitter_profile: {str(e)}", exc_info=True)
        log_error(
            action="profile_fetch_unexpected_error",
            message=f"Unexpected error in get_twitter_profile",
            component="twitter_api",
            extra_data=json.dumps({"username": username, "error": str(e), "error_type": type(e).__name__})
        )
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
