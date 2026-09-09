import re
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Dict, Any, Union
from pydantic import BaseModel, Field, field_validator, ConfigDict

TOKEN_REGEX = re.compile(r"^[A-Z0-9]{2,10}$")

# Enums cho Intent
class ActionType(str, Enum):
    SPOT_SWAP = "SPOT_SWAP"
    LIMIT_ORDER = "LIMIT_ORDER"
    TRANSFER = "TRANSFER"


class AmountType(str, Enum):
    EXACT = "EXACT"
    PERCENTAGE = "PERCENTAGE"


# 1. API Request Model
class IntentExecuteRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=1000, description="Câu lệnh tự nhiên của người dùng")


# 2. Intermediate Representation (IR) & Validators
class CryptoExecutionIR(BaseModel):
    action: ActionType
    source_asset: str = Field(description="Mã token nguồn")
    target_asset: str = Field(description="Mã token đích")
    amount_type: AmountType = Field(default=AmountType.EXACT)
    amount_value: float = Field(gt=0, description="Giá trị giao dịch, tối thiểu > 0")
    limit_price: Optional[float] = Field(default=None, gt=0)
    max_slippage_pct: float = Field(default=1.0, ge=0.01, le=5.0)
    deadline_seconds: int = Field(default=60, ge=10, le=3600)

    @field_validator("source_asset", "target_asset")
    @classmethod
    def validate_token_symbol(cls, v: str) -> str:
        symbol = v.strip().upper()
        if not TOKEN_REGEX.match(symbol):
            raise ValueError(f"Mã token vi phạm regex ^[A-Z0-9]{{2,10}}$: {v}")
        return symbol

    @field_validator("amount_value")
    @classmethod
    def validate_amount_percentage(cls, v: float, info) -> float:
        if info.data.get("amount_type") == AmountType.PERCENTAGE and v > 100.0:
            raise ValueError("Phần trăm giao dịch không thể vượt quá 100%")
        return v

# 3. Verification & API Response Models
class VerificationResult(BaseModel):
    passed: bool = True
    checked_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class IntentAcceptedResponse(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    status: str = "ACCEPTED"
    intent_id: uuid.UUID
    idempotency_key: str
    intermediate_representation: Union[CryptoExecutionIR, Dict[str, Any]]
    verification: VerificationResult

class IntentRejectedResponse(BaseModel):
    status: str = "REJECTED"
    reason: str
    rejected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class CachedQueryResponse(BaseModel):
    status: str = "CACHE_HIT"
    similarity_score: float
    matched_prompt: str
    data: Dict[str, Any]


# Bổ sung vào cuối app/schemas/intent.py
class IntentLogRecord(BaseModel):
    intent_id: uuid.UUID
    prompt: str
    model_tier: str
    retry_count: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency_ms: float
    status: str  # SUCCESS, HEALED, FAILED
    error_message: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class ActionType(str, Enum):
    SPOT_SWAP = "SPOT_SWAP"
    LIMIT_ORDER = "LIMIT_ORDER"
    TRANSFER = "TRANSFER"
    CANCEL_ORDER = "CANCEL_ORDER"

class CryptoExecutionIR(BaseModel):
    intent_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    referenced_intent_id: Optional[uuid.UUID] = Field(
        default=None, description="ID của intent trước đó nếu là lệnh liên quan (ví dụ hủy lệnh)"
    )
    action: ActionType
    source_asset: Optional[str] = Field(default="N/A", description="Mã token nguồn")
    target_asset: Optional[str] = Field(default="N/A", description="Mã token đích")
    amount_type: AmountType = Field(default=AmountType.EXACT)
    amount_value: Optional[float] = Field(default=None, gt=0)
    limit_price: Optional[float] = Field(default=None, gt=0)
    max_slippage_pct: float = Field(default=1.0, ge=0.01, le=5.0)
    deadline_seconds: int = Field(default=60, ge=10, le=3600)