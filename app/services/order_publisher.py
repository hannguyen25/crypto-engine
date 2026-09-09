import json
import logging
import os
from typing import Any, Dict
import aio_pika
from aio_pika import DeliveryMode, ExchangeType, Message

logger = logging.getLogger(__name__)

# Đọc cấu hình từ biến môi trường
RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost:5672/")
EXCHANGE_NAME = "orders.execution.requested"


class RabbitMQOrderPublisher:
    def __init__(self):
        self._connection: aio_pika.abc.AbstractRobustConnection | None = None
        self._channel: aio_pika.abc.AbstractChannel | None = None
        self._exchange: aio_pika.abc.AbstractExchange | None = None

    async def connect(self) -> None:
        """Khởi tạo kết nối Robust Connection và khai báo Durable Topic Exchange."""
        if self._connection and not self._connection.is_closed:
            return

        try:
            self._connection = await aio_pika.connect_robust(RABBITMQ_URL)
            self._channel = await self._connection.channel()

            # Khai báo Topic Exchange với durable=True (NFR-3.1)
            self._exchange = await self._channel.declare_exchange(
                name=EXCHANGE_NAME,
                type=ExchangeType.TOPIC,
                durable=True,
            )
            logger.info(f"[RabbitMQ] Đã kết nối và khai báo exchange durable '{EXCHANGE_NAME}'")
        except Exception as exc:
            logger.error(f"[RabbitMQ] Không thể kết nối tới broker: {exc}")
            raise

    async def publish_order(
        self,
        payload: Dict[str, Any],
        routing_key: str = "order.spot.swap",
    ) -> None:
        """Đẩy lệnh giao dịch vào Exchange với chế độ lưu trữ bền vững (Persistent)."""
        if not self._exchange:
            await self.connect()

        body = json.dumps(payload, default=str).encode("utf-8")

        message = Message(
            body=body,
            delivery_mode=DeliveryMode.PERSISTENT,  # SRS NFR-3.1: Persistent Messages
            content_type="application/json",
        )

        await self._exchange.publish(message, routing_key=routing_key)
        logger.info(f"[RabbitMQ] Đã publish order id={payload.get('intent_id')} với routing_key='{routing_key}'")

    async def close(self) -> None:
        """Đóng kết nối khi shutdown application."""
        if self._connection and not self._connection.is_closed:
            await self._connection.close()


order_publisher = RabbitMQOrderPublisher()