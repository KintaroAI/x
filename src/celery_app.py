"""Celery application configuration."""

import os
from celery import Celery
from celery.schedules import crontab

# Redis URL from environment
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# Create Celery app
app = Celery("posting_worker")

# Configure Celery
app.conf.update(
    broker_url=REDIS_URL,
    result_backend=REDIS_URL,
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=300,  # 5 minutes
    task_soft_time_limit=240,  # 4 minutes
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    worker_disable_rate_limits=False,
    task_ignore_result=True,  # Ignore results to reduce Redis churn
)

# Queue Configuration
app.conf.task_routes = {
    "publish.post": {"queue": "publish"},
    "metrics.capture": {"queue": "metrics"},
    "media.prepare": {"queue": "media"},
    "scheduler.tick": {"queue": "scheduler"},  # Beat scheduler tick
    "process_dead_letter": {"queue": "dlq"},
}

# Rate-limit tier configuration
API_TIER = os.getenv("X_API_TIER", "basic")

# Beat schedule configuration
app.conf.beat_schedule = {
    "scheduler-tick-every-60s": {
        "task": "scheduler.tick",
        "schedule": crontab(minute="*"),  # Every minute
    },
    "cleanup-orphaned-jobs-every-5min": {
        "task": "scheduler.cleanup_orphaned_jobs",
        "schedule": crontab(minute="*/5"),  # Every 5 minutes
    },
}

# Import tasks here so they're registered
from src.tasks import publish, scheduler

