import os
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import NullPool

# Đọc DATABASE_URL từ môi trường (.env), mặc định cổng 5433 vừa cấu hình
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:Xuanhan2506@localhost:5433/crypto_engine_db",
)

# Khởi tạo Async Engine cho PostgreSQL
engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
    poolclass=NullPool,
)

# Tạo Session Factory bất đồng bộ
async_session_maker = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def get_async_db():
    """Dependency cung cấp db session cho FastAPI endpoint nếu cần."""
    async with async_session_maker() as session:
        try:
            yield session
        finally:
            await session.close()