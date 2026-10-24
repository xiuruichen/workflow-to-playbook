"""Vision analysis: keyframes + input events -> calibrated, consolidated playbook steps.

Pass 1 sends overlapping windows of keyframes (annotated with click markers) plus the
event log to a vision model and gets back fine-grained step candidates as JSON.
Pass 2 consolidates all candidates into a coherent playbook (goal, merged steps, inputs,
open questions). Confidence is the model's own estimate adjusted by rules that the model
can't see (missing input-event evidence, repaired output, long gaps between frames).

The model is reached through Gemini's OpenAI-compatible endpoint, so any OpenAI-compatible
vision API can be substituted by changing GEMINI_BASE_URL / GEMINI_MODEL.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, TypeVar

from pydantic import BaseModel, Field, ValidationError, field_validator

from . import prompts
from .config import Settings, get_settings
from .keyframes import annotate, encode_jpeg, load_image
from .models import Event, InputVariable, Keyframe, Manifest, Playbook, Step, StepCandidate

T = TypeVar("T", bound=BaseModel)
Progress = Callable[[float, str], None]

PASSIVE_ACTIONS = {"read", "wait"}
PENALTY_NO_EVENT = 0.15
PENALTY_REPAIRED = 0.10
PENALTY_LONG_GAP = 0.10
LONG_GAP_S = 20.0
MERGE_LEEWAY = 0.10  # pass 2 may raise a step merged from several candidates this much above the weakest


class AnalysisError(RuntimeError):
    """`recoverable` errors affect one request (e.g. unparseable output); others (auth, quota,
    network) would fail every request, so the whole analysis stops."""

    def __init__(self, message: str, recoverable: bool = False):
        super().__init__(message)
        self.recoverable = recoverable


# ---------------------------------------------------------------------- response schemas
def _coerce_conf(v: Any) -> float | None:
    if v is None:
        return None
    try:
        v = float(v)
    except (TypeError, ValueError):
        return 0.5
    return v / 100 if v > 1 else v  # tolerate percentages


class _EmptyResponse(Exception):
    pass


class _Pass1Step(BaseModel):
    action: str = "other"
    description: str
    target: str | None = None
    value: str | None = None
    app: str | None = None
    expected_result: str | None = None
    start_image: int = 1
    end_image: int = 1
    confidence: float = 0.5
    evidence: str = ""
    uncertainty_reason: str | None = None

    @field_validator("confidence", mode="before")
    @classmethod
    def coerce_conf(cls, v: Any) -> float:
        c = _coerce_conf(v)
        return 0.5 if c is None else c

    @field_validator("evidence", mode="before")
    @classmethod
    def none_to_empty(cls, v: Any) -> str:
        return v or ""


class _Pass1Resp(BaseModel):
    window_context: str = ""
    steps: list[_Pass1Step] = Field(default_factory=list)


class _Pass2Step(BaseModel):
    title: str
    description: str = ""
    action: str | None = None
    target: str | None = None
    value: str | None = None
    app: str | None = None
    expected_result: str | None = None
    source_ids: list[str] = Field(default_factory=list)
    confidence: float | None = None
    uncertainty_reason: str | None = None

    @field_validator("confidence", mode="before")
    @classmethod
    def coerce_conf(cls, v: Any) -> float | None:
        return _coerce_conf(v)


class _Dropped(BaseModel):
    id: str
    reason: str = ""


class _Pass2Resp(BaseModel):
    title: str = "Recorded workflow"
    goal: str = ""
    summary: str = ""
    apps: list[str] = Field(default_factory=list)
    prerequisites: list[str] = Field(default_factory=list)
    steps: list[_Pass2Step] = Field(default_factory=list)
    dropped_ids: list[_Dropped] = Field(default_factory=list)
    inputs: list[InputVariable] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)

    @field_validator("dropped_ids", mode="before")
    @classmethod
    def coerce_dropped(cls, v: Any) -> Any:
        return [{"id": d} if isinstance(d, str) else d for d in (v or [])]


# ---------------------------------------------------------------------- helpers
def parse_json(text: str) -> Any:
    """Parse a JSON object from model output, tolerating fences and surrounding prose."""
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise
        data = json.loads(text[start : end + 1])
    if isinstance(data, list):
        data = {"steps": data}
    return data


def fmt_ts(seconds: float) -> str:
    seconds = max(0, int(seconds))  # floor, so labels match the #t=<int> seek links
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def build_windows(keyframes: list[Keyframe], size: int) -> list[list[Keyframe]]:
    """Consecutive windows that share their boundary keyframe, so every transition
    between two keyframes belongs to exactly one window."""
    size = max(2, size)
    if len(keyframes) < 2:
        return [keyframes] if keyframes else []
    windows, i = [], 0
    while i < len(keyframes) - 1:
        windows.append(keyframes[i : i + size])
        i += size - 1
    return windows


def assign_events(kfs: list[Keyframe], events: list[Event], is_last_window: bool) -> list[list[tuple[int, Event]]]:
    """For each keyframe in a window, the (global index, event) pairs that happen after it
    and before the next keyframe. Events after the window's last keyframe belong to the
    next window (except in the final window)."""
    out: list[list[tuple[int, Event]]] = [[] for _ in kfs]
    if not kfs:
        return out
    first_window = kfs[0].id == 0
    for gi, ev in enumerate(events):
        if ev.t < kfs[0].t:
            if first_window:  # events before the very first keyframe go with it
                out[0].append((gi, ev))
            continue
        for i in range(len(kfs) - 1, -1, -1):
            if ev.t >= kfs[i].t:
                if i == len(kfs) - 1 and not is_last_window:
                    break  # shown in the next window
                out[i].append((gi, ev))
                break
    return out


class _RateLimiter:
    def __init__(self, rpm: int):
        self.interval = 60.0 / max(rpm, 1)
        self.last = -1e9

    def delay(self) -> float:
        return max(0.0, self.last + self.interval - time.monotonic())

    def mark(self) -> None:
        self.last = time.monotonic()


MAX_RETRIES = 6  # per model, for per-minute rate limits and transient server/network errors
MAX_WAIT_S = 90.0  # a suggested wait longer than this means the quota is effectively gone for now
_UNITS = {"h": 3600, "m": 60, "s": 1}


def classify_rate_limit(exc: Exception) -> tuple[bool, float | None]:
    """Return (exhausted, retry_after_s) for a 429 error.

    `exhausted` means retrying this model is pointless: its free-tier limit is 0, the daily
    quota is used up, or Google asks us to wait longer than MAX_WAIT_S.
    """
    text = str(exc)
    retry_after = None
    m = re.search(r"retry in ((?:[\d.]+h)?(?:[\d.]+m)?(?:[\d.]+s)?)", text, re.I)
    if m and m.group(1):
        retry_after = sum(float(v) * _UNITS[u] for v, u in re.findall(r"([\d.]+)([hms])", m.group(1)))
    else:
        m = re.search(r"retryDelay\W+([\d.]+)s", text)
        if m:
            retry_after = float(m.group(1))
    exhausted = (
        "limit: 0" in text
        or "PerDay" in text
        or "per day" in text.lower()
        or (retry_after is not None and retry_after > MAX_WAIT_S)
    )
    return exhausted, retry_after


# ---------------------------------------------------------------------- model client
class VisionClient:
    """OpenAI-compatible chat client with throttling, retries, model fallback, disk cache
    and JSON repair. `status` receives human-readable updates (waits, retries, switches)."""

    def __init__(self, settings: Settings, client: Any = None, status: Callable[[str], None] | None = None):
        self.s = settings
        self.model = settings.gemini_model
        self.notes: list[str] = []
        self.status = status or (lambda msg: None)
        self.dead_models: dict[str, str] = {}  # model -> why it can't be used
        if client is None:
            if not settings.gemini_api_key:
                raise AnalysisError(
                    "GEMINI_API_KEY is not set. Create a free key at https://aistudio.google.com/apikey "
                    "and put it in .env (see .env.example)."
                )
            from openai import OpenAI

            client = OpenAI(
                api_key=settings.gemini_api_key,
                base_url=settings.gemini_base_url,
                timeout=settings.request_timeout_s,
                max_retries=0,  # retries handled below
            )
        self.client = client
        self.limiter = _RateLimiter(settings.rpm_limit)
        self.cache_dir = settings.cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.calls = 0
        self.cache_hits = 0
        self._available: list[str] | None = None

    def _cache_path(self, messages: list[dict]) -> Path:
        key = hashlib.sha256(json.dumps([self.model, messages], sort_keys=True).encode()).hexdigest()
        return self.cache_dir / f"{key}.json"

    def chat(self, messages: list[dict]) -> str:
        path = self._cache_path(messages)
        if path.exists():
            self.cache_hits += 1
            return json.loads(path.read_text(encoding="utf-8"))["content"]
        content = self._call_with_retry(messages)
        path = self._cache_path(messages)  # the model may have changed during the call
        path.write_text(json.dumps({"model": self.model, "content": content}), encoding="utf-8")
        return content

    def _sleep(self, seconds: float, msg: str) -> None:
        """Sleep while reporting a countdown, so the UI never looks frozen."""
        end = time.monotonic() + seconds
        while (left := end - time.monotonic()) > 0:
            self.status(msg.format(left=int(left) + 1))
            time.sleep(min(1.0, left))

    def _call_with_retry(self, messages: list[dict]) -> str:
        import openai

        attempt = 0
        while True:
            if (d := self.limiter.delay()) > 0:
                self._sleep(d, f"Pacing requests ({self.s.rpm_limit}/min)... {{left}}s")
            self.limiter.mark()
            self.calls += 1
            try:
                resp = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=0.2,
                    response_format={"type": "json_object"},
                )
                content = resp.choices[0].message.content
                if not content:
                    raise _EmptyResponse("Model returned an empty response")
                return content
            except openai.RateLimitError as exc:
                exhausted, retry_after = classify_rate_limit(exc)
                if exhausted or attempt >= MAX_RETRIES:
                    why = "has no free-tier quota left" if exhausted else "kept hitting its rate limit"
                    if retry_after and retry_after > MAX_WAIT_S:
                        why += f" (resets in ~{retry_after / 3600:.1f} h)"
                    self._switch_model(why)
                    attempt = 0
                    continue
                attempt += 1
                wait = min(max(retry_after or 0, 5 * 2 ** (attempt - 1)), MAX_WAIT_S)
                self._sleep(wait, f"Rate-limited by {self.model}; retrying in {{left}}s (attempt {attempt}/{MAX_RETRIES})")
            except (openai.AuthenticationError, openai.PermissionDeniedError) as exc:
                raise AnalysisError(f"The API key was rejected: {exc}") from exc
            except (openai.NotFoundError, openai.BadRequestError) as exc:
                if isinstance(exc, openai.BadRequestError) and "model" not in str(exc).lower():
                    raise AnalysisError(f"Request failed: {str(exc)[:500]}") from exc
                self._switch_model("is not available to this API key")
                attempt = 0
            except (openai.APIConnectionError, openai.APITimeoutError, openai.InternalServerError, _EmptyResponse) as exc:
                if attempt >= MAX_RETRIES:
                    self._switch_model(f"kept failing ({type(exc).__name__})")
                    attempt = 0
                    continue
                attempt += 1
                wait = min(5 * 2 ** (attempt - 1), MAX_WAIT_S)
                self._sleep(wait, f"{type(exc).__name__} from {self.model}; retrying in {{left}}s (attempt {attempt}/{MAX_RETRIES})")
            except openai.APIError as exc:
                raise AnalysisError(f"Request failed: {str(exc)[:500]}") from exc

    def available_models(self) -> list[str]:
        """Models this key can see ([] if listing fails, meaning 'unknown')."""
        if self._available is None:
            try:
                self._available = [m.id.removeprefix("models/") for m in self.client.models.list()]
            except Exception:
                self._available = []
        return self._available

    def fallback_models(self) -> list[str]:
        prefs = [m.strip() for m in self.s.gemini_fallback_models.split(",") if m.strip()]
        if self.available_models():  # only suggest models this key can see
            prefs = [m for m in prefs if m in self._available]
        return [m for m in prefs if m != self.model and m not in self.dead_models]

    def _switch_model(self, why: str) -> None:
        self.dead_models[self.model] = why
        candidates = self.fallback_models()
        if not candidates:
            tried = "; ".join(f"{m} {w}" for m, w in self.dead_models.items())
            raise AnalysisError(
                f"No usable model left. Tried: {tried}. Free-tier quotas reset daily (midnight Pacific time). "
                "Run `python -m playbook check` to see which models work right now, set GEMINI_MODEL in .env, "
                "or enable billing in Google AI Studio. Finished segments are cached, so a re-run resumes."
            )
        old, self.model = self.model, candidates[0]
        msg = f"Model '{old}' {why}; switched to '{self.model}'."
        self.notes.append(msg)
        self.status(msg)

    def complete_json(self, messages: list[dict], schema: type[T]) -> tuple[T, bool]:
        """Return (parsed response, repaired?) with one repair round-trip on invalid output."""
        content = self.chat(messages)
        try:
            return schema.model_validate(parse_json(content)), False
        except (json.JSONDecodeError, ValidationError) as exc:
            error = str(exc)[:500]
        repair = messages + [
            {"role": "assistant", "content": content},
            {"role": "user", "content": prompts.REPAIR_PROMPT.format(error=error)},
        ]
        content = self.chat(repair)
        try:
            return schema.model_validate(parse_json(content)), True
        except (json.JSONDecodeError, ValidationError) as exc:
            raise AnalysisError(f"Model returned invalid JSON twice: {str(exc)[:300]}", recoverable=True) from exc


def _image_part(jpeg: bytes) -> dict:
    return {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(jpeg).decode()}}


def _dedupe(items: list[str]) -> list[str]:
    seen, out = set(), []
    for it in items:
        if it and it not in seen:
            seen.add(it)
            out.append(it)
    return out


# ---------------------------------------------------------------------- analyzer
class Analyzer:
    def __init__(self, settings: Settings | None = None, client: Any = None, progress: Progress | None = None):
        self.s = settings or get_settings()
        self.progress = progress or (lambda f, m: None)
        self._frac = 0.0
        self.vc = VisionClient(self.s, client, status=lambda msg: self.progress(self._frac, msg))

    def _step(self, frac: float, msg: str) -> None:
        self._frac = frac
        self.progress(frac, msg)

    # -- public ---------------------------------------------------------------------------
    def analyze(self, session_dir: Path) -> Playbook:
        session_dir = Path(session_dir)
        manifest = Manifest.load(session_dir)
        if len(manifest.keyframes) < 2:
            raise AnalysisError(
                "Fewer than 2 keyframes were captured, so there is nothing to analyze. Record a longer workflow "
                "or lower CHANGE_THRESHOLD."
            )
        windows = build_windows(manifest.keyframes, self.s.window_size)
        candidates, window_log = self._pass1(session_dir, manifest, windows)
        self._step(0.9, f"Consolidating {len(candidates)} actions into a playbook with {self.vc.model}...")
        playbook, dropped = self._pass2(session_dir, manifest, candidates, window_log)
        (session_dir / "analysis.json").write_text(
            json.dumps(
                {
                    "model": self.vc.model,
                    "api_calls": self.vc.calls,
                    "cache_hits": self.vc.cache_hits,
                    "windows": window_log,
                    "candidates": [c.model_dump() for c in candidates],
                    "dropped": dropped,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        playbook.save(session_dir)
        self._step(1.0, f"Done: {len(playbook.steps)} steps, {len(playbook.review_steps)} flagged for review")
        return playbook

    # -- pass 1 ---------------------------------------------------------------------------
    def _window_messages(self, session_dir: Path, manifest: Manifest, kfs: list[Keyframe], seg: int, n_seg: int, prev_ctx: str) -> list[dict]:
        is_last = seg == n_seg
        per_image = assign_events(kfs, manifest.events, is_last)
        live = manifest.source == "live"
        header = prompts.PASS1_USER_HEADER.format(
            segment=seg,
            segments=n_seg,
            source_note=prompts.SOURCE_NOTE_LIVE if live else prompts.SOURCE_NOTE_IMPORT,
            prev_context=prev_ctx or "(start of recording)",
        )
        parts: list[dict] = [{"type": "text", "text": header}]
        counter = 0
        for i, (kf, evs) in enumerate(zip(kfs, per_image), start=1):
            numbered = []
            lines = []
            for _, ev in evs:
                counter += 1
                numbered.append((counter, ev))
                lines.append(f"  #{counter} [{fmt_ts(ev.t)}] {ev.describe()}")
            img = load_image(session_dir / kf.path)
            img = annotate(img, numbered, manifest.width, manifest.height)
            parts.append({"type": "text", "text": f"Image {i} — recording time {fmt_ts(kf.t)} (captured: {kf.trigger.replace('_', ' ')})"})
            parts.append(_image_part(encode_jpeg(img, 80)))
            if live:
                parts.append({"type": "text", "text": f"Events after image {i}:\n" + ("\n".join(lines) if lines else "  (none)")})
        parts.append({"type": "text", "text": f"Describe the user actions between image 1 and image {len(kfs)} as JSON."})
        return [{"role": "system", "content": prompts.PASS1_SYSTEM}, {"role": "user", "content": parts}]

    def _pass1(self, session_dir: Path, manifest: Manifest, windows: list[list[Keyframe]]) -> tuple[list[StepCandidate], list[dict]]:
        candidates: list[StepCandidate] = []
        log: list[dict] = []
        prev_ctx = ""
        n = len(windows)
        for seg, kfs in enumerate(windows, start=1):
            self._step(0.02 + 0.85 * (seg - 1) / n, f"Analyzing segment {seg}/{n} ({fmt_ts(kfs[0].t)}–{fmt_ts(kfs[-1].t)}) with {self.vc.model}...")
            entry: dict = {"segment": seg, "keyframes": [k.id for k in kfs], "t_start": kfs[0].t, "t_end": kfs[-1].t}
            try:
                msgs = self._window_messages(session_dir, manifest, kfs, seg, n, prev_ctx)
                resp, repaired = self.vc.complete_json(msgs, _Pass1Resp)
            except AnalysisError as exc:
                if not exc.recoverable:
                    raise
                entry["error"] = str(exc)
                log.append(entry)
                candidates.append(self._failed_segment(kfs, str(exc), len(candidates)))
                continue
            entry.update(context=resp.window_context, repaired=repaired, steps=len(resp.steps))
            log.append(entry)
            prev_ctx = resp.window_context or prev_ctx
            for st in resp.steps:
                candidates.append(self._to_candidate(st, kfs, manifest, repaired, len(candidates)))
        return candidates, log

    def _failed_segment(self, kfs: list[Keyframe], error: str, n: int) -> StepCandidate:
        return StepCandidate(
            id=f"c{n + 1}",
            action="other",
            description=f"Unanalyzed segment {fmt_ts(kfs[0].t)}–{fmt_ts(kfs[-1].t)}: review the recording manually",
            start_keyframe=kfs[0].id,
            end_keyframe=kfs[-1].id,
            t_start=kfs[0].t,
            t_end=kfs[-1].t,
            model_confidence=0.0,
            confidence=0.0,
            uncertainty_reason=f"Vision analysis failed for this segment: {error[:200]}",
            calibration_notes=["Segment could not be analyzed"],
        )

    def _to_candidate(self, st: _Pass1Step, kfs: list[Keyframe], manifest: Manifest, repaired: bool, n: int) -> StepCandidate:
        a = min(max(st.start_image, 1), len(kfs))
        b = min(max(st.end_image, 1), len(kfs))
        if b < a:
            a, b = b, a
        k0, k1 = kfs[a - 1], kfs[b - 1]
        hi = k1.t if b > a else (kfs[a].t if a < len(kfs) else k1.t + 1)
        evs = [e for e in manifest.events if k0.t <= e.t < hi]
        t_start = evs[0].t if evs else k0.t

        notes: list[str] = []
        conf = st.confidence
        action = (st.action or "other").lower()
        if action not in PASSIVE_ACTIONS:
            if manifest.source == "import":
                conf -= PENALTY_NO_EVENT
                notes.append("Imported video: no input events recorded, so the action is inferred from visual change only")
            elif not evs:
                conf -= PENALTY_NO_EVENT
                notes.append("No mouse/keyboard event corroborates this step")
        if repaired:
            conf -= PENALTY_REPAIRED
            notes.append("Model output needed a repair retry")
        if k1.t - k0.t > LONG_GAP_S and b - a <= 1:
            conf -= PENALTY_LONG_GAP
            notes.append(f"Inferred across a {k1.t - k0.t:.0f}s gap between screenshots; intermediate actions may be missing")

        return StepCandidate(
            id=f"c{n + 1}",
            action=action,
            description=st.description,
            target=st.target,
            value=st.value,
            app=st.app,
            expected_result=st.expected_result,
            start_keyframe=k0.id,
            end_keyframe=k1.id,
            t_start=t_start,
            t_end=max(k1.t, t_start),
            model_confidence=st.confidence,
            confidence=max(0.0, conf),
            evidence=st.evidence,
            uncertainty_reason=st.uncertainty_reason,
            calibration_notes=notes,
        )

    # -- pass 2 ---------------------------------------------------------------------------
    def _pass2(self, session_dir: Path, manifest: Manifest, cands: list[StepCandidate], window_log: list[dict]) -> tuple[Playbook, list[dict]]:
        kf_by_id = {k.id: k for k in manifest.keyframes}
        pb_notes: list[str] = []
        if manifest.source == "import":
            pb_notes.append("Built from an imported video without mouse/keyboard data; confidence is lower and more steps are flagged.")
        failed = [w for w in window_log if w.get("error")]
        if failed:
            pb_notes.append(f"{len(failed)} segment(s) could not be analyzed; they appear as flagged steps.")

        resp: _Pass2Resp | None = None
        dropped: list[dict] = []
        if cands:
            payload = [
                {
                    "id": c.id,
                    "time": fmt_ts(c.t_start),
                    "action": c.action,
                    "description": c.description,
                    "target": c.target,
                    "value": c.value,
                    "app": c.app,
                    "expected_result": c.expected_result,
                    "confidence": round(c.confidence, 2),
                    "evidence": c.evidence,
                    "uncertainty_reason": c.uncertainty_reason,
                }
                for c in cands
            ]
            contexts = "\n".join(f"- Segment {w['segment']} ({fmt_ts(w['t_start'])}): {w.get('context', '(failed)')}" for w in window_log)
            first, last = manifest.keyframes[0], manifest.keyframes[-1]
            user = [
                {"type": "text", "text": f"Recording length {fmt_ts(manifest.duration)}. Segment summaries:\n{contexts}\n\nCandidate steps:\n{json.dumps(payload, indent=1)}"},
                {"type": "text", "text": "First screenshot of the recording:"},
                _image_part(encode_jpeg(load_image(session_dir / first.path), 70)),
                {"type": "text", "text": "Last screenshot of the recording:"},
                _image_part(encode_jpeg(load_image(session_dir / last.path), 70)),
            ]
            try:
                resp, repaired = self.vc.complete_json(
                    [{"role": "system", "content": prompts.PASS2_SYSTEM}, {"role": "user", "content": user}], _Pass2Resp
                )
            except AnalysisError as exc:
                if not exc.recoverable:
                    raise
                pb_notes.append(f"Consolidation pass failed ({str(exc)[:150]}); showing raw steps.")

        by_id = {c.id: c for c in cands}
        used: set[str] = set()
        steps: list[Step] = []

        def make_step(srcs: list[StepCandidate], p2: _Pass2Step | None) -> Step:
            weakest = min(c.confidence for c in srcs)
            # Merging can resolve ambiguity (e.g. a click explained by the text typed next), so a
            # merged step may sit slightly above its weakest part; a single step never exceeds it.
            cap = weakest + (MERGE_LEEWAY if len(srcs) > 1 else 0.0)
            conf = weakest if p2 is None or p2.confidence is None else min(p2.confidence, cap)
            notes = _dedupe([n for c in srcs for n in c.calibration_notes])
            if p2 is not None and p2.confidence is not None and p2.confidence < weakest - 0.05:
                notes.append("Lowered by the consolidation pass")
            reason = (p2.uncertainty_reason if p2 else None) or "; ".join(_dedupe([c.uncertainty_reason or "" for c in srcs])) or None
            first, last = min(srcs, key=lambda c: c.t_start), max(srcs, key=lambda c: c.t_end)
            base = srcs[0]

            def pick(field: str) -> Any:  # pass-2 value, else what the sources agree on
                v = getattr(p2, field, None) if p2 else None
                if v:
                    return v
                vals = _dedupe([getattr(c, field) or "" for c in srcs])
                return vals[-1] if field == "expected_result" and vals else (" / ".join(vals) or None)

            return Step(
                index=0,
                title=(p2.title if p2 else base.description[:80]),
                description=(p2.description if p2 and p2.description else "; then ".join(c.description for c in srcs)),
                action=(p2.action if p2 and p2.action else " + ".join(_dedupe([c.action for c in srcs]))),
                target=pick("target"),
                value=pick("value"),
                app=pick("app"),
                expected_result=pick("expected_result"),
                t_start=first.t_start,
                t_end=last.t_end,
                keyframe_before=kf_by_id[first.start_keyframe].path if first.start_keyframe in kf_by_id else None,
                keyframe_after=kf_by_id[last.end_keyframe].path if last.end_keyframe in kf_by_id else None,
                model_confidence=min(c.model_confidence for c in srcs) if p2 is None or p2.confidence is None else p2.confidence,
                confidence=conf,
                evidence=" | ".join(_dedupe([c.evidence for c in srcs]))[:800],
                uncertainty_reason=reason,
                calibration_notes=notes,
                source_ids=[c.id for c in srcs],
            )

        if resp is not None:
            dropped = [d.model_dump() for d in resp.dropped_ids if d.id in by_id]
            dropped_ids = {d["id"] for d in dropped}
            for p2 in resp.steps:
                srcs = [by_id[i] for i in p2.source_ids if i in by_id and i not in used]
                if not srcs:
                    continue
                used.update(c.id for c in srcs)
                steps.append(make_step(srcs, p2))
            leftovers = [c for c in cands if c.id not in used and c.id not in dropped_ids]
            for c in leftovers:
                st = make_step([c], None)
                st.calibration_notes.append("Not placed by the consolidation pass; kept as recorded")
                steps.append(st)
            if dropped:
                pb_notes.append(f"{len(dropped)} raw action(s) were dropped as noise or duplicates (see analysis.json).")
        else:
            steps = [make_step([c], None) for c in cands]

        steps.sort(key=lambda s: s.t_start)
        for i, st in enumerate(steps, start=1):
            st.index = i

        pb = Playbook(
            title=resp.title if resp else "Recorded workflow",
            goal=resp.goal if resp else "",
            summary=resp.summary if resp else "",
            apps=resp.apps if resp else _dedupe([c.app or "" for c in cands]),
            prerequisites=resp.prerequisites if resp else [],
            inputs=resp.inputs if resp else [],
            open_questions=resp.open_questions if resp else [],
            steps=steps,
            session_id=manifest.session_id,
            source=manifest.source,
            video=manifest.video,
            duration=manifest.duration,
            model=self.vc.model,
            threshold=self.s.confidence_threshold,
            generated_at=datetime.now().isoformat(timespec="seconds"),
            notes=self.vc.notes + pb_notes,
        )
        pb.refresh_flags()
        return pb, dropped


def analyze_session(session_dir: Path, settings: Settings | None = None, progress: Progress | None = None) -> Playbook:
    return Analyzer(settings, progress=progress).analyze(session_dir)


def check_models(settings: Settings | None = None, client: Any = None) -> list[tuple[str, bool, str]]:
    """Send a tiny request to the configured model and each fallback and report which work
    right now. Costs one request of quota per model."""
    import openai

    s = settings or get_settings()
    vc = VisionClient(s, client)
    available = vc.available_models()
    results = []
    for m in _dedupe([s.gemini_model] + [x.strip() for x in s.gemini_fallback_models.split(",")]):
        if available and m not in available:
            results.append((m, False, "not offered to this API key"))
            continue
        try:
            vc.client.chat.completions.create(model=m, messages=[{"role": "user", "content": "Reply with OK"}], max_tokens=5)
            results.append((m, True, "ok"))
        except openai.RateLimitError as exc:
            exhausted, after = classify_rate_limit(exc)
            if "limit: 0" in str(exc):
                detail = "no free-tier quota for this model"
            elif exhausted:
                detail = "quota used up" + (f" (resets in ~{after / 3600:.1f} h)" if after else "")
            else:
                detail = "per-minute limit hit; usable again shortly"
            results.append((m, False, detail))
        except openai.APIError as exc:
            results.append((m, False, f"{type(exc).__name__}: {str(exc)[:120]}"))
    return results
