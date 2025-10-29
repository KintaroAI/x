# Testing Guide: Post Publishing and Job State Transitions

## 🚨 **IMPORTANT: Status Mismatch Issue**

There's a **status mismatch** between `instant_publish` and the state machine:

- `instant_publish()` creates jobs with status `"pending"` (line 464 in `src/api/posts.py`)
- The state machine expects: `"planned"`, `"enqueued"`, `"running"`, `"succeeded"`, `"failed"`, `"cancelled"`, `"dead_letter"`
- The scheduler creates jobs with status `"planned"` and transitions them to `"enqueued"`

**This means instant publish jobs won't be processed correctly!** They need to either:
1. Be created with status `"planned"` and handled by the scheduler, OR
2. Be directly enqueued to Celery with status `"enqueued"`

## Current System Flow

### Flow 1: Scheduled Publishing (via Scheduler)
1. **Schedule Created** → `Schedule` with `next_run_at` set
2. **Scheduler Tick** (runs every minute) → Finds due schedules
3. **Job Created** → `PublishJob` with status `"planned"`
4. **Task Enqueued** → Celery task enqueued, job status → `"enqueued"`
5. **Task Executes** → Job status → `"running"`
6. **Task Completes** → Job status → `"succeeded"` or `"failed"`

### Flow 2: Instant Publish (Current - Has Issue)
1. **User Clicks "Publish Now"** → Calls `/api/posts/{post_id}/instant-publish`
2. **Job Created** → `PublishJob` with status `"pending"` ⚠️
3. **Issue**: Status `"pending"` is not recognized by state machine
4. **Issue**: Scheduler doesn't pick up `"pending"` jobs

## Prerequisites for Testing

### 1. Start Services
```bash
# Start all services (API, workers, beat, Redis, DB)
make dev

# Or manually:
docker compose --profile dev up -d
```

### 2. Verify Services Running
```bash
# Check service status
docker compose ps

# Check Celery worker logs
docker compose logs worker -f

# Check Celery beat logs (scheduler)
docker compose logs beat -f

# Check API logs
docker compose logs api -f
```

### 3. Verify Workers Are Listening
```bash
# Check worker is running
docker compose exec worker celery -A src.celery_app inspect active

# Check registered tasks
docker compose exec worker celery -A src.celery_app inspect registered
```

### 4. Environment Setup
Ensure `.env` or environment variables are set:
- `DRY_RUN=true` (for testing without real X API calls) - **RECOMMENDED for testing**
- `X_CLIENT_ID` and `X_CLIENT_SECRET` (if not in dry-run mode)
- `REDIS_URL` (default: `redis://redis:6379/0`)
- `DATABASE_URL` (default: postgres connection)

## Testing Steps

### Test 1: View Posts and Create Draft

1. **Open UI**: Navigate to `http://localhost:8000`

2. **Create a New Post**:
   - Click "Create Post" button
   - Enter post text (e.g., "Test post for job state tracking")
   - Click "Save Post"
   - You should see: "✓ Post Created Successfully"

3. **View Post List**:
   - You should see your draft post in the list
   - Click on the post to view details (or click "Post #X")

### Test 2: Test Instant Publish (Current Implementation - Has Issues)

1. **Go to Post Detail Page**:
   - From the main page, click on a post to view details
   - Or navigate to `/view-post/{post_id}`

2. **Click "Publish Now" Button**:
   - You should see a success notification
   - The page should reload

3. **Check Job Status**:
   - Scroll to "Publish Jobs" section
   - You should see a job with status `"pending"` ⚠️
   - **Problem**: This job won't be processed because `"pending"` is not in the state machine

4. **Check Worker Logs**:
   ```bash
   docker compose logs worker -f
   ```
   - You should see the task is NOT being picked up (because status is wrong)

### Test 3: Test Scheduled Publishing (via Scheduler)

1. **Create a Schedule** (requires API endpoint or database):
   ```bash
   # Via database (psql)
   docker compose exec db psql -U postgres -d x_scheduler
   
   # Insert a schedule that runs in 1 minute
   INSERT INTO schedules (post_id, kind, schedule_spec, timezone, next_run_at, enabled, created_at, updated_at)
   VALUES (
       1,  -- Replace with your post_id
       'one_shot',
       NOW() + INTERVAL '1 minute',
       'UTC',
       NOW() + INTERVAL '1 minute',
       true,
       NOW(),
       NOW()
   );
   ```

2. **Watch Scheduler Tick**:
   ```bash
   # Watch beat scheduler logs
   docker compose logs beat -f
   ```
   - Every minute you should see: "Starting scheduler tick"
   - When schedule becomes due, you should see: "Found X due schedules"

3. **Watch Worker Process Job**:
   ```bash
   # Watch worker logs
   docker compose logs worker -f
   ```
   - When scheduler enqueues job, you should see task execution
   - Job should transition: `planned` → `enqueued` → `running` → `succeeded`/`failed`

4. **Check Job Status in UI**:
   - Refresh `/view-post/{post_id}` page
   - Check "Publish Jobs" section
   - Status should progress through states

### Test 4: Monitor Job States

**Via Database**:
```bash
docker compose exec db psql -U postgres -d x_scheduler

# View all jobs
SELECT id, schedule_id, status, planned_at, started_at, finished_at, attempt, error 
FROM publish_jobs 
ORDER BY created_at DESC 
LIMIT 10;

# View jobs by status
SELECT status, COUNT(*) FROM publish_jobs GROUP BY status;
```

**Via UI**:
- Go to `/view-post/{post_id}`
- Scroll to "Publish Jobs" section
- Status badges:
  - 🟡 **Pending** (old status, should be fixed)
  - 🟡 **Planned** (created by scheduler, waiting to be enqueued)
  - 🔵 **Running** (task is executing)
  - 🟢 **Completed** (task succeeded) - UI shows this, DB uses `"succeeded"`
  - 🔴 **Failed** (task failed)
  - ⚫ **Cancelled** (manually cancelled)

### Test 5: Test Dry Run Mode

1. **Set Dry Run**:
   ```bash
   # In docker-compose or .env
   DRY_RUN=true
   ```

2. **Publish a Post**:
   - Create and publish a post
   - Check worker logs - should see `[DRY RUN]` messages
   - Job should complete successfully with a fake X post ID

3. **Verify Published Post**:
   - In UI, check "Published Posts" section
   - Should show an entry with X post ID `"dry_run_123"`

### Test 6: Test Error Handling

1. **Disable X API Credentials**:
   ```bash
   # Temporarily remove credentials
   docker compose exec api env | grep X_CLIENT
   ```

2. **Try to Publish**:
   - Create and publish a post
   - Job should fail
   - Check status → should be `"failed"`
   - Check error field → should have error message

3. **Check Retry**:
   - With `max_retries=5` configured, Celery will retry
   - Check job `attempt` field should increment
   - After max retries, job should stay `"failed"`

## Expected State Transitions

### Normal Flow:
```
planned → enqueued → running → succeeded
```

### With Retries:
```
planned → enqueued → running → failed → running (retry) → succeeded
```

### Cancellation:
```
planned → cancelled (terminal)
enqueued → cancelled (terminal)
```

### Exceeding Retries:
```
planned → enqueued → running → failed (attempt 1)
→ running (attempt 2) → failed 
→ ... (max 5 attempts)
→ failed (terminal) or dead_letter (if implemented)
```

## Current Issues to Fix

### Issue 1: Instant Publish Status Mismatch
**Problem**: `instant_publish()` creates jobs with status `"pending"` which is not in the state machine.

**Fix Needed**: Either:
1. Change `instant_publish()` to create with status `"planned"` and let scheduler pick it up (may have delay)
2. OR: Directly enqueue to Celery and set status to `"enqueued"` immediately

**Location**: `src/api/posts.py` line 464

### Issue 2: UI Status Display
**Problem**: UI shows `"completed"` but database uses `"succeeded"`.

**Location**: `templates/view_post.html` line 85

## Database Queries for Debugging

### Check Recent Jobs
```sql
SELECT 
    j.id,
    j.status,
    j.planned_at,
    j.started_at,
    j.finished_at,
    j.attempt,
    j.error,
    s.post_id
FROM publish_jobs j
JOIN schedules s ON j.schedule_id = s.id
ORDER BY j.created_at DESC
LIMIT 10;
```

### Check Job State Distribution
```sql
SELECT status, COUNT(*) as count
FROM publish_jobs
GROUP BY status
ORDER BY count DESC;
```

### Find Stuck Jobs (running > 10 minutes)
```sql
SELECT id, status, started_at, 
       EXTRACT(EPOCH FROM (NOW() - started_at))/60 as minutes_running
FROM publish_jobs
WHERE status = 'running'
  AND started_at < NOW() - INTERVAL '10 minutes';
```

### Check Schedules Ready to Run
```sql
SELECT id, post_id, kind, next_run_at, enabled
FROM schedules
WHERE enabled = true
  AND next_run_at <= NOW()
ORDER BY next_run_at;
```

## Monitoring Checklist

When testing, verify:

- [ ] Celery worker is running and processing tasks
- [ ] Celery beat is running scheduler ticks every minute
- [ ] Redis is accessible and storing task queues
- [ ] Jobs are created with correct status (`"planned"` not `"pending"`)
- [ ] Jobs transition through states correctly
- [ ] Published posts are created in database
- [ ] Error messages are stored in job.error field
- [ ] Retries work correctly (job.attempt increments)
- [ ] Dry-run mode works without hitting X API

## Next Steps After Testing

1. **Fix Instant Publish**: Update `instant_publish()` to use correct status
2. **Add Direct Enqueue**: Optionally enqueue directly to Celery for instant publish
3. **Fix UI Status Display**: Update template to show `"succeeded"` instead of `"completed"`
4. **Add API Endpoint**: Add endpoint to manually trigger scheduler tick (for testing)
5. **Add Job Status Endpoint**: Add `/api/jobs/{job_id}` to query job status via API

## Manual Testing via API

### Check Job Status
```bash
curl http://localhost:8000/api/posts/1 | jq .jobs
```

### Trigger Instant Publish
```bash
curl -X POST http://localhost:8000/api/posts/1/instant-publish
```

### Get Post Details
```bash
curl http://localhost:8000/api/posts/1 | jq .
```

## Tips

1. **Use Dry Run Mode**: Set `DRY_RUN=true` to test without real X API calls
2. **Watch Logs**: Keep terminal windows open with logs for real-time monitoring
3. **Check Database**: Use psql to directly inspect job states
4. **Refresh UI**: The UI doesn't auto-refresh, manually refresh to see state changes
5. **Timing**: Scheduler runs every minute, so jobs may take up to 60 seconds to be picked up

