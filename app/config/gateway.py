from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class GatewaySettings(BaseSettings):
    """Payment gateway emulation."""

    model_config = SettingsConfigDict(env_prefix="GATEWAY_", env_file=".env", extra="ignore")

    failure_rate: float = Field(default=0.1, ge=0, le=1)
    min_delay_s: float = 2.0
    max_delay_s: float = 5.0
