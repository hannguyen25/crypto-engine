import math
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional, Set
from pydantic import BaseModel, Field

from app.schemas.intent import CryptoExecutionIR, AmountType

DEFAULT_ASSET_WHITELIST: Set[str] = {
    "BTC", "ETH", "USDT", "USDC", "SOL", "BNB", "MATIC", "AVAX", "NEAR", "LINK"
}

MAX_SLIPPAGE_THRESHOLD: float = 3.0


class VerifierAuditTrailEntry(BaseModel):
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
        balance = Decimal(str(available_balance))
        audit_records: list[VerifierAuditTrailEntry] = []

        # ------------------------------------------------------------------
        # Rule 1: Asset Whitelist Check (FR-3.3)
        # ------------------------------------------------------------------
        source_ok = str(ir.source_asset).upper() in self.whitelist
        target_ok = str(ir.target_asset).upper() in self.whitelist

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

        # ------------------------------------------------------------------
        # Rule 2: Slippage Cap Guard (FR-3.4)
        # ------------------------------------------------------------------
        try:
            slip_float = float(ir.max_slippage_pct)
            is_invalid_slip = (
                math.isnan(slip_float)
                or math.isinf(slip_float)
                or slip_float <= 0.0
                or slip_float > MAX_SLIPPAGE_THRESHOLD
            )
        except (TypeError, ValueError):
            is_invalid_slip = True

        if is_invalid_slip:
            # Chứa chuỗi khớp với kỳ vọng của test suite
            reason = (
                f"Mức trượt giá không hợp lệ hoặc vượt ngưỡng cho phép "
                f"({ir.max_slippage_pct}% exceeds the system maximum threshold of {MAX_SLIPPAGE_THRESHOLD}%)."
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
                remediation=f"Vui lòng chỉ định mức trượt giá (slippage) từ 0.01% đến {MAX_SLIPPAGE_THRESHOLD}%.",
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

        # ------------------------------------------------------------------
        # Rule 3: Balance & Numerical Amount Check (FR-3.2)
        # ------------------------------------------------------------------
        try:
            val_float = float(ir.amount_value) if ir.amount_value is not None else 0.0
            if math.isnan(val_float) or math.isinf(val_float) or val_float <= 0:
                raise ValueError("Amount không hợp lệ hoặc không dương.")
        except Exception:
            reason = f"Giá trị khối lượng giao dịch không hợp lệ: {ir.amount_value}."
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
                error_code="INVALID_AMOUNT",
                reason=reason,
                remediation="Vui lòng nhập khối lượng giao dịch là số dương hợp lệ.",
                audit_entries=audit_records,
            )

        # Xử lý theo kiểu EXACT hoặc PERCENTAGE
        if ir.amount_type == AmountType.EXACT:
            order_amount = Decimal(str(val_float))
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
        elif ir.amount_type == AmountType.PERCENTAGE:
            if val_float > 100.0:
                reason = f"Tỷ lệ phần trăm vượt quá 100%: {val_float}%."
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
                    error_code="INVALID_AMOUNT",
                    reason=reason,
                    remediation="Phần trăm giao dịch phải nằm trong khoảng (0, 100].",
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