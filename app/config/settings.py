from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.config.consumer import ConsumerSettings
from app.config.database import DatabaseSettings
from app.config.expiry import ExpirySettings
from app.config.gateway import GatewaySettings
from app.config.outbox import OutboxSettings
from app.config.rabbitmq import RabbitMQSettings


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # default_factory: nested settings are built when Settings() is, not at import time.
    db: DatabaseSettings = Field(default_factory=DatabaseSettings)
    rabbitmq: RabbitMQSettings = Field(default_factory=RabbitMQSettings)
    consumer: ConsumerSettings = Field(default_factory=ConsumerSettings)
    gateway: GatewaySettings = Field(default_factory=GatewaySettings)
    outbox: OutboxSettings = Field(default_factory=OutboxSettings)
    expiry: ExpirySettings = Field(default_factory=ExpirySettings)

    api_key: SecretStr
    log_level: str = "INFO"
    cors_origins: str = "*"


settings = Settings()
