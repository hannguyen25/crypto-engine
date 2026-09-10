import asyncio
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
import redis.asyncio as aioredis

from app.main import app
from app.core.config import settings
from app.core.security import create_access_token
from app.db.session import engine


# 1. Cấu hình Event Loop Policy chuẩn cho Windows Proactor
@pytest.fixture(scope="session")
def event_loop_policy():
    return asyncio.WindowsProactorEventLoopPolicy()


# 2. HTTP Async Client Fixture
@pytest_asyncio.fixture
async def async_client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# 3. Auth Headers Fixture
@pytest.fixture
def auth_headers():
    token = create_access_token(data={"sub": "user_semantic_test"})
    return {"Authorization": f"Bearer {token}"}


# 4. Tự động dọn dẹp Redis Rate Limiting sau mỗi bài test
@pytest_asyncio.fixture(autouse=True)
async def cleanup_redis():
    yield
    try:
        client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        keys = await client.keys("rate_limit:*")
        if keys:
            await client.delete(*keys)
        await client.aclose()
    except Exception:
        pass


# 5. Dọn dẹp connection pool DB
@pytest_asyncio.fixture(autouse=True)
async def cleanup_db_pool():
    yield
    try:
        await engine.dispose()
    except Exception:
        pass