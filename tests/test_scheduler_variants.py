"""Integration tests for scheduler with variant selection."""

import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
import pytz

from src.tasks.scheduler import scheduler_tick
from src.models import Schedule, PublishJob, PostTemplate, PostVariant


@pytest.mark.integration
class TestSchedulerVariantSelection:
    """Integration tests for variant selection in scheduler."""
    
    def test_scheduler_tick_with_variant_selection(self, test_db):
        """Test scheduler_tick creates jobs with variant_id for template-based schedules."""
        # Create template
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
        
        # Create variants
        variants = []
        for i in range(3):
            variant = PostVariant(
                template_id=template.id,
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
        
        # Create schedule with template_id
        next_run = datetime.utcnow() - timedelta(minutes=1)  # Past time (due)
        schedule = Schedule(
            template_id=template.id,
            kind="one_shot",
            schedule_spec=next_run.isoformat(),
            timezone="UTC",
            selection_policy="RANDOM_UNIFORM",
            no_repeat_window=0,
            no_repeat_scope="template",
            next_run_at=next_run,
            enabled=True,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        test_db.add(schedule)
        test_db.commit()
        test_db.refresh(schedule)
        
        # Mock acquire_dedupe_lock to return True
        with patch('src.tasks.scheduler.acquire_dedupe_lock', return_value=True):
            # Mock publish_post.apply_async to avoid actual publishing
            with patch('src.tasks.publish.publish_post.apply_async') as mock_publish:
                # Run scheduler tick
                scheduler_tick()
        
        # Verify job was created with variant_id
        job = test_db.query(PublishJob).filter(
            PublishJob.schedule_id == schedule.id
        ).first()
        
        assert job is not None, "Job should be created"
        assert job.variant_id is not None, "Job should have variant_id"
        assert job.variant_id in [v.id for v in variants], "variant_id should match one of the variants"
        assert job.selection_policy == "RANDOM_UNIFORM", "Job should have selection_policy"
        assert job.selection_seed is not None, "Job should have selection_seed"
        assert job.selected_at is not None, "Job should have selected_at"
    
    def test_scheduler_tick_backwards_compatibility(self, test_db):
        """Test scheduler_tick still works with post_id (backwards compatibility)."""
        # Create post
        from src.models import Post
        post = Post(
            text="Test post",
            media_refs=None,
            deleted=False,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        test_db.add(post)
        test_db.commit()
        test_db.refresh(post)
        
        # Create schedule with post_id (legacy)
        next_run = datetime.utcnow() - timedelta(minutes=1)  # Past time (due)
        schedule = Schedule(
            post_id=post.id,
            kind="one_shot",
            schedule_spec=next_run.isoformat(),
            timezone="UTC",
            next_run_at=next_run,
            enabled=True,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        test_db.add(schedule)
        test_db.commit()
        test_db.refresh(schedule)
        
        # Mock acquire_dedupe_lock to return True
        with patch('src.tasks.scheduler.acquire_dedupe_lock', return_value=True):
            # Mock publish_post.apply_async to avoid actual publishing
            with patch('src.tasks.publish.publish_post.apply_async') as mock_publish:
                # Run scheduler tick
                scheduler_tick()
        
        # Verify job was created without variant_id (legacy)
        job = test_db.query(PublishJob).filter(
            PublishJob.schedule_id == schedule.id
        ).first()
        
        assert job is not None, "Job should be created"
        assert job.variant_id is None, "Legacy job should not have variant_id"
        assert job.selection_policy is None, "Legacy job should not have selection_policy"
        assert job.selection_seed is None, "Legacy job should not have selection_seed"
    
    def test_scheduler_tick_no_active_variants(self, test_db):
        """Test scheduler_tick skips schedules with no active variants."""
        # Create template
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
        
        # Create only inactive variants
        variant = PostVariant(
            template_id=template.id,
            text="Inactive variant",
            weight=1,
            active=False,  # Inactive
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        test_db.add(variant)
        test_db.commit()
        
        # Create schedule with template_id
        next_run = datetime.utcnow() - timedelta(minutes=1)  # Past time (due)
        schedule = Schedule(
            template_id=template.id,
            kind="one_shot",
            schedule_spec=next_run.isoformat(),
            timezone="UTC",
            selection_policy="RANDOM_UNIFORM",
            no_repeat_window=0,
            no_repeat_scope="template",
            next_run_at=next_run,
            enabled=True,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        test_db.add(schedule)
        test_db.commit()
        test_db.refresh(schedule)
        
        # Mock acquire_dedupe_lock to return True
        with patch('src.tasks.scheduler.acquire_dedupe_lock', return_value=True):
            # Mock publish_post.apply_async to avoid actual publishing
            with patch('src.tasks.publish.publish_post.apply_async') as mock_publish:
                # Run scheduler tick
                scheduler_tick()
        
        # Verify no job was created
        job = test_db.query(PublishJob).filter(
            PublishJob.schedule_id == schedule.id
        ).first()
        
        assert job is None, "Job should not be created when no active variants exist"
    
    def test_scheduler_tick_deterministic_selection(self, test_db):
        """Test that same planned_at always selects the same variant (deterministic)."""
        # Create template
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
        
        # Create variants
        variants = []
        for i in range(3):
            variant = PostVariant(
                template_id=template.id,
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
        
        # Create schedule with template_id
        planned_at = datetime.utcnow().replace(tzinfo=pytz.UTC) - timedelta(minutes=1)
        next_run = planned_at.replace(tzinfo=None)
        schedule = Schedule(
            template_id=template.id,
            kind="one_shot",
            schedule_spec=next_run.isoformat(),
            timezone="UTC",
            selection_policy="RANDOM_UNIFORM",
            no_repeat_window=0,
            no_repeat_scope="template",
            next_run_at=next_run,
            enabled=True,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        test_db.add(schedule)
        test_db.commit()
        test_db.refresh(schedule)
        
        # Run scheduler tick twice with same planned_at
        variant_ids = []
        seeds = []
        
        for _ in range(2):
            # Delete previous job if exists
            test_db.query(PublishJob).filter(
                PublishJob.schedule_id == schedule.id
            ).delete()
            test_db.commit()
            
            # Reset next_run_at
            schedule.next_run_at = next_run
            test_db.commit()
            test_db.refresh(schedule)
            
            # Mock acquire_dedupe_lock to return True
            with patch('src.tasks.scheduler.acquire_dedupe_lock', return_value=True):
                # Mock publish_post.apply_async to avoid actual publishing
                with patch('src.tasks.publish.publish_post.apply_async'):
                    # Run scheduler tick
                    scheduler_tick()
            
            # Get job
            job = test_db.query(PublishJob).filter(
                PublishJob.schedule_id == schedule.id
            ).first()
            
            assert job is not None
            variant_ids.append(job.variant_id)
            seeds.append(job.selection_seed)
        
        # Verify same variant and seed for same planned_at
        assert variant_ids[0] == variant_ids[1], "Same planned_at should select same variant"
        assert seeds[0] == seeds[1], "Same planned_at should use same seed"
    
    def test_scheduler_tick_records_selection_history(self, test_db):
        """Test that scheduler_tick records variant selection history."""
        # Create template
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
        
        # Create variant
        variant = PostVariant(
            template_id=template.id,
            text="Test variant",
            weight=1,
            active=True,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        test_db.add(variant)
        test_db.commit()
        test_db.refresh(variant)
        
        # Create schedule with template_id
        next_run = datetime.utcnow() - timedelta(minutes=1)  # Past time (due)
        schedule = Schedule(
            template_id=template.id,
            kind="one_shot",
            schedule_spec=next_run.isoformat(),
            timezone="UTC",
            selection_policy="RANDOM_UNIFORM",
            no_repeat_window=0,
            no_repeat_scope="template",
            next_run_at=next_run,
            enabled=True,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        test_db.add(schedule)
        test_db.commit()
        test_db.refresh(schedule)
        
        # Mock acquire_dedupe_lock to return True
        with patch('src.tasks.scheduler.acquire_dedupe_lock', return_value=True):
            # Mock publish_post.apply_async to avoid actual publishing
            with patch('src.tasks.publish.publish_post.apply_async'):
                # Run scheduler tick
                scheduler_tick()
        
        # Verify selection history was recorded
        from src.models import VariantSelectionHistory
        history = test_db.query(VariantSelectionHistory).filter(
            VariantSelectionHistory.schedule_id == schedule.id
        ).first()
        
        assert history is not None, "Selection history should be recorded"
        assert history.variant_id == variant.id
        assert history.template_id == template.id
        assert history.schedule_id == schedule.id
        assert history.job_id is not None

