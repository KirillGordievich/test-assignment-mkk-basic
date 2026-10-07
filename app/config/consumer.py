from pydantic_settings import BaseSettings, SettingsConfigDict


class ConsumerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CONSUMER_", env_file=".env", extra="ignore")

    max_retries: int = 3
    retry_base_delay_ms: int = 5000
    webhook_timeout_s: float = 5.0
