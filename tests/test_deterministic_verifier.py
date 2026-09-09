import uuid
from decimal import Decimal
from unittest.mock import patch
import pytest

from app.core.verifier import deterministic_verifier
from app.schemas.intent import CryptoExecutionIR


def build_sample_ir(
    action: str = "SPOT_SWAP",
    source_asset: str = "USDT",
    target_asset: str = "ETH",
    amount_type: str = "EXACT",
    amount_value: float = 500.0,
    max_slippage_pct: float = 1.0,
) -> CryptoExecutionIR:
    """Helper khởi tạo nhanh CryptoExecutionIR với giá trị chuỗi chuẩn SRS."""
    return CryptoExecutionIR(
        intent_id=uuid.uuid4(),
        action=action,
        source_asset=source_asset,
        target_asset=target_asset,
        amount_type=amount_type,
        amount_value=amount_value,
        limit_price=None,
        max_slippage_pct=max_slippage_pct,
        deadline_seconds=60,
    )


# TC-VRF-01: Kiểm tra số dư khả dụng - Đủ tiền
def test_tc_vrf_01_sufficient_balance():
    ir = build_sample_ir(amount_value=500.0, source_asset="USDT")
    available_balance = Decimal("1000.0")

    result = deterministic_verifier.verify(ir=ir, available_balance=available_balance)

    assert result.is_valid is True
    assert result.error_code is None

    balance_audit = next(
        (entry for entry in result.audit_entries if entry.verification_rule == "BALANCE_CHECK"),
        None,
    )
    assert balance_audit is not None
    assert balance_audit.is_passed is True
    assert balance_audit.checked_balance == available_balance


# TC-VRF-02: Kiểm tra số dư khả dụng - Không đủ tiền (FR-3.2)
def test_tc_vrf_02_insufficient_balance():
    ir = build_sample_ir(amount_value=1200.0, source_asset="USDT")
    available_balance = Decimal("1000.0")

    result = deterministic_verifier.verify(ir=ir, available_balance=available_balance)

    assert result.is_valid is False
    assert result.error_code == "INSUFFICIENT_FUNDS"
    assert "Số dư khả dụng không đủ" in result.reason

    balance_audit = next(
        (entry for entry in result.audit_entries if entry.verification_rule == "BALANCE_CHECK"),
        None,
    )
    assert balance_audit is not None
    assert balance_audit.is_passed is False
    assert balance_audit.checked_balance == available_balance
    assert balance_audit.rejection_reason is not None


# TC-VRF-03: Tính toán số dư theo tỷ lệ phần trăm (%)
def test_tc_vrf_03_percentage_balance_calculation():
    ir = build_sample_ir(
        amount_type="PERCENTAGE",
        amount_value=20.0,
        source_asset="USDT",
    )
    available_balance = Decimal("2000.0")

    result = deterministic_verifier.verify(ir=ir, available_balance=available_balance)

    assert result.is_valid is True
    balance_audit = next(
        (entry for entry in result.audit_entries if entry.verification_rule == "BALANCE_CHECK"),
        None,
    )
    assert balance_audit is not None
    assert balance_audit.is_passed is True


# TC-VRF-04: Whitelist tài sản hợp lệ (FR-3.3)
def test_tc_vrf_04_valid_whitelist_assets():
    ir = build_sample_ir(source_asset="USDT", target_asset="ETH")
    available_balance = Decimal("5000.0")

    result = deterministic_verifier.verify(ir=ir, available_balance=available_balance)

    whitelist_audit = next(
        (entry for entry in result.audit_entries if entry.verification_rule == "ASSET_WHITELIST"),
        None,
    )
    assert whitelist_audit is not None
    assert whitelist_audit.is_passed is True
    assert result.is_valid is True


# TC-VRF-05: Chặn tài sản ngoài Whitelist (FR-3.3)
def test_tc_vrf_05_unsupported_asset_rejection():
    ir = build_sample_ir(source_asset="USDT", target_asset="SCAM_COIN")
    available_balance = Decimal("5000.0")

    result = deterministic_verifier.verify(ir=ir, available_balance=available_balance)

    assert result.is_valid is False
    assert result.error_code == "UNSUPPORTED_ASSET"

    whitelist_audit = next(
        (entry for entry in result.audit_entries if entry.verification_rule == "ASSET_WHITELIST"),
        None,
    )
    assert whitelist_audit is not None
    assert whitelist_audit.is_passed is False
    assert "SCAM_COIN" in whitelist_audit.rejection_reason


# TC-VRF-06: Giới hạn trượt giá an toàn (FR-3.4)
def test_tc_vrf_06_slippage_cap_guardrail():
    ir = build_sample_ir(amount_value=100.0, max_slippage_pct=4.5)
    available_balance = Decimal("1000.0")

    result = deterministic_verifier.verify(ir=ir, available_balance=available_balance)

    assert result.is_valid is False
    assert result.error_code == "GUARDRAIL_VIOLATION"
    assert "exceeds the system maximum threshold of 3.0%" in result.reason

    slippage_audit = next(
        (entry for entry in result.audit_entries if entry.verification_rule == "SLIPPAGE_CAP"),
        None,
    )
    assert slippage_audit is not None
    assert slippage_audit.is_passed is False


# TC-VRF-07: Độc lập hoàn toàn với AI (FR-3.1)
def test_tc_vrf_07_complete_ai_isolation():
    ir = build_sample_ir(amount_value=300.0)
    available_balance = Decimal("1000.0")

    with patch("openai.OpenAI", side_effect=RuntimeError("AI must not be called in Verifier")), \
         patch("httpx.AsyncClient.post", side_effect=RuntimeError("Network calls forbidden")):

        result = deterministic_verifier.verify(ir=ir, available_balance=available_balance)
        assert result.is_valid is True
        assert len(result.audit_entries) >= 3