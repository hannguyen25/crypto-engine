import asyncio
import json
import logging
import os
from typing import Any, Dict
import aio_pika
from aio_pika import ExchangeType, Message, DeliveryMode
import redis.asyncio as aioredis
from app.services.exchange_connector import (
    exchange_connector,
    NetworkTemporaryError,
    BusinessLogicError,
)
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost:5672/")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6380/0")

MAIN_EXCHANGE = "orders.execution.requested"
MAIN_QUEUE = "orders.execution.queue"
DLQ_EXCHANGE = "orders.dlq.exchange"
DLQ_QUEUE = "orders.execution.dlq"
MAX_RETRIES = 3


class OrderExecutionWorker:
    def __init__(self):
        self.redis_client = aioredis.from_url(REDIS_URL, decode_responses=True)
        self.connection = None
        self.channel = None

    async def setup_queues(self):
        """Khai báo Main Queue, Dead Letter Queue (DLQ) và Exchange theo NFR-3.1 & NFR-3.2."""
        self.connection = await aio_pika.connect_robust(RABBITMQ_URL)
        self.channel = await self.connection.channel()
        await self.channel.set_qos(prefetch_count=10)

        # 1. Khai báo DLQ Exchange & Queue
        dlq_exchange = await self.channel.declare_exchange(
            DLQ_EXCHANGE, ExchangeType.DIRECT, durable=True
        )
        dlq = await self.channel.declare_queue(DLQ_QUEUE, durable=True)
        await dlq.bind(dlq_exchange, routing_key="dead_letter")

        # 2. Khai báo Main Topic Exchange
        main_exchange = await self.channel.declare_exchange(
            MAIN_EXCHANGE, ExchangeType.TOPIC, durable=True
        )

        # 3. Khai báo Main Queue gắn routing sang DLQ khi bị reject
        main_queue = await self.channel.declare_queue(
            MAIN_QUEUE,
            durable=True,
            arguments={
                "x-dead-letter-exchange": DLQ_EXCHANGE,
                "x-dead-letter-routing-key": "dead_letter",
            },
        )
        await main_queue.bind(main_exchange, routing_key="order.#")
        return main_queue, dlq_exchange

    async def forward_to_dlq(self, dlq_exchange, payload: Dict[str, Any], reason: str):
        """Đẩy task vào Dead Letter Queue sau khi quá số lần retry (NFR-3.2)."""
        payload["dlq_reason"] = reason
        message = Message(
            body=json.dumps(payload).encode(),
            delivery_mode=DeliveryMode.PERSISTENT,
        )
        await dlq_exchange.publish(message, routing_key="dead_letter")
        logger.error(f"[DLQ] Lệnh {payload.get('intent_id')} đã bị chuyển vào Dead Letter Queue. Lý do: {reason}")

    async def process_order(self, message: aio_pika.IncomingMessage, dlq_exchange):
        async with message.process(requeue=False):
            data = json.loads(message.body.decode())
            idempotency_key = data.get("idempotency_key")
            intent_id = data.get("intent_id")
            ir = data.get("intermediate_representation", {})

            # 1. Khóa phân tán Redis & Idempotency Gatekeeper: SET key "PENDING" EX 86400 NX (FR-4.2)
            is_locked = await self.redis_client.set(
                idempotency_key, "PENDING", ex=86400, nx=True
            )

            if not is_locked:
                status = await self.redis_client.get(idempotency_key)
                logger.warning(f"[Idempotency Block] Lệnh trùng lặp bị hủy: {idempotency_key}, trạng thái hiện tại: {status}")
                return  # Hủy task lặp, không thực thi tiếp

            # 2. Tiến hành thực thi kèm Exponential Backoff Retry (FR-4.3)
            attempt = 0
            while attempt < MAX_RETRIES:
                try:
                    result = await exchange_connector.execute_order(ir)
                    
                    # Thành công: Cập nhật state COMPLETED
                    await self.redis_client.set(idempotency_key, "COMPLETED", ex=86400)
                    logger.info(f"[Order Filled] Intent {intent_id} thành công: {result['exchange_order_id']}")
                    return

                except NetworkTemporaryError as net_err:
                    attempt += 1
                    backoff_delay = 2 ** attempt  # Exponential backoff: 2s, 4s, 8s
                    logger.warning(f"[Retry {attempt}/{MAX_RETRIES}] Lỗi mạng: {net_err}. Thử lại sau {backoff_delay}s...")
                    if attempt >= MAX_RETRIES:
                        # Đạt ngưỡng thất bại: Cập nhật FAILED và đẩy DLQ
                        await self.redis_client.set(idempotency_key, "FAILED", ex=86400)
                        await self.forward_to_dlq(dlq_exchange, data, str(net_err))
                        return
                    await asyncio.sleep(backoff_delay)

                except BusinessLogicError as biz_err:
                    # Lỗi nghiệp vụ sàn: Dừng ngay, không retry
                    logger.error(f"[Business Error] Lỗi nghiệp vụ sàn: {biz_err}")
                    await self.redis_client.set(idempotency_key, "FAILED", ex=86400)
                    await self.forward_to_dlq(dlq_exchange, data, str(biz_err))
                    return

    async def start(self):
        main_queue, dlq_exchange = await self.setup_queues()
        logger.info("[Worker Started] Đang lắng nghe hàng đợi orders.execution.queue...")

        async with main_queue.iterator() as queue_iter:
            async for message in queue_iter:
                await self.process_order(message, dlq_exchange)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    worker = OrderExecutionWorker()
    asyncio.run(worker.start())