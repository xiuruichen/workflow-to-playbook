"""Resolve which vision backend to use (local Ollama by default) and with what settings."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from .config import Settings
from .hardware import Tier, choose_tier, detect, low_power_tier, tier_for_model
from .security import SecurityError, check_endpoint

LOCAL_ALIAS = "playbook-vl"  # created by `python -m playbook setup-local` with a suitable context size


@dataclass
class Backend:
    provider: str  # "local" | "gemini"
    base_url: str
    api_key: str
    model: str
    fallbacks: list[str]
    rpm: int  # 0 = no pacing
    timeout_s: float
    window_size: int
    image_width: int
    local: bool
    tier: Tier | None = None
    notes: list[str] = field(default_factory=list)
    server: dict | None = None  # llama runtime: what to start for the analysis (see llama_runtime.serving)


OUT_OF_MEMORY_HINT = (
    "The local model couldn't load: this computer is out of memory. Close memory-heavy apps (browser tabs, "
    "editors, OneNote) and try again, or set LOW_POWER=true and re-run `python -m playbook setup-local` "
    "to use the smallest model."
)


EMPTY_REPLY_HINT = (
    "The local model keeps returning empty replies. Usually this means it is a \"thinking\" model that spends its "
    "whole budget reasoning (use an -instruct tag, e.g. qwen3-vl:2b-instruct, and re-run `python -m playbook "
    "setup-local`), or the computer is short on memory (close apps and try again)."
)


def is_out_of_memory(exc: Exception) -> bool:
    text = str(exc).lower()
    return "failed to allocate" in text or "out of memory" in text or "out-of-memory" in text


def _split(models: str) -> list[str]:
    return [m.strip() for m in models.split(",") if m.strip()]


def local_setup_info(s: Settings) -> dict:
    """What `setup-local` configured on this machine (base model + tier), if anything."""
    try:
        return json.loads((s.data_dir / "local_model.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def resolve_backend(s: Settings) -> Backend:
    if s.provider == "gemini":
        if not s.allow_cloud:
            raise SecurityError(
                "PROVIDER=gemini uploads screenshots to Google, and cloud analysis is disabled. "
                "Set ALLOW_CLOUD=true to allow it, or use the default local provider."
            )
        check_endpoint(s.gemini_base_url, allow_cloud=True)
        return Backend(
            provider="gemini", base_url=s.gemini_base_url, api_key=s.gemini_api_key, model=s.gemini_model,
            fallbacks=_split(s.gemini_fallback_models), rpm=s.rpm_limit, timeout_s=s.request_timeout_s,
            window_size=s.window_size or 10, image_width=s.analysis_image_width or s.max_image_width, local=False,
        )

    info = local_setup_info(s) if s.local_model == "auto" else {}
    if info.get("runtime") == "llama":
        from .llama_runtime import api_key

        tier = tier_for_model(info["base"])
        return Backend(
            provider="local", base_url=f"http://127.0.0.1:{s.llama_port}/v1", api_key=api_key(s), model=info["base"], fallbacks=[], rpm=0,
            timeout_s=s.local_timeout_s, window_size=s.window_size or min(tier.window_size, 3 if s.low_power else 99),
            image_width=s.analysis_image_width or min(tier.image_width, 896 if s.low_power else 9999),
            local=True, tier=tier, server=info,
        )
    check_endpoint(s.local_base_url, s.allow_cloud)
    if s.local_model == "auto":
        if info.get("base"):
            tier = tier_for_model(info["base"])
            model = LOCAL_ALIAS
        else:
            tier = low_power_tier(detect()) if s.low_power else choose_tier(detect())
            model = tier.model
    else:
        tier = tier_for_model(s.local_model)
        model = s.local_model
    return Backend(
        provider="local", base_url=s.local_base_url, api_key="ollama", model=model,
        fallbacks=_split(s.local_fallback_models), rpm=0, timeout_s=s.local_timeout_s,
        window_size=s.window_size or tier.window_size, image_width=s.analysis_image_width or tier.image_width,
        local=True, tier=tier,
    )
