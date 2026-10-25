"""On-prem guarantees: egress guard, sync-folder guard, hardware tiers, local backend, UI elements, OCR."""

import json
from pathlib import Path

import numpy as np
import pytest

from playbook import ocr
from playbook.analyzer import AnalysisError, VisionClient, json_schema_format
from playbook.backend import LOCAL_ALIAS, resolve_backend
from playbook.config import Settings
from playbook.hardware import Hardware, choose_tier, tier_for_model
from playbook.recorder import _Raw, new_session_dir
from playbook.security import SecurityError, check_endpoint, check_storage, is_local_host, synced_folder
from playbook.uia import Element


@pytest.mark.parametrize("host,local", [
    ("127.0.0.1", True), ("localhost", True), ("::1", True), ("192.168.1.20", True), ("10.0.0.5", True),
    ("172.16.4.4", True), ("8.8.8.8", False), ("1.1.1.1", False), ("", False),
])
def test_is_local_host(host, local):
    assert is_local_host(host) is local


def test_cloud_endpoints_are_refused_unless_allowed():
    with pytest.raises(SecurityError, match="ALLOW_CLOUD"):
        check_endpoint("https://generativelanguage.googleapis.com/v1beta/openai/", allow_cloud=False)
    check_endpoint("https://generativelanguage.googleapis.com/v1beta/openai/", allow_cloud=True)
    check_endpoint("http://127.0.0.1:11434/v1", allow_cloud=False)


@pytest.mark.parametrize("path,service", [
    ("C:/Users/a/OneDrive - Contoso/Desktop/x", "Onedrive"),
    ("/Users/a/Dropbox/work", "Dropbox"),
    ("/Users/a/Library/Mobile Documents/com~apple~CloudDocs/x", "Mobile Documents"),
    ("/home/a/Google Drive/x", "Google Drive"),
])
def test_synced_folders_are_detected(path, service):
    assert synced_folder(Path(path)) == service


def test_local_folder_is_not_synced(tmp_path):
    assert synced_folder(tmp_path) is None


def test_recordings_are_not_written_to_synced_folders(settings, tmp_path):
    settings.sessions_dir = tmp_path / "Dropbox" / "sessions"
    with pytest.raises(SecurityError, match="Dropbox"):
        new_session_dir(settings)
    settings.allow_synced_dir = True
    assert new_session_dir(settings).is_dir()
    check_storage(tmp_path, allow_synced=False)


@pytest.mark.parametrize("hw,model", [
    (Hardware(7.6, 2.5, 0, False, 14), "qwen3-vl:2b-instruct"),
    (Hardware(7.6, 4.0, 0, False, 14), "qwen3-vl:4b-instruct"),
    (Hardware(16, 9, 0, False, 16), "qwen3-vl:8b-instruct"),
    (Hardware(16, 9, 8, False, 16), "qwen3-vl:8b-instruct"),
    (Hardware(64, 40, 24, False, 32), "qwen3-vl:32b-instruct"),
    (Hardware(36, 20, 0, True, 12), "qwen3-vl:32b-instruct"),  # Apple silicon: unified memory
    (Hardware(16, 8, 0, True, 8), "qwen3-vl:8b-instruct"),
])
def test_model_tier_fits_the_machine(hw, model):
    assert choose_tier(hw).model == model


def test_smaller_models_get_smaller_inputs():
    tiny, small, large = tier_for_model("qwen3-vl:2b-instruct"), tier_for_model("qwen3-vl:4b-instruct"), tier_for_model("qwen3-vl:32b-instruct")
    assert tiny.window_size < small.window_size < large.window_size
    assert tiny.image_width < small.image_width <= large.image_width


def test_default_backend_is_local(settings):
    b = resolve_backend(settings)
    assert b.local and b.provider == "local" and b.rpm == 0 and b.base_url.startswith("http://127.0.0.1")


def test_gemini_requires_explicit_cloud_opt_in(settings):
    settings.provider = "gemini"
    with pytest.raises(SecurityError, match="ALLOW_CLOUD"):
        resolve_backend(settings)
    settings.allow_cloud = True
    assert resolve_backend(settings).provider == "gemini"


def test_remote_local_server_is_refused(settings):
    settings.local_base_url = "http://8.8.8.8:11434/v1"
    with pytest.raises(AnalysisError, match="Refusing"):
        VisionClient(settings, client=object())


def test_setup_local_alias_is_used(settings, tmp_path):
    settings.data_dir = tmp_path
    (tmp_path / "local_model.json").write_text('{"base": "qwen3-vl:8b-instruct", "tier": "medium"}', encoding="utf-8")
    b = resolve_backend(settings)
    assert b.model == LOCAL_ALIAS and b.tier.name == "medium"


def test_json_schema_has_no_refs():
    from playbook.analyzer import _Pass1Resp

    fmt = json_schema_format(_Pass1Resp)
    assert fmt["type"] == "json_schema" and "$ref" not in str(fmt) and "$defs" not in str(fmt)


# ---------------------------------------------------------------------- UI elements in the recorder
@pytest.fixture
def rec(settings, tmp_path):
    from playbook.recorder import Recorder

    r = Recorder(settings)
    r.session_dir = tmp_path / "session"
    (r.session_dir / "keyframes").mkdir(parents=True)
    r._mon = {"left": 0, "top": 0}
    r._reset_capture_state()
    r._frame = np.zeros((90, 160, 3), np.uint8)
    r._ring.append((0.0, r._frame))
    return r


def feed(rec, raws, now):
    for raw in raws:
        rec._raw.put(raw)
    rec._process_input(now, rec._frame)


def test_clicked_element_and_typed_field_are_recorded(rec):
    feed(rec, [_Raw(1.0, "press", 50, 50, button="left", element=Element("Button", "New Email")),
               _Raw(1.05, "release", 50, 50, button="left")], now=1.1)
    to = Element("Edit", "To", value="jon.doe@example.com")
    feed(rec, [_Raw(2.0 + i * 0.05, "key", key=c, element=to if i == 0 else None) for i, c in enumerate("jon.doe@example.com")]
         + [_Raw(3.5, "key", key="tab")], now=3.6)
    click, typed = rec.events[0], rec.events[1]
    assert click.element == 'Button "New Email"' and 'on Button "New Email"' in click.describe()
    assert typed.element == 'Edit "To"' and typed.element_value == "jon.doe@example.com"


def test_password_field_values_are_never_recorded(rec):
    pw = Element("Edit", "Password", value="hunter2")
    feed(rec, [_Raw(1.0 + i * 0.05, "key", key=c, element=pw if i == 0 else None) for i, c in enumerate("hunter2")]
         + [_Raw(2.0, "key", key="enter")], now=2.1)
    assert rec.events[0].element_value is None


# ---------------------------------------------------------------------- OCR
def test_ocr_near_click_and_changed_text(tmp_path, monkeypatch):
    from playbook.keyframes import save_jpeg

    (tmp_path / "keyframes").mkdir()
    a = np.full((200, 300, 3), 240, np.uint8)
    b = a.copy()
    b[120:160, 150:280] = 30  # something new appeared bottom-right
    save_jpeg(a, tmp_path / "keyframes/0.jpg", 300)
    save_jpeg(b, tmp_path / "keyframes/1.jpg", 300)
    calls = []

    def fake_read(img, min_score=0.6, offset=(0, 0)):
        calls.append(offset)
        ox, oy = offset
        boxes = [ocr.TextBox("New Email", 10, 10, 80, 25, 0.99), ocr.TextBox("jon.doe@example.com", 160, 130, 270, 150, 0.95)]
        h, w = img.shape[:2]
        return [bx for bx in boxes if ox <= bx.x1 and bx.x2 <= ox + w and oy <= bx.y1 and bx.y2 <= oy + h]

    monkeypatch.setattr(ocr, "available", lambda: True)
    monkeypatch.setattr(ocr, "read_image", fake_read)
    s = ocr.SessionOCR(tmp_path)
    assert s.near("keyframes/0.jpg", 30, 15)[0] == "New Email"
    assert s.changed_text("keyframes/0.jpg", "keyframes/1.jpg") == ["jon.doe@example.com"]
    s.save()
    n = len(calls)
    s2 = ocr.SessionOCR(tmp_path)  # cached in ocr.json: no new OCR calls
    assert s2.changed_text("keyframes/0.jpg", "keyframes/1.jpg") == ["jon.doe@example.com"]
    assert len(calls) == n


def test_ocr_disabled_is_a_no_op(tmp_path):
    s = ocr.SessionOCR(tmp_path, enabled=False)
    assert s.near("x.jpg", 1, 1) == [] and s.changed_text(None, "x.jpg") == []


def test_settings_default_to_local_data_dir():
    s = Settings(_env_file=None)
    assert s.provider == "local" and not s.allow_cloud
    assert synced_folder(s.sessions_dir) is None or s.allow_synced_dir is False


def test_low_power_mode_uses_smallest_model_and_caps_threads(settings, monkeypatch):
    import psutil

    from playbook.hardware import cpu_threads

    assert cpu_threads(settings) is None
    settings.low_power = True
    b = resolve_backend(settings)
    assert b.model == "qwen3-vl:2b-instruct" and b.tier.window_size == 3
    for logical, cap in ((14, 6), (8, 4), (4, 2), (2, 2)):  # half the CPU, at most 6
        monkeypatch.setattr(psutil, "cpu_count", lambda logical_=logical, **kw: logical_)
        assert cpu_threads(settings) == cap
    settings.max_threads = 2
    assert cpu_threads(settings) == 2


def test_low_power_never_uses_software_video_encoders(tmp_path, monkeypatch):
    from playbook import archive

    tried = []
    monkeypatch.setattr(archive, "video_duration", lambda p: 1.0)
    monkeypatch.setattr(archive.subprocess, "run", lambda cmd, **kw: tried.append(cmd[cmd.index("-c:v") + 1])
                        or type("R", (), {"returncode": 1})())
    src = tmp_path / "in.mp4"
    src.write_bytes(b"x")
    assert archive.transcode_video(src, tmp_path / "out.mp4", hardware_only=True) is None
    assert tried and set(tried) <= archive.HARDWARE_ENCODERS


def test_local_out_of_memory_is_a_clear_error_without_retries(settings, monkeypatch):
    import openai

    from playbook import analyzer

    class OOM(openai.InternalServerError):
        def __init__(self):
            Exception.__init__(self, "llama-server: failed to allocate CPU buffer")

    err = OOM()
    calls = []

    def create(**kw):
        calls.append(1)
        raise err

    from types import SimpleNamespace
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)), models=SimpleNamespace(list=lambda: []))
    vc = analyzer.VisionClient(settings, client=client)
    with pytest.raises(AnalysisError, match="out of memory"):
        vc.chat([{"role": "user", "content": "hi"}])
    assert len(calls) == 1


def test_local_empty_replies_stop_early_with_a_hint(settings):
    from types import SimpleNamespace

    from playbook import analyzer

    requests = []

    def create(**kw):
        requests.append(kw)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=""))])

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)), models=SimpleNamespace(list=lambda: []))
    vc = analyzer.VisionClient(settings, client=client)
    vc._sleep = lambda seconds, msg: None
    with pytest.raises(AnalysisError, match="instruct"):
        vc.chat([{"role": "user", "content": "hi"}])
    assert len(requests) == 2
    assert requests[0]["max_tokens"] == settings.local_max_tokens  # a rambling model can't hold a request forever
    assert requests[0]["extra_body"]["chat_template_kwargs"] == {"enable_thinking": False}


def _llama_info(tmp_path, settings):
    model, mmproj = tmp_path / "m.gguf", tmp_path / "p.gguf"
    model.write_bytes(b"x")
    mmproj.write_bytes(b"x")
    return {"runtime": "llama", "base": "qwen3-vl-2b", "tier": "tiny", "num_ctx": 8192, "num_thread": 4,
            "base_url": f"http://127.0.0.1:{settings.llama_port}/v1", "model": str(model), "mmproj": str(mmproj)}


def test_llama_runtime_backend_and_server_args(settings, tmp_path):
    from playbook import llama_runtime
    from playbook.backend import resolve_backend
    from playbook.hardware import cpu_threads

    settings.low_power, settings.window_size = True, 0  # 0 = automatic
    info = _llama_info(tmp_path, settings)
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    (settings.data_dir / "local_model.json").write_text(json.dumps(info), encoding="utf-8")
    b = resolve_backend(settings)
    assert b.base_url == info["base_url"] and b.model == "qwen3-vl-2b" and b.server == info
    assert b.fallbacks == [] and b.window_size <= 3 and b.image_width <= 896
    args = llama_runtime.server_args(settings, info)
    for flag, value in (("--image-max-tokens", "448"), ("--reasoning", "off"), ("--host", "127.0.0.1"), ("-t", str(cpu_threads(settings)))):
        assert args[args.index(flag) + 1] == value


def test_llama_runtime_is_picked_only_in_low_power_mode(settings):
    from playbook.local_setup import resolve_runtime

    assert resolve_runtime(settings) == "ollama"
    settings.low_power, settings.llama_server = True, "C:/tools/llama-server.exe"
    assert resolve_runtime(settings) == "llama"
    assert resolve_runtime(settings, "ollama") == "ollama"


def test_setup_llama_records_the_server_and_tests_it(settings, tmp_path, monkeypatch):
    from contextlib import nullcontext

    from playbook import llama_runtime, local_setup

    info = _llama_info(tmp_path, settings)
    monkeypatch.setattr(llama_runtime, "install", lambda s, name, out: info)
    monkeypatch.setattr(llama_runtime, "serving", lambda s, i: nullcontext())
    seen = {}
    monkeypatch.setattr(local_setup, "smoke_test", lambda s, model, base_url=None, api_key="": seen.update(url=base_url) or (1.0, '{"label": "Submit order"}'))
    lines = []
    assert local_setup.setup(settings, assume_yes=True, out=lines.append, runtime="llama") == 0
    assert json.loads((settings.data_dir / "local_model.json").read_text(encoding="utf-8")) == info
    assert seen["url"] == info["base_url"]


def test_download_rejects_a_bad_checksum(tmp_path, monkeypatch):
    import io

    from playbook import llama_runtime

    class Resp(io.BytesIO):
        headers = {"Content-Length": "5"}

    monkeypatch.setattr(llama_runtime.urllib.request, "urlopen", lambda url, timeout: Resp(b"hello"))
    with pytest.raises(llama_runtime.LlamaError, match="integrity"):
        llama_runtime._download("https://example.invalid/x", tmp_path / "x.gguf", "0" * 64, lambda m: None)
    assert not (tmp_path / "x.gguf").exists() and not (tmp_path / "x.gguf.part").exists()


def test_llama_backend_follows_llama_port(settings, tmp_path):
    from playbook.backend import resolve_backend

    settings.data_dir.mkdir(parents=True, exist_ok=True)
    (settings.data_dir / "local_model.json").write_text(json.dumps(_llama_info(tmp_path, settings)), encoding="utf-8")
    settings.llama_port = 18555  # changed after setup: the server and the client must agree
    assert resolve_backend(settings).base_url == "http://127.0.0.1:18555/v1"


def test_preflight_reports_a_missing_llama_install(settings, tmp_path):
    from playbook.local_setup import preflight

    info = _llama_info(tmp_path, settings)
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    (settings.data_dir / "local_model.json").write_text(json.dumps(info), encoding="utf-8")
    settings.llama_server = str(tmp_path / "missing-llama-server.exe")
    assert "setup-local" in preflight(settings)
    settings.llama_server = info["model"]  # any existing file
    assert preflight(settings) is None


def test_llama_server_that_exits_early_is_reported(settings, tmp_path):
    import socket
    import sys

    from playbook import llama_runtime

    with socket.socket() as sock:  # a port nothing listens on
        sock.bind(("127.0.0.1", 0))
        settings.llama_port = sock.getsockname()[1]
    settings.llama_server = sys.executable  # rejects llama-server's flags and exits at once
    with pytest.raises(llama_runtime.LlamaError, match="stopped while loading"):
        with llama_runtime.serving(settings, _llama_info(tmp_path, settings)):
            pass
    assert (llama_runtime.home(settings) / "server.log").read_bytes()  # the server's output is kept for diagnosis


def test_llama_server_requires_a_per_install_key(settings, tmp_path):
    from playbook import llama_runtime
    from playbook.backend import resolve_backend

    info = _llama_info(tmp_path, settings)
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    (settings.data_dir / "local_model.json").write_text(json.dumps(info), encoding="utf-8")
    args = llama_runtime.server_args(settings, info)
    key_file = Path(args[args.index("--api-key-file") + 1])
    key = key_file.read_text(encoding="utf-8")
    assert len(key) >= 32 and key not in " ".join(args)  # off the command line
    assert resolve_backend(settings).api_key == key == llama_runtime.api_key(settings)


def test_server_hook_runs_only_on_a_cache_miss(settings):
    from types import SimpleNamespace

    from playbook import analyzer

    reply = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok": 1}'))])
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kw: reply)),
                             models=SimpleNamespace(list=lambda: []))
    started = []
    msgs = [{"role": "user", "content": "hi"}]
    vc = analyzer.VisionClient(settings, client=client)
    vc.before_call = lambda: started.append(1)
    vc.chat(msgs)
    vc.chat(msgs)
    assert started == [1]
    vc2 = analyzer.VisionClient(settings, client=client)  # e.g. re-analyzing a finished session
    vc2.before_call = lambda: started.append(2)
    vc2.chat(msgs)
    assert started == [1]  # everything was cached: the model is never loaded
