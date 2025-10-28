"""Celery tasks module."""

# Import tasks from publish module
from .publish import publish_post

__all__ = ["publish_post"]

