"""On-prem guarantees: egress guard, sync-folder guard, hardware tiers, local backend, UI elements, OCR."""

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


def test_low_power_mode_uses_smallest_model_and_caps_threads(settings):
    from playbook.hardware import cpu_threads

    assert cpu_threads(settings) is None
    settings.low_power = True
    b = resolve_backend(settings)
    assert b.model == "qwen3-vl:2b-instruct" and b.tier.window_size == 3
    assert cpu_threads(settings) == 4
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
