import logging
from sqlalchemy import text
from app.db.session import async_session_maker
from app.core.verifier import VerifierAuditTrailEntry

logger = logging.getLogger(__name__)


async def persist_verifier_audit(entry: VerifierAuditTrailEntry) -> None:
    """
    Ghi vết thẩm định (audit trail) của Deterministic Verifier vào bảng
    verifier_audit_trail trong PostgreSQL (SRS FR-3.5).
    """
    query = text("""
        INSERT INTO verifier_audit_trail 
        (intent_id, verification_rule, is_passed, rejection_reason, checked_balance, created_at)
        VALUES 
        (:intent_id, :verification_rule, :is_passed, :rejection_reason, :checked_balance, :created_at)
    """)
    try:
        async with async_session_maker() as session:
            await session.execute(
                query,
                {
                    "intent_id": entry.intent_id,
                    "verification_rule": entry.verification_rule,
                    "is_passed": entry.is_passed,
                    "rejection_reason": entry.rejection_reason,
                    "checked_balance": entry.checked_balance,
                    "created_at": entry.created_at,
                },
            )
            await session.commit()
    except Exception as exc:
        logger.error(f"[Verifier Audit Log Failed] Lỗi ghi DB: {exc}")