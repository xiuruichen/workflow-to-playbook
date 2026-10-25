"""Local llama.cpp runtime (`llama-server`): the lighter, faster option for low-power computers.

Compared with Ollama on a laptop CPU it is about twice as fast for the same model: Ollama scales
every screenshot to ~1,000 tokens, while llama-server keeps it at its native size
(`--image-max-tokens`), and it reuses the cached system prompt across requests. The server is
started only for the length of an analysis, so it holds no memory in between.

Downloads (the server build from GitHub and the model files from Hugging Face) happen only in
`python -m playbook setup-local --runtime llama`, after the user confirms, and are checked against
pinned SHA-256 hashes. Analysis itself only talks to the server on 127.0.0.1.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator

from .config import Settings
from .hardware import cpu_threads

# PrismML's llama.cpp build (upstream llama.cpp plus ternary kernels), pinned. Bonsai 2 2B/4B were tried on a
# low-power laptop: the 2B lost accuracy and the 4B was ~4x slower than Qwen3-VL 2B (see NOTES.md).
RELEASE = "prism-b10777-e3de715"
_GH = f"https://github.com/PrismML-Eng/llama.cpp/releases/download/{RELEASE}/"
RUNTIMES = {  # (sys.platform, machine) -> (zip url, sha256)
    ("win32", "amd64"): (_GH + f"llama-{RELEASE}-bin-win-cpu-x64.zip",
                         "cff7eeff19163e6263720618cf98023715b8dac14d0873f5be0918765de323c4"),
    ("win32", "arm64"): (_GH + f"llama-{RELEASE}-bin-win-cpu-arm64.zip",
                         "b63c740d4fad53db482b70022d7574884751277f4569e3be20908df081bbde95"),
}
_HF = "https://huggingface.co/{repo}/resolve/main/{file}"
MODELS = {
    # name -> tier, then (repo, file, sha256) for the language model and the vision projector
    "qwen3-vl-2b": {
        "tier": "tiny", "gb": 1.5,
        "model": ("Qwen/Qwen3-VL-2B-Instruct-GGUF", "Qwen3VL-2B-Instruct-Q4_K_M.gguf",
                  "089d75c52f4b7ffc56ba998ffc50aae89fcafc755f9e7208aacca281dca6c2ae"),
        "mmproj": ("Qwen/Qwen3-VL-2B-Instruct-GGUF", "mmproj-Qwen3VL-2B-Instruct-Q8_0.gguf",
                   "f9a68fabba69c3b81e153367b2c7521030b0fa8bb0de400c9599c8e6725f9c82"),
    },
}
DEFAULT_MODEL = "qwen3-vl-2b"
DEFAULT_PORT = 8080
CONTEXT = 8192


class LlamaError(RuntimeError):
    pass


def home(s: Settings) -> Path:
    return s.data_dir / "llama"


def server_exe(s: Settings) -> Path:
    if s.llama_server:
        return Path(s.llama_server)
    return home(s) / "bin" / ("llama-server.exe" if sys.platform == "win32" else "llama-server")


def runtime_download() -> tuple[str, str] | None:
    return RUNTIMES.get((sys.platform, platform.machine().lower()))


def _download(url: str, dest: Path, sha256: str, out: Callable[[str], None]) -> None:
    if dest.exists() and _sha256(dest) == sha256:
        out(f"  {dest.name}: already downloaded")
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    h = hashlib.sha256()
    with urllib.request.urlopen(url, timeout=60) as r, open(tmp, "wb") as f:
        total, done, shown = int(r.headers.get("Content-Length") or 0), 0, -1
        out(f"  {dest.name}" + (f" ({total / 2**20:.0f} MB)" if total else ""))
        while chunk := r.read(1 << 20):
            f.write(chunk)
            h.update(chunk)
            done += len(chunk)
            if total and done * 4 // total > shown:  # a line every 25%
                shown = done * 4 // total
                out(f"    {done * 100 // total}%")
    if h.hexdigest() != sha256:
        tmp.unlink(missing_ok=True)
        raise LlamaError(f"{dest.name} failed its integrity check (SHA-256 mismatch); nothing was installed.")
    os.replace(tmp, dest)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def install(s: Settings, name: str, out: Callable[[str], None] = print) -> dict:
    """Download the server (unless LLAMA_SERVER points at one) and the model; return the setup info."""
    spec = MODELS[name]
    if not s.llama_server:
        rt = runtime_download()
        if rt is None:
            raise LlamaError(
                f"No prebuilt llama-server for {sys.platform}/{platform.machine()}. Install llama.cpp "
                "(https://github.com/ggml-org/llama.cpp) and set LLAMA_SERVER to its llama-server, or use --runtime ollama."
            )
        exe = server_exe(s)
        if not exe.exists():
            import zipfile

            zpath = home(s) / "runtime.zip"
            _download(rt[0], zpath, rt[1], out)
            with zipfile.ZipFile(zpath) as z:
                z.extractall(exe.parent)
            zpath.unlink()
    files = {}
    for key in ("model", "mmproj"):
        repo, file, sha = spec[key]
        dest = home(s) / "models" / file
        _download(_HF.format(repo=repo, file=file), dest, sha, out)
        files[key] = str(dest)
    return {"runtime": "llama", "base": name, "tier": spec["tier"], "num_ctx": CONTEXT,
            "num_thread": cpu_threads(s), "base_url": f"http://127.0.0.1:{s.llama_port}/v1", **files}


def server_args(s: Settings, info: dict) -> list[str]:
    args = [str(server_exe(s)), "-m", info["model"], "--mmproj", info["mmproj"], "-c", str(info.get("num_ctx") or CONTEXT),
            "-np", "1", "--image-max-tokens", str(s.image_max_tokens), "--reasoning", "off",
            "--host", "127.0.0.1", "--port", str(s.llama_port), "--no-webui"]
    if threads := cpu_threads(s):
        args += ["-t", str(threads)]
    return args


def healthy(s: Settings, timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{s.llama_port}/health", timeout=timeout) as r:
            return json.load(r).get("status") == "ok"
    except (urllib.error.URLError, OSError, ValueError):
        return False


def start(s: Settings, info: dict, wait_s: float = 180.0) -> subprocess.Popen:
    """Start llama-server in the background (below-normal priority, no window) and wait until it is ready."""
    exe = server_exe(s)
    if not exe.exists() or not Path(info.get("model", "")).exists():
        raise LlamaError("The local model isn't installed. Run `python -m playbook setup-local --runtime llama`.")
    log = open(home(s) / "server.log", "ab")
    kw: dict = {"stdout": log, "stderr": subprocess.STDOUT, "stdin": subprocess.DEVNULL}
    if sys.platform == "win32":
        kw["creationflags"] = subprocess.BELOW_NORMAL_PRIORITY_CLASS | subprocess.CREATE_NO_WINDOW
    else:
        kw["preexec_fn"] = lambda: os.nice(10)
    proc = subprocess.Popen(server_args(s, info), **kw)
    end = time.monotonic() + wait_s
    while time.monotonic() < end:
        if proc.poll() is not None:
            raise LlamaError(f"llama-server stopped while loading (exit {proc.returncode}); see {home(s) / 'server.log'}.")
        if healthy(s):
            return proc
        time.sleep(0.5)
    proc.kill()
    raise LlamaError(f"llama-server didn't become ready within {wait_s:.0f}s; see {home(s) / 'server.log'}.")


@contextmanager
def serving(s: Settings, info: dict, status: Callable[[str], None] = lambda m: None) -> Iterator[None]:
    """Make sure the server runs for the duration of the block; stop it afterwards if we started it."""
    if healthy(s):
        yield
        return
    status("Starting the local model...")
    proc = start(s, info)
    try:
        yield
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
