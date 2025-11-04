"""Integration tests for no-repeat window functionality."""

import pytest
from datetime import datetime, timedelta
from unittest.mock import patch
import pytz

from src.tasks.scheduler import scheduler_tick
from src.models import Schedule, PublishJob, PostTemplate, PostVariant, VariantSelectionHistory


@pytest.mark.integration
class TestNoRepeatWindow:
    """Integration tests for no-repeat window functionality."""
    
    def test_no_repeat_window_schedule_scope(self, test_db):
        """Test no-repeat window with schedule scope."""
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
        
        # Create 3 variants
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
        
        # Create schedule with no_repeat_window=2 and scope=schedule
        next_run = datetime.utcnow() - timedelta(minutes=1)
        schedule = Schedule(
            template_id=template.id,
            kind="one_shot",
            schedule_spec=next_run.isoformat(),
            timezone="UTC",
            selection_policy="NO_REPEAT_WINDOW",
            no_repeat_window=2,
            no_repeat_scope="schedule",
            next_run_at=next_run,
            enabled=True,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        test_db.add(schedule)
        test_db.commit()
        test_db.refresh(schedule)
        
        selected_variant_ids = []
        
        # Fire schedule 3 times
        for i in range(3):
            # Reset next_run_at
            schedule.next_run_at = next_run + timedelta(minutes=i)
            test_db.commit()
            test_db.refresh(schedule)
            
            # Delete previous job if exists
            test_db.query(PublishJob).filter(
                PublishJob.schedule_id == schedule.id
            ).delete()
            test_db.commit()
            
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
            
            assert job is not None, f"Job should be created on fire {i+1}"
            selected_variant_ids.append(job.variant_id)
            
            # Verify selection history was recorded
            history = test_db.query(VariantSelectionHistory).filter(
                VariantSelectionHistory.job_id == job.id
            ).first()
            
            assert history is not None, f"Selection history should be recorded on fire {i+1}"
        
        # Verify all 3 variants were selected (different each time)
        assert len(set(selected_variant_ids)) == 3, "All 3 variants should be selected"
        
        # Verify 3rd fire excluded first 2 variants
        # (This is probabilistic - the test verifies the mechanism works)
        assert selected_variant_ids[2] not in selected_variant_ids[:2], \
            "3rd fire should exclude variants from first 2 fires"
    
    def test_no_repeat_window_template_scope(self, test_db):
        """Test no-repeat window with template scope (across all schedules)."""
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
        
        # Create 3 variants
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
        
        # Create two schedules with same template and no_repeat_window=1, scope=template
        next_run1 = datetime.utcnow() - timedelta(minutes=1)
        schedule1 = Schedule(
            template_id=template.id,
            kind="one_shot",
            schedule_spec=next_run1.isoformat(),
            timezone="UTC",
            selection_policy="NO_REPEAT_WINDOW",
            no_repeat_window=1,
            no_repeat_scope="template",  # Template scope
            next_run_at=next_run1,
            enabled=True,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        test_db.add(schedule1)
        test_db.commit()
        test_db.refresh(schedule1)
        
        next_run2 = datetime.utcnow() - timedelta(minutes=1)
        schedule2 = Schedule(
            template_id=template.id,
            kind="one_shot",
            schedule_spec=next_run2.isoformat(),
            timezone="UTC",
            selection_policy="NO_REPEAT_WINDOW",
            no_repeat_window=1,
            no_repeat_scope="template",  # Template scope
            next_run_at=next_run2,
            enabled=True,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        test_db.add(schedule2)
        test_db.commit()
        test_db.refresh(schedule2)
        
        # Fire schedule1 first
        schedule1.next_run_at = next_run1
        test_db.commit()
        test_db.refresh(schedule1)
        
        with patch('src.tasks.scheduler.acquire_dedupe_lock', return_value=True):
            with patch('src.tasks.publish.publish_post.apply_async'):
                scheduler_tick()
        
        job1 = test_db.query(PublishJob).filter(
            PublishJob.schedule_id == schedule1.id
        ).first()
        
        assert job1 is not None
        variant1_id = job1.variant_id
        
        # Fire schedule2 - should exclude variant from schedule1 (template scope)
        schedule2.next_run_at = next_run2
        test_db.commit()
        test_db.refresh(schedule2)
        
        # Delete previous job if exists
        test_db.query(PublishJob).filter(
            PublishJob.schedule_id == schedule2.id
        ).delete()
        test_db.commit()
        
        with patch('src.tasks.scheduler.acquire_dedupe_lock', return_value=True):
            with patch('src.tasks.publish.publish_post.apply_async'):
                scheduler_tick()
        
        job2 = test_db.query(PublishJob).filter(
            PublishJob.schedule_id == schedule2.id
        ).first()
        
        assert job2 is not None
        variant2_id = job2.variant_id
        
        # Verify schedule2 excluded variant from schedule1 (template scope)
        assert variant2_id != variant1_id, \
            "Schedule2 should exclude variant from schedule1 (template scope)"
    
    def test_no_repeat_window_fallback(self, test_db):
        """Test that no-repeat window falls back to all variants when all are excluded."""
        # Create template with only 2 variants
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
        
        # Create only 2 variants
        variants = []
        for i in range(2):
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
        
        # Create schedule with no_repeat_window=3 (more than variants available)
        next_run = datetime.utcnow() - timedelta(minutes=1)
        schedule = Schedule(
            template_id=template.id,
            kind="one_shot",
            schedule_spec=next_run.isoformat(),
            timezone="UTC",
            selection_policy="NO_REPEAT_WINDOW",
            no_repeat_window=3,  # More than variants available
            no_repeat_scope="schedule",
            next_run_at=next_run,
            enabled=True,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        test_db.add(schedule)
        test_db.commit()
        test_db.refresh(schedule)
        
        # Fire schedule 3 times
        for i in range(3):
            # Reset next_run_at
            schedule.next_run_at = next_run + timedelta(minutes=i)
            test_db.commit()
            test_db.refresh(schedule)
            
            # Delete previous job if exists
            test_db.query(PublishJob).filter(
                PublishJob.schedule_id == schedule.id
            ).delete()
            test_db.commit()
            
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
            
            assert job is not None, f"Job should be created on fire {i+1} (should fallback to all variants)"
            assert job.variant_id in [v.id for v in variants], "Should select from available variants"

