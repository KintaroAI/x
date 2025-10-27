"""Twitter/X API utility functions."""


def extract_urls_from_entities(entities: dict | None) -> dict:
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
    urls_info = extract_urls_from_entities(entities)

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

