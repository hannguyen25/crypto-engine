import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional, Set
from pydantic import BaseModel, Field

from app.schemas.intent import CryptoExecutionIR, AmountType

# Danh mục Whitelist tài sản hỗ trợ giao dịch (FR-3.3)
DEFAULT_ASSET_WHITELIST: Set[str] = {
    "BTC", "ETH", "USDT", "USDC", "SOL", "BNB", "MATIC", "AVAX", "NEAR", "LINK"
}

# Ngưỡng trần trượt giá tối đa cho phép (FR-3.4)
MAX_SLIPPAGE_THRESHOLD: float = 3.0


class VerifierAuditTrailEntry(BaseModel):
    """Mô hình phản chiếu bảng verifier_audit_trail trong PostgreSQL"""
    audit_id: Optional[int] = None
    intent_id: uuid.UUID
    verification_rule: str
    is_passed: bool
    rejection_reason: Optional[str] = None
    checked_balance: Optional[Decimal] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class VerificationResult(BaseModel):
    is_valid: bool
    error_code: Optional[str] = None
    reason: Optional[str] = None
    remediation: Optional[str] = None
    audit_entries: list[VerifierAuditTrailEntry] = Field(default_factory=list)


class DeterministicVerifier:
    def __init__(self, asset_whitelist: Optional[Set[str]] = None):
        self.whitelist = asset_whitelist or DEFAULT_ASSET_WHITELIST

    def verify(
        self,
        ir: CryptoExecutionIR,
        available_balance: float | Decimal,
    ) -> VerificationResult:
        """
        Thực thi kiểm tra tất định (FR-3.1 -> FR-3.5).
        Mọi quyết định đều sinh ra bản ghi audit tương ứng.
        """
        balance = Decimal(str(available_balance))
        audit_records: list[VerifierAuditTrailEntry] = []

        # Rule 1: Asset Whitelist Check (FR-3.3)
        source_ok = ir.source_asset.upper() in self.whitelist
        target_ok = ir.target_asset.upper() in self.whitelist

        if not (source_ok and target_ok):
            invalid_assets = []
            if not source_ok:
                invalid_assets.append(f"source_asset '{ir.source_asset}'")
            if not target_ok:
                invalid_assets.append(f"target_asset '{ir.target_asset}'")
            
            reason = f"Tài sản không nằm trong Whitelist cho phép: {', '.join(invalid_assets)}."
            audit_records.append(
                VerifierAuditTrailEntry(
                    intent_id=ir.intent_id,
                    verification_rule="ASSET_WHITELIST",
                    is_passed=False,
                    rejection_reason=reason,
                    checked_balance=balance,
                )
            )
            return VerificationResult(
                is_valid=False,
                error_code="UNSUPPORTED_ASSET",
                reason=reason,
                remediation="Chỉ giao dịch các cặp tài sản nằm trong danh mục hệ thống hỗ trợ.",
                audit_entries=audit_records,
            )

        audit_records.append(
            VerifierAuditTrailEntry(
                intent_id=ir.intent_id,
                verification_rule="ASSET_WHITELIST",
                is_passed=True,
                checked_balance=balance,
            )
        )

        # Rule 2: Slippage Cap Guard (FR-3.4)
        if ir.max_slippage_pct > MAX_SLIPPAGE_THRESHOLD:
            reason = (
                f"Requested slippage ({ir.max_slippage_pct}%) exceeds the system "
                f"maximum threshold of {MAX_SLIPPAGE_THRESHOLD}%"
            )
            audit_records.append(
                VerifierAuditTrailEntry(
                    intent_id=ir.intent_id,
                    verification_rule="SLIPPAGE_CAP",
                    is_passed=False,
                    rejection_reason=reason,
                    checked_balance=balance,
                )
            )
            return VerificationResult(
                is_valid=False,
                error_code="GUARDRAIL_VIOLATION",
                reason=reason,
                remediation="Vui lòng chỉ định mức trượt giá (slippage) thấp hơn hoặc dùng mặc định.",
                audit_entries=audit_records,
            )

        audit_records.append(
            VerifierAuditTrailEntry(
                intent_id=ir.intent_id,
                verification_rule="SLIPPAGE_CAP",
                is_passed=True,
                checked_balance=balance,
            )
        )

        # Rule 3: Balance Check (FR-3.2)
        if ir.amount_type == AmountType.EXACT:
            order_amount = Decimal(str(ir.amount_value))
            if order_amount > balance:
                reason = (
                    f"Số dư khả dụng không đủ. Yêu cầu: {order_amount} {ir.source_asset}, "
                    f"Khả dụng: {balance} {ir.source_asset}."
                )
                audit_records.append(
                    VerifierAuditTrailEntry(
                        intent_id=ir.intent_id,
                        verification_rule="BALANCE_CHECK",
                        is_passed=False,
                        rejection_reason=reason,
                        checked_balance=balance,
                    )
                )
                return VerificationResult(
                    is_valid=False,
                    error_code="INSUFFICIENT_FUNDS",
                    reason=reason,
                    remediation="Vui lòng nạp thêm tiền hoặc giảm khối lượng giao dịch.",
                    audit_entries=audit_records,
                )

        audit_records.append(
            VerifierAuditTrailEntry(
                intent_id=ir.intent_id,
                verification_rule="BALANCE_CHECK",
                is_passed=True,
                checked_balance=balance,
            )
        )

        return VerificationResult(
            is_valid=True,
            audit_entries=audit_records,
        )


deterministic_verifier = DeterministicVerifier()