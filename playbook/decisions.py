"""The decision log: what the person saw each time they paused, and what they did next.

A decision point is a dwell frame (see frames.py) plus the outcome that followed: the next
action the person took, or "none" when they took no action. "None" is the interesting case
for tacit knowledge: leaving things alone leaves no click, only time spent looking.

What was on screen is read as labelled numbers ("Spikes: 2", "Batch size: 512") from local
OCR of the keyframe at the end of the dwell. Reading a number off a chart image is not
attempted. This is a stated limitation: the method needs the readouts to be text.

Pooling decisions from many sessions adds cross-session context: for each readout the
previous decision's value is known, so "the batch size was just changed" becomes a feature
(`changed_<name>`) even when no single recording shows both values. The log is written to
`decisions.jsonl` next to the session.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

from .frames import DWELL_MIN_S, compile_frames
from .models import Event, Manifest
from .ocr import SessionOCR

NONE = "none"
READOUT = re.compile(r"([A-Za-z][A-Za-z ./_%-]{1,30}?)\s*[:=]\s*(-?\d[\d,]*(?:\.\d+)?)")
ACTION_KINDS = {"click", "double_click", "right_click", "drag", "type", "hotkey", "key"}


@dataclass
class Decision:
    session: str
    t0: float
    t1: float
    window: str | None
    readouts: dict[str, float]  # what was on screen, as numbers
    outcome: str  # NONE, or a short label of the action taken next
    keyframe: str | None = None  # screenshot the readouts came from (evidence)
    features: dict[str, float] = field(default_factory=dict)  # readouts plus cross-session context

    @property
    def dwell_s(self) -> float:
        return self.t1 - self.t0

    def to_dict(self) -> dict:
        return asdict(self) | {"dwell_s": round(self.dwell_s, 3)}


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def parse_readouts(lines: list[str]) -> dict[str, float]:
    """'Spikes: 2' -> {'spikes': 2.0}. Later lines win when a name repeats."""
    found: dict[str, float] = {}
    for line in lines:
        for name, num in READOUT.findall(line):
            try:
                found[slug(name)] = float(num.replace(",", ""))
            except ValueError:
                continue
    return found


Labeler = Callable[[Event, "SessionOCR | None", str | None], str]


def default_labeler(ev: Event, ocr: SessionOCR | None, keyframe: str | None) -> str:
    """A short label for an action: the UI element, the typed text, or the words next to the click."""
    if ev.kind == "type":
        return f"type {(ev.text or '')[:30]}".strip()
    if ev.element and '"' in ev.element:  # a named element, e.g. Button "Stop run"
        return ev.element
    if ocr is not None and keyframe and ev.x is not None and ev.y is not None:
        near = ocr.near(keyframe, ev.x, ev.y, size=200, limit=1)
        if near:  # an unnamed control (a bare 'Button'): the words on it say more
            return near[0]
    if ev.element:
        return ev.element
    return f"{ev.kind} {ev.text or ''}".strip()


def build_decisions(session_dir: Path, ocr: SessionOCR | None = None, labeler: Labeler = default_labeler,
                    dwell_min_s: float = DWELL_MIN_S) -> list[Decision]:
    """Decision points of one session, in time order. Needs OCR for the screen readouts."""
    session_dir = Path(session_dir)
    m = Manifest.load(session_dir)
    ocr = ocr if ocr is not None else SessionOCR(session_dir)
    by_id = {k.id: k for k in m.keyframes}
    out: list[Decision] = []
    for fr in compile_frames(m, dwell_min_s):
        if fr.kind != "dwell" or not fr.keyframe_ids:
            continue
        seen = by_id[fr.keyframe_ids[-1]]  # the screen as it was when the person decided
        nxt = next((e for e in m.events if e.t >= fr.t1 - 1e-6 and e.kind in ACTION_KINDS), None)
        # The action only counts as this decision's outcome if it comes right after the pause.
        starts_here = nxt is not None and nxt.t - fr.t1 < 1e-6
        after = by_id[max((k.id for k in m.keyframes if k.t <= fr.t1), default=seen.id)]
        if starts_here and nxt.x is not None and ocr.enabled:
            # Event coordinates are screen pixels; the saved keyframes may be smaller.
            scale = ocr._image(after.path).shape[1] / m.width
            nxt = nxt.model_copy(update={"x": round(nxt.x * scale), "y": round((nxt.y or 0) * scale)})
        outcome = labeler(nxt, ocr, after.path) if starts_here else NONE
        readouts = parse_readouts([b.text for b in ocr.boxes(seen.path)])
        out.append(Decision(m.session_id, round(fr.t0, 3), round(fr.t1, 3), fr.window, readouts, outcome, seen.path))
    ocr.save()
    return out


def unify_names(decisions: list[Decision]) -> None:
    """OCR sometimes drops the space in a label ("Batchsize" for "Batch size"), which would split one
    readout into two features that each look constant. Names that differ only by underscores are one
    readout; the most common spelling wins (a tie goes to the one with underscores)."""
    count: dict[str, int] = {}
    for d in decisions:
        for name in d.readouts:
            count[name] = count.get(name, 0) + 1
    groups: dict[str, list[str]] = {}
    for name in count:
        groups.setdefault(name.replace("_", ""), []).append(name)
    rename = {n: max(names, key=lambda x: (count[x], "_" in x)) for names in groups.values() if len(names) > 1 for n in names}
    if rename:
        for d in decisions:
            d.readouts = {rename.get(k, k): v for k, v in d.readouts.items()}


def add_context(decisions: list[Decision]) -> list[Decision]:
    """Fill in `features` from readouts plus the previous decision's values (time order).

    changed_<name> is 1.0 when the value differs from the previous decision's (a change the
    person remembers but no single screen shows); delta_<name> is the difference.
    """
    unify_names(decisions)
    prev: dict[str, float] = {}
    for d in decisions:
        feats = dict(d.readouts)
        for name, value in d.readouts.items():
            if name in prev:
                feats[f"changed_{name}"] = float(value != prev[name])
                feats[f"delta_{name}"] = value - prev[name]
        d.features = feats
        prev = {**prev, **d.readouts}
    return decisions


def save_decisions(decisions: list[Decision], path: Path) -> None:
    path.write_text("".join(json.dumps(d.to_dict(), ensure_ascii=False) + "\n" for d in decisions), encoding="utf-8")


def load_decisions(path: Path) -> list[Decision]:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            raw = json.loads(line)
            raw.pop("dwell_s", None)
            out.append(Decision(**raw))
    return out


def has_saved(session: Path) -> bool:
    """True if the session (a folder, or an encrypted .pbx archive) already has a decision log."""
    session = Path(session)
    if session.suffix == ".pbx":
        from .archive import read_member

        try:
            return read_member(session, "decisions.jsonl") is not None
        except Exception:  # unreadable archive or no key: treat as having none
            return False
    return (session / "decisions.jsonl").is_file()


def _load_saved(session: Path) -> list[Decision]:
    session = Path(session)
    if session.suffix == ".pbx":
        from .archive import read_member

        raw = (read_member(session, "decisions.jsonl") or b"").decode("utf-8")
        out = []
        for line in raw.splitlines():
            if line.strip():
                row = json.loads(line)
                row.pop("dwell_s", None)
                out.append(Decision(**row))
        return out
    return load_decisions(session / "decisions.jsonl")


def pool(session_dirs: list[Path], **kw) -> list[Decision]:
    """All decisions of several sessions, oldest first, with cross-session context added.

    Sessions without a log are analysed now and the log is saved; archives are read without restoring."""
    all_d: list[Decision] = []
    for s in sorted(session_dirs, key=lambda p: Path(p).stem):
        if has_saved(s):
            d = _load_saved(s)
        else:
            d = build_decisions(Path(s), **kw)
            save_decisions(d, Path(s) / "decisions.jsonl")
        all_d.extend(d)
    return add_context(all_d)
