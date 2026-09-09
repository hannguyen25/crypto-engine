import uuid
from decimal import Decimal
import pytest
from app.services.balance_service import balance_service


@pytest.mark.asyncio
async def test_get_balance_existing_user():
    # User mẫu đã được thêm vào PostgreSQL ở bước trước
    test_user_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    balance = await balance_service.get_available_balance(test_user_id, "USDT")
    
    # Số dư nạp mẫu trong bảng user_balances là 1500.0
    assert balance == Decimal("1500.0000000000")


@pytest.mark.asyncio
async def test_get_balance_non_existing_asset():
    test_user_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    balance = await balance_service.get_available_balance(test_user_id, "BTC")
    
    # Chưa có bản ghi BTC -> Trả về 0.0 an toàn
    assert balance == Decimal("0.0")


@pytest.mark.asyncio
async def test_get_balance_invalid_uuid():
    balance = await balance_service.get_available_balance("not-a-valid-uuid", "USDT")
    assert balance == Decimal("0.0")