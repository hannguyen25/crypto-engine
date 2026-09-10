import asyncio
import uuid
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import PointStruct, VectorParams, Distance
from fastembed import TextEmbedding

# Cấu hình Qdrant & Embedding
QDRANT_URL = "http://localhost:6333"
COLLECTION_NAME = "semantic_cache"
EMBEDDING_MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
VECTOR_SIZE = 384  # Kích thước vector của mô hình MiniLM-L12-v2

# Tập dữ liệu mẫu cần Pre-seed (FR-1.2.1)
SEED_DATA = [
    {
        "query": "Giá BTC hiện tại là bao nhiêu?",
        "response": {
            "symbol": "BTCUSDT",
            "price": "65420.50",
            "timestamp": 1772859000,
            "source": "SEMANTIC_CACHE"
        }
    },
    {
        "query": "Cho tôi xem tỷ giá ETH/USDT lúc này",
        "response": {
            "symbol": "ETHUSDT",
            "price": "3450.20",
            "timestamp": 1772859000,
            "source": "SEMANTIC_CACHE"
        }
    },
    {
        "query": "Giá SOL hôm nay thế nào?",
        "response": {
            "symbol": "SOLUSDT",
            "price": "145.80",
            "timestamp": 1772859000,
            "source": "SEMANTIC_CACHE"
        }
    },
    {
        "query": "Giá Bitcoin hiện tại bao nhiêu USDT?",
        "response": {
            "symbol": "BTCUSDT",
            "price": "65420.50",
            "timestamp": 1772859000,
            "source": "SEMANTIC_CACHE"
        }
    }
]


async def seed_cache():
    print(f"[*] Đang kết nối Qdrant tại {QDRANT_URL}...")
    client = AsyncQdrantClient(url=QDRANT_URL)
    
    # 1. Đảm bảo Collection tồn tại với chuẩn Cosine Distance
    collections = await client.get_collections()
    exists = any(c.name == COLLECTION_NAME for c in collections.collections)
    
    if not exists:
        print(f"[*] Tạo mới collection '{COLLECTION_NAME}' (Cosine metric)...")
        await client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE)
        )
    else:
        print(f"[+] Collection '{COLLECTION_NAME}' đã tồn tại.")

    # 2. Khởi tạo model embedding và encode toàn bộ prompt
    print(f"[*] Đang tính toán embeddings bằng model {EMBEDDING_MODEL_NAME}...")
    embed_model = TextEmbedding(model_name=EMBEDDING_MODEL_NAME)
    queries = [item["query"] for item in SEED_DATA]
    embeddings = list(embed_model.embed(queries))

    # 3. Đóng gói PointStruct và Upsert vào Qdrant
    points = []
    for idx, item in enumerate(SEED_DATA):
        point = PointStruct(
            id=str(uuid.uuid5(uuid.NAMESPACE_DNS, item["query"])),
            vector=embeddings[idx].tolist(),
            payload={
                "query": item["query"],
                "cached_response": item["response"],
                "is_read_only": True
            }
        )
        points.append(point)

    print(f"[*] Đang upsert {len(points)} vector điểm vào collection...")
    await client.upsert(
        collection_name=COLLECTION_NAME,
        points=points
    )
    print(f"[SUCCESS] Đã nạp thành công {len(points)} vectors vào Semantic Cache!")


if __name__ == "__main__":
    asyncio.run(seed_cache())