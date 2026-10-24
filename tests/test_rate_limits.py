from types import SimpleNamespace

import openai

try:  # the HTTP library the installed openai SDK is built on
    import httpx2 as httpx
except ImportError:
    import httpx
import pytest

from playbook import analyzer
from playbook.analyzer import AnalysisError, VisionClient, check_models, classify_rate_limit

REQ = httpx.Request("POST", "https://example.test")

# Shapes copied from real Gemini 429 messages.
NO_FREE_TIER = ("Error code: 429 - Quota exceeded for metric: generate_content_free_tier_requests, limit: 0, "
                "model: gemini-omni-1.1-flash ... Please retry in 13h49.971958622s.")
DAILY = "Error code: 429 - Quota exceeded ... quotaId': 'GenerateRequestsPerDayPerProjectPerModel-FreeTier' ... retryDelay': '40000s'"
PER_MINUTE = "Error code: 429 - Quota exceeded ... GenerateRequestsPerMinutePerProjectPerModel-FreeTier ... Please retry in 3.2s."


def rate_error(msg):
    return openai.RateLimitError(msg, response=httpx.Response(429, request=REQ), body=None)


def not_found(model):
    return openai.NotFoundError(f"models/{model} is no longer available to new users", response=httpx.Response(404, request=REQ), body=None)


class ScriptedClient:
    """Per-model scripted outcomes: an exception to raise, or a string to return."""

    def __init__(self, script, available):
        self.script = {m: list(v) for m, v in script.items()}
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))
        self.models = SimpleNamespace(list=lambda: [SimpleNamespace(id=f"models/{m}") for m in available])

    def _create(self, model, **kw):
        self.calls.append(model)
        outcomes = self.script.get(model, ['{"ok": true}'])
        out = outcomes.pop(0) if len(outcomes) > 1 else outcomes[0]
        if isinstance(out, Exception):
            raise out
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=out))])


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    slept = []
    monkeypatch.setattr(analyzer.time, "sleep", lambda s: slept.append(s))
    return slept


@pytest.fixture
def cfg(settings):
    settings.gemini_model = "model-a"
    settings.gemini_fallback_models = "model-a,model-b,model-c"
    return settings


def test_classify_rate_limit():
    assert classify_rate_limit(rate_error(NO_FREE_TIER))[0] is True
    assert classify_rate_limit(rate_error(NO_FREE_TIER))[1] == pytest.approx(13 * 3600 + 49.97, abs=0.1)
    assert classify_rate_limit(rate_error(DAILY)) == (True, 40000.0)
    assert classify_rate_limit(rate_error(PER_MINUTE)) == (False, 3.2)


def test_zero_quota_switches_model_immediately_without_retrying(cfg):
    client = ScriptedClient({"model-a": [rate_error(NO_FREE_TIER)]}, ["model-a", "model-b"])
    statuses = []
    vc = VisionClient(cfg, client, status=statuses.append)
    assert vc.chat([{"role": "user", "content": "hi"}]) == '{"ok": true}'
    assert client.calls == ["model-a", "model-b"]  # no pointless retries on model-a
    assert vc.model == "model-b"
    assert any("switched to 'model-b'" in s for s in statuses)
    assert "no free-tier quota" in vc.notes[0]


def test_fallback_skips_models_the_key_cannot_see(cfg):
    client = ScriptedClient({"model-a": [not_found("model-a")]}, ["model-a", "model-c"])
    vc = VisionClient(cfg, client)
    vc.chat([{"role": "user", "content": "hi"}])
    assert client.calls == ["model-a", "model-c"]


def test_per_minute_limit_waits_suggested_delay_with_countdown(cfg, no_sleep):
    client = ScriptedClient({"model-a": [rate_error(PER_MINUTE), '{"ok": 1}']}, ["model-a"])
    statuses = []
    vc = VisionClient(cfg, client, status=statuses.append)
    vc.chat([{"role": "user", "content": "hi"}])
    assert client.calls == ["model-a", "model-a"]
    assert sum(no_sleep) >= 5  # at least the minimum backoff (Google suggested 3.2s)
    assert any("retrying in" in s for s in statuses)


def test_all_models_exhausted_gives_actionable_error(cfg):
    client = ScriptedClient({m: [rate_error(DAILY)] for m in ("model-a", "model-b", "model-c")}, ["model-a", "model-b", "model-c"])
    with pytest.raises(AnalysisError, match="No usable model left.*playbook check"):
        VisionClient(cfg, client).chat([{"role": "user", "content": "hi"}])
    assert client.calls == ["model-a", "model-b", "model-c"]


def test_check_models_reports_each_model(cfg):
    client = ScriptedClient({"model-a": [rate_error(NO_FREE_TIER)], "model-b": ["OK"]}, ["model-a", "model-b"])
    results = {m: (ok, d) for m, ok, d in check_models(cfg, client)}
    assert results["model-a"] == (False, "no free-tier quota for this model")
    assert results["model-b"] == (True, "ok")
    assert results["model-c"] == (False, "not offered to this API key")
