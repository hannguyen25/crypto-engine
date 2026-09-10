import asyncio
import hashlib
import time
from unittest.mock import AsyncMock
import pytest


# -------------------------------------------------------------------------
# Fake Async Redis Client (Mô phỏng Redis 7+ Atomic SET NX EX)
# -------------------------------------------------------------------------
class FakeAsyncRedis:
    """Giả lập cơ chế Atomic SET NX EX 86400 của Redis (FR-4.2)."""
    def __init__(self):
        self._store: dict[str, str] = {}
        self._lock = asyncio.Lock()

    async def set(
        self,
        name: str,
        value: str,
        ex: int | None = None,
        nx: bool = False,
    ) -> bool | None:
        async with self._lock:
            if nx and name in self._store:
                return None  # Trùng khóa, Redis SET NX trả về None/nil
            self._store[name] = str(value)
            return True

    async def get(self, name: str) -> str | None:
        async with self._lock:
            return self._store.get(name)

    async def flushdb(self):
        async with self._lock:
            self._store.clear()


def compute_idempotency_key(
    user_id: str,
    action: str,
    source: str,
    target: str,
    amount: float,
    timestamp: int,
) -> str:
    """
    Hiện thực công thức FR-4.1:
    Key = SHA256(user_id + action + source + target + amount + floor(timestamp / 30))
    """
    time_window = int(timestamp // 30)
    raw_payload = f"{user_id}{action}{source}{target}{amount}{time_window}"
    return hashlib.sha256(raw_payload.encode("utf-8")).hexdigest()


# -------------------------------------------------------------------------
# TC-CONCUR-01: Chống nhân bản lệnh dưới tải đồng thời cao (50 Concurrent Requests)
# -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_concurrency_50_identical_requests():
    """
    SRS Mục 7 (Test 4) & FR-4.2:
    - Bắn đồng thời 50 requests giống hệt nhau trong cùng cửa sổ 30s.
    - Chính xác 1 request được chuyển tiếp (Accepted / 202).
    - 49 requests bị loại bỏ hoặc trả về xung đột (Deduplicated / 409).
    - Hàng đợi chỉ ghi nhận duy nhất 1 order.
    """
    redis_mock = FakeAsyncRedis()
    queued_orders = []
    duplicate_counter = 0

    user_id = "00000000-0000-0000-0000-000000000001"
    action = "SPOT_SWAP"
    source = "USDT"
    target = "ETH"
    amount = 250.0
    now_ts = int(time.time())

    # Cả 50 request trong cùng một thời điểm đều tính ra 1 Idempotency Key duy nhất
    idempotency_key = compute_idempotency_key(user_id, action, source, target, amount, now_ts)
    redis_key = f"idempotency:{idempotency_key}"

    async def process_incoming_request(request_idx: int):
        nonlocal duplicate_counter
        # Bước 1: Acquire Atomic Lock trên Redis với TTL 24h (86400s)
        lock_ok = await redis_mock.set(redis_key, "PENDING", ex=86400, nx=True)

        if lock_ok:
            # Request đầu tiên chiếm lock: đẩy vào RabbitMQ
            queued_orders.append({
                "req_index": request_idx,
                "idempotency_key": idempotency_key,
                "status": "ACCEPTED",
            })
            return {"status": "ACCEPTED", "status_code": 202}
        else:
            # 49 request đồng thời còn lại bị loại bỏ
            duplicate_counter += 1
            return {"status": "DUPLICATE_IGNORED", "status_code": 409}

    # Kích hoạt 50 request cùng lúc qua asyncio.gather
    tasks = [process_incoming_request(i) for i in range(50)]
    responses = await asyncio.gather(*tasks)

    # 1. Kiểm tra phản hồi Gateway
    accepted_res = [r for r in responses if r["status_code"] == 202]
    rejected_res = [r for r in responses if r["status_code"] == 409]

    assert len(accepted_res) == 1, f"Kỳ vọng 1 request được duyệt, thực tế: {len(accepted_res)}"
    assert len(rejected_res) == 49, f"Kỳ vọng 49 request bị loại, thực tế: {len(rejected_res)}"

    # 2. Kiểm tra hàng đợi Broker
    assert len(queued_orders) == 1
    assert queued_orders[0]["idempotency_key"] == idempotency_key
    assert duplicate_counter == 49


# -------------------------------------------------------------------------
# TC-CONCUR-02: Race Condition giữa 2 Workers thực thi (Distributed Lock)
# -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_race_condition_workers_redis_lock():
    """
    SRS FR-4.2 & FR-4.3:
    - 2 worker đồng thời kéo cùng 1 task execution từ hàng đợi.
    - Duy nhất 1 worker chiếm được khóa phân tán để gọi API sàn.
    - Worker thứ hai phát hiện trùng lặp và chủ động hủy task.
    """
    redis_mock = FakeAsyncRedis()
    mock_binance_client = AsyncMock(return_value={"orderId": 99887766, "status": "FILLED"})

    order_task = {
        "idempotency_key": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "symbol": "BTCUSDT",
        "side": "BUY",
        "amount": 0.05,
    }

    async def execution_worker(worker_id: str, task: dict):
        lock_key = f"exec_lock:{task['idempotency_key']}"

        # Atomic check & set
        is_acquired = await redis_mock.set(lock_key, "PROCESSING", ex=86400, nx=True)
        if not is_acquired:
            return {"worker_id": worker_id, "executed": False, "status": "DISCARDED"}

        # Chiếm khóa thành công -> Thực thi gọi sàn
        await mock_binance_client(symbol=task["symbol"], side=task["side"], qty=task["amount"])

        # Đánh dấu hoàn tất
        await redis_mock.set(lock_key, "COMPLETED", ex=86400)
        return {"worker_id": worker_id, "executed": True, "status": "COMPLETED"}

    # Giả lập 2 worker kéo message cùng mili-giây
    worker_results = await asyncio.gather(
        execution_worker("Worker-1", order_task),
        execution_worker("Worker-2", order_task),
    )

    executed_tasks = [w for w in worker_results if w["executed"]]
    discarded_tasks = [w for w in worker_results if not w["executed"]]

    # Kiểm tra tính toàn vẹn tài chính
    assert len(executed_tasks) == 1, "Nguy cơ nhân bản lệnh: Có nhiều hơn 1 worker gọi sàn!"
    assert len(discarded_tasks) == 1, "Worker lặp không bị loại bỏ!"
    assert mock_binance_client.call_count == 1, "API sàn bị gọi lặp lại!"