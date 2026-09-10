import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.core.llm_parser import intent_parser
from app.schemas.intent import CryptoExecutionIR, ActionType, AmountType


# 1. Kiểm tra bộ phân luồng định tuyến SLM vs LLM
@pytest.mark.asyncio
async def test_routing_classifier():
    # Prompt đơn giản -> định tuyến tới SLM
    simple_prompt = "Swap 100 USDT to ETH"
    decision_simple = await intent_parser.graph.nodes["classify_intent"].ainvoke({"prompt": simple_prompt})
    assert decision_simple["model_tier"] == "SLM"
    assert decision_simple["is_complex"] is False

    # Prompt phức tạp (có điều kiện DCA / stop-loss) -> định tuyến tới LLM
    complex_prompt = "DCA 50 USDT to SOL every 4 hours if price drops below 120"
    decision_complex = await intent_parser.graph.nodes["classify_intent"].ainvoke({"prompt": complex_prompt})
    assert decision_complex["model_tier"] == "LLM"
    assert decision_complex["is_complex"] is True


# 2. Kiểm tra Pydantic IR Validators
def test_pydantic_ir_validators():
    # Trường hợp hợp lệ: tự động strip và uppercase
    valid_ir = CryptoExecutionIR(
        action=ActionType.SPOT_SWAP,
        source_asset="usdt ",
        target_asset="sol",
        amount_type=AmountType.PERCENTAGE,
        amount_value=50.0,
        max_slippage_pct=1.5,
    )
    assert valid_ir.source_asset == "USDT"
    assert valid_ir.target_asset == "SOL"

    # Trường hợp vi phạm: Phần trăm > 100%
    with pytest.raises(ValueError, match="vượt quá 100%"):
        CryptoExecutionIR(
            action=ActionType.SPOT_SWAP,
            source_asset="USDT",
            target_asset="BTC",
            amount_type=AmountType.PERCENTAGE,
            amount_value=120.0,
        )

    # Trường hợp vi phạm: Slippage vượt trần 5.0%
    with pytest.raises(ValueError):
        CryptoExecutionIR(
            action=ActionType.SPOT_SWAP,
            source_asset="USDT",
            target_asset="BTC",
            amount_value=100.0,
            max_slippage_pct=6.5,
        )


# 3. Mock test chu trình chạy qua LangGraph
@pytest.mark.asyncio
async def test_intent_graph_execution_mock():
    mock_ir = CryptoExecutionIR(
        action=ActionType.SPOT_SWAP,
        source_asset="USDT",
        target_asset="ETH",
        amount_type=AmountType.EXACT,
        amount_value=250.0,
    )

    fake_raw = MagicMock()
    fake_raw.usage = MagicMock(prompt_tokens=10, completion_tokens=20)

    with patch.object(
        intent_parser.openai_client.chat.completions,
        "create_with_completion",
        new_callable=AsyncMock,
    ) as mock_create_comp, patch.object(
        intent_parser.openai_client.chat.completions,
        "create",
        new_callable=AsyncMock,
    ) as mock_create:
        mock_create_comp.return_value = (mock_ir, fake_raw)
        mock_create.return_value = mock_ir

        result = await intent_parser.parse("Swap 250 USDT to ETH")
        
        ir = result["intermediate_representation"] if isinstance(result, dict) else result
        assert ir is not None
        assert ir.source_asset == "USDT"
        assert ir.target_asset == "ETH"
        assert ir.amount_value == 250.0