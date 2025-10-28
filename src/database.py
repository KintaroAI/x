"""Database connection utilities."""

import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from contextlib import contextmanager

from src.models import Base
from src.utils.redis_utils import get_redis_client, test_redis_connection


def get_database_url() -> str:
    """Get database URL from environment variables."""
    return os.getenv(
        "DATABASE_URL",
        "postgresql://postgres:postgres@localhost:5432/app_db"
    )


def get_engine():
    """Create and return SQLAlchemy engine."""
    database_url = get_database_url()
    return create_engine(database_url, pool_pre_ping=True)


def get_session_maker():
    """Create and return a session factory."""
    engine = get_engine()
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


@contextmanager
def get_db() -> Session:
    """Database session context manager."""
    session_factory = get_session_maker()
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db():
    """Initialize database tables."""
    engine = get_engine()
    Base.metadata.create_all(bind=engine)


def test_connections() -> dict:
    """Test database and Redis connections."""
    results = {
        "database": False,
        "redis": False,
        "errors": []
    }
    
    # Test database
    try:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute("SELECT 1")
        results["database"] = True
    except Exception as e:
        results["errors"].append(f"Database: {str(e)}")
    
    # Test Redis
    try:
        results["redis"] = test_redis_connection()
    except Exception as e:
        results["errors"].append(f"Redis: {str(e)}")
    
    return results

