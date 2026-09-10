import os
import random
import time
from datetime import datetime, timedelta, timezone
import jwt
from locust import HttpUser, between, task
from app.core.config import settings

# Lấy secret để tự sinh token động cho từng user
JWT_SECRET = settings.JWT_SECRET
READ_PROMPTS = [
    "Giá BTC hiện tại là bao nhiêu?",
    "Cho tôi biết giá Bitcoin hôm nay",
    "Tỷ giá BTC/USDT hiện tại",
    "Bitcoin đang có giá bao nhiêu?",
]

TRANSACTION_PROMPTS = [
    "Mua 50 USDT ETH bằng lệnh thị trường",
    "Bán 10% BTC sang USDT ngay lập tức",
    "Swap 100 USDT sang SOL với slippage 0.5%",
    "Mua 20% số USDT trong ví bằng lệnh thị trường khi ETH vượt 3600",
]


class CryptoEngineUser(HttpUser):
    wait_time = between(0.01, 0.05)

    def on_start(self):
        # Mỗi user ảo nhận 1 UUID giả lập riêng
        user_uuid = f"00000000-0000-0000-0000-{random.randint(100000000000, 999999999999)}"
        token = jwt.encode(
            {
                "sub": user_uuid,
                "exp": datetime.now(timezone.utc) + timedelta(days=1),
            },
            JWT_SECRET,
            algorithm="HS256",
        )
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-Benchmark-Mode": "true",
        }

    @task(7)
    def test_semantic_cache_query(self):
        payload = {
            "prompt": random.choice(READ_PROMPTS),
            "metadata": {"client_timestamp": int(time.time())},
        }

        with self.client.post(
            "/api/v1/intents/execute",
            json=payload,
            headers=self.headers,
            name="[Read] Semantic Cache",
            catch_response=True,
        ) as response:
            # 200 (Cache Hit) hoặc 422 (Cache Miss không thể parse IR) đều là hành vi gateway hợp lệ
            if response.status_code in [200, 422]:
                response.success()
            else:
                response.failure(f"HTTP_{response.status_code}")

    @task(3)
    def test_transactional_intent_pipeline(self):
        payload = {
            "prompt": random.choice(TRANSACTION_PROMPTS),
            "metadata": {"client_timestamp": int(time.time())},
        }

        with self.client.post(
            "/api/v1/intents/execute",
            json=payload,
            headers=self.headers,
            name="[Write] Intent-to-Verify",
            catch_response=True,
        ) as response:
            if response.status_code in [200, 202, 422]:
                response.success()
            else:
                response.failure(f"HTTP_{response.status_code}")