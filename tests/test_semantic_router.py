import time
import pytest
from app.core.semantic_router import semantic_cache


@pytest.mark.asyncio
async def test_semantic_cache_hit_and_miss():
    await semantic_cache.init_collection()
    # Dọn dẹp collection trước khi test
    try:
        await semantic_cache.client.delete_collection(semantic_cache.COLLECTION_NAME)
        await semantic_cache.init_collection()
    except Exception:
        pass

    base_prompt = "What is the current market price of Bitcoin?"
    mock_response = {"action": "READ_PRICE", "asset": "BTC", "price_usd": 68500.0}

    # 1. Cache Miss khi chưa có dữ liệu
    miss_result = await semantic_cache.query_cache(base_prompt)
    assert miss_result is None

    # 2. Lưu vào Cache
    await semantic_cache.set_cache(base_prompt, mock_response)

    # 3. Cache Hit (Cosine >= 0.96)
    hit_result = await semantic_cache.query_cache("What is the current market price of Bitcoin?")
    assert hit_result is not None
    assert hit_result["hit"] is True
    assert hit_result["score"] >= 0.96
    assert hit_result["response"]["asset"] == "BTC"

    # 4. Prompt hoàn toàn khác -> Cache Miss
    diff_result = await semantic_cache.query_cache("Transfer 500 SOL to treasury wallet")
    assert diff_result is None


@pytest.mark.asyncio
async def test_semantic_cache_latency_benchmark():
    await semantic_cache.init_collection()

    prompt = "Check current balance of Ethereum"
    mock_resp = {"action": "READ_BALANCE", "asset": "ETH", "balance": 4.5}
    await semantic_cache.set_cache(prompt, mock_resp)

    # Benchmark độ trễ khi Cache Hit
    start_hit = time.perf_counter()
    hit_result = await semantic_cache.query_cache(prompt)
    hit_latency_ms = (time.perf_counter() - start_hit) * 1000

    assert hit_result is not None
    assert hit_latency_ms < 50.0
    print(f"\n[BENCHMARK] Semantic Cache Hit Latency: {hit_latency_ms:.2f} ms")


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_semantic_cache_latency_benchmark():
    await semantic_cache.init_collection()

    prompt = "Check current balance of Ethereum"
    mock_resp = {"action": "READ_BALANCE", "asset": "ETH", "balance": 4.5}
    await semantic_cache.set_cache(prompt, mock_resp)

    # 1. Warm-up embedding model để triệt tiêu cold-start latency
    _ = await semantic_cache.query_cache("warmup prompt")

    # 2. Benchmark độ trễ khi Cache Hit thực tế
    start_hit = time.perf_counter()
    hit_result = await semantic_cache.query_cache(prompt)
    hit_latency_ms = (time.perf_counter() - start_hit) * 1000

    assert hit_result is not None
    # Trên CPU máy phát triển, độ trễ toàn trình (Embedding + Network) đạt dưới 70ms (SRS quy định Cache < 100ms)
    assert hit_latency_ms < 70.0, f"Cache latency quá cao: {hit_latency_ms:.2f} ms"
    print(f"\n[BENCHMARK] Semantic Cache Hit Latency (Warmed): {hit_latency_ms:.2f} ms")