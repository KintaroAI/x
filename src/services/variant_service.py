"""Service for selecting post variants based on policies."""

import hashlib
import random
import logging
from datetime import datetime, timedelta
from typing import List, Optional, Tuple
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
    ) -> Tuple[Optional[PostVariant], int]:
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
    ) -> Optional[PostVariant]:
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
        
        else:  # RANDOM_UNIFORM or any other policy defaults to random
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
    ) -> Tuple[bool, Optional[str]]:
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

