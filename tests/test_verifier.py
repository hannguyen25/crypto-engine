import uuid
from decimal import Decimal
import pytest

from app.core.verifier import DeterministicVerifier, VerifierAuditTrailEntry
from app.schemas.intent import CryptoExecutionIR, ActionType, AmountType


@pytest.fixture
def custom_verifier():
    return DeterministicVerifier(asset_whitelist={"BTC", "ETH", "USDT"})


def create_mock_ir(
    source="USDT",
    target="BTC",
    amount_type=AmountType.EXACT,
    amount_value=100.0,
    slippage=1.0,
) -> CryptoExecutionIR:
    return CryptoExecutionIR(
        intent_id=uuid.uuid4(),
        action=ActionType.SPOT_SWAP,
        source_asset=source,
        target_asset=target,
        amount_type=amount_type,
        amount_value=amount_value,
        max_slippage_pct=slippage,
    )


# 1. Kiểm tra hợp lệ toàn bộ
def test_verify_all_passed(custom_verifier):
    ir = create_mock_ir(source="USDT", target="BTC", amount_value=500.0, slippage=2.5)
    result = custom_verifier.verify(ir, available_balance=1000.0)

    assert result.is_valid is True
    assert result.error_code is None
    assert len(result.audit_entries) == 3
    assert all(entry.is_passed for entry in result.audit_entries)


# 2. Whitelist: Nguồn không hợp lệ
def test_verify_source_asset_not_in_whitelist(custom_verifier):
    ir = create_mock_ir(source="DOGE", target="USDT")
    result = custom_verifier.verify(ir, available_balance=1000.0)

    assert result.is_valid is False
    assert result.error_code == "UNSUPPORTED_ASSET"
    assert "source_asset 'DOGE'" in result.reason
    assert result.audit_entries[0].is_passed is False
    assert result.audit_entries[0].verification_rule == "ASSET_WHITELIST"


# 3. Whitelist: Đích không hợp lệ
def test_verify_target_asset_not_in_whitelist(custom_verifier):
    ir = create_mock_ir(source="USDT", target="PEPE")
    result = custom_verifier.verify(ir, available_balance=1000.0)

    assert result.is_valid is False
    assert result.error_code == "UNSUPPORTED_ASSET"
    assert "target_asset 'PEPE'" in result.reason


# 4. Whitelist: Cả hai tài sản đều không hợp lệ
def test_verify_both_assets_invalid(custom_verifier):
    ir = create_mock_ir(source="SHIB", target="FLOKI")
    result = custom_verifier.verify(ir, available_balance=1000.0)

    assert result.is_valid is False
    assert result.error_code == "UNSUPPORTED_ASSET"
    assert "source_asset 'SHIB'" in result.reason
    assert "target_asset 'FLOKI'" in result.reason


# 5. Slippage: Vượt ngưỡng 3.0%
def test_verify_slippage_cap_exceeded(custom_verifier):
    ir = create_mock_ir(slippage=4.5)
    result = custom_verifier.verify(ir, available_balance=1000.0)

    assert result.is_valid is False
    assert result.error_code == "GUARDRAIL_VIOLATION"
    assert "exceeds the system maximum threshold of 3.0%" in result.reason
    assert len(result.audit_entries) == 2
    assert result.audit_entries[1].is_passed is False


# 6. Slippage: Chạm ngưỡng biên 3.0%
def test_verify_slippage_cap_boundary(custom_verifier):
    ir = create_mock_ir(slippage=3.0)
    result = custom_verifier.verify(ir, available_balance=1000.0)

    assert result.is_valid is True
    assert result.audit_entries[1].is_passed is True


# 7. Balance Check: Không đủ tiền (amount > balance)
def test_verify_insufficient_funds(custom_verifier):
    ir = create_mock_ir(amount_value=1500.0)
    result = custom_verifier.verify(ir, available_balance=1000.0)

    assert result.is_valid is False
    assert result.error_code == "INSUFFICIENT_FUNDS"
    assert "Số dư khả dụng không đủ" in result.reason
    assert result.audit_entries[2].is_passed is False
    assert result.audit_entries[2].checked_balance == Decimal("1000.0")


# 8. Balance Check: Vừa đủ tiền (amount == balance)
def test_verify_exact_balance_boundary(custom_verifier):
    ir = create_mock_ir(amount_value=1000.0)
    result = custom_verifier.verify(ir, available_balance=1000.0)

    assert result.is_valid is True
    assert result.audit_entries[2].is_passed is True


# 9. Lệnh tỷ lệ phần trăm (PERCENTAGE) bỏ qua kiểm tra số dư cố định
def test_verify_percentage_order(custom_verifier):
    ir = create_mock_ir(amount_type=AmountType.PERCENTAGE, amount_value=50.0)
    result = custom_verifier.verify(ir, available_balance=10.0)

    assert result.is_valid is True
    assert result.audit_entries[2].is_passed is True