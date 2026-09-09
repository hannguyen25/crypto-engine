import uuid
import pytest
from unittest.mock import AsyncMock, patch
from pydantic import ValidationError

from app.core.llm_parser import intent_parser
from app.schemas.intent import CryptoExecutionIR, ActionType, AmountType


class MockUsage:
    prompt_tokens = 50
    completion_tokens = 30


class MockRawResponse:
    usage = MockUsage()


# TC-HEAL-01: Tự sửa lỗi thành công ở lần thử thứ 1 (Lần 1 thiếu max_slippage_pct -> Lần 2 bổ sung đúng)
@pytest.mark.asyncio
async def test_tc_heal_01_recover_missing_required_field():
    recovered_ir = CryptoExecutionIR(
        action=ActionType.SPOT_SWAP,
        source_asset="USDT",
        target_asset="ETH",
        amount_type=AmountType.EXACT,
        amount_value=500.0,
        max_slippage_pct=0.5,  # Bổ sung đúng ở lần 2
    )

    mock_call = AsyncMock()
    # Lần 1 ném ValidationError do thiếu trường; Lần 2 trả về IR hoàn chỉnh
    mock_call.side_effect = [
        ValidationError.from_exception_data("Field required: max_slippage_pct", line_errors=[]),
        (recovered_ir, MockRawResponse()),
    ]

    with patch.object(intent_parser.openai_client.chat.completions, "create_with_completion", mock_call):
        ir, log = await intent_parser.parse_and_log("Swap 500 USDT to ETH")

        assert ir is not None
        assert ir.max_slippage_pct == 0.5
        assert log.status == "HEALED"
        assert log.retry_count == 1


# TC-HEAL-02: Vượt quá số lần Self-Healing tối đa (Max Retries = 2) -> Trả về HTTP 422
@pytest.mark.asyncio
async def test_tc_heal_02_max_retries_returns_422(async_client, auth_headers):
    # Giả lập LLM liên tục sinh lỗi qua cả 2 vòng retry
    mock_call = AsyncMock(
        side_effect=ValidationError.from_exception_data("Invalid JSON schema structure", line_errors=[])
    )

    with patch.object(intent_parser.openai_client.chat.completions, "create_with_completion", mock_call):
        response = await async_client.post(
            "/api/v1/intents/execute",
            json={"prompt": "Lệnh sinh JSON sai cấu trúc liên tục"},
            headers=auth_headers,
        )

        assert response.status_code == 422
        res_json = response.json()
        assert res_json["status"] == "FAILED"
        assert "Max retries exceeded" in res_json["reason"]


# TC-HEAL-03: Duy trì ngữ cảnh hội thoại trong State Graph (truy xuất đúng intent_id trước đó)
@pytest.mark.asyncio
async def test_tc_heal_03_multi_turn_context_retrieval():
    session_id = f"test_session_{uuid.uuid4()}"

    # Bước 1: Đặt một lệnh Limit Order trước đó
    prev_ir = CryptoExecutionIR(
        action=ActionType.LIMIT_ORDER,
        source_asset="BTC",
        target_asset="USDT",
        amount_type=AmountType.EXACT,
        amount_value=0.1,
        limit_price=60000.0,
    )

    with patch.object(
        intent_parser.openai_client.chat.completions,
        "create_with_completion",
        AsyncMock(return_value=(prev_ir, MockRawResponse())),
    ):
        first_ir, _ = await intent_parser.parse_and_log(
            "Đặt lệnh bán 0.1 BTC giá 60000", session_id=session_id
        )
        assert first_ir is not None
        first_intent_id = first_ir.intent_id

    # Bước 2: Gửi câu lệnh phụ thuộc ngữ cảnh: "Hủy lệnh vừa đặt"
    cancel_ir, log = await intent_parser.parse_and_log("Hủy lệnh vừa đặt", session_id=session_id)

    assert cancel_ir is not None
    assert cancel_ir.action == ActionType.CANCEL_ORDER
    # State memory phải link chính xác intent_id của bước trước
    assert cancel_ir.referenced_intent_id == first_intent_id