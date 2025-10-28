# Redis-Backed Worker Implementation Plan

## Overview

This document outlines the implementation plan for transitioning from the current APScheduler-based system to a production-ready Redis-backed worker system using Celery. The new system will provide better scalability, reliability, and observability for scheduled posting and metrics collection.

## Current State Analysis

### ✅ Already Implemented
- **Database Models**: All core models are in place (`posts`, `schedules`, `publish_jobs`, `published_posts`, `metrics_snapshots`)
- **API Endpoints**: Basic CRUD operations for posts and schedules
- **Database Setup**: PostgreSQL with Alembic migrations
- **Docker Infrastructure**: Multi-service setup with Redis already configured
- **Dependencies**: All required packages are in `requirements.txt`

### 🔄 Needs Updates
- **PublishJob Model**: Missing `enqueued_at`, `attempt`, `last_run_at` fields
- **Worker Implementation**: Currently just a stub
- **Idempotency**: Basic dedupe_key exists but needs Redis guards
- **Rate Limiting**: Not implemented
- **Error Handling**: Basic retry logic missing
- **Metrics Collection**: Not automated

## Implementation Plan

### Phase 1: Database Schema Updates

#### 1.1 Update PublishJob Model
```sql
-- Add missing fields to publish_jobs table
ALTER TABLE publish_jobs ADD COLUMN enqueued_at TIMESTAMPTZ;
ALTER TABLE publish_jobs ADD COLUMN attempt INTEGER NOT NULL DEFAULT 0;
ALTER TABLE publish_jobs ADD COLUMN last_run_at TIMESTAMPTZ;

-- Update status enum to match new state machine
-- Current: 'pending', 'running', 'completed', 'failed', 'cancelled'
-- New: 'planned', 'enqueued', 'running', 'succeeded', 'failed', 'dead_letter'

-- Add unique constraint for idempotency
ALTER TABLE publish_jobs ADD CONSTRAINT unique_schedule_planned_at 
UNIQUE (schedule_id, planned_at);
```

#### 1.2 Add Post Status Field
```sql
-- Add status field to posts table
ALTER TABLE posts ADD COLUMN status VARCHAR(20) NOT NULL DEFAULT 'draft';
-- Values: 'draft', 'scheduled', 'published', 'failed'
```

#### 1.3 Update Schedule Model
```sql
-- Add last_run_at field to schedules
ALTER TABLE schedules ADD COLUMN last_run_at TIMESTAMPTZ;
```

### Phase 2: Celery Configuration

#### 2.1 Celery App Setup
Create `src/celery_app.py`:
```python
from celery import Celery
import os

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
)
```

#### 2.2 Queue Configuration
```python
# Define queues
app.conf.task_routes = {
    "src.tasks.publish_post": {"queue": "publish"},
    "src.tasks.capture_metrics": {"queue": "metrics"},
    "src.tasks.prepare_media": {"queue": "media"},
    "src.tasks.dead_letter_handler": {"queue": "dlq"},
}
```

### Phase 3: Task Definitions

#### 3.1 Publish Post Task
```python
@app.task(
    name="publish.post",
    queue="publish",
    acks_late=True,
    max_retries=5,
    autoretry_for=(TransientHTTPError,),
    retry_backoff=True,
    retry_jitter=True,
    rate_limit="5/m",  # Adjust based on X API limits
)
def publish_post(job_id: str):
    """Publish a post to X/Twitter."""
    # Implementation details below
```

#### 3.2 Metrics Capture Task
```python
@app.task(
    name="metrics.capture",
    queue="metrics",
    acks_late=True,
)
def capture_metrics(x_post_id: str, stage: str = "fast"):
    """Capture metrics for a published post."""
    # Implementation details below
```

#### 3.3 Media Preparation Task
```python
@app.task(
    name="media.prepare",
    queue="media",
    acks_late=True,
    max_retries=3,
)
def prepare_media(media_refs: List[str]):
    """Prepare media for posting."""
    # Implementation details below
```

### Phase 4: Scheduler Service

#### 4.1 Schedule Resolution
Create `src/services/scheduler.py`:
```python
class ScheduleResolver:
    """Resolves schedules to next run times."""
    
    def resolve_schedule(self, schedule: Schedule) -> Optional[datetime]:
        """Calculate next_run_at for a schedule."""
        if schedule.kind == "one_shot":
            return self._resolve_one_shot(schedule)
        elif schedule.kind == "cron":
            return self._resolve_cron(schedule)
        elif schedule.kind == "rrule":
            return self._resolve_rrule(schedule)
        return None
```

#### 4.2 Scheduler Worker
```python
@app.task(name="scheduler.tick", queue="scheduler")
def scheduler_tick():
    """Main scheduler loop - runs every minute."""
    # Find due schedules
    # Create publish_jobs
    # Enqueue tasks with ETA
    # Update next_run_at
```

### Phase 5: Idempotency & Deduplication

#### 5.1 Redis Guards
```python
def acquire_dedupe_lock(schedule_id: int, planned_at: datetime) -> bool:
    """Acquire Redis lock for deduplication."""
    key = f"dedupe:{schedule_id}:{planned_at.isoformat()}"
    return redis_client.setnx(key, "1", ex=172800)  # 2 days TTL
```

#### 5.2 Database Constraints
- Unique constraint on `(schedule_id, planned_at)`
- Check for existing jobs in terminal states before enqueueing

### Phase 6: State Machine Implementation

#### 6.1 PublishJob State Transitions
```python
class PublishJobStateMachine:
    """Manages state transitions for publish jobs."""
    
    VALID_TRANSITIONS = {
        "planned": ["enqueued", "cancelled"],
        "enqueued": ["running", "cancelled"],
        "running": ["succeeded", "failed"],
        "failed": ["running", "dead_letter"],  # retry or give up
        "succeeded": [],  # terminal
        "dead_letter": [],  # terminal
        "cancelled": [],  # terminal
    }
```

#### 6.2 Atomic State Updates
```python
def update_job_status(job_id: int, new_status: str, **kwargs):
    """Atomically update job status with database lock."""
    with get_db() as db:
        job = db.query(PublishJob).filter(
            PublishJob.id == job_id
        ).with_for_update().first()
        
        if not job:
            raise ValueError(f"Job {job_id} not found")
            
        # Validate transition
        if new_status not in VALID_TRANSITIONS.get(job.status, []):
            raise ValueError(f"Invalid transition: {job.status} -> {new_status}")
            
        # Update fields
        job.status = new_status
        for key, value in kwargs.items():
            setattr(job, key, value)
            
        db.commit()
```

### Phase 7: Error Handling & Retry Logic

#### 7.1 Retry Strategy
```python
class RetryStrategy:
    """Handles retry logic for different error types."""
    
    TRANSIENT_ERRORS = (429, 500, 502, 503, 504)  # HTTP status codes
    PERMANENT_ERRORS = (400, 401, 403, 404)  # Don't retry these
    
    def should_retry(self, error: Exception) -> bool:
        """Determine if error should trigger retry."""
        if isinstance(error, HTTPError):
            return error.response.status_code in self.TRANSIENT_ERRORS
        return True  # Retry other exceptions
    
    def get_backoff_delay(self, attempt: int) -> int:
        """Calculate exponential backoff with jitter."""
        base_delay = min(30 * (2 ** attempt), 1200)  # Max 20 minutes
        jitter = random.uniform(0.5, 1.5)
        return int(base_delay * jitter)
```

#### 7.2 Dead Letter Queue
```python
@app.task(name="dlq.process", queue="dlq")
def process_dead_letter(job_id: int):
    """Process jobs that have exhausted retries."""
    # Log final error
    # Send alert/notification
    # Store in dead letter table for manual review
```

### Phase 8: Rate Limiting

#### 8.1 X API Rate Limits
```python
# Configure based on X API tier
RATE_LIMITS = {
    "free": "1/m",      # 1 post per minute
    "basic": "5/m",     # 5 posts per minute  
    "pro": "50/m",      # 50 posts per minute
    "enterprise": "300/m"  # 300 posts per minute
}
```

#### 8.2 Celery Rate Limiting
```python
# Apply rate limits to publish tasks
app.conf.task_routes = {
    "publish.post": {
        "queue": "publish",
        "rate_limit": RATE_LIMITS[API_TIER]
    }
}
```

### Phase 9: Metrics Collection

#### 9.1 Metrics Polling Strategy
```python
class MetricsPollingStrategy:
    """Manages metrics collection cadence."""
    
    POLLING_SCHEDULE = {
        "fast": [15, 30, 60, 120],  # minutes
        "medium": [240, 480, 720],  # hours  
        "slow": [1440, 2880, 4320, 5760, 7200, 8640, 10080]  # days
    }
    
    def get_next_poll_time(self, stage: str, current_attempt: int) -> Optional[datetime]:
        """Get next polling time based on stage and attempt."""
        schedule = self.POLLING_SCHEDULE.get(stage, [])
        if current_attempt >= len(schedule):
            return None  # Stop polling
            
        minutes = schedule[current_attempt]
        return datetime.utcnow() + timedelta(minutes=minutes)
```

#### 9.2 Metrics Capture Implementation
```python
def capture_metrics(x_post_id: str, stage: str = "fast"):
    """Capture metrics for a published post."""
    # Fetch metrics from X API
    # Store in metrics_snapshots table
    # Schedule next capture if needed
    # Handle rate limiting
```

### Phase 10: API Integration

#### 10.1 X API Client
```python
class XAPIClient:
    """Client for X/Twitter API interactions."""
    
    def __init__(self, access_token: str):
        self.access_token = access_token
        self.client = httpx.AsyncClient(
            base_url="https://api.x.com/2",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=30.0
        )
    
    async def create_post(self, text: str, media_ids: List[str] = None):
        """Create a post on X."""
        payload = {"text": text}
        if media_ids:
            payload["media"] = {"media_ids": media_ids}
            
        response = await self.client.post("/tweets", json=payload)
        response.raise_for_status()
        return response.json()
    
    async def get_metrics(self, tweet_id: str):
        """Get metrics for a tweet."""
        response = await self.client.get(
            f"/tweets/{tweet_id}",
            params={"tweet.fields": "public_metrics,non_public_metrics"}
        )
        response.raise_for_status()
        return response.json()
```

### Phase 11: Observability & Monitoring

#### 11.1 Logging Configuration
```python
import structlog

# Configure structured logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer()
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)
```

#### 11.2 Metrics Export
```python
from prometheus_client import Counter, Histogram, Gauge

# Define metrics
PUBLISH_ATTEMPTS = Counter('publish_attempts_total', 'Total publish attempts', ['status'])
PUBLISH_DURATION = Histogram('publish_duration_seconds', 'Publish job duration')
QUEUE_SIZE = Gauge('queue_size', 'Current queue size', ['queue_name'])
```

#### 11.3 Health Checks
```python
@app.task(name="health.check")
def health_check():
    """Periodic health check."""
    # Check Redis connectivity
    # Check database connectivity  
    # Check X API connectivity
    # Report queue sizes
    # Report worker status
```

### Phase 12: Deployment & Configuration

#### 12.1 Environment Configuration
```python
# .env.dev
ENVIRONMENT=dev
X_API_TIER=free
DRY_RUN=true
LOG_LEVEL=DEBUG

# .env.prod  
ENVIRONMENT=prod
X_API_TIER=pro
DRY_RUN=false
LOG_LEVEL=INFO
```

#### 12.2 Docker Compose Updates
```yaml
# Add Celery worker services
worker-publish:
  build: .
  command: celery -A src.celery_app worker --loglevel=info --queues=publish
  depends_on: [redis, db]

worker-metrics:
  build: .
  command: celery -A src.celery_app worker --loglevel=info --queues=metrics
  depends_on: [redis, db]

worker-scheduler:
  build: .
  command: celery -A src.celery_app worker --loglevel=info --queues=scheduler
  depends_on: [redis, db]

beat:
  build: .
  command: celery -A src.celery_app beat --loglevel=info
  depends_on: [redis, db]
```

#### 12.3 Monitoring Setup
```yaml
# Add monitoring services
flower:
  build: .
  command: celery -A src.celery_app flower
  ports: ["5555:5555"]
  depends_on: [redis]

prometheus:
  image: prom/prometheus
  ports: ["9090:9090"]
  volumes: ["./prometheus.yml:/etc/prometheus/prometheus.yml"]

grafana:
  image: grafana/grafana
  ports: ["3000:3000"]
  environment:
    - GF_SECURITY_ADMIN_PASSWORD=admin
```

## Implementation Timeline

### Week 1: Foundation
- [ ] Update database schema (migrations)
- [ ] Set up Celery configuration
- [ ] Implement basic task structure
- [ ] Add Redis idempotency guards

### Week 2: Core Workers
- [ ] Implement publish worker with retry logic
- [ ] Implement scheduler service
- [ ] Add state machine for job management
- [ ] Implement X API client

### Week 3: Advanced Features
- [ ] Implement metrics collection worker
- [ ] Add rate limiting and backoff strategies
- [ ] Implement dead letter queue handling
- [ ] Add comprehensive error handling

### Week 4: Production Readiness
- [ ] Add observability and monitoring
- [ ] Implement health checks
- [ ] Update API endpoints
- [ ] Add comprehensive testing
- [ ] Deploy and validate

## Testing Strategy

### Unit Tests
- Task functions with mocked dependencies
- State machine transitions
- Retry logic and backoff strategies
- X API client with mocked responses

### Integration Tests
- End-to-end publish flow
- Schedule resolution and job creation
- Metrics collection pipeline
- Error handling and recovery

### Load Tests
- Concurrent job processing
- Rate limit handling
- Queue performance under load
- Database connection pooling

## Migration Strategy

### Phase 1: Parallel Deployment
- Deploy new worker system alongside existing APScheduler
- Use feature flags to control which system processes jobs
- Gradually migrate schedules to new system

### Phase 2: Validation
- Run both systems in parallel for validation period
- Compare results and performance
- Monitor for any discrepancies

### Phase 3: Cutover
- Disable APScheduler system
- Route all new schedules to Celery system
- Monitor system performance and stability

## Rollback Plan

### Immediate Rollback
- Re-enable APScheduler system
- Disable Celery workers
- Restore previous API endpoints

### Data Recovery
- Export job status from Celery system
- Import into APScheduler-compatible format
- Resume processing with previous system

## Success Metrics

### Performance
- Job processing latency < 30 seconds
- 99.9% job success rate
- Queue processing rate > 100 jobs/minute

### Reliability
- Zero data loss during migration
- Automatic recovery from transient failures
- Dead letter queue size < 1% of total jobs

### Observability
- Real-time monitoring dashboard
- Alerting for critical failures
- Comprehensive audit trail

## Risk Mitigation

### Technical Risks
- **Redis failure**: Implement Redis clustering and failover
- **Database locks**: Use proper transaction isolation
- **API rate limits**: Implement intelligent backoff
- **Memory leaks**: Monitor worker memory usage

### Operational Risks
- **Deployment issues**: Use blue-green deployment
- **Data corruption**: Implement data validation
- **Performance degradation**: Load test before deployment
- **Security vulnerabilities**: Regular security audits

## Future Enhancements

### Scalability
- Horizontal worker scaling
- Multi-region deployment
- Advanced queue routing

### Features
- Advanced scheduling (timezone support, holidays)
- Media processing pipeline
- A/B testing for posts
- Analytics dashboard

### Integration
- Multiple social platforms
- Webhook notifications
- Third-party analytics tools
- Enterprise SSO integration

---

This implementation plan provides a comprehensive roadmap for transitioning to a production-ready Redis-backed worker system. The phased approach ensures minimal disruption while delivering robust, scalable, and observable scheduling capabilities.
