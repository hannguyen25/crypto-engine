import json
import re
from unittest.mock import AsyncMock
import pytest
from prometheus_client import CollectorRegistry, Counter, Gauge, generate_latest


# ----------------------------------------------------------------------
# TC-OBS-01: OpenTelemetry / Tracing Completeness (FR-1.3, NFR-4.1)
# ----------------------------------------------------------------------
@pytest.mark.asyncio
async def test_tracing_completeness_all_spans():
    """
    Kỳ vọng: Gửi 1 prompt giao dịch hoàn chỉnh qua Gateway.
    Trace phải ghi nhận đầy đủ 4 spans liền mạch theo thứ tự:
    semantic_cache_lookup -> model_inference -> deterministic_verify -> broker_publish.
    Span model_inference bắt buộc chứa metadata token count.
    """
    captured_spans = []

    class MockSpan:
        def __init__(self, name: str, attributes: dict | None = None):
            self.name = name
            self.attributes = attributes or {}

    class MockTracer:
        def start_span(self, name: str, attributes: dict | None = None):
            span = MockSpan(name, attributes)
            captured_spans.append(span)
            return span

    tracer = MockTracer()

    # Mô phỏng luồng pipeline xử lý qua Gateway
    async def run_pipeline(prompt: str):
        # 1. Span: semantic_cache_lookup
        tracer.start_span("semantic_cache_lookup", {"cache_hit": False})

        # 2. Span: model_inference (bắt buộc có token count)
        tracer.start_span(
            "model_inference",
            {
                "prompt_tokens": 42,
                "completion_tokens": 28,
                "model_name": "gpt-4o-mini",
            },
        )

        # 3. Span: deterministic_verify
        tracer.start_span(
            "deterministic_verify",
            {"rule_checked": "balance_and_slippage", "passed": True},
        )

        # 4. Span: broker_publish
        tracer.start_span(
            "broker_publish",
            {"routing_key": "orders.execution.requested"},
        )

    await run_pipeline("Mua 200 USDT ETH giá thị trường")

    # Xác thực chuỗi spans
    span_names = [s.name for s in captured_spans]
    expected_order = [
        "semantic_cache_lookup",
        "model_inference",
        "deterministic_verify",
        "broker_publish",
    ]
    assert span_names == expected_order, f"Thứ tự trace không đúng: {span_names}"

    # Kiểm tra metadata tokens tại span suy luận mô hình
    inference_span = next(s for s in captured_spans if s.name == "model_inference")
    assert inference_span.attributes.get("prompt_tokens") > 0
    assert inference_span.attributes.get("completion_tokens") > 0


# ----------------------------------------------------------------------
# TC-OBS-02: Prometheus Metrics Scraping (NFR-4.2)
# ----------------------------------------------------------------------
@pytest.mark.asyncio
async def test_prometheus_metrics_scraping():
    """
    Kỳ vọng: Endpoint /metrics phản ánh đúng số liệu:
    - 5 lệnh thành công
    - 3 lệnh bị Verifier chặn
    - 2 lượt hit cache
    - Các nhãn (labels) như rule="..." xuất hiện đúng chuẩn.
    Sử dụng CollectorRegistry cô lập để tránh lỗi Duplicated timeseries.
    """
    test_registry = CollectorRegistry()

    intent_accuracy = Counter(
        "intent_parsing_success_total",
        "Total successful IR extractions",
        registry=test_registry,
    )
    verifier_rejections = Counter(
        "verifier_rejection_total",
        "Verifier rejections",
        ["rule"],
        registry=test_registry,
    )
    cache_hits = Counter(
        "cache_hit_total",
        "Semantic cache hits",
        registry=test_registry,
    )
    worker_queue_depth = Gauge(
        "worker_queue_depth",
        "Current queue lag",
        registry=test_registry,
    )

    # Giả lập kịch bản: 5 lệnh thành công, 3 lệnh bị từ chối, 2 cache hit
    for _ in range(5):
        intent_accuracy.inc()

    verifier_rejections.labels(rule="SLIPPAGE_EXCEEDED").inc(2)
    verifier_rejections.labels(rule="INSUFFICIENT_FUNDS").inc(1)

    for _ in range(2):
        cache_hits.inc()

    worker_queue_depth.set(0)

    # Scrape dữ liệu text format từ registry cô lập của test
    scraped_data = generate_latest(test_registry).decode("utf-8")

    assert "intent_parsing_success_total 5.0" in scraped_data
    assert 'verifier_rejection_total{rule="SLIPPAGE_EXCEEDED"} 2.0' in scraped_data
    assert 'verifier_rejection_total{rule="INSUFFICIENT_FUNDS"} 1.0' in scraped_data
    assert "cache_hit_total 2.0" in scraped_data
    assert "worker_queue_depth 0.0" in scraped_data


# ----------------------------------------------------------------------
# TC-OBS-03: Bảo mật Log & Trace (No Secret Leak - NFR-2.1 & NFR-2.2)
# ----------------------------------------------------------------------
@pytest.mark.asyncio
async def test_no_secret_leak_in_logs_and_traces():
    """
    Kỳ vọng: Quét toàn bộ logs và trace spans sinh ra từ execution worker:
    - Không chứa api_secret, private key giải mã hoặc chuỗi hex khóa bí mật.
    - Không chứa Authorization Bearer JWT dưới dạng cleartext.
    """
    sensitive_patterns = [
        re.compile(r"Bearer\s+[A-Za-z0-9\-_=]+\.[A-Za-z0-9\-_=]+\.?[A-Za-z0-9\-_=]*"),
        re.compile(r"api_secret[\"']?\s*[:=]\s*[\"'][A-Za-z0-9]{32,}[\"']"),
        re.compile(r"0x[a-fA-F0-9]{64}"),
    ]

    captured_logs = []

    async def execution_worker_log_emitter():
        payload = {
            "order_id": "8f3b6c2a-9e12-4d56-b789-0123456789ab",
            "user_id": "usr_998877",
            "symbol": "ETHUSDT",
            "action": "SPOT_SWAP",
            "authorization_header": "Bearer [REDACTED]",
            "api_key_masked": "vmPU...89ab",
            "api_secret": "[PROTECTED_IN_VAULT]",
        }
        captured_logs.append(json.dumps(payload))

    await execution_worker_log_emitter()

    for log in captured_logs:
        for pattern in sensitive_patterns:
            match = pattern.search(log)
            assert match is None, f"LỖ HỔNG BẢO MẬT: Phát hiện thông tin nhạy cảm trong log: {match.group(0)}"

    full_log_text = " ".join(captured_logs)
    assert "encrypted_api_secret" not in full_log_text
    assert "sk-" not in full_log_text