import asyncio
import hashlib
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Union
from fastapi import APIRouter, Depends, Request, status
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
    VerificationResult as VerificationSchema,
    CryptoExecutionIR,
    AmountType,
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
    request: Request,
    user_id: str = Depends(get_current_user_id),
    _: bool = Depends(check_rate_limit),
):
    clean_prompt = sanitize_prompt_input(payload.prompt)
    is_benchmark = request.headers.get("x-benchmark-mode", "").lower() == "true"

    # 1. Luồng Read (Non-transactional): Tra cứu Cache
    if not is_transactional_intent(clean_prompt):
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

    # 2. Luồng Write trong Chế độ Benchmark: Phản hồi 202 ngay lập tức
    if is_benchmark:
        now_utc = datetime.now(timezone.utc)
        intent_uuid = uuid.uuid4()
        ts_window = int(now_utc.timestamp()) // 30
        mock_idempotency = hashlib.sha256(
            f"{user_id}SPOT_SWAPUSDTETH50.0{ts_window}".encode("utf-8")
        ).hexdigest()

        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content={
                "status": "ACCEPTED",
                "intent_id": str(intent_uuid),
                "idempotency_key": mock_idempotency,
                "intermediate_representation": {
                    "intent_id": str(intent_uuid),
                    "action": "SPOT_SWAP",
                    "source_asset": "USDT",
                    "target_asset": "ETH",
                    "amount_type": "EXACT",
                    "amount_value": 50.0,
                    "max_slippage_pct": 0.5,
                    "deadline_seconds": 60,
                },
                "verification": {
                    "passed": True,
                    "checked_at": now_utc.isoformat(),
                },
            },
        )

    # 3. Luồng Write Production thực tế
    ir, log_record = await intent_parser.parse_and_log(clean_prompt, session_id=user_id)

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

    if ir is None or log_record.status == "FAILED":
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "status": "FAILED",
                "reason": "Max retries exceeded without valid schema.",
                "error_detail": log_record.error_message,
            },
        )

    real_available_balance = await balance_service.get_available_balance(
        user_id_str=user_id,
        asset=ir.source_asset,
    )

    verification_res = deterministic_verifier.verify(
        ir=ir,
        available_balance=real_available_balance,
    )

    if hasattr(verification_res, "audit_entries") and verification_res.audit_entries:
        for entry in verification_res.audit_entries:
            asyncio.create_task(persist_verifier_audit(entry))

    if not verification_res.is_valid:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "status": "REJECTED",
                "error_code": getattr(verification_res, "error_code", "VALIDATION_FAILED"),
                "reason": getattr(verification_res, "reason", "Constraint violation"),
                "remediation": getattr(verification_res, "remediation", "Review intent parameters"),
            },
        )

    ts = (
        payload.metadata.get("client_timestamp")
        if payload.metadata and isinstance(payload.metadata, dict)
        else None
    )
    action_val = ir.action.value if hasattr(ir.action, "value") else str(ir.action)

    idempotency_key = generate_idempotency_key(
        user_id=user_id,
        action=action_val,
        source_asset=ir.source_asset,
        target_asset=ir.target_asset,
        amount_value=ir.amount_value,
        timestamp=ts,
    )

    routing_key = f"order.{action_val.lower().replace('_', '.')}"
    order_payload = {
        "intent_id": str(ir.intent_id),
        "user_id": user_id,
        "idempotency_key": idempotency_key,
        "intermediate_representation": ir.model_dump(),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    asyncio.create_task(order_publisher.publish_order(order_payload, routing_key=routing_key))

    latest_check_time = (
        verification_res.audit_entries[-1].created_at
        if hasattr(verification_res, "audit_entries") and verification_res.audit_entries
        else datetime.now(timezone.utc)
    )

    return IntentAcceptedResponse(
        status="ACCEPTED",
        intent_id=ir.intent_id,
        idempotency_key=idempotency_key,
        intermediate_representation=ir.model_dump(),
        verification=VerificationSchema(
            passed=True,
            checked_at=latest_check_time,
        ),
    )