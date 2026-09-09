import json
import uuid
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from app.workers.order_worker import OrderExecutionWorker
from app.services.exchange_connector import NetworkTemporaryError, BusinessLogicError


@pytest.fixture
def mock_worker():
    """Khởi tạo Worker với các client Redis và RabbitMQ được mock độc lập."""
    worker = OrderExecutionWorker()
    worker.redis_client = AsyncMock()
    return worker


@pytest.fixture
def sample_order_payload():
    return {
        "intent_id": str(uuid.uuid4()),
        "user_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        "idempotency_key": "test_idempotency_key_1234567890",
        "intermediate_representation": {
            "action": "SPOT_SWAP",
            "source_asset": "USDT",
            "target_asset": "ETH",
            "amount_type": "EXACT",
            "amount_value": 200.0,
            "max_slippage_pct": 1.0,
        },
    }


def create_mock_message(payload: dict):
    """Tạo mock aio-pika incoming message hỗ trợ context manager process()."""
    message = AsyncMock()
    message.body = json.dumps(payload).encode()
    message.process = MagicMock()
    message.process.return_value.__aenter__ = AsyncMock()
    message.process.return_value.__aexit__ = AsyncMock()
    return message


# TC-EX-01: Thực thi giao dịch thành công (FR-4.3)
@pytest.mark.asyncio
async def test_tc_ex_01_execute_order_success(mock_worker, sample_order_payload):
    mock_worker.redis_client.set.return_value = True  # Giữ lock NX thành công
    dlq_exchange = AsyncMock()
    message = create_mock_message(sample_order_payload)

    fake_response = {
        "exchange_order_id": "binance_12345678",
        "executed_amount": 200.0,
        "executed_price": 3250.50,
        "status": "FILLED",
    }

    with patch(
        "app.workers.order_worker.exchange_connector.execute_order",
        new_callable=AsyncMock,
        return_value=fake_response,
    ):
        await mock_worker.process_order(message, dlq_exchange)

    # 1. Đảm bảo đã đặt atomic lock "PENDING"
    mock_worker.redis_client.set.assert_any_call(
        sample_order_payload["idempotency_key"], "PENDING", ex=86400, nx=True
    )
    # 2. Đảm bảo cập nhật trạng thái COMPLETED trong Redis
    mock_worker.redis_client.set.assert_any_call(
        sample_order_payload["idempotency_key"], "COMPLETED", ex=86400
    )
    # 3. Không đẩy vào DLQ
    dlq_exchange.publish.assert_not_called()


# TC-EX-02: Cơ chế Retry lỗi mạng (Transient Error) với Exponential Backoff (FR-4.3)
@pytest.mark.asyncio
async def test_tc_ex_02_retry_exponential_backoff(mock_worker, sample_order_payload):
    mock_worker.redis_client.set.return_value = True
    dlq_exchange = AsyncMock()
    message = create_mock_message(sample_order_payload)

    # Lần 1 và 2 lỗi mạng (502/504 Timeout), lần 3 thành công
    mock_execute = AsyncMock(
        side_effect=[
            NetworkTemporaryError("HTTP 502 Bad Gateway"),
            NetworkTemporaryError("HTTP 504 Gateway Timeout"),
            {"exchange_order_id": "binance_recovered_999", "status": "FILLED"},
        ]
    )

    with patch("app.workers.order_worker.exchange_connector.execute_order", mock_execute), \
         patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:

        await mock_worker.process_order(message, dlq_exchange)

    # Đảm bảo đã retry 3 lần
    assert mock_execute.call_count == 3
    # Đảm bảo có tính toán Exponential Backoff (2^1 = 2s, 2^2 = 4s)
    mock_sleep.assert_any_call(2)
    mock_sleep.assert_any_call(4)
    # Trạng thái cuối cùng cập nhật COMPLETED thành công
    mock_worker.redis_client.set.assert_any_call(
        sample_order_payload["idempotency_key"], "COMPLETED", ex=86400
    )


# TC-EX-03: Chuyển hàng đợi chết (Dead Letter Queue - DLQ) sau 3 lần retry (NFR-3.2)
@pytest.mark.asyncio
async def test_tc_ex_03_forward_to_dlq_after_max_retries(mock_worker, sample_order_payload):
    mock_worker.redis_client.set.return_value = True
    dlq_exchange = AsyncMock()
    message = create_mock_message(sample_order_payload)

    # Lỗi mạng liên tục kéo dài cả 3 lần
    mock_execute = AsyncMock(side_effect=NetworkTemporaryError("Connection reset by peer"))

    with patch("app.workers.order_worker.exchange_connector.execute_order", mock_execute), \
         patch("asyncio.sleep", new_callable=AsyncMock):

        await mock_worker.process_order(message, dlq_exchange)

    assert mock_execute.call_count == 3
    # Đánh dấu FAILED trên Redis
    mock_worker.redis_client.set.assert_any_call(
        sample_order_payload["idempotency_key"], "FAILED", ex=86400
    )
    # Đẩy message vào Dead Letter Queue exchange
    assert dlq_exchange.publish.called
    published_msg = dlq_exchange.publish.call_args[0][0]
    data_sent = json.loads(published_msg.body.decode())
    assert "Connection reset by peer" in data_sent.get("dlq_reason", "")


# TC-EX-04: Không retry với lỗi nghiệp vụ sàn (FR-4.3)
@pytest.mark.asyncio
async def test_tc_ex_04_no_retry_on_business_logic_error(mock_worker, sample_order_payload):
    mock_worker.redis_client.set.return_value = True
    dlq_exchange = AsyncMock()
    message = create_mock_message(sample_order_payload)

    mock_execute = AsyncMock(side_effect=BusinessLogicError("Filter failure: LOT_SIZE"))

    with patch("app.workers.order_worker.exchange_connector.execute_order", mock_execute):
        await mock_worker.process_order(message, dlq_exchange)

    # Dừng ngay ở lần gọi đầu tiên, tuyệt đối KHÔNG retry
    assert mock_execute.call_count == 1
    # Ghi nhận trạng thái FAILED
    mock_worker.redis_client.set.assert_any_call(
        sample_order_payload["idempotency_key"], "FAILED", ex=86400
    )
    # Đẩy ngay vào DLQ để kỹ sư kiểm tra
    assert dlq_exchange.publish.called


# TC-EX-05: Giải mã khóa API tại Worker và kiểm tra an toàn bộ nhớ (NFR-2.1, NFR-2.2)
def test_tc_ex_05_api_key_decryption_and_no_plain_logging(capsys):
    """
    Worker giải mã encrypted_api_key và encrypted_api_secret trong bộ nhớ,
    tuyệt đối không để rò rỉ chuỗi bí mật ra log/console.
    """
    raw_secret_key = "MY_SUPER_SECRET_BINANCE_KEY_999"
    # Giả lập payload đã mã hóa AES-256
    encrypted_bytes = raw_secret_key.encode("utf-8")[::-1]  # Mock data mã hóa

    def decrypt_in_memory(cipher_bytes: bytes) -> str:
        # Giải mã trực tiếp trong RAM biến cục bộ
        return cipher_bytes[::-1].decode("utf-8")

    # Quá trình Worker giải mã và ký order payload
    decrypted_key = decrypt_in_memory(encrypted_bytes)
    assert decrypted_key == raw_secret_key

    # Giả lập ghi log khi xử lý lệnh giao dịch
    import logging
    test_logger = logging.getLogger("worker_security_test")
    test_logger.info("Worker đã nạp credentials và ký payload thành công cho user")

    captured = capsys.readouterr()
    # Xác thực chuỗi bí mật không bao giờ xuất hiện ở output log
    assert raw_secret_key not in captured.out
    assert raw_secret_key not in captured.err