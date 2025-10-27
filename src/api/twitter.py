"""Twitter/X API endpoints."""

import os
import json
import logging
import tweepy
from fastapi import Form
from fastapi.responses import HTMLResponse, JSONResponse

from src.services.twitter_service import get_or_fetch_profile

logger = logging.getLogger(__name__)


async def get_twitter_profile(username: str = Form(...)):
    """Load a Twitter profile by username with caching."""
    logger.debug(f"get_twitter_profile called with username: {username}")
    
    try:
        if not username:
            logger.error("get_twitter_profile: Username is required")
            return JSONResponse(
                status_code=400,
                content={"error": "Username is required"}
            )
        
        # Get OAuth2 credentials from environment
        client_id = os.getenv("X_CLIENT_ID")
        client_secret = os.getenv("X_CLIENT_SECRET")
        
        if not client_id or not client_secret:
            logger.error("get_twitter_profile: Twitter OAuth2 credentials not configured")
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
        return JSONResponse(
            status_code=404,
            content={"error": str(e)}
        )
    except tweepy.TooManyRequests as e:
        error_message = "Twitter API rate limit exceeded. Please try again later."
        logger.error(f"Rate limit error in get_twitter_profile for {username}: {str(e)}")
        return JSONResponse(
            status_code=429,
            content={"error": error_message}
        )
    except Exception as e:
        logger.error(f"Unexpected error in get_twitter_profile: {str(e)}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )

