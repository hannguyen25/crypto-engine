import uuid
import pytest
from alembic.config import Config
from alembic import command
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from app.core.config import settings

# Lấy trực tiếp URL asyncpg từ settings
TEST_ASYNC_DB_URL = settings.POSTGRES_URL


def test_tc_db_01_migration_consistency():
    alembic_cfg = Config("alembic.ini")
    
    # 1. Upgrade lên head
    command.upgrade(alembic_cfg, "head")

    # 2. Downgrade về base
    command.downgrade(alembic_cfg, "base")

    # 3. Upgrade lại head để chuẩn bị schema cho TC-02, TC-03, TC-04
    command.upgrade(alembic_cfg, "head")


@pytest.fixture
async def async_db_session():
    engine = create_async_engine(TEST_ASYNC_DB_URL, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.connect() as conn:
        trans = await conn.begin()
        async with async_session(bind=conn) as session:
            yield session
        await trans.rollback()

    await engine.dispose()


@pytest.mark.asyncio
async def test_tc_db_02_fk_violation(async_db_session: AsyncSession):
    non_existent_intent = str(uuid.uuid4())
    sql = text("""
        INSERT INTO execution_orders (
            order_id, intent_id, idempotency_key, status, source_asset, target_asset
        ) VALUES (
            gen_random_uuid(), :intent_id, 'idem_001', 'PENDING', 'USDT', 'BTC'
        );
    """)
    with pytest.raises(IntegrityError) as exc_info:
        await async_db_session.execute(sql, {"intent_id": non_existent_intent})
        await async_db_session.flush()

    assert "foreign key" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_tc_db_03_unique_idempotency_key(async_db_session: AsyncSession):
    user_id = str(uuid.uuid4())
    intent_id = str(uuid.uuid4())
    key = "idem_key_dup_check_01"

    await async_db_session.execute(text("""
        INSERT INTO users (user_id, username, encrypted_api_key, encrypted_api_secret)
        VALUES (:u_id, 'trader_1', '\\x01', '\\x02');
    """), {"u_id": user_id})

    await async_db_session.execute(text("""
        INSERT INTO intent_logs (intent_id, user_id, raw_prompt, model_name, prompt_tokens, completion_tokens, latency_ms)
        VALUES (:i_id, :u_id, 'buy 100 USDT ETH', 'gpt-4o-mini', 10, 20, 110);
    """), {"i_id": intent_id, "u_id": user_id})

    order_sql = text("""
        INSERT INTO execution_orders (order_id, intent_id, idempotency_key, status, source_asset, target_asset)
        VALUES (gen_random_uuid(), :intent_id, :key, 'PENDING', 'USDT', 'ETH');
    """)

    await async_db_session.execute(order_sql, {"intent_id": intent_id, "key": key})
    await async_db_session.flush()

    with pytest.raises(IntegrityError) as exc_info:
        await async_db_session.execute(order_sql, {"intent_id": intent_id, "key": key})
        await async_db_session.flush()

    assert "unique constraint" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_tc_db_04_check_constraint_status(async_db_session: AsyncSession):
    user_id = str(uuid.uuid4())
    intent_id = str(uuid.uuid4())

    await async_db_session.execute(text("""
        INSERT INTO users (user_id, username, encrypted_api_key, encrypted_api_secret)
        VALUES (:u_id, 'trader_2', '\\x01', '\\x02');
    """), {"u_id": user_id})

    await async_db_session.execute(text("""
        INSERT INTO intent_logs (intent_id, user_id, raw_prompt, model_name, prompt_tokens, completion_tokens, latency_ms)
        VALUES (:i_id, :u_id, 'sell 50 SOL', 'gpt-4o-mini', 8, 15, 95);
    """), {"i_id": intent_id, "u_id": user_id})

    invalid_sql = text("""
        INSERT INTO execution_orders (order_id, intent_id, idempotency_key, status, source_asset, target_asset)
        VALUES (gen_random_uuid(), :intent_id, 'idem_test_status', 'INVALID_STATUS', 'SOL', 'USDT');
    """)

    with pytest.raises(IntegrityError) as exc_info:
        await async_db_session.execute(invalid_sql, {"intent_id": intent_id})
        await async_db_session.flush()

    assert "check constraint" in str(exc_info.value).lower()