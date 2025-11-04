"""Integration tests for publishing with variants."""

import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock, AsyncMock
import pytz

from src.tasks.publish import publish_post
from src.models import Schedule, PublishJob, PostTemplate, PostVariant, PublishedPost


@pytest.mark.integration
class TestPublishVariants:
    """Integration tests for publishing with variants."""
    
    def test_publish_post_with_variant(self, test_db):
        """Test publishing a post from a variant."""
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
            text="Test variant text",
            weight=1,
            active=True,
            media_refs='["url1", "url2"]',
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        test_db.add(variant)
        test_db.commit()
        test_db.refresh(variant)
        
        # Create schedule with template_id
        schedule = Schedule(
            template_id=template.id,
            kind="one_shot",
            schedule_spec=datetime.utcnow().isoformat(),
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
        
        # Create job with variant_id (use "enqueued" status to match state machine)
        job = PublishJob(
            schedule_id=schedule.id,
            variant_id=variant.id,
            planned_at=datetime.utcnow(),
            status="enqueued",  # Must be enqueued to transition to running
            selection_policy="RANDOM_UNIFORM",
            selection_seed=12345,
            selected_at=datetime.utcnow(),
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        test_db.add(job)
        test_db.commit()
        test_db.refresh(job)
        
        # Mock Twitter API to avoid actual posting
        # create_twitter_post is async but called with asyncio.run, so we use AsyncMock
        from unittest.mock import AsyncMock
        with patch('src.tasks.publish.create_twitter_post', new_callable=AsyncMock) as mock_twitter:
            mock_twitter.return_value = {"data": {"id": "123456", "text": variant.text}}
            
            # Run publish_post
            publish_post(job.id)
        
        # Verify PublishedPost was created with variant_id
        # Find by variant_id and x_post_id to ensure we get the right one
        published = test_db.query(PublishedPost).filter(
            PublishedPost.variant_id == variant.id,
            PublishedPost.x_post_id == "123456"
        ).first()
        
        assert published is not None, "PublishedPost should be created"
        assert published.variant_id == variant.id, "PublishedPost should have variant_id"
        assert published.post_id is None, "PublishedPost should not have post_id when using variant"
    
    def test_publish_post_backwards_compatibility(self, test_db):
        """Test publishing still works with post_id (backwards compatibility)."""
        # Create post
        from src.models import Post
        post = Post(
            text="Test post text",
            media_refs='["url1"]',
            deleted=False,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        test_db.add(post)
        test_db.commit()
        test_db.refresh(post)
        
        # Create schedule with post_id (legacy)
        schedule = Schedule(
            post_id=post.id,
            kind="one_shot",
            schedule_spec=datetime.utcnow().isoformat(),
            timezone="UTC",
            enabled=True,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        test_db.add(schedule)
        test_db.commit()
        test_db.refresh(schedule)
        
        # Create job without variant_id (legacy)
        # Note: PublishJob doesn't have post_id - it gets post from schedule.post_id
        job = PublishJob(
            schedule_id=schedule.id,
            planned_at=datetime.utcnow(),
            status="enqueued",  # Must be enqueued to transition to running
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        test_db.add(job)
        test_db.commit()
        test_db.refresh(job)
        
        # Mock Twitter API to avoid actual posting
        with patch('src.tasks.publish.create_twitter_post') as mock_twitter:
            mock_twitter.return_value = {"id": "123456", "text": post.text}
            
            # Run publish_post
            publish_post(job.id)
        
        # Verify PublishedPost was created with post_id (legacy)
        published = test_db.query(PublishedPost).filter(
            PublishedPost.post_id == post.id,
            PublishedPost.x_post_id == "123456"
        ).first()
        
        assert published is not None, "PublishedPost should be created"
        assert published.post_id == post.id, "PublishedPost should have post_id (legacy)"
        assert published.variant_id is None, "PublishedPost should not have variant_id when using post"
    
    def test_publish_post_retry_idempotency(self, test_db):
        """Test that retries use the same variant (idempotency)."""
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
        schedule = Schedule(
            template_id=template.id,
            kind="one_shot",
            schedule_spec=datetime.utcnow().isoformat(),
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
        
        # Create job with variant_id (already selected)
        selected_variant = variants[0]
        job = PublishJob(
            schedule_id=schedule.id,
            variant_id=selected_variant.id,
            planned_at=datetime.utcnow(),
            status="enqueued",  # Must be enqueued to transition to running
            selection_policy="RANDOM_UNIFORM",
            selection_seed=12345,
            selected_at=datetime.utcnow(),
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        test_db.add(job)
        test_db.commit()
        test_db.refresh(job)
        
        # Mock Twitter API to fail first time, succeed on retry
        with patch('src.tasks.publish.post_to_twitter') as mock_twitter:
            mock_twitter.side_effect = [
                Exception("Network error"),  # First attempt fails
                {"id": "123456", "text": selected_variant.text}  # Retry succeeds
            ]
            
            # First attempt (fails)
            try:
                publish_post(job.id)
            except Exception:
                pass
            
            # Verify job status after failure
            test_db.refresh(job)
            assert job.status == "failed" or job.attempt > 1
            
            # Retry (should use same variant)
            test_db.refresh(job)
            job.status = "enqueued"  # Reset for retry (must be enqueued to transition to running)
            test_db.commit()
            
            publish_post(job.id)
        
        # Verify PublishedPost was created with same variant_id
        published = test_db.query(PublishedPost).filter(
            PublishedPost.variant_id == selected_variant.id,
            PublishedPost.x_post_id == "123456"
        ).first()
        
        assert published is not None, "PublishedPost should be created on retry"
        assert published.variant_id == selected_variant.id, "Retry should use same variant"
    
    def test_publish_post_variant_not_found(self, test_db):
        """Test publishing fails gracefully when variant is not found."""
        # Create template first
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
        
        # Create schedule with template_id
        schedule = Schedule(
            template_id=template.id,
            kind="one_shot",
            schedule_spec=datetime.utcnow().isoformat(),
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
        
        # Create job with non-existent variant_id
        # Note: FK constraint will prevent this, so we need to bypass it or use a valid variant then delete it
        # For this test, we'll create a variant, use it, then delete it
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
        
        job = PublishJob(
            schedule_id=schedule.id,
            variant_id=variant.id,
            planned_at=datetime.utcnow(),
            status="enqueued",  # Must be enqueued to transition to running
            selection_policy="RANDOM_UNIFORM",
            selection_seed=12345,
            selected_at=datetime.utcnow(),
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        test_db.add(job)
        test_db.commit()
        test_db.refresh(job)
        
        # Now delete the variant to simulate it not being found
        variant_id = variant.id
        test_db.delete(variant)
        test_db.commit()
        
        # Run publish_post (should fail gracefully)
        with pytest.raises(Exception):  # Should raise exception when variant not found
            publish_post(job.id)
        
        # Verify job status is updated
        test_db.refresh(job)
        assert job.status == "failed" or job.error is not None, "Job should be marked as failed"

