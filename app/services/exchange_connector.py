import asyncio
import logging
import random
from typing import Any, Dict

logger = logging.getLogger(__name__)


class NetworkTemporaryError(Exception):
    """Lỗi mạng tạm thời (kích hoạt retry backoff)."""
    pass


class BusinessLogicError(Exception):
    """Lỗi nghiệp vụ sàn: số dư tài khoản sàn không đủ, cặp coin đóng (không retry)."""
    pass


class BinanceExchangeConnector:
    async def execute_order(self, ir: Dict[str, Any]) -> Dict[str, Any]:
        """
        Mô phỏng gọi Binance Testnet API (FR-4.3).
        Hỗ trợ giả lập các case lỗi để kiểm thử retry và DLQ.
        """
        symbol = f"{ir.get('source_asset')}{ir.get('target_asset')}"
        amount = ir.get("amount_value")

        logger.info(f"[Exchange] Đang gửi lệnh testnet {ir.get('action')} cặp {symbol}, khối lượng: {amount}")

        # Mô phỏng độ trễ mạng thực tế
        await asyncio.sleep(0.3)

        # Giả lập lỗi để test luồng retry (nếu amount == 9999)
        if amount == 9999:
            raise NetworkTemporaryError("504 Gateway Timeout từ Binance Testnet")

        # Giả lập lỗi nghiệp vụ (nếu amount == 8888)
        if amount == 8888:
            raise BusinessLogicError("Symbol is halted for trading")

        return {
            "exchange_order_id": f"binance_{random.randint(100000, 999999)}",
            "executed_amount": amount,
            "executed_price": 3250.50 if "ETH" in symbol else 65000.0,
            "status": "FILLED",
        }


exchange_connector = BinanceExchangeConnector()