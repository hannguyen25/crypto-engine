import asyncio
import pytest
from httpx import AsyncClient
from app.core.security import create_access_token


def get_auth_headers(user_id: str):
    token = create_access_token(data={"sub": user_id})
    return {"Authorization": f"Bearer {token}"}


# TC-RATE-01: Chấp thuận lưu lượng trong ngưỡng (10 requests liên tiếp)
@pytest.mark.asyncio
async def test_tc_rate_01_within_threshold(async_client: AsyncClient):
    headers = get_auth_headers("user_rate_01")
    payload = {"prompt": "Swap 100 USDT to SOL"}

    for _ in range(10):
        res = await async_client.post(
            "/api/v1/intents/execute",
            json=payload,
            headers=headers,
        )
        assert res.status_code in [200, 202]


# TC-RATE-02: Chặn vượt ngưỡng (Spike traffic 30 requests đồng thời)
@pytest.mark.asyncio
async def test_tc_rate_02_spike_traffic_rejection(async_client: AsyncClient):
    headers = get_auth_headers("user_rate_02")
    payload = {"prompt": "Swap 50 USDT to BTC"}

    # Bắn liên tiếp nhiều requests để ép cạn bucket
    responses = []
    for _ in range(30):
        res = await async_client.post(
            "/api/v1/intents/execute",
            json=payload,
            headers=headers,
        )
        responses.append(res)

    status_codes = [r.status_code for r in responses]

    # Phải có request thành công và có request bị chặn 429
    assert any(code in [200, 202] for code in status_codes)
    assert 429 in status_codes

    # Kiểm tra header Retry-After ở các response 429 theo chuẩn TC-RATE-02
    rate_limited_res = next(r for r in responses if r.status_code == 429)
    assert "retry-after" in [k.lower() for k in rate_limited_res.headers.keys()]


# TC-RATE-03: Khôi phục hạn mức sau thời gian chờ (Cooldown recovery)
@pytest.mark.asyncio
async def test_tc_rate_03_cooldown_recovery(async_client: AsyncClient):
    headers = get_auth_headers("user_rate_03")
    payload = {"prompt": "Swap 20 USDT to ETH"}

    # 1. Bắn dồn dập đến khi nhận mã 429
    got_429 = False
    for _ in range(30):
        res = await async_client.post(
            "/api/v1/intents/execute",
            json=payload,
            headers=headers,
        )
        if res.status_code == 429:
            got_429 = True
            break

    assert got_429, "Không kích hoạt được rate limit 429"

    # 2. Chờ cooldown để token phục hồi (1 giây)
    await asyncio.sleep(1.2)

    # 3. Gửi request kế tiếp -> phải được xử lý bình thường (200 hoặc 202)
    recovered_res = await async_client.post(
        "/api/v1/intents/execute",
        json=payload,
        headers=headers,
    )
    assert recovered_res.status_code in [200, 202]