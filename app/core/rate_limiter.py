import time
from fastapi import HTTPException, status
import redis.asyncio as aioredis
from app.core.config import settings


class TokenBucketRateLimiter:
    def __init__(self, capacity: int = 10, refill_rate: float = 2.0):
        self.capacity = float(capacity)        # Số token tối đa
        self.refill_rate = float(refill_rate)  # Token hồi phục mỗi giây

    async def check_rate_limit(self, user_id: str):
        # Tạo client gắn theo event loop đang active của request/test case hiện tại
        client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        try:
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
            pipe.expire(key, 3600)  # Giữ key 1 giờ
            await pipe.execute()

        finally:
            # Đóng connection để giải phóng socket trên Windows EventLoop
            await client.aclose()