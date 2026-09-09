from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Core Application Settings
    PROJECT_NAME: str = "High-Throughput Crypto Intent Engine"
    ENVIRONMENT: str = "development"
    DEBUG: bool = False

    # Database, Cache & Broker URLs
    POSTGRES_URL: str = (
        "postgresql+asyncpg://crypto_admin:crypto_secret_2026@localhost:5433/intent_engine"
    )
    REDIS_URL: str = "redis://localhost:6380/0"
    RABBITMQ_URL: str = "amqp://guest:guest@localhost:5672/"
    QDRANT_HOST: str = "localhost"
    QDRANT_PORT: int = 6333

    # Business Constraints from SRS
    DEFAULT_MAX_SLIPPAGE_PCT: float = Field(default=3.0, ge=0.01, le=5.0)
    IDEMPOTENCY_TTL_SECONDS: int = 86400

    # Security & Guardrails
    JWT_SECRET: str = "changethisinproduction_supersecretkey"
    VAULT_SECRET_KEY: str = "deterministic_crypto_master_secret_32b!"


settings = Settings()