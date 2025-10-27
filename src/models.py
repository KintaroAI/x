"""Database models for the application."""

from datetime import datetime
from typing import Optional
from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean, ForeignKey
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()


class AuditLog(Base):
    """Audit log model for tracking system events."""

    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    level = Column(String(20), nullable=False, index=True)  # INFO, WARNING, ERROR, CRITICAL
    component = Column(String(100), nullable=True)  # api, worker, scheduler, etc.
    action = Column(String(100), nullable=False)  # login, post_scheduled, error, etc.
    message = Column(Text, nullable=False)
    extra_data = Column(Text, nullable=True)  # JSON string for additional data
    user_id = Column(String(100), nullable=True, index=True)
    ip_address = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f"<AuditLog(id={self.id}, level={self.level}, action={self.action})>"


class TokenManagement(Base):
    """Model for storing and managing API tokens."""

    __tablename__ = "token_management"

    id = Column(Integer, primary_key=True, index=True)
    service_name = Column(String(100), nullable=False, index=True)  # e.g., 'twitter', 'linkedin', etc.
    token_type = Column(String(50), nullable=False)  # e.g., 'access_token', 'refresh_token'
    token = Column(Text, nullable=False)  # The actual token
    expires_at = Column(DateTime, nullable=True)  # When the token expires (if applicable)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f"<TokenManagement(id={self.id}, service={self.service_name}, type={self.token_type})>"


class Account(Base):
    """Model for X/Twitter account information."""

    __tablename__ = "accounts"

    id = Column(Integer, primary_key=True, index=True)
    handle = Column(String(100), nullable=False, unique=True)  # @username
    access_token = Column(Text, nullable=True)  # OAuth 2.0 access token
    refresh_token = Column(Text, nullable=True)  # Refresh token if available
    scopes = Column(Text, nullable=True)  # Comma-separated list of scopes
    rotated_at = Column(DateTime, nullable=True)  # Last token rotation time
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f"<Account(id={self.id}, handle={self.handle})>"


class Post(Base):
    """Model for draft and scheduled posts."""

    __tablename__ = "posts"

    id = Column(Integer, primary_key=True, index=True)
    text = Column(Text, nullable=False)  # Post text content
    media_refs = Column(Text, nullable=True)  # JSON array of media URLs or IDs
    deleted = Column(Boolean, default=False, nullable=False)  # Soft delete flag
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    schedules = relationship("Schedule", back_populates="post")
    published_posts = relationship("PublishedPost", back_populates="post")

    def __repr__(self):
        return f"<Post(id={self.id}, text={self.text[:50]}...)>"


class Schedule(Base):
    """Model for one-off or recurring post schedules."""

    __tablename__ = "schedules"

    id = Column(Integer, primary_key=True, index=True)
    post_id = Column(Integer, ForeignKey("posts.id"), nullable=False)
    kind = Column(String(50), nullable=False)  # 'one_shot', 'cron', 'rrule'
    schedule_spec = Column(Text, nullable=False)  # Cron string, RRULE, or ISO datetime for one_shot
    timezone = Column(String(100), nullable=True, default="UTC")
    next_run_at = Column(DateTime, nullable=True, index=True)  # Next scheduled execution time
    enabled = Column(Boolean, default=True, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    post = relationship("Post", back_populates="schedules")
    publish_jobs = relationship("PublishJob", back_populates="schedule")

    def __repr__(self):
        return f"<Schedule(id={self.id}, post_id={self.post_id}, kind={self.kind}, enabled={self.enabled})>"


class PublishJob(Base):
    """Model for tracking each attempt to publish a post."""

    __tablename__ = "publish_jobs"

    id = Column(Integer, primary_key=True, index=True)
    schedule_id = Column(Integer, ForeignKey("schedules.id"), nullable=False)
    planned_at = Column(DateTime, nullable=False, index=True)  # When this job was scheduled to run
    started_at = Column(DateTime, nullable=True)  # When execution actually started
    finished_at = Column(DateTime, nullable=True)  # When execution completed
    status = Column(String(50), nullable=False, index=True)  # 'pending', 'running', 'completed', 'failed'
    error = Column(Text, nullable=True)  # Error message if status is 'failed'
    dedupe_key = Column(String(200), nullable=True, unique=True)  # For idempotency
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    schedule = relationship("Schedule", back_populates="publish_jobs")

    def __repr__(self):
        return f"<PublishJob(id={self.id}, schedule_id={self.schedule_id}, status={self.status})>"


class PublishedPost(Base):
    """Model for mapping posts to their X/Twitter post IDs."""

    __tablename__ = "published_posts"

    id = Column(Integer, primary_key=True, index=True)
    post_id = Column(Integer, ForeignKey("posts.id"), nullable=False)
    x_post_id = Column(String(100), nullable=False, unique=True, index=True)  # X/Twitter post ID
    published_at = Column(DateTime, nullable=False, index=True)
    url = Column(String(500), nullable=True)  # Full URL to the post on X

    # Relationships
    post = relationship("Post", back_populates="published_posts")
    metrics_snapshots = relationship("MetricsSnapshot", back_populates="published_post")

    def __repr__(self):
        return f"<PublishedPost(id={self.id}, post_id={self.post_id}, x_post_id={self.x_post_id})>"


class MetricsSnapshot(Base):
    """Model for time series of post metrics from X/Twitter."""

    __tablename__ = "metrics_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    x_post_id = Column(String(100), ForeignKey("published_posts.x_post_id"), nullable=False)
    captured_at = Column(DateTime, nullable=False, index=True)  # When these metrics were captured
    impressions = Column(Integer, default=0, nullable=True)  # Total impressions
    likes = Column(Integer, default=0, nullable=True)
    replies = Column(Integer, default=0, nullable=True)
    reposts = Column(Integer, default=0, nullable=True)  # Retweets
    bookmarks = Column(Integer, default=0, nullable=True)
    profile_clicks = Column(Integer, default=0, nullable=True)
    link_clicks = Column(Integer, default=0, nullable=True)
    video_views = Column(Integer, default=0, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    published_post = relationship("PublishedPost", back_populates="metrics_snapshots")

    def __repr__(self):
        return f"<MetricsSnapshot(id={self.id}, x_post_id={self.x_post_id}, impressions={self.impressions})>"


class ProfileCache(Base):
    """Model for caching Twitter/X profile data with expiration."""

    __tablename__ = "profile_cache"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), nullable=False, unique=True, index=True)  # Twitter username
    raw = Column(JSON, nullable=False)  # Full API response as JSON
    fetched_at = Column(DateTime, nullable=False, index=True)  # When the data was fetched
    expires_at = Column(DateTime, nullable=False, index=True)  # When the cached data expires
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f"<ProfileCache(id={self.id}, username={self.username}, expires_at={self.expires_at})>"

