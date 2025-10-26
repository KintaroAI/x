"""Audit logging utilities."""

from datetime import datetime
from typing import Optional
from src.models import AuditLog
from src.database import get_db


def log_audit_event(
    level: str,
    action: str,
    message: str,
    component: Optional[str] = None,
    user_id: Optional[str] = None,
    ip_address: Optional[str] = None,
    metadata: Optional[str] = None,
):
    """
    Log an audit event to the audit_log table.
    
    Args:
        level: Log level (INFO, WARNING, ERROR, CRITICAL)
        action: Action being performed
        message: Log message
        component: Component name (e.g., 'api', 'worker')
        user_id: User ID if applicable
        ip_address: IP address if applicable
        metadata: JSON string with additional metadata
    """
    with get_db() as db:
        audit_entry = AuditLog(
            timestamp=datetime.utcnow(),
            level=level,
            component=component,
            action=action,
            message=message,
            metadata=metadata,
            user_id=user_id,
            ip_address=ip_address,
            created_at=datetime.utcnow(),
        )
        db.add(audit_entry)
        db.commit()


def log_info(action: str, message: str, component: Optional[str] = None, **kwargs):
    """Convenience method to log INFO level events."""
    log_audit_event("INFO", action, message, component, **kwargs)


def log_warning(action: str, message: str, component: Optional[str] = None, **kwargs):
    """Convenience method to log WARNING level events."""
    log_audit_event("WARNING", action, message, component, **kwargs)


def log_error(action: str, message: str, component: Optional[str] = None, **kwargs):
    """Convenience method to log ERROR level events."""
    log_audit_event("ERROR", action, message, component, **kwargs)


def log_critical(action: str, message: str, component: Optional[str] = None, **kwargs):
    """Convenience method to log CRITICAL level events."""
    log_audit_event("CRITICAL", action, message, component, **kwargs)

