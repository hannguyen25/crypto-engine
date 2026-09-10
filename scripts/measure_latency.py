import os
import time
import requests
import jwt
from datetime import datetime, timedelta, timezone
from app.core.config import settings

# Tự sinh token chuẩn theo secret cấu hình
token = jwt.encode(
    {
        "sub": "00000000-0000-0000-0000-111122223333",
        "exp": datetime.now(timezone.utc) + timedelta(days=1),
    },
    settings.JWT_SECRET,
    algorithm="HS256",
)

headers = {
    "Authorization": f"Bearer {token}",
    "X-Benchmark-Mode": "true",
    "Content-Type": "application/json",
}

payload = {
    "prompt": "Giá BTC hiện tại là bao nhiêu?",
    "metadata": {"client_timestamp": 1772859000},
}

session = requests.Session()
url = "http://127.0.0.1:8000/api/v1/intents/execute"

# Warm-up kết nối Keep-Alive
for _ in range(3):
    session.post(url, json=payload, headers=headers)

# Đo latency thực tế qua connection pool
t0 = time.perf_counter()
res = session.post(url, json=payload, headers=headers)
t1 = time.perf_counter()

print(f"HTTP Status: {res.status_code}")
print(f"Actual Server Latency: {(t1 - t0) * 1000:.2f} ms")
print("Response body:", res.json())
