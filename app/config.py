from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "LLM Shadow Evaluator"
    environment: str = "development"
    log_level: str = "INFO"

    database_url: str = "sqlite+aiosqlite:///./evaluator.db"
    sample_rate: float = Field(default=0.1, ge=0, le=1)
    max_prompt_chars: int = Field(default=32_000, ge=1)

    primary_provider: Literal["mock", "openai"] = "mock"
    primary_base_url: str | None = None
    primary_api_key: str = ""
    primary_model: str = "primary-mock"

    candidate_provider: Literal["mock", "openai"] = "mock"
    candidate_base_url: str | None = None
    candidate_api_key: str = ""
    candidate_model: str = "candidate-mock"

    llm_timeout_seconds: float = Field(default=30, gt=0)
    llm_max_retries: int = Field(default=2, ge=0)

    score_backend: Literal["heuristic", "llm"] = "heuristic"
    judge_base_url: str | None = None
    judge_api_key: str = ""
    judge_model: str = ""
    judge_max_chars: int = Field(default=12_000, ge=100)

    queue_backend: Literal["database", "sqs", "azure"] = "database"
    queue_visibility_seconds: int = Field(default=120, ge=1)
    queue_max_attempts: int = Field(default=3, ge=1)
    worker_poll_seconds: float = Field(default=2, gt=0)

    aws_region: str | None = None
    sqs_queue_url: str = ""
    azure_service_bus_connection_string: str = ""
    azure_service_bus_queue_name: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
