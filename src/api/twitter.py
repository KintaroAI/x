"""Twitter/X API endpoints."""

import os
import json
import logging
import tweepy
from fastapi import Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from typing import List, Optional, Dict, Any

from src.services.twitter_service import get_or_fetch_profile, get_or_refresh_token
from src.database import get_db
from src.models import Account, TokenManagement

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


async def oauth_start():
    """Start OAuth2 PKCE flow: return authorization URL."""
    try:
        client_id = os.getenv("X_CLIENT_ID")
        client_secret = os.getenv("X_CLIENT_SECRET")
        redirect_uri = os.getenv("X_REDIRECT_URI")
        scopes = os.getenv("X_SCOPES", "tweet.read users.read tweet.write offline.access").split()

        if not client_id or not redirect_uri:
            return JSONResponse(status_code=500, content={"error": "Missing X_CLIENT_ID or X_REDIRECT_URI"})

        oauth = tweepy.OAuth2UserHandler(
            client_id=client_id,
            redirect_uri=redirect_uri,
            scope=scopes,
            client_secret=client_secret if client_secret else None,
        )
        url = oauth.get_authorization_url()
        return {"auth_url": url}
    except Exception as e:
        logger.error(f"oauth_start error: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"error": str(e)})


async def oauth_callback(request: Request):
    """Handle OAuth2 callback: exchange code, persist tokens, and upsert account."""
    try:
        client_id = os.getenv("X_CLIENT_ID")
        client_secret = os.getenv("X_CLIENT_SECRET")
        redirect_uri = os.getenv("X_REDIRECT_URI")
        scopes = os.getenv("X_SCOPES", "tweet.read users.read tweet.write offline.access").split()

        if not client_id or not redirect_uri:
            return JSONResponse(status_code=500, content={"error": "Missing X_CLIENT_ID or X_REDIRECT_URI"})

        oauth = tweepy.OAuth2UserHandler(
            client_id=client_id,
            redirect_uri=redirect_uri,
            scope=scopes,
            client_secret=client_secret if client_secret else None,
        )

        token = oauth.fetch_token(str(request.url))
        access_token = token.get("access_token")
        refresh_token = token.get("refresh_token")
        scope_str = token.get("scope") or " ".join(scopes)

        if not access_token:
            return JSONResponse(status_code=400, content={"error": "No access_token in response"})

        # Fetch user to determine handle (@username)
        client = tweepy.Client(access_token)
        me = client.get_me()
        handle = me.data.username if getattr(me, "data", None) else "me"

        # Persist tokens
        with get_db() as db:
            # Upsert Account (by handle)
            account = db.query(Account).filter(Account.handle == handle).first()
            if not account:
                account = Account(handle=handle)
                db.add(account)
                db.flush()
            account.access_token = access_token
            account.refresh_token = refresh_token
            account.scopes = scope_str
            account.rotated_at = None

            # TokenManagement: access_token
            tm_access = db.query(TokenManagement).filter(
                TokenManagement.service_name == "twitter",
                TokenManagement.token_type == "access_token",
            ).first()
            if not tm_access:
                db.add(TokenManagement(
                    service_name="twitter",
                    token_type="access_token",
                    token=access_token,
                ))
            else:
                tm_access.token = access_token

            # TokenManagement: refresh_token
            if refresh_token:
                tm_refresh = db.query(TokenManagement).filter(
                    TokenManagement.service_name == "twitter",
                    TokenManagement.token_type == "refresh_token",
                ).first()
                if not tm_refresh:
                    db.add(TokenManagement(
                        service_name="twitter",
                        token_type="refresh_token",
                        token=refresh_token,
                    ))
                else:
                    tm_refresh.token = refresh_token

            db.commit()

        return RedirectResponse(url="/", status_code=302)
    except Exception as e:
        logger.error(f"oauth_callback error: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"error": str(e)})

async def create_twitter_post(text: str, media_ids: List[str] = None, dry_run: bool = False) -> Dict[str, Any]:
    """Create a post on Twitter/X using tweepy."""
    logger.debug(f"create_twitter_post called with text: {text[:50]}...")
    
    try:
        if not text:
            logger.error("create_twitter_post: Text is required")
            return {"error": "Text is required"}
        
        if dry_run:
            logger.info(f"[DRY RUN] Would create post: {text[:50]}...")
            return {"data": {"id": "dry_run_123", "text": text}}
        
        # Get OAuth2 credentials from environment
        client_id = os.getenv("X_CLIENT_ID")
        client_secret = os.getenv("X_CLIENT_SECRET")
        
        if not client_id or not client_secret:
            logger.error("create_twitter_post: Twitter OAuth2 credentials not configured")
            raise ValueError("Twitter OAuth2 credentials not configured (X_CLIENT_ID and X_CLIENT_SECRET required)")
        
        # Get access token
        access_token = await get_or_refresh_token("twitter", client_id, client_secret)
        
        # Create tweepy client
        client = tweepy.Client(bearer_token=access_token)
        
        # Create the post
        if media_ids:
            response = client.create_tweet(text=text, media_ids=media_ids)
        else:
            response = client.create_tweet(text=text)
        
        if response.data:
            logger.info(f"Successfully created tweet with ID: {response.data['id']}")
            return {"data": {"id": response.data["id"], "text": text}}
        else:
            raise ValueError("No tweet ID returned from Twitter API")
            
    except tweepy.TooManyRequests as e:
        error_message = "Twitter API rate limit exceeded. Please try again later."
        logger.error(f"Rate limit error in create_twitter_post: {str(e)}")
        raise Exception(error_message)
    except tweepy.Unauthorized as e:
        error_message = "Twitter API authentication failed. Please check credentials."
        logger.error(f"Authentication error in create_twitter_post: {str(e)}")
        raise Exception(error_message)
    except tweepy.Forbidden as e:
        error_message = "Twitter API access forbidden. Please check permissions."
        logger.error(f"Forbidden error in create_twitter_post: {str(e)}")
        raise Exception(error_message)
    except Exception as e:
        logger.error(f"Unexpected error in create_twitter_post: {str(e)}", exc_info=True)
        raise


async def get_tweet_metrics(tweet_id: str, dry_run: bool = False) -> Dict[str, Any]:
    """Get metrics for a tweet using tweepy."""
    logger.debug(f"get_tweet_metrics called for tweet_id: {tweet_id}")
    
    try:
        if not tweet_id:
            logger.error("get_tweet_metrics: Tweet ID is required")
            return {"error": "Tweet ID is required"}
        
        if dry_run:
            logger.info(f"[DRY RUN] Would fetch metrics for {tweet_id}")
            return {"data": {}}
        
        # Get OAuth2 credentials from environment
        client_id = os.getenv("X_CLIENT_ID")
        client_secret = os.getenv("X_CLIENT_SECRET")
        
        if not client_id or not client_secret:
            logger.error("get_tweet_metrics: Twitter OAuth2 credentials not configured")
            raise ValueError("Twitter OAuth2 credentials not configured (X_CLIENT_ID and X_CLIENT_SECRET required)")
        
        # Get access token
        access_token = await get_or_refresh_token("twitter", client_id, client_secret)
        
        # Create tweepy client
        client = tweepy.Client(bearer_token=access_token)
        
        # Get tweet metrics
        tweet = client.get_tweet(
            tweet_id,
            tweet_fields=["public_metrics", "non_public_metrics"]
        )
        
        if tweet.data:
            logger.info(f"Successfully fetched metrics for tweet {tweet_id}")
            return {"data": tweet.data}
        else:
            raise ValueError(f"Tweet {tweet_id} not found")
            
    except tweepy.TooManyRequests as e:
        error_message = "Twitter API rate limit exceeded. Please try again later."
        logger.error(f"Rate limit error in get_tweet_metrics: {str(e)}")
        raise Exception(error_message)
    except tweepy.Unauthorized as e:
        error_message = "Twitter API authentication failed. Please check credentials."
        logger.error(f"Authentication error in get_tweet_metrics: {str(e)}")
        raise Exception(error_message)
    except tweepy.Forbidden as e:
        error_message = "Twitter API access forbidden. Please check permissions."
        logger.error(f"Forbidden error in get_tweet_metrics: {str(e)}")
        raise Exception(error_message)
    except Exception as e:
        logger.error(f"Unexpected error in get_tweet_metrics: {str(e)}", exc_info=True)
        raise

