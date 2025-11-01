"""Utility functions for timezone handling."""

import os
import pytz
from typing import Optional

# Default timezone from environment variable
DEFAULT_TIMEZONE = os.getenv("DEFAULT_TIMEZONE", "UTC")


def get_default_timezone() -> str:
    """
    Get the default timezone from environment variable.
    
    Returns:
        Timezone string (e.g., "UTC", "America/New_York")
    """
    return DEFAULT_TIMEZONE


def get_timezone_list() -> list:
    """
    Get list of common timezones for UI dropdown.
    
    Returns:
        List of timezone tuples (value, label)
    """
    return [
        ("UTC", "UTC"),
        ("America/New_York", "Eastern Time (ET)"),
        ("America/Chicago", "Central Time (CT)"),
        ("America/Denver", "Mountain Time (MT)"),
        ("America/Los_Angeles", "Pacific Time (PT)"),
        ("Europe/London", "London (GMT)"),
        ("Europe/Paris", "Paris (CET)"),
        ("Asia/Tokyo", "Tokyo (JST)"),
    ]


def is_valid_timezone(timezone: str) -> bool:
    """
    Check if a timezone string is valid.
    
    Args:
        timezone: Timezone string to validate
        
    Returns:
        True if valid, False otherwise
    """
    try:
        pytz.timezone(timezone)
        return True
    except pytz.exceptions.UnknownTimeZoneError:
        return False


def format_datetime_with_timezone(dt, timezone: Optional[str] = None) -> str:
    """
    Format a datetime with timezone information.
    
    Args:
        dt: datetime object (assumed to be UTC if naive)
        timezone: Target timezone (defaults to DEFAULT_TIMEZONE)
        
    Returns:
        Formatted datetime string with timezone info
    """
    if timezone is None:
        timezone = get_default_timezone()
    
    try:
        tz = pytz.timezone(timezone)
        if dt.tzinfo is None:
            # Assume UTC if naive
            dt = pytz.UTC.localize(dt)
        
        # Convert to target timezone
        dt_local = dt.astimezone(tz)
        return dt_local.strftime('%Y-%m-%d %H:%M:%S %Z')
    except Exception:
        # Fallback to UTC formatting
        return dt.strftime('%Y-%m-%d %H:%M:%S UTC')

