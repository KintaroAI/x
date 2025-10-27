"""Twitter/X API service for token management and profile fetching."""

import os
import base64
import json
import logging
from datetime import datetime, timedelta
import httpx
import tweepy

from src.models import TokenManagement, ProfileCache
from src.database import get_db
from src.audit import log_info, log_error
from src.utils.twitter_utils import serialize_user_to_dict, format_user_object

logger = logging.getLogger(__name__)


async def get_or_refresh_token(service_name: str, client_id: str, client_secret: str) -> str:
    """Get existing token from database or fetch a new one from Twitter API."""
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

