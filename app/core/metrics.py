from prometheus_client import Counter, Gauge, Histogram

# 1. Trích xuất Intent (NFR-4.2: intent_parsing_accuracy)
INTENT_PARSING_TOTAL = Counter(
    "intent_parsing_total",
    "Tổng số intent được phân tích",
    ["status", "model_tier"]
)

# 2. Verifier Guardrails (NFR-4.2: verifier_rejection_total)
VERIFIER_REJECTIONS_TOTAL = Counter(
    "verifier_rejection_total",
    "Số lệnh bị Verifier từ chối",
    ["rule_violated"]
)

# 3. Semantic Cache Hit Ratio (NFR-4.2: cache_hit_ratio)
CACHE_REQUESTS_TOTAL = Counter(
    "cache_requests_total",
    "Thống kê truy vấn Cache Semantic",
    ["result"]  # hit hoặc miss
)

# 4. RabbitMQ Queue Lag / Depth (NFR-4.2: worker_queue_depth)
WORKER_QUEUE_DEPTH = Gauge(
    "worker_queue_depth",
    "Số lượng message đang chờ trong hàng đợi RabbitMQ",
    ["queue_name"]
)

# 5. Latency phân tích và xử lý (NFR-1.1, NFR-1.2)
INTENT_PROCESSING_LATENCY = Histogram(
    "intent_processing_latency_seconds",
    "Thời gian xử lý intent từ tiếp nhận tới verify",
    buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0]
)