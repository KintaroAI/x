"""Audit log API endpoints."""

import random
import logging
from datetime import datetime
from fastapi.responses import HTMLResponse

from src.models import AuditLog
from src.database import get_db
from src.audit import log_info

logger = logging.getLogger(__name__)


async def get_audit_log():
    """Get the latest 10 audit log records."""
    with get_db() as db:
        records = db.query(AuditLog).order_by(AuditLog.timestamp.desc()).limit(10).all()
        
        return [
            {
                "id": record.id,
                "timestamp": record.timestamp.isoformat(),
                "level": record.level,
                "component": record.component,
                "action": record.action,
                "message": record.message,
                "extra_data": record.extra_data,
                "user_id": record.user_id,
                "ip_address": record.ip_address,
            }
            for record in records
        ]


async def get_audit_log_html():
    """Get the latest 10 audit log records as HTML."""
    with get_db() as db:
        records = db.query(AuditLog).order_by(AuditLog.timestamp.desc()).limit(10).all()
        
        def get_level_color(level):
            colors = {
                "INFO": "text-blue-600",
                "WARNING": "text-yellow-600",
                "ERROR": "text-red-600",
                "CRITICAL": "text-red-800 font-bold"
            }
            return colors.get(level, "text-gray-600")
        
        if not records:
            return HTMLResponse(
                "<p class='text-gray-600 p-4 text-center'>No audit log records found.</p>"
            )
        
        html_rows = ""
        for record in records:
            level_color = get_level_color(record.level)
            timestamp = record.timestamp.strftime("%Y-%m-%d %H:%M:%S")
            html_rows += f"""
            <tr class="hover:bg-gray-50">
                <td class="border border-gray-300 px-4 py-2 text-sm">{record.id}</td>
                <td class="border border-gray-300 px-4 py-2 text-sm text-gray-700">{timestamp}</td>
                <td class="border border-gray-300 px-4 py-2 text-sm {level_color}">{record.level}</td>
                <td class="border border-gray-300 px-4 py-2 text-sm">{record.component or '-'}</td>
                <td class="border border-gray-300 px-4 py-2 text-sm">{record.action}</td>
                <td class="border border-gray-300 px-4 py-2 text-sm">{record.message}</td>
            </tr>
            """
        
        html = f"""
        <div class="overflow-x-auto">
            <table class="min-w-full border-collapse border border-gray-300">
                <thead class="bg-gray-100">
                    <tr>
                        <th class="border border-gray-300 px-4 py-2 text-left text-sm font-semibold">ID</th>
                        <th class="border border-gray-300 px-4 py-2 text-left text-sm font-semibold">Timestamp</th>
                        <th class="border border-gray-300 px-4 py-2 text-left text-sm font-semibold">Level</th>
                        <th class="border border-gray-300 px-4 py-2 text-left text-sm font-semibold">Component</th>
                        <th class="border border-gray-300 px-4 py-2 text-left text-sm font-semibold">Action</th>
                        <th class="border border-gray-300 px-4 py-2 text-left text-sm font-semibold">Message</th>
                    </tr>
                </thead>
                <tbody>
                    {html_rows}
                </tbody>
            </table>
        </div>
        """
        
        return HTMLResponse(html)


async def create_test_audit_log():
    """Create a dummy audit log record for testing."""
    levels = ["INFO", "WARNING", "ERROR"]
    actions = ["test_action", "dummy_action", "sample_action", "check_action"]
    components = ["ui", "api", "test", "frontend"]
    messages = [
        "Testing audit log functionality",
        "Dummy record created from UI",
        "Test audit entry created successfully",
        "Sample audit log for testing",
    ]
    
    with get_db() as db:
        audit_entry = AuditLog(
            timestamp=datetime.utcnow(),
            level=random.choice(levels),
            component=random.choice(components),
            action=random.choice(actions),
            message=random.choice(messages),
            extra_data='{"test": true, "source": "ui"}',
            user_id="test_user",
            ip_address="127.0.0.1",
            created_at=datetime.utcnow(),
        )
        db.add(audit_entry)
        db.commit()
        db.refresh(audit_entry)
        
        return {
            "id": audit_entry.id,
            "timestamp": audit_entry.timestamp.isoformat(),
            "level": audit_entry.level,
            "component": audit_entry.component,
            "action": audit_entry.action,
            "message": audit_entry.message,
        }

