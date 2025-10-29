"""Test configuration and utilities."""

import os
import sys
import pytest
from datetime import datetime, timedelta

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

# Set test environment variables
os.environ.setdefault('ENVIRONMENT', 'test')
os.environ.setdefault('DRY_RUN', 'true')
os.environ.setdefault('LOG_LEVEL', 'DEBUG')


@pytest.fixture
def test_db():
    """Provide a test database session."""
    from src.database import get_db
    with get_db() as db:
        yield db


@pytest.fixture
def sample_post():
    """Create a sample post for testing."""
    from src.models import Post
    return Post(
        text="Test post content",
        media_refs=None,
        deleted=False,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
    )


@pytest.fixture
def sample_schedule():
    """Create a sample schedule for testing."""
    from src.models import Schedule
    return Schedule(
        post_id=1,
        kind="one_shot",
        schedule_spec=(datetime.utcnow() + timedelta(minutes=5)).isoformat(),
        timezone="UTC",
        next_run_at=datetime.utcnow() + timedelta(minutes=5),
        enabled=True,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
    )
