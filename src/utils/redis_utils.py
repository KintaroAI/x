"""Redis utilities for deduplication and caching."""

import os
import redis
from typing import Union
from uuid import UUID
from datetime import datetime


def get_redis_client() -> redis.Redis:
    """Get Redis client instance."""
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    return redis.from_url(redis_url, decode_responses=True)


def acquire_dedupe_lock(schedule_id: Union[str, UUID], planned_at: datetime) -> bool:
    """
    Acquire Redis lock for deduplication (idempotent enqueue).
    
    Args:
        schedule_id: Schedule ID
        planned_at: Planned execution time
        
    Returns:
        True if lock acquired, False if already exists
    """
    redis_client = get_redis_client()
    key = f"dedupe:{schedule_id}:{planned_at.isoformat()}"
    
    # Use SET with NX + EX (expiry). Do NOT use setnx(); it cannot set expiry.
    # 2 days TTL to handle any clock skew or delayed processing
    return redis_client.set(key, "1", nx=True, ex=172800)


def release_dedupe_lock(schedule_id: Union[str, UUID], planned_at: datetime) -> bool:
    """
    Release Redis dedupe lock.
    
    Args:
        schedule_id: Schedule ID
        planned_at: Planned execution time
        
    Returns:
        True if lock was released, False if it didn't exist
    """
    redis_client = get_redis_client()
    key = f"dedupe:{schedule_id}:{planned_at.isoformat()}"
    
    return redis_client.delete(key) > 0


def test_redis_connection() -> bool:
    """Test Redis connection."""
    try:
        redis_client = get_redis_client()
        redis_client.ping()
        return True
    except Exception:
        return False


def get_redis_info() -> dict:
    """Get Redis server info."""
    try:
        redis_client = get_redis_client()
        return redis_client.info()
    except Exception as e:
        return {"error": str(e)}

