import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from prometheus_fastapi_instrumentator import Instrumentator

from app.services.order_publisher import order_publisher
from app.api.v1.router import api_router
from app.core.config import settings
from app.core.metrics import (
    INTENT_PARSING_TOTAL,
    VERIFIER_REJECTIONS_TOTAL,
    CACHE_REQUESTS_TOTAL,
    WORKER_QUEUE_DEPTH,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # 1. Startup: Kết nối RabbitMQ và khai báo Exchange
    logger.info("Initializing connection pools (AsyncIO)...")
    try:
        await order_publisher.connect()
        logger.info("[RabbitMQ] Connected & exchange declared successfully.")
    except Exception as e:
        logger.error(f"[RabbitMQ Error] Không thể kết nối broker: {e}")

    yield

    # 2. Shutdown: Đóng connection an toàn
    logger.info("Closing active connections...")
    await order_publisher.close()


# Khởi tạo duy nhất 1 instance FastAPI
app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Abstraction layer connecting natural language to deterministic crypto execution.",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
    openapi_url="/openapi.json" if settings.DEBUG else None,
)

# Tự động đo HTTP requests, RPS, Latency P50/P95/P99
Instrumentator(
    should_group_status_codes=True,
    should_ignore_untemplated=True,
    excluded_handlers=["/metrics", "/health"]
).instrument(app)

# Đăng ký trực tiếp endpoint /metrics cho Prometheus scraper
@app.get("/metrics", include_in_schema=False)
def get_metrics():
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


origins = getattr(settings, "ALLOWED_ORIGINS", ["*"])
allow_creds = False if "*" in origins else True

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=allow_creds,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api/v1")