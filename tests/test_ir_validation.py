import pytest
from unittest.mock import AsyncMock, patch
from pydantic import ValidationError
from app.core.llm_parser import intent_parser
from app.schemas.intent import CryptoExecutionIR, ActionType, AmountType


class MockUsage:
    prompt_tokens = 40
    completion_tokens = 30


class MockRawResponse:
    usage = MockUsage()


# TC-IR-01: Parse lệnh Swap chuẩn xác (Exact Amount)
@pytest.mark.asyncio
async def test_tc_ir_01_parse_exact_swap():
    prompt = "Dùng 1000 USDT mua BNB với trượt giá tối đa 0.5%"
    
    mock_ir = CryptoExecutionIR(
        action=ActionType.SPOT_SWAP,
        source_asset="USDT",
        target_asset="BNB",
        amount_type=AmountType.EXACT,
        amount_value=1000.0,
        max_slippage_pct=0.5,
    )

    with patch.object(
        intent_parser.openai_client.chat.completions,
        "create_with_completion",
        AsyncMock(return_value=(mock_ir, MockRawResponse())),
    ):
        ir, log = await intent_parser.parse_and_log(prompt)

        assert ir.action == ActionType.SPOT_SWAP
        assert ir.source_asset == "USDT"
        assert ir.target_asset == "BNB"
        assert ir.amount_type == AmountType.EXACT
        assert ir.amount_value == 1000.0
        assert ir.max_slippage_pct == 0.5
        assert log.status == "SUCCESS"


# TC-IR-02: Parse lệnh theo tỷ lệ phần trăm (Percentage)
@pytest.mark.asyncio
async def test_tc_ir_02_parse_percentage_swap():
    prompt = "Dùng 25% ví ETH đổi sang USDT"

    mock_ir = CryptoExecutionIR(
        action=ActionType.SPOT_SWAP,
        source_asset="ETH",
        target_asset="USDT",
        amount_type=AmountType.PERCENTAGE,
        amount_value=25.0,
    )

    with patch.object(
        intent_parser.openai_client.chat.completions,
        "create_with_completion",
        AsyncMock(return_value=(mock_ir, MockRawResponse())),
    ):
        ir, log = await intent_parser.parse_and_log(prompt)

        assert ir.amount_type == AmountType.PERCENTAGE
        assert ir.amount_value == 25.0
        assert ir.source_asset == "ETH"
        assert ir.target_asset == "USDT"


# TC-IR-03: Parse lệnh Limit Order kèm giá kích hoạt
@pytest.mark.asyncio
async def test_tc_ir_03_parse_limit_order():
    prompt = "Đặt lệnh mua BTC ở giá 62000 USDT số lượng 0.05 BTC"

    mock_ir = CryptoExecutionIR(
        action=ActionType.LIMIT_ORDER,
        source_asset="USDT",
        target_asset="BTC",
        amount_type=AmountType.EXACT,
        amount_value=0.05,
        limit_price=62000.0,
    )

    with patch.object(
        intent_parser.openai_client.chat.completions,
        "create_with_completion",
        AsyncMock(return_value=(mock_ir, MockRawResponse())),
    ):
        ir, log = await intent_parser.parse_and_log(prompt)

        assert ir.action == ActionType.LIMIT_ORDER
        assert ir.limit_price == 62000.0
        assert ir.amount_value == 0.05


# TC-IR-04: Chặn giá trị âm hoặc bằng 0
def test_tc_ir_04_reject_zero_or_negative_amount():
    # amount_value = 0
    with pytest.raises(ValidationError) as exc_zero:
        CryptoExecutionIR(
            action=ActionType.SPOT_SWAP,
            source_asset="USDT",
            target_asset="BTC",
            amount_value=0.0,
        )
    assert "greater than 0" in str(exc_zero.value)

    # amount_value = -5
    with pytest.raises(ValidationError) as exc_neg:
        CryptoExecutionIR(
            action=ActionType.SPOT_SWAP,
            source_asset="USDT",
            target_asset="BTC",
            amount_value=-5.0,
        )
    assert "greater than 0" in str(exc_neg.value)


# TC-IR-05: Chặn mã Token sai quy cách (Regex ^[A-Z0-9]{2,10}$)
def test_tc_ir_05_reject_invalid_token_regex():
    # Token vượt quá 10 ký tự
    with pytest.raises(ValidationError) as exc_long:
        CryptoExecutionIR(
            action=ActionType.SPOT_SWAP,
            source_asset="BITCOIN_TOKEN_VERY_LONG",
            target_asset="USDT",
            amount_value=100.0,
        )
    assert "vi phạm regex" in str(exc_long.value)

    # Token chỉ có 1 ký tự hoặc ký tự đặc biệt
    with pytest.raises(ValidationError):
        CryptoExecutionIR(
            action=ActionType.SPOT_SWAP,
            source_asset="B",
            target_asset="USDT$",
            amount_value=100.0,
        )