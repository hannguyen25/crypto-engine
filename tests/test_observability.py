import pytest
from httpx import AsyncClient
from app.main import app
from app.core.metrics import VERIFIER_REJECTIONS_TOTAL, CACHE_REQUESTS_TOTAL

@pytest.mark.asyncio
async def test_metrics_endpoint_exposed():
    # Tăng thử một số metric mẫu
    VERIFIER_REJECTIONS_TOTAL.labels(rule_violated="SLIPPAGE_CAP").inc()
    CACHE_REQUESTS_TOTAL.labels(result="hit").inc()

    async with AsyncClient(app=app, base_url="http://test") as ac:
        response = await ac.get("/metrics")

    assert response.status_code == 200
    content = response.text
    assert "verifier_rejection_total" in content
    assert "cache_requests_total" in content
    assert "http_requests_total" in content
    