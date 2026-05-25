from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

Provider = Literal["anthropic", "openai", "groq", "local"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    anthropic_api_key: str = ""
    openai_api_key: str = ""
    groq_api_key: str = ""

    llm_orchestrator_provider: Provider = "anthropic"
    llm_orchestrator_model: str = "claude-sonnet-4-6"
    llm_validator_provider: Provider = "openai"
    llm_validator_model: str = "gpt-4o"
    llm_utility_provider: Provider = "groq"
    llm_utility_model: str = "llama-3.1-8b-instant"

    embeddings_provider: Provider = "local"
    embeddings_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"

    database_url: str = "postgresql://partselect:partselect@localhost:5432/partselect"
    chroma_path: str = "./data/chroma"
    kg_path: str = "./data/kg.json"

    cors_origins: str = "http://localhost:3000"
    log_level: str = "INFO"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def project_root(self) -> Path:
        return Path(__file__).resolve().parents[2]


settings = Settings()
