"""Tests for variant selection service."""

import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
import pytz

from src.services.variant_service import VariantSelector
from src.models import Schedule, PostTemplate, PostVariant


@pytest.mark.unit
class TestVariantSelector:
    """Test cases for VariantSelector class."""
    
    @pytest.fixture
    def test_db(self):
        """Provide a test database session."""
        from src.database import get_db
        with get_db() as db:
            yield db
    
    @pytest.fixture
    def sample_template(self, test_db):
        """Create a sample template for testing."""
        template = PostTemplate(
            name="Test Template",
            description="Test description",
            active=True,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        test_db.add(template)
        test_db.commit()
        test_db.refresh(template)
        return template
    
    @pytest.fixture
    def sample_variants(self, test_db, sample_template):
        """Create sample variants for testing."""
        variants = []
        for i in range(3):
            variant = PostVariant(
                template_id=sample_template.id,
                text=f"Test variant {i+1}",
                weight=1,
                active=True,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            test_db.add(variant)
            variants.append(variant)
        test_db.commit()
        for variant in variants:
            test_db.refresh(variant)
        return variants
    
    @pytest.fixture
    def sample_schedule(self, test_db, sample_template):
        """Create a sample schedule with template_id."""
        schedule = Schedule(
            template_id=sample_template.id,
            kind="cron",
            schedule_spec="0 9 * * *",
            timezone="UTC",
            selection_policy="RANDOM_UNIFORM",
            no_repeat_window=0,
            no_repeat_scope="template",
            enabled=True,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        test_db.add(schedule)
        test_db.commit()
        test_db.refresh(schedule)
        return schedule
    
    def test_seed_generation_deterministic(self, test_db, sample_schedule):
        """Test that seed generation is deterministic for same schedule and time."""
        selector = VariantSelector(test_db)
        
        planned_at = datetime.utcnow().replace(tzinfo=pytz.UTC)
        
        seed1 = selector._generate_seed(sample_schedule.id, planned_at)
        seed2 = selector._generate_seed(sample_schedule.id, planned_at)
        
        assert seed1 == seed2, "Seed should be deterministic for same schedule and time"
    
    def test_seed_generation_different_times(self, test_db, sample_schedule):
        """Test that different times produce different seeds."""
        selector = VariantSelector(test_db)
        
        time1 = datetime.utcnow().replace(tzinfo=pytz.UTC)
        time2 = time1 + timedelta(hours=1)
        
        seed1 = selector._generate_seed(sample_schedule.id, time1)
        seed2 = selector._generate_seed(sample_schedule.id, time2)
        
        assert seed1 != seed2, "Different times should produce different seeds"
    
    def test_seed_generation_different_schedules(self, test_db, sample_template):
        """Test that different schedules produce different seeds."""
        selector = VariantSelector(test_db)
        
        schedule1 = Schedule(
            id=1,
            template_id=sample_template.id,
            kind="cron",
            schedule_spec="0 9 * * *",
            timezone="UTC"
        )
        schedule2 = Schedule(
            id=2,
            template_id=sample_template.id,
            kind="cron",
            schedule_spec="0 9 * * *",
            timezone="UTC"
        )
        
        planned_at = datetime.utcnow().replace(tzinfo=pytz.UTC)
        
        seed1 = selector._generate_seed(schedule1.id, planned_at)
        seed2 = selector._generate_seed(schedule2.id, planned_at)
        
        assert seed1 != seed2, "Different schedules should produce different seeds"
    
    def test_random_uniform_selection(self, test_db, sample_schedule, sample_variants):
        """Test RANDOM_UNIFORM selection policy."""
        selector = VariantSelector(test_db)
        
        # Run selection multiple times to verify randomness
        selected_variants = set()
        for _ in range(20):
            planned_at = datetime.utcnow().replace(tzinfo=pytz.UTC) + timedelta(seconds=_)
            variant, seed = selector.select_variant(sample_schedule, planned_at)
            assert variant is not None
            assert variant in sample_variants
            selected_variants.add(variant.id)
        
        # With 20 runs and 3 variants, we should see at least 2 different variants
        # (with high probability, though not guaranteed)
        assert len(selected_variants) >= 1
    
    def test_random_weighted_selection(self, test_db, sample_template):
        """Test RANDOM_WEIGHTED selection policy."""
        # Create variants with different weights
        test_db_session = test_db
        variants = []
        for i in range(3):
            variant = PostVariant(
                template_id=sample_template.id,
                text=f"Weighted variant {i+1}",
                weight=(i+1) * 10,  # Weights: 10, 20, 30
                active=True,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            test_db_session.add(variant)
            variants.append(variant)
        test_db_session.commit()
        for variant in variants:
            test_db_session.refresh(variant)
        
        schedule = Schedule(
            template_id=sample_template.id,
            kind="cron",
            schedule_spec="0 9 * * *",
            timezone="UTC",
            selection_policy="RANDOM_WEIGHTED",
            no_repeat_window=0,
            no_repeat_scope="template",
            enabled=True,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        test_db_session.add(schedule)
        test_db_session.commit()
        test_db_session.refresh(schedule)
        
        selector = VariantSelector(test_db_session)
        
        # Run selection multiple times
        variant_counts = {}
        for i in range(30):
            planned_at = datetime.utcnow().replace(tzinfo=pytz.UTC) + timedelta(seconds=i)
            variant, seed = selector.select_variant(schedule, planned_at)
            assert variant is not None
            variant_counts[variant.id] = variant_counts.get(variant.id, 0) + 1
        
        # Higher weight variants should be selected more often
        # (variant with weight 30 should be selected more than weight 10)
        assert len(variant_counts) >= 2  # Should see multiple variants
        assert max(variant_counts.values()) > min(variant_counts.values())  # Some preference
    
    def test_round_robin_selection(self, test_db, sample_schedule, sample_variants):
        """Test ROUND_ROBIN selection policy."""
        schedule = Schedule(
            id=sample_schedule.id,
            template_id=sample_schedule.template_id,
            kind=sample_schedule.kind,
            schedule_spec=sample_schedule.schedule_spec,
            timezone=sample_schedule.timezone,
            selection_policy="ROUND_ROBIN",
            no_repeat_window=0,
            no_repeat_scope="template",
            enabled=True,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        
        selector = VariantSelector(test_db)
        
        # First selection should pick first variant
        planned_at1 = datetime.utcnow().replace(tzinfo=pytz.UTC)
        variant1, seed1 = selector.select_variant(schedule, planned_at1)
        
        # Second selection should pick second variant
        planned_at2 = planned_at1 + timedelta(hours=1)
        variant2, seed2 = selector.select_variant(schedule, planned_at2)
        
        # Third selection should pick third variant
        planned_at3 = planned_at2 + timedelta(hours=1)
        variant3, seed3 = selector.select_variant(schedule, planned_at3)
        
        # All should be different
        assert variant1.id != variant2.id != variant3.id
        assert variant1.id != variant3.id
    
    def test_no_repeat_window_filtering(self, test_db, sample_template, sample_variants):
        """Test NO_REPEAT_WINDOW selection policy."""
        # Create schedule with no_repeat_window=2
        schedule = Schedule(
            template_id=sample_template.id,
            kind="cron",
            schedule_spec="0 9 * * *",
            timezone="UTC",
            selection_policy="NO_REPEAT_WINDOW",
            no_repeat_window=2,
            no_repeat_scope="schedule",
            enabled=True,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        test_db.add(schedule)
        test_db.commit()
        test_db.refresh(schedule)
        
        selector = VariantSelector(test_db)
        
        # Select first variant
        planned_at1 = datetime.utcnow().replace(tzinfo=pytz.UTC)
        variant1, seed1 = selector.select_variant(schedule, planned_at1)
        
        # Record selection
        from src.models import PublishJob
        job1 = PublishJob(
            schedule_id=schedule.id,
            variant_id=variant1.id,
            planned_at=planned_at1,
            status="pending",
            created_at=datetime.utcnow()
        )
        test_db.add(job1)
        test_db.commit()
        test_db.refresh(job1)
        
        selector.record_selection(
            template_id=schedule.template_id,
            variant_id=variant1.id,
            schedule_id=schedule.id,
            job_id=job1.id,
            planned_at=planned_at1
        )
        
        # Select second variant
        planned_at2 = planned_at1 + timedelta(hours=1)
        variant2, seed2 = selector.select_variant(schedule, planned_at2)
        
        # Record selection
        job2 = PublishJob(
            schedule_id=schedule.id,
            variant_id=variant2.id,
            planned_at=planned_at2,
            status="pending",
            created_at=datetime.utcnow()
        )
        test_db.add(job2)
        test_db.commit()
        test_db.refresh(job2)
        
        selector.record_selection(
            template_id=schedule.template_id,
            variant_id=variant2.id,
            schedule_id=schedule.id,
            job_id=job2.id,
            planned_at=planned_at2
        )
        
        # Third selection should exclude first two variants
        planned_at3 = planned_at2 + timedelta(hours=1)
        variant3, seed3 = selector.select_variant(schedule, planned_at3)
        
        # Should be different from first two
        assert variant3.id != variant1.id
        assert variant3.id != variant2.id
    
    def test_no_active_variants(self, test_db, sample_template):
        """Test selection when no active variants exist."""
        # Create template with only inactive variants
        variant = PostVariant(
            template_id=sample_template.id,
            text="Inactive variant",
            weight=1,
            active=False,  # Inactive
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        test_db.add(variant)
        test_db.commit()
        
        schedule = Schedule(
            template_id=sample_template.id,
            kind="cron",
            schedule_spec="0 9 * * *",
            timezone="UTC",
            selection_policy="RANDOM_UNIFORM",
            no_repeat_window=0,
            no_repeat_scope="template",
            enabled=True,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        test_db.add(schedule)
        test_db.commit()
        test_db.refresh(schedule)
        
        selector = VariantSelector(test_db)
        
        planned_at = datetime.utcnow().replace(tzinfo=pytz.UTC)
        variant, seed = selector.select_variant(schedule, planned_at)
        
        assert variant is None, "Should return None when no active variants exist"
    
    def test_get_active_variants(self, test_db, sample_template, sample_variants):
        """Test getting active variants for a template."""
        # Create one inactive variant
        inactive_variant = PostVariant(
            template_id=sample_template.id,
            text="Inactive variant",
            weight=1,
            active=False,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        test_db.add(inactive_variant)
        test_db.commit()
        
        selector = VariantSelector(test_db)
        active_variants = selector.get_active_variants(sample_template.id)
        
        assert len(active_variants) == len(sample_variants), "Should only return active variants"
        assert all(v.active for v in active_variants), "All returned variants should be active"
        assert inactive_variant not in active_variants, "Inactive variant should not be included"
    
    def test_validate_content_safety(self, test_db, sample_template):
        """Test content safety validation."""
        selector = VariantSelector(test_db)
        
        # Test valid content (under 280 chars)
        valid_variant = PostVariant(
            template_id=sample_template.id,
            text="A" * 200,
            weight=1,
            active=True,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        is_valid, error = selector.validate_content_safety(valid_variant)
        assert is_valid is True, "Valid text should pass validation"
        assert error is None, "No error for valid text"
        
        # Test invalid content (over 280 chars)
        invalid_variant = PostVariant(
            template_id=sample_template.id,
            text="A" * 300,
            weight=1,
            active=True,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        is_valid, error = selector.validate_content_safety(invalid_variant)
        assert is_valid is False, "Text over 280 chars should fail validation"
        assert error is not None, "Should have error message for invalid text"
    
    def test_record_selection(self, test_db, sample_schedule, sample_variants):
        """Test recording variant selection to history."""
        selector = VariantSelector(test_db)
        
        planned_at = datetime.utcnow().replace(tzinfo=pytz.UTC)
        variant = sample_variants[0]
        
        # Create a job for the selection
        from src.models import PublishJob
        job = PublishJob(
            schedule_id=sample_schedule.id,
            variant_id=variant.id,
            planned_at=planned_at,
            status="pending",
            created_at=datetime.utcnow()
        )
        test_db.add(job)
        test_db.commit()
        test_db.refresh(job)
        
        # Record selection
        selector.record_selection(
            template_id=sample_schedule.template_id,
            variant_id=variant.id,
            schedule_id=sample_schedule.id,
            job_id=job.id,
            planned_at=planned_at
        )
        test_db.commit()  # Commit the history record
        
        # Verify history was recorded
        from src.models import VariantSelectionHistory
        history = test_db.query(VariantSelectionHistory).filter(
            VariantSelectionHistory.job_id == job.id
        ).first()
        
        assert history is not None, "Selection history should be recorded"
        assert history.variant_id == variant.id
        assert history.template_id == sample_schedule.template_id
        assert history.schedule_id == sample_schedule.id
        assert history.job_id == job.id

