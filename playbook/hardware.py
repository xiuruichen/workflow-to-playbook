"""Pick a local vision model and analysis settings that fit this machine."""

from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass


@dataclass
class Hardware:
    ram_gb: float
    available_gb: float
    vram_gb: float  # dedicated GPU memory (NVIDIA); 0 if none / unknown
    apple_silicon: bool
    cpu_threads: int


@dataclass
class Tier:
    name: str  # "tiny" | "small" | "medium" | "large"
    model: str  # Ollama base tag
    window_size: int  # keyframes per request
    image_width: int  # longest side of images sent to the model
    num_ctx: int  # context window to configure in Ollama
    reason: str


def detect() -> Hardware:
    try:
        import psutil

        vm = psutil.virtual_memory()
        ram, avail = vm.total / 2**30, vm.available / 2**30
        threads = psutil.cpu_count() or 1
    except Exception:
        ram = avail = 8.0
        threads = 4
    vram = 0.0
    if shutil.which("nvidia-smi"):
        try:
            out = subprocess.run(
                ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5,
            ).stdout
            vram = max((float(x) for x in out.split() if x.strip()), default=0.0) / 1024
        except Exception:
            vram = 0.0
    apple = sys.platform == "darwin" and _is_arm_mac()
    return Hardware(round(ram, 1), round(avail, 1), round(vram, 1), apple, threads)


def _is_arm_mac() -> bool:
    import platform

    return platform.machine() == "arm64"


def cpu_threads(settings) -> int | None:
    """Thread cap for heavy work (None = no cap)."""
    if settings.max_threads > 0:
        return settings.max_threads
    return 4 if settings.low_power else None


def be_gentle(settings) -> None:
    """In low-power mode, run this process at below-normal priority so the desktop stays responsive."""
    if not settings.low_power:
        return
    try:
        import psutil

        p = psutil.Process()
        p.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS if sys.platform == "win32" else 10)
    except Exception:
        pass


def low_power_tier(hw: Hardware) -> Tier:
    return Tier("tiny", "qwen3-vl:2b", 3, 896, 4096, "low-power mode")


def choose_tier(hw: Hardware) -> Tier:
    """Biggest Qwen3-VL model that runs comfortably; smaller inputs for smaller models."""
    # Apple silicon shares RAM with a capable GPU, so treat ~70% of RAM as usable "VRAM".
    gpu = max(hw.vram_gb, hw.ram_gb * 0.7 if hw.apple_silicon else 0.0)
    if gpu >= 24:
        return Tier("large", "qwen3-vl:32b", 8, 1280, 32768, f"{gpu:.0f} GB of GPU memory")
    if gpu >= 8 or hw.ram_gb >= 16:
        why = f"{gpu:.0f} GB of GPU memory" if gpu >= 8 else f"{hw.ram_gb:.0f} GB RAM"
        return Tier("medium", "qwen3-vl:8b", 6, 1280, 16384, why)
    if hw.ram_gb >= 7 and hw.available_gb >= 3.5:
        return Tier("small", "qwen3-vl:4b", 4, 1024, 8192, f"{hw.ram_gb:.0f} GB RAM, no large GPU")
    return Tier("tiny", "qwen3-vl:2b", 3, 896, 6144, f"only {hw.available_gb:.1f} GB RAM free")


def tier_for_model(model: str) -> Tier:
    """Analysis settings for an explicitly chosen model tag (by its parameter count)."""
    tag = model.lower()
    for size, tier in (("32b", "large"), ("30b", "large"), ("8b", "medium"), ("7b", "medium"), ("12b", "medium"), ("2b", "tiny")):
        if size in tag:
            return {
                "large": Tier("large", model, 8, 1280, 32768, "configured"),
                "medium": Tier("medium", model, 6, 1280, 16384, "configured"),
                "tiny": Tier("tiny", model, 3, 896, 6144, "configured"),
            }[tier]
    return Tier("small", model, 4, 1024, 8192, "configured")
