"""
config.py — All tuneable knobs in one place.
Adjust DB_ARTIFICIAL_DELAY_SECONDS and DB_POOL_MAX_SIZE to control
how easy it is to trigger the stampede.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # ── PostgreSQL ────────────────────────────────────────────────────────────
    DATABASE_URL: str = "postgresql://flashsale:flashsale@postgres:5432/flashsale"

    # Deliberately tiny pool → pool exhaustion happens fast during stampede
    DB_POOL_MIN_SIZE: int = 2
    DB_POOL_MAX_SIZE: int = 10          # key knob: lower = stampede faster

    # Artificial query latency injected via pg_sleep()
    # This widens the concurrency window so many requests pile up simultaneously
    DB_ARTIFICIAL_DELAY_SECONDS: float = 1.0   # 0.5–2.0 recommended

    # ── Redis ─────────────────────────────────────────────────────────────────
    REDIS_URL: str = "redis://redis:6379/0"

    # How long a cached product lives (seconds)
    CACHE_TTL_SECONDS: int = 10

    # ── Hot product ───────────────────────────────────────────────────────────
    HOT_PRODUCT_ID: int = 123

    # ── Application ───────────────────────────────────────────────────────────
    # Checkout will time out if the product fetch takes longer than this
    CHECKOUT_TIMEOUT_SECONDS: float = 3.0

    # How many control (non-hot) products to seed
    CONTROL_PRODUCT_COUNT: int = 20


settings = Settings()