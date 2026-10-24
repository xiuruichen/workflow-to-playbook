import json
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from playbook import prompts  # noqa: E402
from playbook.config import Settings  # noqa: E402
from playbook.keyframes import save_jpeg  # noqa: E402
from playbook.models import Event, Keyframe, Manifest  # noqa: E402


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        GEMINI_API_KEY="test-key",
        rpm_limit=100000,
        sessions_dir=tmp_path / "sessions",
        cache_dir=tmp_path / "cache",
        window_size=6,
    )


class FakeClient:
    """Stands in for openai.OpenAI. `pass1` / `pass2` are lists of replies, used in order;
    the last one repeats."""

    def __init__(self, pass1, pass2):
        self.pass1, self.pass2 = list(pass1), list(pass2)
        self.requests = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))
        self.models = SimpleNamespace(list=lambda: [])

    def _create(self, **kw):
        self.requests.append(kw)
        queue = self.pass1 if kw["messages"][0]["content"] == prompts.PASS1_SYSTEM else self.pass2
        content = queue.pop(0) if len(queue) > 1 else queue[0]
        if not isinstance(content, str):
            content = json.dumps(content)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


@pytest.fixture
def make_session(tmp_path: Path):
    """Build a session directory with 4 distinct keyframes at t=0,2,4,6."""

    def _make(source="live", events=None):
        d = tmp_path / f"session-{source}"
        (d / "keyframes").mkdir(parents=True)
        kfs = []
        for i, t in enumerate([0.0, 2.0, 4.0, 6.0]):
            img = np.full((360, 640, 3), 40 * i + 50, np.uint8)
            rel = f"keyframes/{i:04d}.jpg"
            save_jpeg(img, d / rel, 640)
            kfs.append(Keyframe(id=i, t=t, path=rel, trigger="start" if i == 0 else "event_before"))
        if events is None and source == "live":
            events = [
                Event(t=2.0, kind="click", x=100, y=100, button="left"),
                Event(t=4.0, kind="type", text="hello"),
            ]
        Manifest(
            session_id=d.name, source=source, video="recording.mp4", duration=7.0, width=640, height=360,
            fps=5, created="2026-01-01T00:00:00", keyframes=kfs, events=events or [],
        ).save(d)
        return d

    return _make
