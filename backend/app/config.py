from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/order_supervisor"

    temporal_host: str = "localhost:7233"
    temporal_namespace: str = "default"
    temporal_task_queue: str = "order-supervisor"

    anthropic_api_key: str = ""
    llm_model: str = "claude-sonnet-4-6"
    # auto: use LLM only when a key is present; true: require it; false: always mock
    use_llm: str = "auto"

    @property
    def llm_enabled(self) -> bool:
        if self.use_llm.lower() == "false":
            return False
        if self.use_llm.lower() == "true":
            return True
        return bool(self.anthropic_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
