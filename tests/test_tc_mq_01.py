import asyncio
import docker
import pytest
import aio_pika

RABBITMQ_URL = "amqp://guest:guest@localhost:5672/"

async def wait_for_rabbitmq(url: str, max_retries: int = 20, delay: float = 2.0):
    """Thử kết nối lặp lại cho đến khi RabbitMQ thực sự sẵn sàng nhận AMQP frame."""
    for attempt in range(max_retries):
        try:
            conn = await aio_pika.connect_robust(url, timeout=5.0)
            await conn.close()
            return True
        except Exception:
            await asyncio.sleep(delay)
    return False

@pytest.mark.asyncio
async def test_tc_mq_01_message_durability():
    # 1. Kết nối và khởi tạo Durable Exchange/Queue
    connection = await aio_pika.connect_robust(RABBITMQ_URL)
    channel = await connection.channel()
    
    exchange = await channel.declare_exchange(
        "orders.execution.requested", 
        aio_pika.ExchangeType.TOPIC, 
        durable=True
    )
    queue = await channel.declare_queue("test_durable_orders", durable=True)
    await queue.bind(exchange, routing_key="order.create")

    # Xóa sạch tin nhắn cũ nếu còn sót lại từ lần chạy trước
    await queue.purge()

    # 2. Publish 100 persistent messages
    for i in range(100):
        message = aio_pika.Message(
            body=f'{{"intent_id": "test-{i}"}}'.encode(),
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT
        )
        await exchange.publish(message, routing_key="order.create")

    await connection.close()

    # 3. Restart container RabbitMQ
    client = docker.from_env()
    all_containers = client.containers.list()
    rabbitmq_container = next(
        (c for c in all_containers if "rabbitmq" in c.name.lower()), 
        None
    )

    if not rabbitmq_container:
        pytest.fail("Không tìm thấy container RabbitMQ nào đang chạy!")

    rabbitmq_container.restart()

    # 4. Đợi RabbitMQ khởi động và sẵn sàng hoàn toàn
    ready = await wait_for_rabbitmq(RABBITMQ_URL, max_retries=15, delay=2.0)
    assert ready, "RabbitMQ không thể khởi động lại thành công sau khi restart."

    # 5. Reconnect và verify số lượng message
    reconnect = await aio_pika.connect_robust(RABBITMQ_URL)
    new_channel = await reconnect.channel()
    
    inspected_queue = await new_channel.declare_queue("test_durable_orders", passive=True)
    
    assert inspected_queue.declaration_result.message_count == 100

    # Cleanup queue sau test
    await inspected_queue.purge()
    await reconnect.close()