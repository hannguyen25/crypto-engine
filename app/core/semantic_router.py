import uuid
from typing import Optional, Dict, Any
from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models
from fastembed import TextEmbedding
from app.core.config import settings


class SemanticRouter:
    COLLECTION_NAME = "semantic_cache"
    VECTOR_DIM = 384
    SIMILARITY_THRESHOLD = 0.96

    def __init__(self):
        self.client = AsyncQdrantClient(
            host=settings.QDRANT_HOST,
            port=settings.QDRANT_PORT,
            timeout=5.0,
        )
        self.embed_model = TextEmbedding(model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
        self._initialized = False

    async def init_collection(self) -> None:
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

    def _get_embedding(self, text: str) -> list[float]:
        embeddings = list(self.embed_model.embed([text]))
        return embeddings[0].tolist()

    async def query_cache(self, prompt: str) -> Optional[Dict[str, Any]]:
        if not self._initialized:
            await self.init_collection()

        vector = self._get_embedding(prompt)

        # Sử dụng query_points tương thích với Qdrant Server mới
        search_result = await self.client.query_points(
            collection_name=self.COLLECTION_NAME,
            query=vector,
            limit=1,
            score_threshold=self.SIMILARITY_THRESHOLD,
        )

        if search_result.points:
            hit = search_result.points[0]
            return {
                "hit": True,
                "score": hit.score,
                "cached_prompt": hit.payload.get("prompt"),
                "response": hit.payload.get("response"),
            }
        return None

    async def set_cache(self, prompt: str, response: Dict[str, Any]) -> None:
        if not self._initialized:
            await self.init_collection()

        vector = self._get_embedding(prompt)
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