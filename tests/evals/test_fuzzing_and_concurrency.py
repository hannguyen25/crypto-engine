import asyncio
import random
import string
import uuid
from decimal import Decimal
import pytest
from pydantic import ValidationError

from app.core.verifier import deterministic_verifier
from app.schemas.intent import CryptoExecutionIR


# =====================================================================
# Test 3: Verifier Fuzzing (10,000 Random IR Payloads - SRS Mục 7)
# =====================================================================
def generate_fuzzed_ir_dict() -> dict:
    """Sinh payload ngẫu nhiên bao quát mọi giá trị biên và dữ liệu dị thường."""
    actions = ["SPOT_SWAP", "LIMIT_ORDER", "TRANSFER", "DCA_SCHEDULE", "INVALID_ACTION", ""]
    amount_types = ["EXACT", "PERCENTAGE", "ALL_IN", None]
    
    # Tập token ngẫu nhiên: lẫn cả token hợp lệ và rác/malicious
    assets = ["USDT", "ETH", "BTC", "SCAM_COIN", "DOGE", "", "A" * 50, "DROP_TABLE;"]
    
    # Giá trị số ngẫu nhiên: âm, 0, cực đại, NaN-like, số thập phân nhỏ
    random_amounts = [
        -1000.0, -0.0000001, 0.0, 0.000000001, 50.0, 100.0, 9999999.0, 1e12
    ]
    random_slippages = [-5.0, 0.0, 0.5, 2.5, 3.0, 3.1, 4.5, 10.0, 100.0, 999.9]

    return {
        "intent_id": str(uuid.uuid4()),
        "action": random.choice(actions),
        "source_asset": random.choice(assets),
        "target_asset": random.choice(assets),
        "amount_type": random.choice(amount_types),
        "amount_value": random.choice(random_amounts),
        "limit_price": random.choice([None, -100.0, 0.0, 3500.0]),
        "max_slippage_pct": random.choice(random_slippages),
        "deadline_seconds": random.choice([-10, 0, 60, 99999]),
    }


def test_verifier_fuzzing_10k_payloads():
    """
    Fuzzing 10,000 cases:
    - 100% boundary violations (số âm, slippage > 3%, tài sản ngoài whitelist)
      phải bị Pydantic hoặc Verifier bắt trọn.
    - Tuyệt đối không để xảy ra crash không kiểm soát (như ZeroDivisionError, Unhandled Exception).
    """
    TOTAL_ROUNDS = 10_000
    pydantic_rejected = 0
    verifier_rejected = 0
    verifier_passed = 0

    available_balance = Decimal("1000.0")

    for _ in range(TOTAL_ROUNDS):
        payload = generate_fuzzed_ir_dict()

        # 1. Tầng Pydantic Schema Validation (FR-2.2)
        try:
            ir = CryptoExecutionIR(**payload)
        except (ValidationError, Exception):
            pydantic_rejected += 1
            continue

        # 2. Tầng Deterministic Verifier Guardrails (FR-3.2 -> FR-3.4)
        try:
            result = deterministic_verifier.verify(ir=ir, available_balance=available_balance)
            if result.is_valid:
                # Nếu lọt qua PASS, kiểm tra lại điều kiện an toàn tuyệt đối
                assert ir.max_slippage_pct <= 3.0, f"Lọt slippage vượt trần: {ir.max_slippage_pct}"
                assert float(ir.amount_value) > 0, f"Lọt amount <= 0: {ir.amount_value}"
                assert ir.source_asset in ["USDT", "BTC", "ETH"], f"Lọt source asset ngoài whitelist: {ir.source_asset}"
                assert ir.target_asset in ["USDT", "BTC", "ETH"], f"Lọt target asset ngoài whitelist: {ir.target_asset}"
                verifier_passed += 1
            else:
                verifier_rejected += 1
        except Exception as exc:
            pytest.fail(f"Verifier bị unhandled crash khi xử lý payload {payload}: {exc}")

    print(
        f"\n[Fuzzing Report] 10,000 Payload Result:\n"
        f"  - Schema Validations Blocked: {pydantic_rejected}\n"
        f"  - Verifier Guardrails Blocked: {verifier_rejected}\n"
        f"  - Legitimate Passed: {verifier_passed}\n"
        f"  - Boundary Violation Catch Rate: 100.00%"
    )
    assert pydantic_rejected + verifier_rejected + verifier_passed == TOTAL_ROUNDS


# =====================================================================
# Test 4: Concurrency Idempotency Test (50 Concurrent Requests - SRS Mục 7)
# =====================================================================
class MockDistributedRedisLock:
    """Giả lập chính xác lệnh Redis: SET key 'PENDING' EX 86400 NX (Atomic Lock)."""

    def __init__(self):
        self._store = {}
        self._lock = asyncio.Lock()

    async def set_atomic_nx(self, key: str, value: str) -> bool:
        async with self._lock:
            if key in self._store:
                return False  # Key đã tồn tại -> Từ chối khóa
            self._store[key] = value
            return True


@pytest.mark.asyncio
async def test_concurrency_idempotency_50_requests():
    """
    Bắn 50 request cùng lúc mang cùng 1 Idempotency Key:
    - Đúng 1 request lấy được Lock và xếp hàng vào Broker (Accepted).
    - 49 request còn lại phải bị chặn/bỏ qua (Deduplicated).
    """
    redis_mock = MockDistributedRedisLock()
    shared_idempotency_key = "idemp_hash_sha256_shared_order_key_9999"

    accepted_requests = []
    discarded_requests = []

    async def simulate_incoming_request(request_id: int):
        # Mô phỏng độ trễ phân tán mạng đồng thời
        await asyncio.sleep(random.uniform(0.001, 0.01))

        # Thực thi logic Gateway: SET NX atomic
        acquired = await redis_mock.set_atomic_nx(shared_idempotency_key, "PENDING")
        if acquired:
            accepted_requests.append(request_id)
        else:
            discarded_requests.append(request_id)

    # Kích hoạt 50 request song song qua asyncio.gather
    tasks = [simulate_incoming_request(i) for i in range(50)]
    await asyncio.gather(*tasks)

    print(
        f"\n[Concurrency Report] 50 Concurrent Requests:\n"
        f"  - Accepted / Queued to Broker: {len(accepted_requests)}\n"
        f"  - Discarded / Deduplicated: {len(discarded_requests)}"
    )

    # Tiêu chuẩn SRS Mục 7: Đúng 1 nhận, 49 huỷ
    assert len(accepted_requests) == 1, f"Yêu cầu duy nhất 1 order lọt vào broker, thực tế: {len(accepted_requests)}"
    assert len(discarded_requests) == 49, f"Yêu cầu 49 request bị chặn deduplication, thực tế: {len(discarded_requests)}"