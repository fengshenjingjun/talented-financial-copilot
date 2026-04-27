import os
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

load_dotenv()


class Settings(BaseSettings):
    # LLM models (tiered by task complexity)
    router_model: str = "claude-haiku-4-5-20251001"      # lightweight: intent routing
    analysis_model: str = "claude-sonnet-4-6"             # powerful: financial analysis
    chat_model: str = "claude-haiku-4-5-20251001"         # lightweight: casual chat

    # Anthropic
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")

    # Storage (in-memory fallback when URLs not set)
    redis_url: str = ""
    mongo_url: str = ""
    mongo_db: str = "financial_copilot"

    # Stability knobs
    tool_timeout_seconds: int = 10
    circuit_breaker_threshold: int = 5     # failures before open
    circuit_breaker_reset_seconds: int = 60
    max_turns_per_session: int = 50

    # LLM parameters
    router_temperature: float = 0.0        # deterministic routing
    analysis_temperature: float = 0.3
    chat_temperature: float = 0.7

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
