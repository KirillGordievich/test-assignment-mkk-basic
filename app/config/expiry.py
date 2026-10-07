from pydantic_settings import BaseSettings, SettingsConfigDict


class ExpirySettings(BaseSettings):
    """Failing of payments stuck in pending, e.g. the DB was down when retries ran out."""

    model_config = SettingsConfigDict(env_prefix="EXPIRY_", env_file=".env", extra="ignore")

    interval_s: float = 300.0
    # Must exceed the time a payment can legitimately spend in the queues (retries, backlog),
    # or a payment that would still succeed is failed.
    ttl_s: float = 1800.0
    batch_size: int = 100
