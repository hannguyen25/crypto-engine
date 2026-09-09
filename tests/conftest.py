import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
import redis.asyncio as aioredis
import asyncio
from app.main import app
from app.core.config import settings
from app.core.security import create_access_token
from app.db.session import engine

@pytest_asyncio.fixture
async def async_client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def auth_headers():
    token = create_access_token(data={"sub": "user_semantic_test"})
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture(autouse=True)
async def cleanup_redis():
    client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    yield
    keys = await client.keys("rate_limit:*")
    if keys:
        await client.delete(*keys)
    await client.aclose()

@pytest.fixture(scope="session")
def event_loop():
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# Dọn dẹp connection pool sau khi chạy xong toàn bộ test
@pytest.fixture(scope="session", autouse=True)
async def cleanup_db_pool():
    yield
    await engine.dispose()