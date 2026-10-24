"""Runtime configuration, loaded from environment variables and `.env`."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- Vision API (Gemini via its OpenAI-compatible endpoint) ---
    gemini_api_key: str = Field(
        default="", validation_alias=AliasChoices("GEMINI_API_KEY", "GOOGLE_API_KEY")
    )
    gemini_model: str = "gemini-3.5-flash"
    # Tried in order when the model is unavailable or out of free quota (filtered to models the key can see).
    gemini_fallback_models: str = "gemini-3.5-flash,gemini-3.6-flash,gemini-3-flash-preview,gemini-3.5-flash-lite,gemini-3.1-flash-lite,gemini-2.5-flash-lite,gemini-flash-lite-latest"
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai/"
    rpm_limit: int = 5
    request_timeout_s: float = 120.0

    # --- Analysis ---
    confidence_threshold: float = 0.70
    window_size: int = 10  # keyframes per vision call (consecutive windows share one frame)
    max_image_width: int = 1280

    # --- Capture ---
    capture_fps: float = 5.0
    record_max_width: int = 1920  # recording video is downscaled to this width
    heartbeat_s: float = 10.0
    change_threshold: float = 0.02  # fraction of changed pixels that counts as a "visual change"
    settle_s: float = 0.8  # delay after an event before grabbing the "after" frame
    mask_typed_text: bool = False
    monitor: int = 1  # mss monitor index (1 = primary)

    # --- Storage ---
    sessions_dir: Path = PROJECT_ROOT / "sessions"
    cache_dir: Path = PROJECT_ROOT / ".cache"


@lru_cache
def get_settings() -> Settings:
    return Settings()
