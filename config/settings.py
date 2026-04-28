import os
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

load_dotenv()


class Settings(BaseSettings):
    # Provider selection
    llm_provider_primary: str = "anthropic"  # anthropic | openai | qwen
    llm_fallback_enabled: bool = True

    # API Keys
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    qwen_api_key: str = os.getenv("QWEN_API_KEY", "")

    # Model tiers — Anthropic
    router_model_anthropic: str = "claude-haiku-4-5-20251001"
    analysis_model_anthropic: str = "claude-sonnet-4-6"
    chat_model_anthropic: str = "claude-haiku-4-5-20251001"

    # Model tiers — OpenAI
    router_model_openai: str = "gpt-4o-mini"
    analysis_model_openai: str = "gpt-4o"
    chat_model_openai: str = "gpt-4o-mini"

    # Model tiers — Qwen (DashScope)
    router_model_qwen: str = "qwen-turbo"
    analysis_model_qwen: str = "qwen-max"
    chat_model_qwen: str = "qwen-turbo"

    # Backward-compat aliases (resolved at runtime by factory)
    router_model: str = "claude-haiku-4-5-20251001"
    analysis_model: str = "claude-sonnet-4-6"
    chat_model: str = "claude-haiku-4-5-20251001"

    # Storage (in-memory fallback when URLs not set)
    redis_url: str = ""
    mongo_url: str = ""
    mongo_db: str = "financial_copilot"

    # Stability knobs
    tool_timeout_seconds: int = 10
    circuit_breaker_threshold: int = 5
    circuit_breaker_reset_seconds: int = 60
    max_turns_per_session: int = 50

    # LLM parameters
    router_temperature: float = 0.0
    analysis_temperature: float = 0.3
    chat_temperature: float = 0.7

    # API server
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: list[str] = ["*"]

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
