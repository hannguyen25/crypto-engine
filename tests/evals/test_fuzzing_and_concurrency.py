import math
import os
import uuid
import pytest
from hypothesis import given, settings, strategies as st

from app.schemas.intent import CryptoExecutionIR, AmountType
from app.core.verifier import (
    deterministic_verifier,
    DEFAULT_ASSET_WHITELIST,
    MAX_SLIPPAGE_THRESHOLD,
)

IS_CI = os.getenv("CI") == "true"
FUZZ_EXAMPLES = 10000 if IS_CI else 500


# ----------------------------------------------------------------------
# TC-FUZZ-01: Fuzzing biên tham số tài chính (FR-3.2)
# ----------------------------------------------------------------------
@settings(max_examples=FUZZ_EXAMPLES, deadline=None)
@given(
    amount=st.one_of(
        st.floats(min_value=-1e18, max_value=1e18),
        st.just(float("nan")),
        st.just(float("inf")),
        st.just(float("-inf")),
        st.just(0.0),
        st.floats(min_value=0.0001, max_value=500.0),
    ),
    amount_type=st.sampled_from([AmountType.EXACT, AmountType.PERCENTAGE]),
    action=st.sampled_from(["SPOT_SWAP", "LIMIT_ORDER"]),
)
def test_fuzz_financial_boundaries(amount, amount_type, action):
    ir = CryptoExecutionIR.model_construct(
        intent_id=uuid.uuid4(),
        action=action,
        source_asset="USDT",
        target_asset="BTC",
        amount_type=amount_type,
        amount_value=amount,
        max_slippage_pct=1.0,
        deadline_seconds=60,
    )

    try:
        result = deterministic_verifier.verify(ir, available_balance=1000.0)
    except Exception as exc:
        pytest.fail(f"Verifier crash voi amount={amount}: {exc}")

    assert result is not None

    if amount_type == AmountType.EXACT:
        is_invalid = math.isnan(amount) or math.isinf(amount) or amount <= 0 or amount > 1000.0
        if is_invalid:
            assert result.is_valid is False
            assert result.error_code in ["INVALID_AMOUNT", "INSUFFICIENT_FUNDS"]


# ----------------------------------------------------------------------
# TC-FUZZ-02: Fuzzing trượt giá cực đoan (FR-3.4)
# ----------------------------------------------------------------------
@settings(max_examples=min(FUZZ_EXAMPLES, 1000), deadline=None)
@given(
    slippage=st.one_of(
        st.floats(min_value=-100.0, max_value=1000.0),
        st.just(float("nan")),
        st.just(float("inf")),
        st.just(float("-inf")),
    )
)
def test_fuzz_extreme_slippage(slippage):
    ir = CryptoExecutionIR.model_construct(
        intent_id=uuid.uuid4(),
        action="SPOT_SWAP",
        source_asset="USDT",
        target_asset="ETH",
        amount_type=AmountType.EXACT,
        amount_value=50.0,
        max_slippage_pct=slippage,
        deadline_seconds=60,
    )

    try:
        result = deterministic_verifier.verify(ir, available_balance=1000.0)
    except Exception as exc:
        pytest.fail(f"Verifier crash khi test slippage={slippage}: {exc}")

    assert result is not None

    is_invalid_slippage = (
        math.isnan(slippage)
        or math.isinf(slippage)
        or slippage <= 0.0
        or slippage > MAX_SLIPPAGE_THRESHOLD
    )
    if is_invalid_slippage:
        assert result.is_valid is False
        assert result.error_code == "GUARDRAIL_VIOLATION"


# ----------------------------------------------------------------------
# TC-FUZZ-03: Fuzzing Whitelist & SQL/Injection (FR-3.3)
# ----------------------------------------------------------------------
@settings(max_examples=min(FUZZ_EXAMPLES, 1000), deadline=None)
@given(
    malicious_symbol=st.one_of(
        st.text(min_size=1, max_size=50),
        st.sampled_from(["BTC'; DROP TABLE users;--", "0xFAKEE", "<script>", "ETH\x00NULL", "USDT%20"]),
    )
)
def test_fuzz_token_symbol_whitelist(malicious_symbol):
    ir = CryptoExecutionIR.model_construct(
        intent_id=uuid.uuid4(),
        action="SPOT_SWAP",
        source_asset=malicious_symbol,
        target_asset="BTC",
        amount_type=AmountType.EXACT,
        amount_value=10.0,
        max_slippage_pct=1.0,
        deadline_seconds=60,
    )

    try:
        result = deterministic_verifier.verify(ir, available_balance=1000.0)
    except Exception as exc:
        pytest.fail(f"Verifier crash khi gap symbol={malicious_symbol}: {exc}")

    assert result is not None

    if malicious_symbol.upper() not in DEFAULT_ASSET_WHITELIST:
        assert result.is_valid is False
        assert result.error_code == "UNSUPPORTED_ASSET"