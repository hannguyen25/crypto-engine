import uuid
import logging
from decimal import Decimal
from sqlalchemy import text
from app.db.session import async_session_maker

logger = logging.getLogger(__name__)


class BalanceService:
    @staticmethod
    async def get_available_balance(user_id_str: str, asset: str) -> Decimal:
        """
        Truy vấn số dư khả dụng thực tế của user từ PostgreSQL (FR-3.2).
        Trả về Decimal để đảm bảo độ chính xác số học.
        """
        try:
            user_uuid = uuid.UUID(str(user_id_str))
        except ValueError:
            logger.error(f"[BalanceService] Invalid UUID format: {user_id_str}")
            return Decimal("0.0")

        asset_clean = asset.strip().upper()

        query = text("""
            SELECT available_amount 
            FROM user_balances 
            WHERE user_id = :user_id AND asset = :asset
        """)

        try:
            async with async_session_maker() as session:
                result = await session.execute(
                    query,
                    {"user_id": user_uuid, "asset": asset_clean}
                )
                row = result.scalar_one_or_none()
                
                if row is None:
                    logger.warning(
                        f"[BalanceService] No balance record for user {user_id_str}, asset {asset_clean}. Defaulting to 0."
                    )
                    return Decimal("0.0")
                
                return Decimal(str(row))
        except Exception as exc:
            logger.error(f"[BalanceService] Database query error: {exc}")
            # Theo chuẩn fail-safe: Lỗi kết nối DB thì chặn giao dịch để bảo vệ quỹ
            return Decimal("0.0")


balance_service = BalanceService()