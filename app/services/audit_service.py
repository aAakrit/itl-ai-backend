"""
Audit logging helper.

One function, used everywhere an admin action needs to be recorded.
Deliberately synchronous/best-effort within the caller's existing
transaction — callers commit alongside their own change so an audit
entry and the change it describes are never split across transactions.
"""

from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog


def log_action(
    db: Session,
    *,
    actor_id: Optional[int],
    action: str,
    target_type: str,
    target_id: int,
    previous_value: Optional[dict[str, Any]] = None,
    new_value: Optional[dict[str, Any]] = None,
    reason: Optional[str] = None,
) -> AuditLog:
    entry = AuditLog(
        actor_id=actor_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        previous_value=previous_value,
        new_value=new_value,
        reason=reason,
    )
    db.add(entry)
    db.flush()
    return entry