from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import RedisDsn
from src.constants import Environment


class Config(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    ENVIRONMENT: Environment = Environment.DEVELOPMENT
    GEMINI_API_KEY: str | None = None
    OPENAI_API_KEY: str | None = None
    GEMINI_MODEL: str = "gemini-3-flash-preview"
    PARSING_AGENT_GEMINI_MODEL: str = "gemini-3-pro"
    EXECUTION_AGENT_GEMINI_MODEL: str = "gemini-3-flash-preview"
    EXECUTION_AGENT_MAX_TOOL_CALLS: int = 4
    REDIS_URL: RedisDsn
    FIREBASE_PROJECT_ID: str
    FIREBASE_CLIENT_EMAIL: str
    FIREBASE_PRIVATE_KEY: str
    RESTAURANT_ID: str
    MERCHANT_ID: str | None = None
    DEFAULT_PREVIOUS_MESSAGES_K: int = 10
    # Clover REST API origin (no trailing slash). Sandbox NA default; production: https://api.clover.com
    CLOVER_API_BASE_URL: str = "https://apisandbox.dev.clover.com"
    # Clover app ID (OAuth client_id); required on server for /oauth/v2/refresh unless stored on the Clover Firestore doc
    CLOVER_APP_ID: str | None = None


settings = Config()
