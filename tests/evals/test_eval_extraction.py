import json
import pytest
from deepeval.test_case import LLMTestCase, LLMTestCaseParams
from deepeval.metrics import GEval
from app.services.intent_engine import parse_intent_to_ir  # LangGraph / Instructor call

with open("tests/evals/datasets/crypto_intents_150.json") as f:
    eval_data = json.load(f)

# Metric đánh giá trích xuất chính xác cấu trúc tài chính
extraction_metric = GEval(
    name="CryptoIRExtractionAccuracy",
    criteria="Evaluate whether all numerical fields (amount, price, slippage) and assets strictly match the intended values from the raw user prompt without distortion.",
    evaluation_params=[LLMTestCaseParams.INPUT, LLMTestCaseParams.ACTUAL_OUTPUT, LLMTestCaseParams.EXPECTED_OUTPUT],
    threshold=0.98
)

@pytest.mark.asyncio
async def test_grounding_and_extraction_accuracy():
    passed_count = 0
    total_count = len(eval_data)
    
    for case in eval_data:
        raw_prompt = case["input"]
        expected = case["expected_ir"]
        
        # Gọi engine phân tích
        actual_ir = await parse_intent_to_ir(raw_prompt)
        
        # 1. Kiểm tra Exact Match trên các enum/code bắt buộc
        field_matches = (
            actual_ir.action == expected["action"] and
            actual_ir.source_asset == expected["source_asset"] and
            actual_ir.target_asset == expected["target_asset"] and
            actual_ir.amount_type == expected["amount_type"] and
            abs(actual_ir.amount_value - expected["amount_value"]) < 1e-4
        )
        
        # 2. DeepEval test case run
        test_case = LLMTestCase(
            input=raw_prompt,
            actual_output=actual_ir.model_dump_json(),
            expected_output=json.dumps(expected)
        )
        await extraction_metric.a_measure(test_case)
        
        if field_matches and extraction_metric.is_successful():
            passed_count += 1

    accuracy_rate = passed_count / total_count
    assert accuracy_rate >= 0.98, f"Accuracy rate fell below 98%: {passed_count}/{total_count} ({accuracy_rate:.2%})"
    