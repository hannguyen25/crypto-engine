import asyncio
import logging
from typing import Optional, Dict, Any
from pydantic import BaseModel
from app.schemas.intent import IntentLogRecord, CryptoExecutionIR

logger = logging.getLogger(__name__)


class IntentDBLogger:
    def __init__(self):
        # In-memory storage mô phỏng bảng intent_logs phục vụ unit/integration tests
        self.logs: list[Dict[str, Any]] = []

    async def save_intent_log(
        self,
        raw_prompt: str,
        parsed_ir: Optional[CryptoExecutionIR],
        model_name: str,
        prompt_tokens: int,
        completion_tokens: int,
        latency_ms: float,
    ) -> Dict[str, Any]:
        """Tác vụ chạy ngầm lưu intent log vào database."""
        # Chuyển parsed_ir sang dict (tương đương định dạng JSONB)
        ir_jsonb = parsed_ir.model_dump(mode="json") if parsed_ir else None

        record = {
            "raw_prompt": raw_prompt,
            "parsed_ir": ir_jsonb,
            "model_name": model_name,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "latency_ms": latency_ms,
        }
        self.logs.append(record)
        logger.info(f"[Audit] Ghi nhận log intent thành công: {model_name} | {latency_ms}ms")
        return record


intent_db_logger = IntentDBLogger()