import asyncio
from datetime import datetime, timezone
from app.core.idempotency import generate_idempotency_key
from app.services.order_publisher import order_publisher


async def run_manual_test():
    # 1. Kết nối tới RabbitMQ và mở Durable Topic Exchange
    print("[1/3] Đang kết nối tới RabbitMQ...")
    await order_publisher.connect()

    # 2. Chuẩn bị payload giả lập một Intent đã qua Verifier
    user_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    action = "SPOT_SWAP"
    source_asset = "USDT"
    target_asset = "ETH"
    amount_value = 200.0

    # Sinh Idempotency Key theo chuẩn SHA256 cửa sổ 30s (FR-4.1)
    idem_key = generate_idempotency_key(
        user_id=user_id,
        action=action,
        source_asset=source_asset,
        target_asset=target_asset,
        amount_value=amount_value,
    )

    order_payload = {
        "intent_id": "8f3b6c2a-9e12-4d56-b789-0123456789ab",
        "user_id": user_id,
        "idempotency_key": idem_key,
        "intermediate_representation": {
            "action": action,
            "source_asset": source_asset,
            "target_asset": target_asset,
            "amount_type": "EXACT",
            "amount_value": amount_value,
            "limit_price": None,
            "max_slippage_pct": 1.0,
            "deadline_seconds": 60,
        },
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    # 3. Publish order message vào RabbitMQ
    routing_key = "order.spot.swap"
    print(f"[2/3] Bắn message vào exchange với routing key '{routing_key}'...")
    await order_publisher.publish_order(order_payload, routing_key=routing_key)

    print(f"[3/3] Bắn thành công! Idempotency-Key: {idem_key}")

    # Đóng kết nối an toàn
    await order_publisher.close()


if __name__ == "__main__":
    asyncio.run(run_manual_test())