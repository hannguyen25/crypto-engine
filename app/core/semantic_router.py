import asyncio
import hashlib
import json
import uuid
from typing import Any, Dict, Optional
from fastembed import TextEmbedding
from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models
import redis.asyncio as aioredis
from app.core.config import settings


class SemanticRouter:
    COLLECTION_NAME = "semantic_cache"
    VECTOR_DIM = 384
    SIMILARITY_THRESHOLD = 0.82

    def __init__(self):
        self.client = AsyncQdrantClient(
            host=settings.QDRANT_HOST,
            port=settings.QDRANT_PORT,
            timeout=5.0,
        )
        self.embed_model = TextEmbedding(
            model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
        )
        # Redis Connection Pool dùng chung cho toàn bộ các processes/requests
        self._redis_pool = aioredis.ConnectionPool.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            max_connections=50,
        )
        self._initialized = False
        self._init_lock = asyncio.Lock()

    def _get_redis(self) -> aioredis.Redis:
        return aioredis.Redis(connection_pool=self._redis_pool)

    async def init_collection(self) -> None:
        if self._initialized:
            return

        async with self._init_lock:
            if self._initialized:
                return

            collections = await self.client.get_collections()
            exists = any(c.name == self.COLLECTION_NAME for c in collections.collections)

            if not exists:
                await self.client.create_collection(
                    collection_name=self.COLLECTION_NAME,
                    vectors_config=models.VectorParams(
                        size=self.VECTOR_DIM,
                        distance=models.Distance.COSINE,
                    ),
                )
            self._initialized = True

    def _compute_embedding_sync(self, text: str) -> list[float]:
        embeddings = list(self.embed_model.embed([text]))
        return embeddings[0].tolist()

    async def query_cache(self, prompt: str) -> Optional[Dict[str, Any]]:
        # Chuẩn hóa khoảng trắng và chữ thường để hash luôn đồng nhất
        clean_text = " ".join(prompt.strip().lower().split())
        cache_key = f"l1_cache:{hashlib.sha256(clean_text.encode('utf-8')).hexdigest()}"

        # --- TẦNG 1: Tra cứu Redis L1 Cache (< 5ms) ---
        redis_client = self._get_redis()
        cached_data = await redis_client.get(cache_key)
        if cached_data:
            data = json.loads(cached_data)
            return {
                "hit": True,
                "score": 1.0,
                "cached_prompt": data.get("prompt"),
                "response": data.get("response"),
            }

        # --- TẦNG 2: Qdrant Vector Semantic Cache ---
        if not self._initialized:
            await self.init_collection()

        vector = await asyncio.to_thread(self._compute_embedding_sync, prompt)

        search_result = await self.client.query_points(
            collection_name=self.COLLECTION_NAME,
            query=vector,
            limit=1,
            score_threshold=self.SIMILARITY_THRESHOLD,
        )

        if search_result.points:
            hit = search_result.points[0]
            result = {
                "hit": True,
                "score": hit.score,
                "cached_prompt": hit.payload.get("prompt"),
                "response": hit.payload.get("response"),
            }

            # Đồng bộ kết quả vào Redis L1 để mọi worker khác hit ngay lập tức
            await redis_client.setex(
                cache_key,
                3600,
                json.dumps({
                    "prompt": hit.payload.get("prompt"),
                    "response": hit.payload.get("response"),
                }),
            )
            return result

        return None

    async def set_cache(self, prompt: str, response: Dict[str, Any]) -> None:
        if not self._initialized:
            await self.init_collection()

        clean_text = " ".join(prompt.strip().lower().split())
        cache_key = f"l1_cache:{hashlib.sha256(clean_text.encode('utf-8')).hexdigest()}"

        # Ghi đồng thời vào Redis L1
        redis_client = self._get_redis()
        await redis_client.setex(
            cache_key,
            3600,
            json.dumps({"prompt": prompt, "response": response}),
        )

        # Ghi vào Qdrant L2
        vector = await asyncio.to_thread(self._compute_embedding_sync, prompt)
        point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, prompt))

        await self.client.upsert(
            collection_name=self.COLLECTION_NAME,
            points=[
                models.PointStruct(
                    id=point_id,
                    vector=vector,
                    payload={"prompt": prompt, "response": response},
                )
            ],
        )


semantic_cache = SemanticRouter()