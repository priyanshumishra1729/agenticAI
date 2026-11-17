import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]

# Silence framework telemetry before CrewAI / ADK are imported anywhere.
os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")
os.environ.setdefault("OTEL_SDK_DISABLED", "true")
os.environ.setdefault("CREWAI_TRACING_ENABLED", "false")


class Settings(BaseSettings):
    app_name: str = "signalchain"
    environment: str = "development"
    database_url: str = f"sqlite:///{(BACKEND_DIR / 'signalchain.db').as_posix()}"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173"
    upload_dir: str = str(BACKEND_DIR / "uploads")
    max_upload_size_mb: int = 10

    # LLM configuration. "auto" uses Gemini when a key is present, otherwise the
    # deterministic offline simulator (the real CrewAI / ADK runtimes still execute).
    llm_mode: str = "auto"  # auto | gemini | simulated
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"

    # A2A: "inprocess" sends real JSON-RPC over an ASGI transport to this app.
    # Set to an http(s) URL to call a remotely deployed CrewAI specialist.
    a2a_crewai_url: str = "inprocess"
    public_base_url: str = "http://localhost:8000"

    # External tool (Open-Meteo, no key required). Disable for fully offline runs.
    enable_external_apis: bool = True

    # Optional Langfuse export (traces are always stored locally as well).
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"

    # Cost model (USD per 1M tokens) – Gemini 2.5 Flash list price.
    price_input_per_m: float = 0.30
    price_output_per_m: float = 2.50

    frontend_dist: str = str(BACKEND_DIR.parent / "frontend" / "dist")

    model_config = SettingsConfigDict(
        env_file=(str(BACKEND_DIR.parent / ".env"), str(BACKEND_DIR / ".env")),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def use_gemini(self) -> bool:
        if self.llm_mode == "simulated":
            return False
        if self.llm_mode == "gemini":
            return True
        return bool(self.gemini_api_key)


settings = Settings()
if settings.gemini_api_key:
    os.environ.setdefault("GEMINI_API_KEY", settings.gemini_api_key)
    os.environ.setdefault("GOOGLE_API_KEY", settings.gemini_api_key)
