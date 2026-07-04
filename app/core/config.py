from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache

class Settings(BaseSettings):
    PROJECT_NAME: str = "Generic Interview API"
    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "INFO"
    PORT: int = 8000

    # Add other environment variables here (e.g., DB_URL, API_KEYS)
    # DATABASE_URL: str

    # Candidate (shadow) model — DigitalOcean Serverless Inference
    # Model IDs from DO catalog: "openai-gpt-5-mini" (fast/cheap) or "openai-gpt-5".
    CANDIDATE_BASE_URL: str = "https://inference.do-ai.run/v1"
    CANDIDATE_MODEL: str = "openai-gpt-5-mini"
    MODEL_ACCESS_KEY: str = ""  # secret, from env only (sk-do-... / doo_v1_...)
    CANDIDATE_TIMEOUT_S: float = 30.0
    CANDIDATE_MAX_RETRIES: int = 2

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

@lru_cache()
def get_settings() -> Settings:
    return Settings()

settings = get_settings()
