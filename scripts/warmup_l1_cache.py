import hashlib
import json
import redis
from app.core.config import settings

r = redis.from_url(settings.REDIS_URL)

prompts = [
    "Giá BTC hiện tại là bao nhiêu?",
    "Cho tôi biết giá Bitcoin hôm nay",
    "Tỷ giá BTC/USDT hiện tại",
    "Bitcoin đang có giá bao nhiêu?",
]

for p in prompts:
    # Chuẩn hóa đồng nhất với logic trong semantic_router.py
    clean_text = p.strip().strip('"').strip("'").lower()
    clean_text = " ".join(clean_text.split())
    p_hash = hashlib.sha256(clean_text.encode("utf-8")).hexdigest()
    key = f"l1_cache:{p_hash}"
    val = json.dumps({
        "prompt": p,
        "response": {
            "symbol": "BTCUSDT",
            "price": 65000.0,
            "source": "SEMANTIC_CACHE"
        }
    })
    r.setex(key, 86400, val)

print("[SUCCESS] Da nap day du 4 prompts vao Redis L1!")
