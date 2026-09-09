import asyncio
import pytest
import aio_pika

RABBITMQ_URL = "amqp://guest:guest@localhost:5672/"
QUEUE_NAME = "test_fair_dispatch_queue"
TOTAL_MESSAGES = 30

async def spawn_worker(worker_id: int, queue_name: str, processed_bucket: list, stop_event: asyncio.Event):
    """Mỗi worker kết nối riêng biệt, đặt prefetch_count=1 để nhận task theo Fair Dispatch."""
    connection = await aio_pika.connect_robust(RABBITMQ_URL)
    channel = await connection.channel()
    
    # Kích hoạt Fair Dispatch (chỉ nhận tối đa 1 task unacknowledged cùng lúc)
    await channel.set_qos(prefetch_count=1)
    queue = await channel.declare_queue(queue_name, durable=True)

    async with queue.iterator() as queue_iter:
        async for message in queue_iter:
            async with message.process():
                msg_body = message.body.decode()
                processed_bucket.append((worker_id, msg_body))
                
                # Giả lập thời gian xử lý lệnh sàn (I/O latency)
                await asyncio.sleep(0.03)

                if len(processed_bucket) >= TOTAL_MESSAGES:
                    stop_event.set()
            
            if stop_event.is_set():
                break

    await connection.close()

@pytest.mark.asyncio
async def test_tc_mq_02_fair_dispatch_and_no_duplicates():
    # 1. Khởi tạo queue và làm sạch dữ liệu cũ
    connection = await aio_pika.connect_robust(RABBITMQ_URL)
    channel = await connection.channel()
    queue = await channel.declare_queue(QUEUE_NAME, durable=True)
    await queue.purge()

    # 2. Đẩy đồng loạt 30 orders vào queue
    for i in range(TOTAL_MESSAGES):
        await channel.default_exchange.publish(
            aio_pika.Message(
                body=f"order_{i}".encode(),
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT
            ),
            routing_key=QUEUE_NAME
        )
    await connection.close()

    # 3. Kích hoạt 3 worker kéo tin nhắn song song
    processed_messages = []
    stop_event = asyncio.Event()

    worker_tasks = [
        asyncio.create_task(spawn_worker(w_id, QUEUE_NAME, processed_messages, stop_event))
        for w_id in range(1, 4)
    ]

    # Timeout guard tối đa 10s để tránh treo test
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=10.0)
    finally:
        # Hủy các task worker còn đang lắng nghe sau khi gom đủ message
        for task in worker_tasks:
            task.cancel()
        await asyncio.gather(*worker_tasks, return_exceptions=True)

    # 4. Xác thực dữ liệu
    all_processed_ids = [msg[1] for msg in processed_messages]

    # Đủ 30 tin nhắn
    assert len(all_processed_ids) == TOTAL_MESSAGES

    # Không có bất kỳ order nào bị xử lý trùng lặp giữa 3 worker
    assert len(set(all_processed_ids)) == TOTAL_MESSAGES

    # Thống kê phân phối tải
    w1_count = sum(1 for w, _ in processed_messages if w == 1)
    w2_count = sum(1 for w, _ in processed_messages if w == 2)
    w3_count = sum(1 for w, _ in processed_messages if w == 3)

    print(f"\n[Fair Dispatch Stats] Worker 1: {w1_count} | Worker 2: {w2_count} | Worker 3: {w3_count}")

    # Đảm bảo phân phối đều: Mỗi worker nhận tối thiểu 5 và tối đa 15 tasks
    assert 5 <= w1_count <= 15
    assert 5 <= w2_count <= 15
    assert 5 <= w3_count <= 15

    # 5. Cleanup
    clean_conn = await aio_pika.connect_robust(RABBITMQ_URL)
    clean_ch = await clean_conn.channel()
    q = await clean_ch.declare_queue(QUEUE_NAME, passive=True)
    await q.purge()
    await clean_conn.close()