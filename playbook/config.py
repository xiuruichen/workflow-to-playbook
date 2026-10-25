"""Runtime configuration, loaded from environment variables and `.env`."""

from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def default_data_dir() -> Path:
    """Per-user local app-data folder (never inside a cloud-synced folder by default)."""
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / "WorkflowPlaybook"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- Where analysis runs ---
    # "local": a vision model on this machine via Ollama (default; nothing leaves the machine).
    # "gemini": Google's API. Only allowed with ALLOW_CLOUD=true, because screenshots are uploaded.
    provider: Literal["local", "gemini"] = "local"
    allow_cloud: bool = False

    # --- Local vision model (Ollama, OpenAI-compatible endpoint) ---
    local_base_url: str = "http://127.0.0.1:11434/v1"
    local_model: str = "auto"  # "auto" picks by RAM/VRAM (see hardware.py), or an Ollama tag
    local_fallback_models: str = "playbook-vl,qwen3-vl:4b-instruct,qwen3-vl:8b-instruct,qwen3-vl:2b-instruct,gemma3:4b"
    local_max_tokens: int = 3000  # cap per reply, so a rambling model can't hold a request for many minutes
    local_timeout_s: float = 1800.0  # CPU inference on a laptop can take many minutes; a timeout restarts from zero

    # --- Cloud vision model (Gemini via its OpenAI-compatible endpoint; opt-in) ---
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
    window_size: int = 0  # keyframes per vision call; 0 = auto (smaller for small local models)
    analysis_image_width: int = 0  # width of images sent to the model; 0 = auto
    max_image_width: int = 1280  # width keyframes are stored at
    # Low-power mode for slow machines: smallest local model, capped CPU threads, below-normal
    # priority, and hardware-only video encoding when archiving.
    low_power: bool = False
    max_threads: int = 0  # CPU threads for the model / OCR / encoders; 0 = all (4 in low-power mode)
    use_ocr: bool = True  # local OCR of keyframes: exact on-screen text for the model and the consistency check
    send_crops: bool = True  # also send a zoomed crop around each click

    # --- Capture ---
    capture_fps: float = 5.0
    record_max_width: int = 1920  # recording video is downscaled to this width
    heartbeat_s: float = 10.0
    change_threshold: float = 0.02  # fraction of changed pixels that counts as a "visual change"
    settle_s: float = 0.8  # delay after an event before grabbing the "after" frame
    mask_typed_text: bool = False
    capture_window_titles: bool = True  # record the focused app/window title with each event (Windows)
    capture_ui_elements: bool = True  # record the UI element clicked / typed into (Windows UI Automation)
    monitor: int = 1  # mss monitor index (1 = primary)

    # --- Storage ---
    data_dir: Path = Field(default_factory=default_data_dir)
    sessions_dir: Path = Field(default_factory=lambda: default_data_dir() / "sessions")
    cache_dir: Path = Field(default_factory=lambda: default_data_dir() / "cache")
    allow_synced_dir: bool = False  # permit storing recordings in OneDrive/Dropbox/iCloud/Google Drive
    # When to compress + encrypt sessions into .pbx archives: "idle:<days>" (default: sessions
    # untouched for 2 days, checked whenever the CLI or app starts), "after_analysis", or "off".
    auto_compact: str = "idle:2"
    # Video in archives: "compress" (AV1, lossy but sharp; keyframes stay lossless), "original", or "drop".
    archive_video: Literal["compress", "original", "drop"] = "compress"
    archive_passphrase: str = ""  # only used when no OS keyring is available to hold the archive key


@lru_cache
def get_settings() -> Settings:
    return Settings()
