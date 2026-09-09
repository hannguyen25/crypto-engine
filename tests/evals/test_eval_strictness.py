import json
import pytest
from deepeval.test_case import LLMTestCase
from deepeval.metrics import HallucinationMetric
from app.services.intent_engine import parse_intent_to_ir
from app.core.exceptions import AmbiguousIntentException, SelfHealingExhaustedException

with open("tests/evals/datasets/ambiguous_intents_30.json") as f:
    ambiguous_prompts = json.load(f)

hallucination_metric = HallucinationMetric(threshold=0.0)  # Yêu cầu 0% ảo giác

@pytest.mark.asyncio
async def test_schema_strictness_and_no_hallucination():
    for case in ambiguous_prompts:
        prompt = case["prompt"]
        
        try:
            actual_ir = await parse_intent_to_ir(prompt)
            
            # Nếu engine tự ý điền thông số mà người dùng không đề cập (ví dụ tự gán BTC/ETH)
            test_case = LLMTestCase(
                input=prompt,
                actual_output=actual_ir.model_dump_json(),
                context=["The user did not specify the target token, source token, or explicit amount in the prompt."]
            )
            await hallucination_metric.a_measure(test_case)
            
            assert not hallucination_metric.is_successful(), \
                f"Hallucination detected! Engine invented fields for ambiguous prompt: '{prompt}' -> {actual_ir}"
                
        except (AmbiguousIntentException, SelfHealingExhaustedException):
            # Kết quả kỳ vọng: Báo lỗi thiếu dữ kiện, không tự suy diễn
            pass