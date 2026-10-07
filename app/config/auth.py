from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class AuthSettings(BaseSettings):
    """API authentication."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    api_key: SecretStr
