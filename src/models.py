"""Database models for the application."""

from datetime import datetime
from typing import Optional
from sqlalchemy import Column, Integer, String, DateTime, Text
from sqlalchemy.ext.declarative import declarative_base

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

