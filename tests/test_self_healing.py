import pytest
from unittest.mock import AsyncMock, patch
from pydantic import ValidationError

from app.core.llm_parser import intent_parser
from app.schemas.intent import CryptoExecutionIR, ActionType, AmountType


class MockUsage:
    prompt_tokens = 45
    completion_tokens = 25


class MockRawResponse:
    usage = MockUsage()


# TC-HEAL-01: Tự sửa lỗi thành công sau 1 lần sinh sai schema
@pytest.mark.asyncio
async def test_self_healing_recovers_invalid_schema():
    valid_ir = CryptoExecutionIR(
        action=ActionType.SPOT_SWAP,
        source_asset="USDT",
        target_asset="SOL",
        amount_type=AmountType.EXACT,
        amount_value=50.0,
        max_slippage_pct=1.0,
    )

    # Lần 1: Ném lỗi Validation (ví dụ slippage > 5%) -> Lần 2: Trả về IR hợp lệ
    mock_call = AsyncMock()
    mock_call.side_effect = [
        ValidationError.from_exception_data("Validation Error: max_slippage_pct > 5.0", line_errors=[]),
        (valid_ir, MockRawResponse()),
    ]

    with patch.object(intent_parser.openai_client.chat.completions, "create_with_completion", mock_call):
        ir, log = await intent_parser.parse_and_log("Swap 50 USDT to SOL with huge slippage")

        assert ir is not None
        assert ir.target_asset == "SOL"
        assert log.status == "HEALED"
        assert log.retry_count == 1
        assert log.total_tokens > 0
        assert log.latency_ms > 0.0


# TC-HEAL-02: Dừng sau tối đa 2 lượt retry khi schema liên tục lỗi
@pytest.mark.asyncio
async def test_self_healing_max_retries_exceeded():
    # Cả 3 lần gọi (1 ban đầu + 2 retry) đều ném lỗi
    mock_call = AsyncMock()
    mock_call.side_effect = ValidationError.from_exception_data("Persistent schema failure", line_errors=[])

    with patch.object(intent_parser.openai_client.chat.completions, "create_with_completion", mock_call):
        ir, log = await intent_parser.parse_and_log("Broken unparseable prompt")

        assert ir is None
        assert log.status == "FAILED"
        assert log.retry_count == 2
        assert log.latency_ms > 0.0


# TC-HEAL-03: Ghi nhận intent_logs đầy đủ token và latency khi thành công ngay lần đầu
@pytest.mark.asyncio
async def test_intent_logs_metrics_recorded():
    valid_ir = CryptoExecutionIR(
        action=ActionType.SPOT_SWAP,
        source_asset="USDT",
        target_asset="BTC",
        amount_type=AmountType.EXACT,
        amount_value=100.0,
    )

    with patch.object(
        intent_parser.openai_client.chat.completions,
        "create_with_completion",
        AsyncMock(return_value=(valid_ir, MockRawResponse())),
    ):
        ir, log = await intent_parser.parse_and_log("Swap 100 USDT to BTC")

        assert ir is not None
        assert log.status == "SUCCESS"
        assert log.retry_count == 0
        assert log.prompt_tokens == 45
        assert log.completion_tokens == 25
        assert log.total_tokens == 70
        assert log.latency_ms > 0.0