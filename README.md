# ⚡ Crypto Intent Engine (v1.0.0)

[![CI/CD Pipeline](https://github.com/hannguyen25/crypto-engine/actions/workflows/test.yml/badge.svg)](https://github.com/hannguyen25/crypto-engine/actions/workflows/test.yml)

[![Python 3.11](https://img.shields.io/badge/Python-3.11-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/Framework-FastAPI-009688.svg)](https://fastapi.tiangolo.com/)
[![Throughput](https://img.shields.io/badge/Peak%20Throughput-590%2B%20RPS-brightgreen.svg)]()
[![Failures](https://img.shields.io/badge/Fail%20Rate-0.00%25-success.svg)]()
[![License](https://img.shields.io/badge/License-MIT-purple.svg)]()

Hệ thống xử lý ý định giao dịch tiền mã hóa thông minh (Crypto Intent-based Execution Engine) hiệu năng cao. Hệ thống chuyển đổi ngôn ngữ tự nhiên thành các giao dịch on-chain/CEX xác thực đa tầng, tích hợp bộ đệm ngữ nghĩa hai cấp (Two-tier Semantic Cache), giải thuật kiểm định ràng buộc giao dịch tất định (Deterministic Verifier) và cơ chế xử lý bất đồng bộ qua hàng đợi thông điệp AMQP.

---

## 🚀 Key Benchmarks & Production Metrics (Locust Load Test)

Hệ thống đã vượt qua kiểm thử chịu tải thực tế (**200 Concurrent Users**, spawn-rate 40 users/s liên tục trong 60 giây):

* **Tỷ lệ lỗi (Failure Rate):** **0.00%** xuyên suốt toàn bộ bài test (>32,000 requests).
* **Thông lượng tối đa (Peak Throughput):** Đạt **590.30 RPS** (Vượt tiêu chuẩn NFR-1.3 $\ge 500$ RPS).
* **Độ trễ đọc Cache L1 (Median):** **12.22 ms** (Vượt chuẩn NFR-1.1 Latency < 100 ms).
* **Độ trễ ghi lệnh Intent-to-Verify (P50):** **160 ms – 190 ms** cho toàn bộ pipeline khử độc, thẩm định ràng buộc và sinh khóa Idempotency.

---

## 🏗 System Architecture & Pipeline

```text
[ Natural Language Prompt ]
│
▼
┌─────────────────────────────────────────────────────────────┐
│ 1. API Gateway & Sanitizer (FastAPI, Input Sanitization)    │
└───────────────────────────┬─────────────────────────────────┘
                            │
         ┌──────────────────┴──────────────────┐
         ▼                                     ▼
   [Read Query]                          [Write Intent]
         │                                     │
         ▼                                     ▼
┌────────────────────────┐            ┌─────────────────────────────┐
│ 2. Two-Tier Cache      │            │ 3. LLM Parsing & Self-Heal  │
│  - L1: Redis Hash Key  │            │    (LangGraph, FastEmbed)   │
│  - L2: Qdrant Vector DB│            └──────────────┬──────────────┘
└────────────────────────┘                           │
                         │                           │
                         └─────────────┬─────────────┘
                                       │
                                       ▼
                        ┌─────────────────────────────┐
                        │ 4. Deterministic Verifier   │
                        │    - Balance check          │
                        │    - Slippage <= 3% (FR-3.4)│
                        │    - Whitelist asset check  │
                        │    - Idempotency Generation │
                        └──────────────┬──────────────┘
                                       │ (202 Accepted)
                                       ▼
                        ┌─────────────────────────────┐
                        │ 5. Message Broker (RabbitMQ)│
                        └──────────────┬──────────────┘
                                       │
                                       ▼
                        ┌─────────────────────────────┐
                        │ 6. Execution Worker         │
                        │    (Binance Spot Testnet)   │
                        └─────────────────────────────┘

---

## 🛠 Tech Stack

* **Core Backend:** Python 3.11, FastAPI, Uvicorn (Multi-worker AsyncIO), Pydantic v2.
* **AI & Intent Routing:** LangGraph, Instructor, OpenAI API (`gpt-4o`, `gpt-4o-mini`), FastEmbed (`paraphrase-multilingual-MiniLM-L12-v2`).
* **Storage & Data Management:**
  * **Redis 7 (L1):** Token Bucket Rate Limiting, Exact Match Hash Cache, Shared Connection Pool.
  * **Qdrant (L2):** Vector Database phục vụ Semantic Search & Cosine Similarity Scoring ($Threshold = 0.82$).
  * **PostgreSQL 16:** SQLAlchemy Asyncpg, Alembic Migrations, Intent Logs & Audit Trail.
* **Message Broker:** RabbitMQ 3.13 (AMQP 0-9-1) với Dead Letter Queue (DLQ).
* **Exchange Connector:** Binance Spot Testnet REST API.
* **Observability & Testing:** Prometheus Instrumentator, Langfuse Trace, Pytest (Coverage $\ge 90\%$), Locust.

---

## 💡 Core Engineering Highlights

**1. Two-Tier Semantic Caching (Read Flow):**
* Phân tách luồng Read (truy vấn giá, thị trường) và Write (giao dịch) ngay tại tầng Gateway.
* Kết hợp L1 Redis Cache (SHA-256 exact match) và L2 Qdrant Vector Search nhằm triệt tiêu tắc nghẽn CPU Event Loop khi tính toán FastEmbed ONNX vector, hạ độ trễ từ ~400ms xuống còn **12.22 ms**.

**2. Deterministic Verifier & AI Isolation (Write Flow):**
* Cô lập hoàn toàn khả năng sinh ảo (hallucination) của LLM với logic xử lý tài chính bằng bộ quy tắc toán học tất định (Deterministic Verifier).
* Tự động kiểm tra số dư ví khả dụng, đối soát danh mục tài sản được phép (Asset Whitelist) và chặn trượt giá quá ngưỡng (Slippage Cap > 3.0%) trước khi lệnh được chấp thuận (202 Accepted).

**3. Idempotency & Distributed Rate Limiter:**
* Thuật toán sinh khóa Idempotency Key tự động theo chu kỳ thời gian (Time-window) ngăn chặn triệt để lỗi double-spending khi mạng mất kết nối hoặc người dùng gửi trùng request.
* Thuật toán Token Bucket phân tán trên Redis giải quyết spike traffic (100 req/min) mà không làm tràn bộ nhớ socket.

---

## 🚦 Quick Start & Deployment

### 1. Khởi động các dịch vụ hạ tầng
```bash
docker compose up -d

### 2. Cài đặt môi trường & migration database
```bash
poetry install
poetry run alembic upgrade head

### 3. Khởi động API Gateway (4 Workers)
```bash
poetry run uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4

### 4.Khởi động Execution Worker (RabbitMQ Consumer)
```bash
poetry run python -m app.workers.execution_worker