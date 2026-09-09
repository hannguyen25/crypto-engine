import time
import pytest
from unittest.mock import patch
from app.core.semantic_router import semantic_cache


@pytest.fixture(autouse=True)
async def setup_cache():
    await semantic_cache.init_collection()
    # Dọn dẹp collection trước mỗi lần test
    try:
        await semantic_cache.client.delete_collection(semantic_cache.COLLECTION_NAME)
        await semantic_cache.init_collection()
    except Exception:
        pass


# TC-SEM-01: Cache Hit cho Query Intent tương đồng cao (Cosine >= 0.96)
@pytest.mark.asyncio
async def test_tc_sem_01_cache_hit_high_similarity(async_client, auth_headers):
    original_prompt = "Giá BTC hiện tại là bao nhiêu?"
    cached_data = {"action": "READ_PRICE", "symbol": "BTC", "price_usd": 68500.0}

    # 1. Nạp cache ban đầu
    await semantic_cache.set_cache(original_prompt, cached_data)

    # 2. Warm-up model embedding để loại bỏ cold start của ONNX Runtime
    _ = list(semantic_cache.embed_model.embed(["warmup"]))

    new_prompt = "Giá BTC hiện tại là bao nhiêu"

    # 3. Đo đạc thời gian thực tế
    start_time = time.perf_counter()
    response = await async_client.post(
        "/api/v1/intents/execute",
        json={"prompt": new_prompt},
        headers=auth_headers,
    )
    latency_ms = (time.perf_counter() - start_time) * 1000

    assert response.status_code == 200
    res_json = response.json()
    assert res_json["status"] == "CACHE_HIT"
    assert res_json["similarity_score"] >= 0.96
    assert res_json["data"]["price_usd"] == 68500.0
    assert latency_ms < 100.0, f"Độ trễ vượt quá 100ms: {latency_ms:.2f}ms"

# TC-SEM-02: Cache Miss do độ tương đồng dưới ngưỡng (< 0.96)
@pytest.mark.asyncio
async def test_tc_sem_02_cache_miss_low_similarity(async_client, auth_headers):
    # Đưa vào cache câu hỏi giá BTC
    await semantic_cache.set_cache(
        "Giá BTC hiện tại là bao nhiêu?",
        {"action": "READ_PRICE", "symbol": "BTC", "price": 68500.0}
    )

    # Gửi câu hỏi chung chung về thị trường
    response = await async_client.post(
        "/api/v1/intents/execute",
        json={"prompt": "Tình hình thị trường tiền ảo hôm nay ra sao?"},
        headers=auth_headers,
    )

    # Phải trả về 202 Accepted (chuyển tiếp sang pipeline/LLM)
    assert response.status_code == 202
    assert response.json()["status"] == "ACCEPTED"


# TC-SEM-03: Bỏ qua Cache với Transactional Intent (FR-1.2.2)
@pytest.mark.asyncio
async def test_tc_sem_03_bypass_cache_for_transactional_intent(async_client, auth_headers):
    # Giả lập prompt giao dịch đã từng được lưu trong cache
    tx_prompt = "Mua 500 USDT ETH"
    await semantic_cache.set_cache(
        tx_prompt,
        {"action": "MOCK_CACHED_TRANSACTION"}
    )

    # Gửi lại đúng prompt giao dịch đó
    response = await async_client.post(
        "/api/v1/intents/execute",
        json={"prompt": tx_prompt},
        headers=auth_headers,
    )

    # Hệ thống phải bỏ qua cache, chuyển thẳng tới pipeline và trả 202 Accepted
    assert response.status_code == 202
    res_json = response.json()
    assert res_json["status"] == "ACCEPTED"
    assert "intermediate_representation" in res_json


# TC-SEM-04: Xử lý lỗi kết nối Vector DB (Graceful Degradation)
@pytest.mark.asyncio
async def test_tc_sem_04_graceful_degradation_vector_down(async_client, auth_headers, caplog):
    # Mock hàm query_cache ném ngoại lệ mô phỏng Qdrant sập mạng/timeout
    with patch.object(semantic_cache, "query_cache", side_effect=Exception("Qdrant Connection Timeout")):
        response = await async_client.post(
            "/api/v1/intents/execute",
            json={"prompt": "Kiểm tra giá ETH hôm nay"},
            headers=auth_headers,
        )

        # API không sập (không trả 500), fallback sang pipeline trả 202 Accepted
        assert response.status_code == 202
        assert response.json()["status"] == "ACCEPTED"
        # Ghi nhận log cảnh báo
        assert any("Graceful Degradation" in record.message for record in caplog.records)