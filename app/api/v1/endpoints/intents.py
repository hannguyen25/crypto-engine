
import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Union
from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse

from app.api.deps import get_current_user_id, check_rate_limit
from app.core.sanitizer import sanitize_prompt_input
from app.core.semantic_router import semantic_cache
from app.core.llm_parser import intent_parser
from app.core.verifier import deterministic_verifier
from app.core.idempotency import generate_idempotency_key
from app.services.intent_logger import intent_db_logger
from app.services.balance_service import balance_service
from app.services.verifier_logger import persist_verifier_audit
from app.services.order_publisher import order_publisher
from app.schemas.intent import (
    IntentExecuteRequest,
    IntentAcceptedResponse,
    CachedQueryResponse,
    VerificationResult,
)

logger = logging.getLogger(__name__)
router = APIRouter()

TRANSACTIONAL_PATTERN = re.compile(
    r"\b(mua|bán|swap|transfer|gửi|chuyển|trade|long|short)\b", re.IGNORECASE
)


def is_transactional_intent(prompt: str) -> bool:
    return bool(TRANSACTIONAL_PATTERN.search(prompt))


@router.post(
    "/execute",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=Union[IntentAcceptedResponse, CachedQueryResponse],
)
async def submit_intent(
    payload: IntentExecuteRequest,
    user_id: str = Depends(get_current_user_id),
    _: bool = Depends(check_rate_limit),
):
    # 1. Khử độc input (NFR-2.3)
    clean_prompt = sanitize_prompt_input(payload.prompt)

    # 2. Quy tắc FR-1.2.2: Bỏ qua cache với Transactional Intent (TC-SEM-03)
    if not is_transactional_intent(clean_prompt):
        # 3. Tra cứu cache kèm cơ chế Graceful Degradation (FR-1.2.1, TC-SEM-01, TC-SEM-04)
        try:
            cached_result = await semantic_cache.query_cache(clean_prompt)
            if cached_result is not None:
                return JSONResponse(
                    status_code=status.HTTP_200_OK,
                    content={
                        "status": "CACHE_HIT",
                        "similarity_score": round(cached_result["score"], 4),
                        "matched_prompt": cached_result["cached_prompt"],
                        "data": cached_result["response"],
                    },
                )
        except Exception as exc:
            logger.warning(f"[Graceful Degradation] Vector DB tra cứu thất bại: {exc}")

    # 4. Pipeline Parsing với Self-Healing qua LangGraph & Context Tracking (FR-2.1 -> FR-2.3)
    ir, log_record = await intent_parser.parse_and_log(clean_prompt, session_id=user_id)

    # 5. Non-blocking Task qua asyncio.create_task lưu intent_logs (TC-LOG-01, TC-LOG-02)
    model_name = "gpt-4o" if log_record.model_tier == "LLM" else "gpt-4o-mini"
    asyncio.create_task(
        intent_db_logger.save_intent_log(
            raw_prompt=clean_prompt,
            parsed_ir=ir,
            model_name=model_name,
            prompt_tokens=log_record.prompt_tokens,
            completion_tokens=log_record.completion_tokens,
            latency_ms=log_record.latency_ms,
        )
    )

    # TC-HEAL-02: Dừng vòng lặp và trả về 422 khi LLM parse lỗi vượt quá max retries
    if ir is None or log_record.status == "FAILED":
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "status": "FAILED",
                "reason": "Max retries exceeded without valid schema.",
                "error_detail": log_record.error_message,
            },
        )

    # 6. Truy vấn số dư THỰC TẾ từ PostgreSQL qua BalanceService (FR-3.2)
    real_available_balance = await balance_service.get_available_balance(
        user_id_str=user_id,
        asset=ir.source_asset,
    )

    # 7. Thẩm định tất định qua Deterministic Verifier (FR-3.1 -> FR-3.5)
    verification_res = deterministic_verifier.verify(
        ir=ir,
        available_balance=real_available_balance,
    )

    # Ghi audit trail bất đồng bộ vào bảng verifier_audit_trail (FR-3.5)
    for entry in verification_res.audit_entries:
        asyncio.create_task(persist_verifier_audit(entry))

    # Nếu vi phạm guardrail (Whitelist, Slippage > 3%, Thiếu balance) -> Trả về 422 theo SRS Mục 5.1
    if not verification_res.is_valid:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "status": "REJECTED",
                "error_code": verification_res.error_code,
                "reason": verification_res.reason,
                "remediation": verification_res.remediation,
            },
        )

    # 8. Sinh Idempotency Key chuẩn SRS FR-4.1 (sử dụng module chung)
    idempotency_key = generate_idempotency_key(
        user_id=user_id,
        action=ir.action.value if hasattr(ir.action, "value") else str(ir.action),
        source_asset=ir.source_asset,
        target_asset=ir.target_asset,
        amount_value=ir.amount_value,
    )

    # 9. Đẩy Verified Order Payload vào RabbitMQ Exchange (FR-4.1)
    action_str = ir.action.value if hasattr(ir.action, "value") else str(ir.action)
    routing_key = f"order.{action_str.lower().replace('_', '.')}"
    
    order_payload = {
        "intent_id": str(ir.intent_id),
        "user_id": user_id,
        "idempotency_key": idempotency_key,
        "intermediate_representation": ir.model_dump(),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    
    # Non-blocking publish order vào RabbitMQ
    asyncio.create_task(order_publisher.publish_order(order_payload, routing_key=routing_key))

    # 10. Phản hồi 202 Accepted chuẩn SRS Mục 5.1
    latest_check_time = (
        verification_res.audit_entries[-1].created_at
        if verification_res.audit_entries
        else datetime.now(timezone.utc)
    )

    return IntentAcceptedResponse(
        status="ACCEPTED",
        intent_id=ir.intent_id,
        idempotency_key=idempotency_key,
        intermediate_representation=ir.model_dump(),
        verification=VerificationResult(
            passed=True,
            checked_at=latest_check_time,
        ),
    )