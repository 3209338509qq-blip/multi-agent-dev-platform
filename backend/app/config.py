"""平台配置：环境变量集中管理（pydantic-settings）。

所有可调参数在此定义，.env 覆盖默认值（见 .env.example）。
"""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent  # backend/


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR.parent / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---- LLM ----
    llm_provider: str = "openai_compatible"
    llm_base_url: str = "https://api.deepseek.com/v1"
    llm_api_key: str = ""
    llm_model: str = "deepseek-chat"
    llm_max_tokens: int = 4096
    llm_temperature: float = 0.2
    llm_timeout_seconds: float = 120.0
    llm_max_retries: int = 3

    # ---- 数据库 ----
    database_url: str = "sqlite+aiosqlite:///" + str(BASE_DIR / "data" / "platform.db")

    # ---- Redis / 事件总线 ----
    redis_url: str = ""

    # ---- 工作区与运行参数 ----
    workspace_root: str = str(BASE_DIR.parent / "workspace")
    sandbox_backend: str = "local"          # local | docker
    agent_timeout_seconds: float = 1800.0
    task_max_retries: int = 2
    debug_max_rounds: int = 3
    project_token_budget: int = 600_000
    max_parallel_tasks: int = 2

    # ---- Web ----
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
