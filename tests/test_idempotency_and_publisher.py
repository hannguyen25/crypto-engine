import pytest
from unittest.mock import AsyncMock, patch
from app.core.idempotency import generate_idempotency_key
from app.services.order_publisher import RabbitMQOrderPublisher


def test_idempotency_key_consistency_within_30s():
    """Hai request trong cùng cửa sổ 30s phải sinh ra cùng 1 khóa băm."""
    t0 = 1772859000.0  # 1772859000 // 30 = 59095300
    t1 = 1772859020.0  # cùng cửa sổ 30s

    key1 = generate_idempotency_key("user_1", "SPOT_SWAP", "USDT", "BTC", 100.0, timestamp=t0)
    key2 = generate_idempotency_key("user_1", "SPOT_SWAP", "USDT", "BTC", 100.0, timestamp=t1)

    assert key1 == key2
    assert len(key1) == 64  # Chuẩn SHA-256 Hex length


def test_idempotency_key_differs_after_30s():
    """Request sau khi chuyển sang cửa sổ 30s mới phải sinh ra khóa khác."""
    t0 = 1772859000.0
    t_after_30s = 1772859031.0

    key1 = generate_idempotency_key("user_1", "SPOT_SWAP", "USDT", "BTC", 100.0, timestamp=t0)
    key2 = generate_idempotency_key("user_1", "SPOT_SWAP", "USDT", "BTC", 100.0, timestamp=t_after_30s)

    assert key1 != key2


@pytest.mark.asyncio
async def test_order_publisher_mock():
    """Kiểm tra publisher gọi exchange.publish với đúng dữ liệu."""
    publisher = RabbitMQOrderPublisher()
    mock_exchange = AsyncMock()
    publisher._exchange = mock_exchange

    payload = {"intent_id": "test-uuid", "amount": 500}
    await publisher.publish_order(payload, routing_key="order.spot_swap")

    assert mock_exchange.publish.called
    published_message = mock_exchange.publish.call_args[0][0]
    assert b"test-uuid" in published_message.body