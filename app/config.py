from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="POSTGRES_", env_file=".env", extra="ignore")

    host: str
    port: int
    user: str
    password: str
    db: str
    pool_size: int = 10
    max_overflow: int = 5

    @property
    def url(self) -> str:
        return f"postgresql+asyncpg://{self.user}:{self.password}@{self.host}:{self.port}/{self.db}"


class RabbitMQSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RABBITMQ_", env_file=".env", extra="ignore")

    host: str = "localhost"
    port: int = 5672
    default_user: str = "guest"
    default_pass: str = "guest"

    @property
    def url(self) -> str:
        return f"amqp://{self.default_user}:{self.default_pass}@{self.host}:{self.port}/"


class ConsumerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CONSUMER_", env_file=".env", extra="ignore")

    max_retries: int = 3
    retry_base_delay_ms: int = 5000
    webhook_timeout_s: float = 5.0


class GatewaySettings(BaseSettings):
    """Payment gateway emulation."""

    model_config = SettingsConfigDict(env_prefix="GATEWAY_", env_file=".env", extra="ignore")

    failure_rate: float = Field(default=0.1, ge=0, le=1)
    min_delay_s: float = 2.0
    max_delay_s: float = 5.0


class OutboxSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OUTBOX_", env_file=".env", extra="ignore")

    poll_interval_s: float = 1.0
    batch_size: int = 50


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # default_factory: nested settings are built when Settings() is, not at import time.
    db: DatabaseSettings = Field(default_factory=DatabaseSettings)
    rabbitmq: RabbitMQSettings = Field(default_factory=RabbitMQSettings)
    consumer: ConsumerSettings = Field(default_factory=ConsumerSettings)
    gateway: GatewaySettings = Field(default_factory=GatewaySettings)
    outbox: OutboxSettings = Field(default_factory=OutboxSettings)

    api_key: SecretStr
    log_level: str = "INFO"
    cors_origins: str = "*"


settings = Settings()
