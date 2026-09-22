from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Data Shopper"
    db_url: str = "sqlite:///./qcom.db"
    openai_api_key: str | None = None
    gemini_api_key: str | None = None
    openrouter_api_key: str | None = None
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    llm_verify_ssl: bool = True
    http_ca_bundle: str | None = None
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
    hf_token: str | None = None  # Hugging Face token for gated model access (indic-conformer)
    indic_conformer_model: str = "ai4bharat/indic-conformer-600m-multilingual"
    indic_conformer_decode_strategy: str = "ctc"  # "ctc" (faster) or "rnnt" (more accurate)
    indic_tts_enabled: bool = True
    indic_tts_timeout_seconds: float = 6.0  # fall back to browser TTS if generation takes longer than this

    model_config = SettingsConfigDict(env_file=("../.env", ".env"), env_file_encoding="utf-8", extra="ignore")

    def resolved_http_ca_bundle(self) -> str | None:
        """Return an absolute CA bundle path when one is configured."""
        if not self.http_ca_bundle:
            return None
        bundle = Path(self.http_ca_bundle).expanduser()
        if not bundle.is_absolute():
            bundle = Path(__file__).resolve().parent.parent / bundle
        return str(bundle)


@lru_cache
def get_settings() -> Settings:
    return Settings()
