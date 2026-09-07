from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Signal Selector"
    db_url: str = "sqlite:///./qcom.db"
    openai_api_key: str | None = None
    gemini_api_key: str | None = None
    openrouter_api_key: str | None = None
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    llm_provider: str = "gemini"
    llm_model: str = "gemini-2.5-flash"
    llm_max_tokens: int = 500
    chroma_path: str = "./chroma_data"
    chroma_enabled: bool = False
    mapbox_token: str | None = None
    api_base_url: str = "http://localhost:8000"
    razorpay_key_id: str | None = None
    razorpay_key_secret: str | None = None

    # Voice mode
    voice_enabled: bool = True
    whisper_model_size: str = "medium"  # tiny/base/small/medium/large-v3 - bump if you get a GPU
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"  # int8 is fastest on CPU with minimal accuracy loss
    indic_tts_enabled: bool = True
    indic_tts_timeout_seconds: float = 6.0  # fall back to browser TTS if generation takes longer than this

    model_config = SettingsConfigDict(env_file=("../.env", ".env"), env_file_encoding="utf-8", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
