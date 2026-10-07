from pydantic_settings import BaseSettings, SettingsConfigDict


class RabbitMQSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RABBITMQ_", env_file=".env", extra="ignore")

    host: str = "localhost"
    port: int = 5672
    default_user: str = "guest"
    default_pass: str = "guest"

    @property
    def url(self) -> str:
        return f"amqp://{self.default_user}:{self.default_pass}@{self.host}:{self.port}/"
