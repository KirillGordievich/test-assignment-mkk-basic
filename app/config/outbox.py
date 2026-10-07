from pydantic_settings import BaseSettings, SettingsConfigDict


class OutboxSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OUTBOX_", env_file=".env", extra="ignore")

    poll_interval_s: float = 1.0
    batch_size: int = 50
