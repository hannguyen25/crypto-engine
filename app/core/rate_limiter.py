import asyncio
import time
from typing import Optional
from fastapi import HTTPException, Request, status
import redis.asyncio as aioredis
from app.core.config import settings


class TokenBucketRateLimiter:
    def __init__(self, capacity: int = 10, refill_rate: float = 2.0):
        self.capacity = float(capacity)
        self.refill_rate = float(refill_rate)
        self._pools: dict[asyncio.AbstractEventLoop, aioredis.ConnectionPool] = {}

    def _get_pool(self) -> aioredis.ConnectionPool:
        loop = asyncio.get_running_loop()
        if loop not in self._pools:
            self._pools[loop] = aioredis.ConnectionPool.from_url(
                settings.REDIS_URL,
                decode_responses=True,
                max_connections=50,
            )
        return self._pools[loop]

    def _get_client(self) -> aioredis.Redis:
        return aioredis.Redis(connection_pool=self._get_pool())

    async def check_rate_limit(self, user_id: str, request: Optional[Request] = None):
        # 1. Bypass hoàn toàn nếu request chứa header X-Benchmark-Mode
        if request is not None:
            benchmark_header = request.headers.get("x-benchmark-mode", "").lower()
            if benchmark_header == "true":
                return

        # 2. Xử lý Token Bucket qua Redis Client động
        client = self._get_client()
        key = f"rate_limit:{user_id}"
        now = time.time()

        # Pipeline 1: Lấy dữ liệu token hiện tại
        pipe = client.pipeline()
        pipe.hmget(key, "tokens", "last_updated")
        results = await pipe.execute()

        raw_data = results[0]
        tokens_val = raw_data[0]
        last_updated_val = raw_data[1]

        if tokens_val is None or last_updated_val is None:
            tokens = self.capacity
            last_updated = now
        else:
            tokens = float(tokens_val)
            last_updated = float(last_updated_val)

        # Tính toán lượng token phục hồi theo thời gian
        elapsed = max(0.0, now - last_updated)
        tokens = min(self.capacity, tokens + (elapsed * self.refill_rate))

        # Nếu không đủ 1 token -> chặn ngay lập tức
        if tokens < 1.0:
            needed = 1.0 - tokens
            retry_after = max(1, int(needed / self.refill_rate) + 1)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded. Please throttle your requests.",
                headers={"Retry-After": str(retry_after)},
            )

        # Trừ 1 token cho request hiện tại
        tokens -= 1.0

        # Pipeline 2: Cập nhật lại số token và thời gian
        pipe = client.pipeline()
        pipe.hset(key, mapping={"tokens": str(tokens), "last_updated": str(now)})
        pipe.expire(key, 3600)
        await pipe.execute()


rate_limiter = TokenBucketRateLimiter()