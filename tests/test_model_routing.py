import pytest
from unittest.mock import AsyncMock, patch
from app.core.llm_parser import intent_parser
from app.schemas.intent import CryptoExecutionIR, ActionType, AmountType


class MockUsage:
    prompt_tokens = 30
    completion_tokens = 20


class MockRawResponse:
    usage = MockUsage()


# TC-ROUT-01: Phân luồng câu lệnh ngắn/đơn giản sang SLM (gpt-4o-mini)
@pytest.mark.asyncio
async def test_tc_rout_01_simple_prompt_to_slm():
    simple_prompt = "Bán 10 SOL lấy USDC"

    mock_ir = CryptoExecutionIR(
        action=ActionType.SPOT_SWAP,
        source_asset="SOL",
        target_asset="USDC",
        amount_type=AmountType.EXACT,
        amount_value=10.0,
    )

    with patch.object(
        intent_parser.openai_client.chat.completions,
        "create_with_completion",
        AsyncMock(return_value=(mock_ir, MockRawResponse())),
    ) as mock_create:
        ir, log = await intent_parser.parse_and_log(simple_prompt)

        # 1. Router phải xác định tầng mô hình là SLM
        assert log.model_tier == "SLM"
        assert log.status == "SUCCESS"

        # 2. Khẳng định model được gọi là gpt-4o-mini
        mock_create.assert_called_once()
        call_kwargs = mock_create.call_args.kwargs
        assert call_kwargs["model"] == "gpt-4o-mini"
        assert ir.source_asset == "SOL"
        assert ir.target_asset == "USDC"


# TC-ROUT-02: Phân luồng câu lệnh phức tạp/có điều kiện sang LLM (gpt-4o)
@pytest.mark.asyncio
async def test_tc_rout_02_complex_conditional_prompt_to_llm():
    complex_prompt = "Nếu BTC chạm 65k thì chốt lời 30% sang USDT, còn nếu thủng 58k thì bán hết"

    mock_ir = CryptoExecutionIR(
        action=ActionType.LIMIT_ORDER,
        source_asset="BTC",
        target_asset="USDT",
        amount_type=AmountType.PERCENTAGE,
        amount_value=30.0,
        limit_price=65000.0,
    )

    with patch.object(
        intent_parser.openai_client.chat.completions,
        "create_with_completion",
        AsyncMock(return_value=(mock_ir, MockRawResponse())),
    ) as mock_create:
        ir, log = await intent_parser.parse_and_log(complex_prompt)

        # 1. Router phải nhận diện được điều kiện phức tạp và định tuyến tới LLM
        assert log.model_tier == "LLM"
        assert log.status == "SUCCESS"

        # 2. Khẳng định model được gọi là gpt-4o
        mock_create.assert_called_once()
        call_kwargs = mock_create.call_args.kwargs
        assert call_kwargs["model"] == "gpt-4o"
        assert ir.source_asset == "BTC"
        assert ir.target_asset == "USDT"