import hashlib
import time
from typing import Optional


def generate_idempotency_key(
    user_id: str,
    action: str,
    source_asset: str,
    target_asset: str,
    amount_value: float | str,
    timestamp: Optional[float] = None,
) -> str:
    """
    Sinh Idempotency Key theo chuẩn SRS FR-4.1:
    Key = SHA256(user_id + action + source + target + amount + floor(timestamp / 30))
    """
    ts = timestamp if timestamp is not None else time.time()
    time_window = int(ts) // 30  # Cửa sổ 30 giây

    amount_str = str(amount_value) if amount_value is not None else "0"

    raw_data = (
        f"{user_id}"
        f"{action}"
        f"{source_asset.upper()}"
        f"{target_asset.upper()}"
        f"{amount_str}"
        f"{time_window}"
    )

    return hashlib.sha256(raw_data.encode("utf-8")).hexdigest()