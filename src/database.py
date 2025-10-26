"""Database connection utilities."""

import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from contextlib import contextmanager

from src.models import Base


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

