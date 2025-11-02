# Post Variant Selection Implementation Plan

## Overview

This plan implements a system where **one schedule** can publish **one of several text variants** each time it fires. This enables A/B testing, content variation, and learning which variants perform best—all while maintaining idempotency, retry safety, and production reliability.

## Goals

1. **One schedule → multiple text variants**: A schedule references a template, which contains multiple variants.
2. **Deterministic variant selection**: Same planned time always selects the same variant (stable on retries/replays).
3. **Selection policies**: Support multiple selection strategies (random, weighted, round-robin, no-repeat, bandit).
4. **Idempotency**: Selection happens once at job creation; retries use the same variant.
5. **Non-breaking migration**: Support existing posts/schedules during transition.
6. **Future-ready**: Designed to plug into metrics collection for bandit learning.

---

## Database Schema Changes

### New Tables

#### 1. `post_templates`
Logical parent for grouping variants. Stores metadata about the template.

```sql
CREATE TABLE post_templates (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    created_by VARCHAR(100),  -- Optional: user tracking
    active BOOLEAN DEFAULT TRUE
);

CREATE INDEX idx_post_templates_active ON post_templates(active);
```

#### 2. `post_variants`
Individual text variants that belong to a template.

```sql
CREATE TABLE post_variants (
    id SERIAL PRIMARY KEY,
    template_id INTEGER NOT NULL REFERENCES post_templates(id) ON DELETE CASCADE,
    text TEXT NOT NULL,  -- The actual post text
    weight INTEGER DEFAULT 1,  -- For weighted selection
    active BOOLEAN DEFAULT TRUE,  -- Can disable individual variants
    media_refs TEXT,  -- JSON array (same format as Post.media_refs)
    locale VARCHAR(10),  -- Optional: for future i18n
    tags TEXT,  -- Optional: comma-separated tags for filtering
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    created_by VARCHAR(100)  -- Optional: user tracking
);

CREATE INDEX idx_post_variants_template_id ON post_variants(template_id);
CREATE INDEX idx_post_variants_active ON post_variants(template_id, active) WHERE active = TRUE;
```

#### 3. `variant_selection_history`
Tracks recent variant selections for no-repeat window policy.

```sql
CREATE TABLE variant_selection_history (
    id SERIAL PRIMARY KEY,
    template_id INTEGER NOT NULL REFERENCES post_templates(id) ON DELETE CASCADE,
    variant_id INTEGER NOT NULL REFERENCES post_variants(id) ON DELETE CASCADE,
    planned_at TIMESTAMP NOT NULL,  -- When this selection was planned (for clarity and dedupe)
    selected_at TIMESTAMP NOT NULL DEFAULT NOW(),  -- When history was recorded
    schedule_id INTEGER NOT NULL REFERENCES schedules(id) ON DELETE CASCADE,
    job_id INTEGER NOT NULL REFERENCES publish_jobs(id) ON DELETE CASCADE,  -- Required: link to job
    
    -- No unique constraint on (template_id, variant_id, selected_at) - allow duplicates
    -- Instead, rely on UNIQUE(schedule_id, planned_at) on publish_jobs for deduplication
    -- Optional unique guard here too:
    -- CONSTRAINT uniq_variant_hist_sched_planned UNIQUE (schedule_id, planned_at)
);

CREATE INDEX idx_variant_selection_template_date 
    ON variant_selection_history(template_id, selected_at DESC);
CREATE INDEX idx_variant_selection_template_variant 
    ON variant_selection_history(template_id, variant_id);
CREATE INDEX idx_variant_selection_schedule_date 
    ON variant_selection_history(schedule_id, selected_at DESC);
CREATE INDEX idx_variant_selection_job_id 
    ON variant_selection_history(job_id);
```

### Modified Tables

#### 1. `schedules`
Add `template_id` field. During migration, support both `post_id` (legacy) and `template_id` (new).

```sql
ALTER TABLE schedules 
    ADD COLUMN template_id INTEGER REFERENCES post_templates(id) ON DELETE CASCADE,
    ADD COLUMN selection_policy VARCHAR(50) DEFAULT 'RANDOM_UNIFORM',
    ADD COLUMN no_repeat_window INTEGER DEFAULT 0,  -- N fires to exclude
    ADD COLUMN no_repeat_scope VARCHAR(20) DEFAULT 'template';  -- 'template' or 'schedule'

-- Make post_id nullable (or keep required for backwards compat during migration)
-- During transition: post_id OR template_id must be set
CREATE INDEX idx_schedules_template_id ON schedules(template_id);
```

**Migration strategy**: 
- Initially keep `post_id` required
- Add `template_id` as nullable
- Code checks both during transition
- Later migration makes one of them required (enforced by app logic)

#### 2. `publish_jobs`
Add variant selection fields.

```sql
ALTER TABLE publish_jobs 
    ADD COLUMN variant_id INTEGER REFERENCES post_variants(id) ON DELETE SET NULL,
    ADD COLUMN selection_policy VARCHAR(50),  -- Copy from schedule for audit
    ADD COLUMN selection_seed BIGINT,  -- Deterministic seed for reproducibility
    ADD COLUMN selected_at TIMESTAMP;  -- When selection occurred

-- CRITICAL: Unique constraint to prevent duplicate jobs across workers
-- This is the true deduplication guard (matches existing dedupe_key logic)
CREATE UNIQUE INDEX uniq_publish_jobs_schedule_planned 
    ON publish_jobs(schedule_id, planned_at);

CREATE INDEX idx_publish_jobs_variant_id ON publish_jobs(variant_id);
CREATE INDEX idx_publish_jobs_selection_seed ON publish_jobs(selection_seed);
```

#### 3. `published_posts`
Add `variant_id` field to track which variant was published (for metrics/analytics and bandit learning).

```sql
ALTER TABLE published_posts 
    ADD COLUMN variant_id INTEGER REFERENCES post_variants(id) ON DELETE SET NULL;

CREATE INDEX idx_published_posts_variant_id ON published_posts(variant_id);
```

---

## Model Changes (`src/models.py`)

### New Models

```python
class PostTemplate(Base):
    """Model for grouping post variants."""
    __tablename__ = "post_templates"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    created_by = Column(String(100), nullable=True)
    active = Column(Boolean, default=True, nullable=False, index=True)
    
    # Relationships
    variants = relationship("PostVariant", back_populates="template", cascade="all, delete-orphan")
    schedules = relationship("Schedule", back_populates="template")
    
    def __repr__(self):
        return f"<PostTemplate(id={self.id}, name={self.name})>"


class PostVariant(Base):
    """Model for individual post text variants."""
    __tablename__ = "post_variants"
    
    id = Column(Integer, primary_key=True, index=True)
    template_id = Column(Integer, ForeignKey("post_templates.id"), nullable=False, index=True)
    text = Column(Text, nullable=False)
    weight = Column(Integer, default=1, nullable=False)
    active = Column(Boolean, default=True, nullable=False, index=True)
    media_refs = Column(Text, nullable=True)
    locale = Column(String(10), nullable=True)
    tags = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    created_by = Column(String(100), nullable=True)
    
    # Relationships
    template = relationship("PostTemplate", back_populates="variants")
    publish_jobs = relationship("PublishJob", back_populates="variant")
    selection_history = relationship("VariantSelectionHistory", back_populates="variant")
    
    def __repr__(self):
        return f"<PostVariant(id={self.id}, template_id={self.template_id}, text={self.text[:50]}...)>"


class VariantSelectionHistory(Base):
    """Model for tracking variant selection history (no-repeat window)."""
    __tablename__ = "variant_selection_history"
    
    id = Column(Integer, primary_key=True, index=True)
    template_id = Column(Integer, ForeignKey("post_templates.id"), nullable=False, index=True)
    variant_id = Column(Integer, ForeignKey("post_variants.id"), nullable=False, index=True)
    planned_at = Column(DateTime, nullable=False, index=True)  -- When this selection was planned
    selected_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)  -- When history was recorded
    schedule_id = Column(Integer, ForeignKey("schedules.id"), nullable=False, index=True)
    job_id = Column(Integer, ForeignKey("publish_jobs.id"), nullable=False, index=True)  -- Required
    
    # Relationships
    template = relationship("PostTemplate")
    variant = relationship("PostVariant", back_populates="selection_history")
    schedule = relationship("Schedule")
    job = relationship("PublishJob")
    
    def __repr__(self):
        return f"<VariantSelectionHistory(template_id={self.template_id}, variant_id={self.variant_id})>"
```

### Modified Models

```python
# Schedule model changes
class Schedule(Base):
    # ... existing fields ...
    
    # Add new fields
    template_id = Column(Integer, ForeignKey("post_templates.id"), nullable=True, index=True)
    selection_policy = Column(String(50), default="RANDOM_UNIFORM", nullable=False)
    no_repeat_window = Column(Integer, default=0, nullable=False)
    no_repeat_scope = Column(String(20), default="template", nullable=False)  -- 'template' or 'schedule'
    last_variant_pos = Column(Integer, nullable=True)  -- For round-robin state tracking
    
    # Keep post_id for backwards compatibility (make nullable later if needed)
    # post_id = Column(Integer, ForeignKey("posts.id"), nullable=True)  # Eventually nullable
    
    # Relationships
    template = relationship("PostTemplate", back_populates="schedules")
    # post relationship remains for backwards compat


# PublishJob model changes
class PublishJob(Base):
    # ... existing fields ...
    
    # Add new fields
    variant_id = Column(Integer, ForeignKey("post_variants.id"), nullable=True, index=True)
    selection_policy = Column(String(50), nullable=True)  # Copy from schedule
    selection_seed = Column(BigInteger, nullable=True, index=True)
    selected_at = Column(DateTime, nullable=True)
    
    # Relationships
    variant = relationship("PostVariant", back_populates="publish_jobs")


# PublishedPost model changes
class PublishedPost(Base):
    # ... existing fields ...
    
    # Add new field
    variant_id = Column(Integer, ForeignKey("post_variants.id"), nullable=True, index=True)
    
    # Relationships
    variant = relationship("PostVariant")  # Optional: link to variant
```

---

## Variant Selection Service

### New File: `src/services/variant_service.py`

```python
"""Service for selecting post variants based on policies."""

import hashlib
import random
import logging
from datetime import datetime, timedelta
from typing import List, Optional
from sqlalchemy.orm import Session
import pytz

from src.models import PostVariant, VariantSelectionHistory, Schedule

logger = logging.getLogger(__name__)


class VariantSelector:
    """Selects variants based on policies."""
    
    def __init__(self, db: Session):
        self.db = db
    
    def select_variant(
        self,
        schedule: Schedule,
        planned_at: datetime,
        seed: Optional[int] = None
    ) -> tuple[Optional[PostVariant], int]:
        """
        Select a variant for a schedule at a given planned time.
        
        Args:
            schedule: Schedule object (must have template_id set)
            planned_at: Planned execution time
            seed: Optional seed for deterministic selection
        
        Returns:
            Tuple of (Selected PostVariant or None, seed used for selection)
        """
        if not schedule.template_id:
            logger.warning(f"Schedule {schedule.id} has no template_id")
            return None, 0
        
        # Fetch active variants
        variants = (
            self.db.query(PostVariant)
            .filter(
                PostVariant.template_id == schedule.template_id,
                PostVariant.active.is_(True)
            )
            .all()
        )
        
        if not variants:
            logger.warning(f"No active variants for template {schedule.template_id}")
            return None, 0
        
        # Generate deterministic seed if not provided
        # Normalize planned_at to UTC and remove microseconds for consistency
        if seed is None:
            planned_at_normalized = planned_at
            if planned_at.tzinfo is None:
                planned_at_normalized = pytz.UTC.localize(planned_at)
            else:
                planned_at_normalized = planned_at.astimezone(pytz.UTC)
            # Remove microseconds for second-precision consistency
            planned_at_normalized = planned_at_normalized.replace(microsecond=0)
            seed = self._generate_seed(schedule.id, planned_at_normalized)
        
        # Create RNG from seed for deterministic randomness
        rng = random.Random(seed)
        
        # Apply no-repeat window filtering if enabled
        pool = self._apply_no_repeat_window(
            variants, 
            schedule,
            planned_at
        )
        
        if not pool:
            # All variants excluded by no-repeat window, fall back to all variants
            logger.info(f"All variants excluded by no-repeat window, using full pool")
            pool = variants
        
        # Select based on policy
        selected = self._select_by_policy(pool, schedule, rng)
        
        return selected, seed
    
    def _generate_seed(self, schedule_id: int, planned_at: datetime) -> int:
        """Generate deterministic seed from schedule_id and planned_at.
        
        CRITICAL: Normalize planned_at to UTC to avoid DST/timezone drift affecting seed.
        """
        # Normalize to UTC (if naive, assume UTC)
        if planned_at.tzinfo is None:
            # Assume naive datetime is in UTC
            planned_at_utc = pytz.UTC.localize(planned_at)
        else:
            planned_at_utc = planned_at.astimezone(pytz.UTC)
        
        # Normalize to UTC and remove microseconds for second-precision consistency
        planned_at_normalized = planned_at_utc.replace(microsecond=0)
        seed_str = f"{schedule_id}:{planned_at_normalized.isoformat()}"
        seed_bytes = hashlib.sha256(seed_str.encode()).digest()
        return int.from_bytes(seed_bytes[:8], "big")  # Use first 8 bytes for int64
    
    def _apply_no_repeat_window(
        self,
        variants: List[PostVariant],
        schedule: Schedule,
        planned_at: datetime
    ) -> List[PostVariant]:
        """
        Filter variants that were recently used (no-repeat window).
        
        Scope can be 'template' (across all schedules) or 'schedule' (per schedule only).
        
        Returns list of variants that haven't been used in the last N fires.
        """
        if schedule.no_repeat_window <= 0:
            return variants
        
        # Build query based on scope
        query = self.db.query(VariantSelectionHistory.variant_id)
        
        if schedule.no_repeat_scope == 'schedule':
            # Per-schedule scope: only exclude variants used by this specific schedule
            query = query.filter(
                VariantSelectionHistory.schedule_id == schedule.id,
                VariantSelectionHistory.selected_at <= planned_at
            )
        else:
            # Template scope (default): exclude variants used by any schedule with this template
            query = query.filter(
                VariantSelectionHistory.template_id == schedule.template_id,
                VariantSelectionHistory.selected_at <= planned_at
            )
        
        # Get recent selections (last N selections)
        recent_selections = (
            query
            .order_by(VariantSelectionHistory.selected_at.desc())
            .limit(schedule.no_repeat_window)
            .all()
        )
        
        excluded_variant_ids = {sel.variant_id for sel in recent_selections}
        
        # Filter out recently used variants
        return [v for v in variants if v.id not in excluded_variant_ids]
    
    def _select_by_policy(
        self,
        pool: List[PostVariant],
        schedule: Schedule,
        rng: random.Random
    ) -> PostVariant:
        """Select variant based on policy."""
        if not pool:
            return None
        
        policy = schedule.selection_policy
        
        if policy == "RANDOM_WEIGHTED":
            weights = [v.weight for v in pool]
            return rng.choices(pool, weights=weights, k=1)[0]
        
        elif policy == "ROUND_ROBIN":
            # True round-robin: track last position per schedule
            # Sort variants by ID for stable ordering
            sorted_pool = sorted(pool, key=lambda v: v.id)
            n = len(sorted_pool)
            
            # Get last position (or start at -1 if no previous selection)
            last_pos = schedule.last_variant_pos if schedule.last_variant_pos is not None else -1
            
            # Next position: (last_pos + 1) % n
            next_pos = (last_pos + 1) % n
            selected = sorted_pool[next_pos]
            
            # Update last_variant_pos to next_pos (caller must persist in same transaction)
            schedule.last_variant_pos = next_pos
            
            return selected
        
        elif policy == "NO_REPEAT_WINDOW":
            # Selection already filtered by _apply_no_repeat_window
            return rng.choice(pool)
        
        elif policy == "RANDOM_UNIFORM":
        default:
            return rng.choice(pool)
    
    def record_selection(
        self,
        template_id: int,
        variant_id: int,
        schedule_id: int,
        job_id: int,
        planned_at: datetime,
        selected_at: Optional[datetime] = None
    ):
        """Record variant selection in history.
        
        CRITICAL: Must be called AFTER job is created (so we have job_id).
        This ensures history is linked to the job from the start.
        
        Args:
            planned_at: The planned execution time (for clarity and dedupe)
            selected_at: When history was recorded (defaults to now)
        """
        if selected_at is None:
            selected_at = datetime.utcnow()
        
        history = VariantSelectionHistory(
            template_id=template_id,
            variant_id=variant_id,
            schedule_id=schedule_id,
            job_id=job_id,
            planned_at=planned_at,
            selected_at=selected_at
        )
        self.db.add(history)
        # Note: Don't commit here - let caller commit
    
    def get_active_variants(self, template_id: int) -> List[PostVariant]:
        """Get all active variants for a template."""
        return (
            self.db.query(PostVariant)
            .filter(
                PostVariant.template_id == template_id,
                PostVariant.active.is_(True)
            )
            .all()
        )
    
    def validate_content_safety(
        self,
        variant: PostVariant,
        recent_published: Optional[List[str]] = None,
        window_size: int = 10
    ) -> tuple[bool, Optional[str]]:
        """
        Validate variant content for safety:
        - Check X character/word limits
        - Check for near-duplicate content using rolling hash of final body
        
        Args:
            variant: Variant to validate
            recent_published: List of recently published post texts (last N)
            window_size: Number of recent publishes to check (if recent_published not provided)
        
        Returns: (is_valid, error_message)
        """
        # Check X character limit (280 for text posts)
        if len(variant.text) > 280:
            return False, f"Text exceeds 280 characters: {len(variant.text)}"
        
        # Check for near-duplicate content using rolling hash
        if recent_published is None:
            # Fetch recent published texts from database
            from src.models import PublishedPost
            recent_posts = (
                self.db.query(PublishedPost)
                .order_by(PublishedPost.published_at.desc())
                .limit(window_size)
                .all()
            )
            recent_published = []
            for pub_post in recent_posts:
                if pub_post.variant_id:
                    variant_obj = (
                        self.db.query(PostVariant)
                        .filter(PostVariant.id == pub_post.variant_id)
                        .first()
                    )
                    if variant_obj:
                        recent_published.append(variant_obj.text)
                # Could also check pub_post.post.text if post_id is set
        
        if recent_published:
            import difflib
            # Compute hash of final body (after any placeholder expansion)
            variant_hash = hashlib.md5(variant.text.encode()).hexdigest()
            for recent_text in recent_published:
                recent_hash = hashlib.md5(recent_text.encode()).hexdigest()
                if variant_hash == recent_hash:
                    return False, "Exact duplicate of recently published content"
                
                # Check similarity (configurable threshold)
                similarity = difflib.SequenceMatcher(
                    None, variant.text, recent_text
                ).ratio()
                if similarity > 0.9:  # 90% similarity threshold
                    return False, f"Near-duplicate content (similarity: {similarity:.2%})"
        
        return True, None
```

**Notes:**
- **Round-Robin**: Implements true round-robin by tracking `last_variant_pos` per schedule. Variants are sorted by ID for stable ordering, and we cycle through them deterministically. If a variant is deactivated, we restart from position 0.
- **Seed Generation**: Normalizes `planned_at` to UTC before generating seed to avoid DST/timezone drift affecting selection.
- **No-Repeat Scope**: Supports both `'template'` (across all schedules) and `'schedule'` (per schedule only) scoping.
- **History Recording**: History is recorded AFTER job creation (so `job_id` is available). All within the same transaction with schedule row locked.
- **Content Safety**: `validate_content_safety()` method checks character limits and near-duplicate content. Called at selection time for lightweight validation, and optionally at publish time for full checks.

---

## Scheduler Integration

### Modify `src/tasks/scheduler.py`

**Changes to `scheduler_tick()` function:**

```python
@app.task(name="scheduler.tick", ...)
def scheduler_tick():
    """Main scheduler loop - runs every minute via Celery Beat."""
    logger.info("Starting scheduler tick")
    
    try:
        with get_db() as db:
            # ... existing due_schedules query ...
            
            scheduler_resolver = ScheduleResolver()
            variant_selector = VariantSelector(db)  # NEW
            jobs_created = 0
            
            for schedule in due_schedules:
                try:
                    planned_at = schedule.next_run_at
                    
                    # ... existing dedupe lock check ...
                    
                    # VARIANT SELECTION (NEW) - All within the same transaction
                    # Schedule row is already locked via WITH FOR UPDATE SKIP LOCKED
                    selected_variant = None
                    selection_seed = None
                    
                    if schedule.template_id:
                        # New template-based schedule
                        # select_variant returns both variant and seed (single generation)
                        selected_variant, selection_seed = variant_selector.select_variant(
                            schedule, 
                            planned_at
                        )
                        
                        if not selected_variant:
                            logger.error(
                                f"Schedule {schedule.id} has no active variants, skipping"
                            )
                            continue
                    # else: Legacy post_id schedule - handled in publish_post()
                    
                    # Create publish job (atomic with selection above)
                    # The UNIQUE constraint on (schedule_id, planned_at) prevents duplicates
                    job = PublishJob(
                        schedule_id=schedule.id,
                        planned_at=planned_at,
                        status="planned",
                        dedupe_key=f"{schedule.id}:{planned_at.isoformat()}",
                        variant_id=selected_variant.id if selected_variant else None,
                        selection_policy=schedule.selection_policy if schedule.template_id else None,
                        selection_seed=selection_seed,
                        selected_at=datetime.utcnow() if selected_variant else None,
                        created_at=datetime.utcnow(),
                        updated_at=datetime.utcnow()
                    )
                    db.add(job)
                    db.flush()  # Get job.id
                    
                    # Record selection history AFTER job creation (so we have job_id)
                    # Always record if variant-based, regardless of no_repeat_window (for audit)
                    if selected_variant and schedule.template_id:
                        variant_selector.record_selection(
                            template_id=schedule.template_id,
                            variant_id=selected_variant.id,
                            schedule_id=schedule.id,
                            job_id=job.id,  # Now available after flush
                            planned_at=planned_at
                        )
                    
                    # ... rest of existing code (enqueue, update schedule, etc.) ...
                    
                except Exception as e:
                    logger.error(f"Error processing schedule {schedule.id}: {str(e)}")
                    continue
            
            db.commit()
            logger.info(f"Scheduler tick completed. Created {jobs_created} jobs.")
            
    except Exception as e:
        logger.error(f"Scheduler tick failed: {str(e)}")
        raise
```

---

## Publish Task Integration

### Modify `src/tasks/publish.py`

**Changes to `publish_post()` function:**

```python
@app.task(name="publish.post", ...)
def publish_post(job_id: str):
    """Publish a post to X/Twitter."""
    logger.info(f"Starting publish job {job_id}")
    
    # ... existing idempotency check ...
    
    try:
        # ... existing job fetch ...
        
        # Get schedule and determine post content
        with get_db() as db:
            schedule = db.query(Schedule).filter(Schedule.id == schedule_id).first()
            if not schedule:
                raise ValueError(f"Schedule {schedule_id} not found")
            
            # VARIANT-BASED OR LEGACY POST-BASED (NEW)
            post_text = None
            media_refs = None
            
            if job.variant_id:
                # New variant-based job
                variant = db.query(PostVariant).filter(
                    PostVariant.id == job.variant_id
                ).first()
                
                if not variant:
                    raise ValueError(
                        f"Variant {job.variant_id} not found for job {job_id}"
                    )
                
                post_text = variant.text
                media_refs = variant.media_refs
                
                # Note: History is already created in scheduler_tick() with job_id,
                # so no need to update it here
                
            elif schedule.post_id:
                # Legacy post-based schedule
                post = db.query(Post).filter(Post.id == schedule.post_id).first()
                if not post:
                    raise ValueError(f"Post {schedule.post_id} not found")
                
                if post.deleted:
                    raise ValueError(f"Post {post.id} is deleted")
                
                post_text = post.text
                media_refs = post.media_refs
            else:
                raise ValueError(
                    f"Schedule {schedule_id} has neither template_id nor post_id"
                )
            
            logger.info(f"Publishing {'variant' if job.variant_id else 'post'}: {post_text[:50]}...")
            
            # ... rest of existing publish logic (media parsing, dry_run, etc.) ...
            
            # Create PublishedPost - link to variant if applicable
            if result.get("data", {}).get("id"):
                x_post_id = result["data"]["id"]
                
                # For variant-based posts: PublishedPost.variant_id tracks which variant was published
                # This enables metrics/analytics per variant
                # post_id is kept for backwards compatibility (may be NULL for variant-only posts)
                
                # ... existing PublishedPost creation ...
```

**Note**: `PublishedPost` should have `variant_id` field added for tracking which variant was published. This enables metrics/analytics per variant and bandit learning. See Modified Tables section below.

---

## Selection Policies

### Implemented Policies

1. **RANDOM_UNIFORM**: Pure random selection from active variants.
2. **RANDOM_WEIGHTED**: Weighted random selection (respects `weight` field).
3. **NO_REPEAT_WINDOW**: Uses history table to exclude recently used variants.
4. **ROUND_ROBIN**: Deterministic cycling (via seed modulo).

### Future Policies (Phase 2)

5. **BANDIT_EPS_GREEDY**: 
   - ε (e.g., 0.1) probability of random exploration
   - Otherwise picks variant with best recent CTR/reply-rate
   - Requires metrics collection integration

**Implementation sketch:**
```python
def _select_bandit_epsilon_greedy(
    self,
    pool: List[PostVariant],
    template_id: int,
    epsilon: float,
    rng: random.Random
) -> PostVariant:
    """Epsilon-greedy bandit selection."""
    if rng.random() < epsilon:
        return rng.choice(pool)  # Explore
    
    # Exploit: pick best performing variant
    # Query metrics_snapshots for recent performance
    # This requires PublishedPost.variant_id and metrics collection
    best_variant = self._get_best_performing_variant(template_id, pool)
    return best_variant or rng.choice(pool)
```

---

## Migration Plan

### Phase 1: Schema Migration (Week 1)

1. **Create migration file**: `add_variant_selection_support.py`
   - Create `post_templates`, `post_variants`, `variant_selection_history` tables
   - Add `template_id`, `selection_policy`, `no_repeat_window` to `schedules`
   - Add `variant_id`, `selection_policy`, `selection_seed`, `selected_at` to `publish_jobs`
   - Add indexes

2. **Update models.py**: Add new models and modify existing ones

3. **Test migration**: Run on dev database, verify schema

### Phase 2: Core Implementation (Week 1-2)

1. **Create `variant_service.py`**: Implement `VariantSelector` class
2. **Modify `scheduler_tick()`**: Add variant selection logic
3. **Modify `publish_post()`**: Read from variant instead of post
4. **Add tests**: Unit tests for variant selection logic

### Phase 3: Backwards Compatibility (Week 2)

1. **Support both paths**: Legacy `post_id` and new `template_id` schedules
2. **Migration script**: Convert existing posts to templates (optional)
   - For each `Post` with a `Schedule`, create:
     - `PostTemplate` with same name/description
     - `PostVariant` with same text/media
     - Update `Schedule` to use `template_id`

3. **API endpoints**: Update to support template/variant creation

### Phase 4: Admin UI (Week 2-3)

1. **Template management**: CRUD for templates
2. **Variant management**: CRUD for variants (per template)
3. **Schedule UI**: Option to create schedule with template instead of post
4. **Selection policy UI**: Dropdown for policy selection
5. **Preview**: Show which variant would be selected for a given time

### Phase 5: Advanced Features (Week 3+)

1. **No-repeat window UI**: Configure window size
2. **Round-robin tracking**: Proper state management
3. **Bandit policy**: Integrate with metrics
4. **Analytics**: Track variant performance

---

## Testing Strategy

### Unit Tests

1. **VariantSelector tests** (`tests/test_variant_service.py`):
   - Test seed generation (deterministic)
   - Test each selection policy
   - Test no-repeat window filtering
   - Test edge cases (no variants, all excluded, etc.)

2. **Scheduler integration tests** (`tests/test_scheduler_variants.py`):
   - Test variant selection in `scheduler_tick()`
   - Test job creation with variant_id
   - Test backwards compatibility (post_id still works)

3. **Publish integration tests** (`tests/test_publish_variants.py`):
   - Test publishing from variant
   - Test backwards compatibility (post-based)
   - Test retry idempotency (same variant on retry)

### Integration Tests

1. **End-to-end variant selection**:
   - Create template → variants → schedule
   - Trigger scheduler
   - Verify job has variant_id
   - Publish and verify correct text

2. **No-repeat window**:
   - Create schedule with window=2
   - Fire 3 times
   - Verify first 2 variants are excluded on 3rd fire

---

## API Changes

### New Endpoints

```python
# POST /api/templates
async def create_template(
    name: str,
    description: Optional[str] = None
) -> PostTemplate

# GET /api/templates/{template_id}
async def get_template(template_id: int) -> PostTemplate

# POST /api/templates/{template_id}/variants
async def create_variant(
    template_id: int,
    text: str,
    weight: int = 1,
    media_refs: Optional[str] = None
) -> PostVariant

# GET /api/templates/{template_id}/variants
async def list_variants(template_id: int) -> List[PostVariant]

# PATCH /api/schedules/{schedule_id}
async def update_schedule(
    schedule_id: int,
    template_id: Optional[int] = None,  # NEW
    selection_policy: Optional[str] = None,  # NEW
    no_repeat_window: Optional[int] = None,  # NEW
    no_repeat_scope: Optional[str] = None  # NEW
)

# GET /api/schedules/{schedule_id}/preview
async def preview_variant_selection(
    schedule_id: int,
    planned_at: Optional[str] = None  # ISO datetime string, defaults to next_run_at
) -> dict:
    """
    Preview which variant would be selected for a given planned_at time.
    Uses the same seed generation and selection logic as scheduler_tick().
    Returns: {
        "variant_id": int,
        "variant_text": str,
        "selection_seed": int,
        "planned_at": str
    }
    """
```

### Modified Endpoints

```python
# POST /api/posts/create
# Add optional template_id parameter
async def create_post(
    # ... existing params ...
    template_id: Optional[int] = None,  # NEW: use template instead of text
    schedule_type: str = Form("none"),
    # ...
)
```

---

## Rollout Strategy

### Feature Flags

Use environment variable to gate feature:

```python
VARIANT_SELECTION_ENABLED = os.getenv("VARIANT_SELECTION_ENABLED", "false").lower() == "true"

# In scheduler_tick():
if VARIANT_SELECTION_ENABLED and schedule.template_id:
    # Use variant selection
else:
    # Use legacy post-based
```

### Gradual Migration

1. **Week 1**: Deploy schema + code (disabled by default)
2. **Week 2**: Enable for new schedules only
3. **Week 3**: Migrate existing schedules (manual or script)
4. **Week 4**: Deprecate post-based schedules (keep support for backwards compat)

---

## Implementation Checklist

### Database & Models
- [ ] Create migration file for new tables
- [ ] Create migration file for modified tables
- [ ] Add `PostTemplate` model
- [ ] Add `PostVariant` model
- [ ] Add `VariantSelectionHistory` model
- [ ] Modify `Schedule` model
- [ ] Modify `PublishJob` model
- [ ] Test migrations on dev database

### Core Logic
- [ ] Create `variant_service.py`
- [ ] Implement `VariantSelector` class
- [ ] Implement seed generation
- [ ] Implement selection policies (RANDOM_UNIFORM, RANDOM_WEIGHTED, ROUND_ROBIN, NO_REPEAT_WINDOW)
- [ ] Implement no-repeat window filtering
- [ ] Integrate into `scheduler_tick()`
- [ ] Integrate into `publish_post()`
- [ ] Add backwards compatibility (post_id support)

### Testing
- [ ] Unit tests for variant selection
- [ ] Integration tests for scheduler
- [ ] Integration tests for publish
- [ ] Test backwards compatibility
- [ ] Test no-repeat window

### API & UI
- [ ] Create template endpoints
- [ ] Create variant endpoints
- [ ] Update schedule endpoints
- [ ] Update create_post endpoint
- [ ] Template management UI
- [ ] Variant management UI
- [ ] Schedule creation with template option
- [ ] Selection policy UI
- [ ] Preview variant selection

### Documentation
- [ ] Update README with variant selection docs
- [ ] API documentation
- [ ] Migration guide
- [ ] User guide (how to create templates/variants)

### Deployment
- [ ] Feature flag configuration
- [ ] Migration script for existing data (optional)
- [ ] Monitoring/logging for variant selection
- [ ] Rollback plan

---

## Future Enhancements

1. **Bandit Learning**: Integrate with metrics to auto-select best variants
2. **A/B Test Framework**: Compare variants statistically
3. **Content Templates**: Placeholder substitution (`{{weekday}}`, `{{count}}`, etc.)
4. **Spintax Support**: `[A|B]` syntax for inline variation
5. **Locale Support**: Variants per language/region
6. **Variant Performance Dashboard**: Analytics per variant
7. **Scheduled Variant Changes**: Update variant weights based on performance

---

## Notes & Considerations

### Idempotency
- Selection happens **once** at job creation
- Seed is deterministic, so same `(schedule_id, planned_at)` → same variant
- Retries use the same `variant_id` (no re-selection)

### Performance
- No-repeat window queries use indexes (template_id, selected_at DESC) or (schedule_id, selected_at DESC)
- **Redis caching for hot paths**: Cache recent N selections per template/schedule in Redis to make no-repeat filter O(1)
  - Key: `variant_selections:template:{template_id}` or `variant_selections:schedule:{schedule_id}`
  - Value: Set of variant_ids (use Redis SET with TTL or capped list)
  - Update cache after each selection, expire after window_size * average_interval
- Variant selection is O(n) where n = number of active variants (typically small)
- History table cleanup: Periodically prune old history beyond retention window

### Data Migration
- Optional: Auto-convert existing `Post` + `Schedule` to `PostTemplate` + `PostVariant`
- Script: `scripts/migrate_posts_to_templates.py`

### Backwards Compatibility
- Keep `post_id` support indefinitely (or deprecate after migration period)
- Code checks both `template_id` and `post_id` during transition

---

## Questions to Resolve

1. ~~**PublishedPost.variant_id**: Should we add this field to track which variant was published?~~
   - **Resolution**: Yes, added to schema. Enables metrics/analytics per variant and bandit learning.

2. ~~**Post record for variants**: Should each variant publish create a `Post` record?~~
   - **Resolution**: No, `PublishedPost.variant_id` directly tracks variant. `post_id` remains for backwards compatibility (may be NULL).

3. ~~**Round-robin implementation**: True stateful round-robin or seed-based?~~
   - **Resolution**: True stateful round-robin using `schedule.last_variant_pos`. Tracks last variant ID per schedule.

4. **Template deletion**: Cascade delete variants, or soft delete?
   - **Recommendation**: Cascade delete (current plan), but warn if schedules exist

5. **Migration strategy**: Auto-migrate existing posts or manual?
   - **Recommendation**: Provide script, let users decide

6. **Content safety checks**: Should validation happen at selection time or publish time?
   - **Recommendation**: Both - lightweight check at selection (length), full validation at publish time (duplicates)

---

## Estimated Timeline

- **Week 1**: Database schema + core logic (2-3 days)
- **Week 2**: Integration + backwards compat (2-3 days)
- **Week 3**: API + UI (3-4 days)
- **Week 4**: Testing + polish (2-3 days)

**Total**: ~3-4 weeks for full implementation with tests and UI.

---

## Success Criteria

1. ✅ One schedule can publish multiple text variants
2. ✅ Selection is deterministic (same time → same variant)
3. ✅ Retries don't change variant (idempotent)
4. ✅ No-repeat window works correctly
5. ✅ Backwards compatibility maintained
6. ✅ Tests pass
7. ✅ Admin UI functional
8. ✅ Documentation complete

---

## References

- Original recommendation (user query)
- Existing codebase structure
- Database migration patterns (Alembic)
- Celery task patterns

---

*Last updated: [Current Date]*
*Version: 1.0*

