"""`python -m playbook setup-local` / `check`: get a local vision model running with Ollama.

Talks only to the Ollama server configured in LOCAL_BASE_URL (refused unless it is on this
machine or the private network). The one network download is `ollama pull`, which Ollama
itself performs, after the user confirms.
"""

from __future__ import annotations

import json
import shutil
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

from .backend import LOCAL_ALIAS, OUT_OF_MEMORY_HINT, is_out_of_memory, local_setup_info
from .config import Settings
from .hardware import Tier, choose_tier, cpu_threads, detect, low_power_tier
from .security import check_endpoint

# Approximate download sizes (GB), to check disk space before pulling.
MODEL_SIZES_GB = {"qwen3-vl:2b-instruct": 1.9, "qwen3-vl:4b-instruct": 3.3, "qwen3-vl:8b-instruct": 6.1, "qwen3-vl:30b-instruct": 19.0, "qwen3-vl:32b-instruct": 21.0}
INSTALL_HINT = (
    "Install Ollama from https://ollama.com/download (Windows: `winget install Ollama.Ollama`; "
    "macOS: the app or `brew install ollama`; Linux: the install script on that page), start it, then run this again."
)


class SetupError(RuntimeError):
    pass


def _api_root(s: Settings) -> str:
    check_endpoint(s.local_base_url, s.allow_cloud)
    root = s.local_base_url.rstrip("/")
    return root[:-3] if root.endswith("/v1") else root


def _request(s: Settings, path: str, payload: dict | None = None, timeout: float = 10.0):
    req = urllib.request.Request(_api_root(s) + path, data=json.dumps(payload).encode() if payload is not None else None,
                                 headers={"Content-Type": "application/json"}, method="POST" if payload is not None else "GET")
    return urllib.request.urlopen(req, timeout=timeout)


def server_version(s: Settings) -> str | None:
    try:
        with _request(s, "/api/version", timeout=3) as r:
            return json.load(r).get("version", "?")
    except (urllib.error.URLError, OSError, ValueError):
        return None


def installed_models(s: Settings) -> list[str]:
    with _request(s, "/api/tags") as r:
        return [m["name"] for m in json.load(r).get("models", [])]


def _has(models: list[str], tag: str) -> bool:
    return tag in models or f"{tag}:latest" in models


def models_dir() -> Path:
    import os

    return Path(os.environ.get("OLLAMA_MODELS") or Path.home() / ".ollama" / "models")


def free_gb(path: Path) -> float:
    path = Path(path)
    while not path.exists() and path.parent != path:
        path = path.parent
    return shutil.disk_usage(path).free / 2**30


def pull(s: Settings, tag: str, out: Callable[[str], None] = print) -> None:
    """Stream `ollama pull` progress."""
    with _request(s, "/api/pull", {"model": tag, "stream": True}, timeout=3600) as r:
        last = ""
        for line in r:
            msg = json.loads(line)
            if "error" in msg:
                raise SetupError(f"ollama pull {tag} failed: {msg['error']}")
            status = msg.get("status", "")
            if msg.get("total"):
                status += f" {msg.get('completed', 0) / msg['total'] * 100:5.1f}%"
            if status != last:
                out(f"\r  {status:<60}")
                last = status
    out("\n")


def create_alias(s: Settings, tier: Tier) -> None:
    """`playbook-vl`: the chosen model with a context window big enough for several screenshots
    (and, in low-power mode, a cap on the CPU threads it may use)."""
    params = {"num_ctx": tier.num_ctx}
    if threads := cpu_threads(s):
        params["num_thread"] = threads
    payload = {"model": LOCAL_ALIAS, "from": tier.model, "parameters": params, "stream": False}
    with _request(s, "/api/create", payload, timeout=600) as r:
        r.read()
    s.data_dir.mkdir(parents=True, exist_ok=True)
    (s.data_dir / "local_model.json").write_text(
        json.dumps({"base": tier.model, "tier": tier.name, "num_ctx": tier.num_ctx, "num_thread": params.get("num_thread")},
                   indent=2), encoding="utf-8")


def smoke_test(s: Settings, model: str) -> tuple[float, str]:
    """One screenshot-like request; returns (seconds, reply)."""
    import base64

    import cv2
    import numpy as np
    from openai import OpenAI

    img = np.full((400, 700, 3), 245, np.uint8)
    cv2.rectangle(img, (240, 170), (460, 230), (200, 120, 30), -1)
    cv2.putText(img, "Submit order", (262, 210), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
    ok, buf = cv2.imencode(".jpg", img)
    url = "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode()
    client = OpenAI(api_key="ollama", base_url=s.local_base_url, timeout=s.local_timeout_s, max_retries=0)
    t = time.time()
    resp = client.chat.completions.create(model=model, temperature=0, messages=[{"role": "user", "content": [
        {"type": "text", "text": 'What does the button say? Reply as JSON: {"label": "..."}'},
        {"type": "image_url", "image_url": {"url": url}},
    ]}], response_format={"type": "json_object"}, max_tokens=200)
    return time.time() - t, (resp.choices[0].message.content or "").strip()


def setup(s: Settings, model: str | None = None, assume_yes: bool = False, out: Callable[[str], None] = print,
          ask: Callable[[str], str] = input) -> int:
    version = server_version(s)
    if not version:
        out(f"Ollama is not reachable at {_api_root(s)}.\n{INSTALL_HINT}")
        return 1
    hw = detect()
    tier = low_power_tier(hw) if s.low_power else choose_tier(hw)
    if model:
        from .hardware import tier_for_model

        tier = tier_for_model(model)
    out(f"Ollama {version} at {_api_root(s)}")
    out(f"This computer: {hw.ram_gb:.0f} GB RAM ({hw.available_gb:.1f} GB free), "
        f"{f'{hw.vram_gb:.0f} GB NVIDIA GPU' if hw.vram_gb else 'Apple silicon' if hw.apple_silicon else 'no dedicated GPU'}, "
        f"{hw.cpu_threads} CPU threads")
    out(f"Model: {tier.model} ({tier.name} tier: {tier.reason}); {tier.window_size} screenshots per request at {tier.image_width}px"
        + (f"; limited to {cpu_threads(s)} CPU threads" if cpu_threads(s) else ""))

    models = installed_models(s)
    if not _has(models, tier.model):
        need, free = MODEL_SIZES_GB.get(tier.model, 4.0), free_gb(models_dir())
        if free < need + 1:
            out(f"Not enough disk space to download {tier.model}: it needs about {need:.1f} GB and {free:.1f} GB is free "
                f"in {models_dir()}. Free up space (or set OLLAMA_MODELS to another drive), or pick a smaller model "
                "with --model qwen3-vl:2b-instruct.")
            return 1
        if not assume_yes and ask(f"Download {tier.model} (~{need:.1f} GB) with Ollama now? [y/N] ").strip().lower() not in ("y", "yes"):
            out("Cancelled.")
            return 1
        pull(s, tier.model, out)
    create_alias(s, tier)
    out(f"Created `{LOCAL_ALIAS}` (= {tier.model}, context {tier.num_ctx} tokens). Testing it with one screenshot...")
    try:
        secs, reply = smoke_test(s, LOCAL_ALIAS)
    except Exception as exc:
        out(OUT_OF_MEMORY_HINT if is_out_of_memory(exc) else f"The test request failed: {str(exc)[:300]}")
        out("The model is installed; run `python -m playbook setup-local` again to re-test.")
        return 1
    out(f"  reply: {reply[:80]}  ({secs:.1f}s for one image)")
    out("Ready. Analysis now runs on this computer; screenshots never leave it.")
    return 0


def status(s: Settings) -> list[str]:
    """Lines for `python -m playbook check` with the local provider."""
    lines = []
    version = server_version(s)
    if not version:
        return [f"FAIL Ollama not reachable at {_api_root(s)}. {INSTALL_HINT}"]
    lines.append(f"OK   Ollama {version} at {_api_root(s)}")
    models = installed_models(s)
    info = local_setup_info(s)
    if info:
        mark = "OK  " if _has(models, LOCAL_ALIAS) else "FAIL"
        lines.append(f"{mark} {LOCAL_ALIAS} -> {info.get('base')} ({info.get('tier')} tier, context {info.get('num_ctx')})")
    else:
        tier = choose_tier(detect())
        mark = "OK  " if _has(models, tier.model) else "FAIL"
        lines.append(f"{mark} {tier.model} (auto-picked: {tier.reason}); run `python -m playbook setup-local` to finish setup")
    vision = [m for m in models if any(k in m for k in ("vl", "llava", "gemma3", "minicpm-v", "moondream"))]
    lines.append(f"     installed vision models: {', '.join(vision) or 'none'}")
    return lines
