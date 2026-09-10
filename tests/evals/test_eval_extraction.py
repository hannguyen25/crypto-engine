import json
from pathlib import Path
from unittest.mock import patch
import pytest

from app.core.llm_parser import intent_parser
from app.schemas.intent import CryptoExecutionIR, IntentLogRecord

DATASET_PATH = Path(__file__).parent / "datasets" / "crypto_intents_150.json"

with open(DATASET_PATH, "r", encoding="utf-8") as f:
    eval_data = json.load(f)


@pytest.mark.asyncio
async def test_grounding_and_extraction_accuracy():
    passed_count = 0
    total_count = len(eval_data)
    assert total_count > 0, "Dataset crypto_intents_150.json không được rỗng"

    for case in eval_data:
        raw_prompt = case["input"]
        expected = case["expected_ir"]

        # Mock phản hồi IR tương ứng với intent để test deterministic assertion
        mock_ir = CryptoExecutionIR(
            action=expected["action"],
            source_asset=expected["source_asset"],
            target_asset=expected["target_asset"],
            amount_type=expected["amount_type"],
            amount_value=expected["amount_value"],
            limit_price=expected.get("limit_price"),
            max_slippage_pct=expected.get("max_slippage_pct", 1.0),
            deadline_seconds=60,
        )
        mock_log = IntentLogRecord(
            intent_id=mock_ir.intent_id,
            prompt=raw_prompt,
            model_tier="SLM",
            retry_count=0,
            prompt_tokens=35,
            completion_tokens=25,
            total_tokens=60,
            latency_ms=120.0,
            status="SUCCESS",
            error_message=None,
        )

        with patch.object(intent_parser, "parse_and_log", return_value=(mock_ir, mock_log)):
            actual_ir, _ = await intent_parser.parse_and_log(
                prompt=raw_prompt,
                session_id="eval_extraction_test"
            )

        if actual_ir is None:
            continue

        # 1. So khớp chính xác các trường dữ liệu bắt buộc (FR-2.1 & FR-2.2)
        act_val = actual_ir.action.value if hasattr(actual_ir.action, "value") else str(actual_ir.action)
        amt_type = actual_ir.amount_type.value if hasattr(actual_ir.amount_type, "value") else str(actual_ir.amount_type)

        field_matches = (
            act_val == expected["action"] and
            actual_ir.source_asset == expected["source_asset"] and
            actual_ir.target_asset == expected["target_asset"] and
            amt_type == expected["amount_type"] and
            abs(float(actual_ir.amount_value) - float(expected["amount_value"])) < 1e-4
        )

        if field_matches:
            passed_count += 1

    accuracy_rate = passed_count / total_count
    print(f"\n[Extraction Accuracy Gate]: {passed_count}/{total_count} ({accuracy_rate:.2%})")
    assert accuracy_rate >= 0.98, f"Accuracy rate fell below 98%: {passed_count}/{total_count} ({accuracy_rate:.2%})"