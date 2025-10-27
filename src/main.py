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
from src.models import AuditLog, TokenManagement, ProfileCache
from src.database import get_db
from src.audit import log_info, log_error, log_warning

# Configure logging
logger = logging.getLogger(__name__)


def _extract_urls_from_entities(entities: dict | None) -> dict:
    """
    Flatten the common URL shapes in Twitter/X entities:
    {
      "url": {"urls": [{"expanded_url": "...", "display_url": "...", "url": "..."}]},
      "description": {"urls": [...]}
    }
    Returns a dict with safe lists of expanded/display/original URLs.
    """
    if not entities:
        return {"profile_urls": [], "description_urls": []}

    def pull(url_block):
        out = []
        if isinstance(url_block, dict):
            for u in url_block.get("urls", []) or []:
                out.append({
                    "expanded": u.get("expanded_url"),
                    "display": u.get("display_url"),
                    "short": u.get("url"),
                    "start": u.get("start"),
                    "end": u.get("end"),
                })
        return out

    return {
        "profile_urls": pull(entities.get("url")),
        "description_urls": pull(entities.get("description")),
    }


def serialize_user_to_dict(user_response) -> dict:
    """
    Accepts Tweepy Response from client.get_user(...)
    Returns a dict with only JSON-serializable fields.
    """
    if not user_response or not user_response.data:
        raise ValueError("No user data in response")

    u = user_response.data  # tweepy.User

    # Some fields may be absent depending on request fields and account privacy/tier.
    public_metrics = getattr(u, "public_metrics", None) or {}
    entities = getattr(u, "entities", None)
    urls_info = _extract_urls_from_entities(entities)

    # Note: u.url is the profile URL provided by the user (if any), not the canonical X profile link.
    # You can always build the canonical profile link as https://x.com/{username}
    profile_link = f"https://x.com/{getattr(u, 'username', '')}" if getattr(u, "username", None) else None

    payload = {
        "id": getattr(u, "id", None),
        "name": getattr(u, "name", None),
        "username": getattr(u, "username", None),
        "profile_link": profile_link,
        "description": getattr(u, "description", None),
        "location": getattr(u, "location", None),
        "verified": getattr(u, "verified", None),
        "profile_image_url": getattr(u, "profile_image_url", None),
        "url": getattr(u, "url", None),  # user-specified profile URL field
        "public_metrics": {
            "followers_count": public_metrics.get("followers_count"),
            "following_count": public_metrics.get("following_count"),
            "tweet_count": public_metrics.get("tweet_count"),
            "listed_count": public_metrics.get("listed_count"),
        },
        # Keep raw entities for completeness and add flattened URLs.
        "entities": entities or {},
        "entities_flat": urls_info,
    }

    return payload


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


@app.get("/audit-log", response_class=HTMLResponse)
async def audit_log_page(request: Request):
    """Audit log page."""
    return templates.TemplateResponse("audit_log.html", {"request": request})


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


def format_user_object(raw_user: dict) -> dict:
    """
    Convert a raw Twitter user object into backward-compatible format.
    
    Args:
        raw_user: Dictionary containing the full user object from Twitter API
        
    Returns:
        Dictionary with fields expected by the frontend
    """
    # Extract metrics from public_metrics if available
    public_metrics = raw_user.get("public_metrics")
    followers_count = 0
    following_count = 0
    tweet_count = 0
    
    if public_metrics and isinstance(public_metrics, dict):
        followers_count = public_metrics.get("followers_count", 0)
        following_count = public_metrics.get("following_count", 0)
        tweet_count = public_metrics.get("tweet_count", 0)
    
    return {
        "username": raw_user.get("username"),
        "name": raw_user.get("name"),
        "description": raw_user.get("description") or raw_user.get("bio") or "",
        "profile_image_url": raw_user.get("profile_image_url") or "",
        "profile_url": f"https://x.com/{raw_user.get('username')}",
        "verified": raw_user.get("verified", False),
        "location": raw_user.get("location"),
        "followers_count": followers_count,
        "following_count": following_count,
        "tweet_count": tweet_count,
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


async def get_or_fetch_profile(username: str, client_id: str, client_secret: str) -> dict:
    """
    Get or fetch Twitter profile data with caching.
    
    First checks the database for cached profile data. If found and not expired,
    returns cached data. Otherwise, fetches from API and caches the result.
    
    Args:
        username: Twitter username (without @)
        client_id: Twitter OAuth2 client ID
        client_secret: Twitter OAuth2 client secret
        
    Returns:
        Dictionary containing profile data (from cache or API)
    """
    from datetime import timedelta
    import json
    
    # Remove @ if present
    username = username.lstrip('@')
    
    logger.debug(f"get_or_fetch_profile called for username: {username}")
    
    # Check cache first
    with get_db() as db:
        cached_profile = db.query(ProfileCache).filter(
            ProfileCache.username == username
        ).first()
        
        # Check if cached data exists and is still valid
        if cached_profile and cached_profile.expires_at > datetime.utcnow():
            logger.info(f"Using cached profile for {username} (expires at {cached_profile.expires_at})")
            log_info(
                action="profile_cache_hit",
                message=f"Retrieved cached profile for {username}",
                component="twitter_api",
                extra_data=json.dumps({"username": username, "fetched_at": cached_profile.fetched_at.isoformat(), "expires_at": cached_profile.expires_at.isoformat()})
            )
            # Return cached data - convert full user object to backward-compatible format
            return format_user_object(cached_profile.raw)
        
        # Cache expired or doesn't exist, fetch from API
        logger.info(f"Cached profile expired or not found for {username}, fetching from API")
        if cached_profile:
            log_info(
                action="profile_cache_expired",
                message=f"Cached profile expired for {username}",
                component="twitter_api",
                extra_data=json.dumps({"username": username, "expires_at": cached_profile.expires_at.isoformat()})
            )
        else:
            log_info(
                action="profile_cache_miss",
                message=f"No cached profile found for {username}",
                component="twitter_api",
                extra_data=json.dumps({"username": username})
            )
    
    # Fetch from Twitter API
    access_token = await get_or_refresh_token("twitter", client_id, client_secret)
    client = tweepy.Client(bearer_token=access_token)
    
    # Fetch user information with all available fields
    user = client.get_user(
        username=username,
        user_fields=["profile_image_url", "description", "public_metrics", "verified", "location", "url", "entities"]
    )
    
    if not user.data:
        error_message = f"User not found: {username}"
        logger.warning(error_message)
        log_error(
            action="profile_fetch_not_found",
            message=error_message,
            component="twitter_api",
            extra_data=json.dumps({"username": username})
        )
        raise ValueError(error_message)
    
    # Convert the tweepy user object to a dict using our serializer
    cache_data = serialize_user_to_dict(user)
    
    # Convert to backward-compatible format for API response
    result = format_user_object(cache_data)
    
    logger.info(f"Fetched profile from API for {username}")
    
    # Cache the result
    fetched_at = datetime.utcnow()
    expires_at = fetched_at + timedelta(days=1)  # 1 day expiration
    
    with get_db() as db:
        # Check if we need to update existing or create new
        existing_cache = db.query(ProfileCache).filter(
            ProfileCache.username == username
        ).first()
        
        if existing_cache:
            # Update existing cache with FULL user object
            existing_cache.raw = cache_data
            existing_cache.fetched_at = fetched_at
            existing_cache.expires_at = expires_at
            existing_cache.updated_at = datetime.utcnow()
        else:
            # Create new cache entry with FULL user object
            new_cache = ProfileCache(
                username=username,
                raw=cache_data,  # Store the full user object
                fetched_at=fetched_at,
                expires_at=expires_at,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            db.add(new_cache)
        
        db.commit()
        logger.info(f"Cached profile for {username} (expires at {expires_at})")
        
        log_info(
            action="profile_fetched_and_cached",
            message=f"Fetched and cached profile for {username}",
            component="twitter_api",
            extra_data=json.dumps({"username": username, "expires_at": expires_at.isoformat()})
        )
    
    return result


@app.post("/api/twitter/profile")
async def get_twitter_profile(username: str = Form(...)):
    """Load a Twitter profile by username with caching."""
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
        
        # Use the caching function
        result = await get_or_fetch_profile(username, client_id, client_secret)
        
        logger.debug(f"Returning profile data for user: {username}")
        return result
        
    except ValueError as e:
        # User not found
        logger.warning(f"User not found: {str(e)}")
        log_error(
            action="profile_fetch_not_found",
            message=str(e),
            component="twitter_api",
            extra_data=json.dumps({"username": username})
        )
        return JSONResponse(
            status_code=404,
            content={"error": str(e)}
        )
    except tweepy.TooManyRequests as e:
        error_message = "Twitter API rate limit exceeded. Please try again later."
        logger.error(f"Rate limit error in get_twitter_profile for {username}: {str(e)}")
        log_error(
            action="profile_fetch_rate_limit",
            message=error_message,
            component="twitter_api",
            extra_data=json.dumps({
                "username": username,
                "error": str(e),
                "retry_after": getattr(e.response, 'headers', {}).get('x-rate-limit-reset') if hasattr(e, 'response') else None
            })
        )
        return JSONResponse(
            status_code=429,
            content={"error": error_message}
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
