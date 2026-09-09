import time
import asyncio
import pytest
from unittest.mock import AsyncMock, patch
from app.services.intent_logger import intent_db_logger
from app.schemas.intent import CryptoExecutionIR, ActionType, AmountType


class MockUsage:
    prompt_tokens = 55
    completion_tokens = 35


class MockRawResponse:
    usage = MockUsage()


# TC-LOG-01: Ghi nhận đầy đủ thông số truy vấn vào intent_logs
@pytest.mark.asyncio
async def test_tc_log_01_record_full_observability_metrics(async_client, auth_headers):
    intent_db_logger.logs.clear()

    mock_ir = CryptoExecutionIR(
        action=ActionType.SPOT_SWAP,
        source_asset="ETH",
        target_asset="USDT",
        amount_type=AmountType.EXACT,
        amount_value=2.0,
    )

    from app.core.llm_parser import intent_parser

    with patch.object(
        intent_parser.openai_client.chat.completions,
        "create_with_completion",
        AsyncMock(return_value=(mock_ir, MockRawResponse())),
    ):
        prompt = "Swap 2 ETH sang USDT"
        response = await async_client.post(
            "/api/v1/intents/execute",
            json={"prompt": prompt},
            headers=auth_headers,
        )

        assert response.status_code == 202
        assert len(intent_db_logger.logs) == 1

        db_row = intent_db_logger.logs[0]
        # Kiểm tra đầy đủ các trường yêu cầu
        assert db_row["raw_prompt"] == prompt
        assert isinstance(db_row["parsed_ir"], dict)  # Chuẩn JSONB
        assert db_row["parsed_ir"]["source_asset"] == "ETH"
        assert db_row["parsed_ir"]["target_asset"] == "USDT"
        assert db_row["model_name"] in ["gpt-4o", "gpt-4o-mini"]
        assert db_row["prompt_tokens"] > 0
        assert db_row["completion_tokens"] > 0
        assert db_row["latency_ms"] > 0


# TC-LOG-01: Ghi nhận đầy đủ thông số truy vấn vào intent_logs
@pytest.mark.asyncio
async def test_tc_log_01_record_full_observability_metrics(async_client, auth_headers):
    intent_db_logger.logs.clear()

    mock_ir = CryptoExecutionIR(
        action=ActionType.SPOT_SWAP,
        source_asset="ETH",
        target_asset="USDT",
        amount_type=AmountType.EXACT,
        amount_value=2.0,
    )

    from app.core.llm_parser import intent_parser

    with patch.object(
        intent_parser.openai_client.chat.completions,
        "create_with_completion",
        AsyncMock(return_value=(mock_ir, MockRawResponse())),
    ):
        prompt = "Swap 2 ETH sang USDT"
        response = await async_client.post(
            "/api/v1/intents/execute",
            json={"prompt": prompt},
            headers=auth_headers,
        )

        assert response.status_code == 202

        # Chờ micro-task của asyncio.create_task hoàn thành
        await asyncio.sleep(0.05)

        assert len(intent_db_logger.logs) == 1

        db_row = intent_db_logger.logs[0]
        # Kiểm tra đầy đủ các trường yêu cầu
        assert db_row["raw_prompt"] == prompt
        assert isinstance(db_row["parsed_ir"], dict)  # Chuẩn JSONB
        assert db_row["parsed_ir"]["source_asset"] == "ETH"
        assert db_row["parsed_ir"]["target_asset"] == "USDT"
        assert db_row["model_name"] in ["gpt-4o", "gpt-4o-mini"]
        assert db_row["prompt_tokens"] > 0
        assert db_row["completion_tokens"] > 0
        assert db_row["latency_ms"] > 0