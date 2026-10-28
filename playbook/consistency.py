"""Deterministic cross-check: values the user typed vs. values seen on screen.

The vision model only sees one segment of the recording at a time, so it misses mistakes
where the source and the typed copy are far apart (e.g. a number read at 0:18 and typed,
with a digit wrong, at 0:43). The keyboard log is ground truth for what was typed, and the
model records what was on screen (step "value" fields and each segment's "visible_values"),
so near-misses between the two are cheap to find without another API call.

A near-miss is "similar but not equal": transposed digits, or 1-2 changed digits in a
number of 5+ digits, or a >= 85% similar string (emails, names, paths, commands). Prefixes
are ignored (autocomplete). A number typed right after reading a similar one (same
magnitude and leading digit, up to half its digits changed) is flagged too: that is a
transcription error, not a different value.

The same log also catches input the software rejected. Error messages quote the input they
refuse ("The term 'pyhton' is not recognized", "bash: pyhton: command not found", "'jon.doe@'
is not a valid email", "No results for 'springfeild'"), so new on-screen text (local OCR)
that reads like an error and cites something just typed marks that entry for review, in any
app.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

from .models import Event, Step, StepCandidate

TYPING_ACTIONS = {"type", "key", "shortcut", "hotkey"}
# Steps whose value the model read off the screen. Other steps often just echo what was typed
# (small models write `click "jon.doe@..."` for clicking into the To field), so only these, and
# local OCR, can prove that a typed value was copied correctly.
SOURCE_ACTIONS = {"read", "select"}
NUMBER = re.compile(r"\d[\d,.\s]*\d")
QUOTED = re.compile(r"['\"“‘]([^'\"”’]{3,80})['\"”’]")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PATHLIKE = re.compile(r"[\w.-]+[/\\][\w./\\-]+|[\w-]+\.[a-z0-9]{2,4}\b", re.I)
MIN_DIGITS = 4
TEXT_SIMILARITY = 0.85
MAX_WHOLE_VALUE = 60  # longer values are searched for tokens instead of compared whole
ERROR_TEXT = re.compile(
    r"\b(errors?|exception|fail(?:ed|ure|s)?|invalid|unrecogni[sz]ed|unknown|unexpected|incorrect|"
    r"undefined|denied|rejected|undeliverable|unable|cannot|can'?t|could\s?n[o']t|"
    r"not\s+(?:an?\s+)?(?:recogni[sz]ed|found|defined|valid|allowed|supported|available|exist)|"
    r"does\s?n[o']t\s+exist|no\s+such|no\s+(?:results|matches)|did\s+not\s+match)\b",
    re.I,
)
TYPED_WORD = re.compile(r"[\w.@/\\+-]{3,}")
ERROR_WINDOW_S = 15.0  # how long after an entry an error message is attributed to it


@dataclass
class NearMiss:
    typed: str
    seen: str  # the similar value seen on screen, or the error message for kind="rejected"
    typed_t: float
    seen_t: float
    kind: str = "near_miss"  # or "rejected": the software showed an error citing the input

    def note(self, fmt_ts) -> str:
        if self.kind == "rejected":
            return f'After typing "{self.typed}" the screen showed "{self.seen}" at {fmt_ts(self.seen_t)} (consistency check).'
        return f'Typed "{self.typed}" but "{self.seen}" was seen at {fmt_ts(self.seen_t)} (consistency check).'


def _digits(s: str) -> str | None:
    """The digits of a number-like string ('315,613' -> '315613'), else None."""
    s = s.strip()
    if not NUMBER.fullmatch(s) and not s.isdigit():
        return None
    d = re.sub(r"\D", "", s)
    return d if len(d) >= MIN_DIGITS else None


def _edit_distance(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _norm(s: str) -> str:
    # Spacing is ignored: OCR often drops spaces ("New Email" -> "NewEmail").
    return re.sub(r"\s+", "", s.strip().lower())


def is_near_miss(typed: str, seen: str) -> bool:
    td, sd = _digits(typed), _digits(seen)
    if td and sd:
        if td == sd or abs(len(td) - len(sd)) > 1:
            return False
        if len(td) == len(sd) and sorted(td) == sorted(sd):
            return True  # transposed digits
        # Short numbers (years, counts) legitimately differ by a digit, so require 5+ digits.
        return len(td) >= 5 and _edit_distance(td, sd) <= min(2, len(td) // 3)
    if td or sd:
        return False
    t, s = _norm(typed), _norm(seen)
    if len(t) < 5 or len(s) < 5 or t == s or t in s or s in t:
        return False
    return SequenceMatcher(None, t, s).ratio() >= TEXT_SIMILARITY


def is_misread_number(typed: str, seen: str) -> bool:
    """A looser test for a number typed just after reading `seen`: same magnitude and leading
    digit, at most half the digits changed (3,163,843 typed for 3,863,148)."""
    td, sd = _digits(typed), _digits(seen)
    if not td or not sd or td == sd or len(td) < 5 or abs(len(td) - len(sd)) > 1 or td[0] != sd[0]:
        return False
    return _edit_distance(td, sd) <= len(td) // 2


def _tokens(value: str) -> set[str]:
    """Comparable pieces of a value: the whole thing if short, plus numbers, emails, paths, quotes."""
    out = {value.strip()} if len(value.strip()) <= MAX_WHOLE_VALUE else set()
    emails = EMAIL.findall(value)
    out.update(emails)
    rest = EMAIL.sub(" ", value)  # so "jon.doe" / "example.com" aren't also taken as file names
    for rx in (NUMBER, PATHLIKE):
        out.update(m.group(0).strip() for m in rx.finditer(rest))
    out.update(m.group(1).strip() for m in QUOTED.finditer(value))
    return {t for t in out if t}


def find_near_misses(
    events: list[Event],
    candidates: list[StepCandidate],
    visible: list[tuple[str, float]] = (),
    ocr: list[tuple[str, float]] = (),
) -> list[NearMiss]:
    """`visible` holds (value, time) pairs the model listed as visible on screen per segment;
    `ocr` holds text local OCR read from keyframes, timed exactly.

    A typed value counts as correctly copied only if it was on screen *before* it was typed:
    read by OCR, or recorded by the model in a read/select step. Visible-value lists can't
    prove it: once typed, the value is on screen too (in the field it was typed into), so they
    are used only to find near-misses.
    """
    from_steps = [
        (tok, c.t_start)
        for c in candidates
        if c.value and c.action not in TYPING_ACTIONS
        for tok in _tokens(c.value)
    ]
    from_ocr = [(tok, t) for text, t in ocr for tok in _tokens(text)]
    sources = [
        (tok, c.t_start) for c in candidates if c.value and c.action in SOURCE_ACTIONS for tok in _tokens(c.value)
    ] + from_ocr
    # Text the user typed shows up on screen too (a terminal's history, a filled-in field).
    # It is their own input, not a source they copied from, so it never counts as "seen".
    typed_anywhere = {_norm(tok) for ev in events if ev.kind == "type" and ev.text for tok in _tokens(ev.text)}

    def not_typed(pairs):
        return [(tok, t) for tok, t in pairs if _norm(tok) not in typed_anywhere]

    seen = not_typed(from_steps + [(tok, t) for value, t in visible for tok in _tokens(value)] + from_ocr)
    timed = not_typed(sources)  # sightings with exact times, for the "just read" number check
    misses: list[NearMiss] = []
    prev_typed_t = float("-inf")
    for ev in events:
        if ev.kind != "type" or not ev.text or set(ev.text) == {"•"}:
            continue
        exact = {_norm(tok) for tok, t in sources if t < ev.t}
        just_read = [(tok, t) for tok, t in timed if prev_typed_t < t < ev.t]
        prev_typed_t = ev.t
        found: list[NearMiss] = []
        for typed in _tokens(ev.text):
            if _norm(typed) in exact:
                continue  # the typed value was on screen before: fine
            matches = [(tok, t) for tok, t in seen if is_near_miss(typed, tok)]
            matches = matches or [(tok, t) for tok, t in just_read if is_misread_number(typed, tok)]
            if matches:
                tok, t = min(matches, key=lambda m: abs(m[1] - ev.t))  # closest sighting in time
                found.append(NearMiss(typed=typed, seen=tok, typed_t=ev.t, seen_t=t))
        if found:  # one note per typed entry: the most specific (longest) match
            misses.append(max(found, key=lambda m: len(m.typed)))
    return misses


def _cites(line: str, token: str) -> bool:
    """The line names `token` the way error messages cite input: quoted, or as "token:"."""
    t = re.escape(token)
    return bool(re.search(rf"['\"`‘“]{t}['\"`’”]|(?:^|[\s:]){t}\s*:", line, re.I))


def find_rejected_input(events: list[Event], ocr: list[tuple[str, float]] = ()) -> list[NearMiss]:
    """Typed entries followed, within seconds, by new on-screen error text that cites them."""
    typing = [ev for ev in events if ev.kind == "type" and ev.text and set(ev.text) != {"•"}]
    out: list[NearMiss] = []
    for i, ev in enumerate(typing):
        until = min(ev.t + ERROR_WINDOW_S, typing[i + 1].t + 0.5 if i + 1 < len(typing) else float("inf"))
        before = {_norm(text) for text, t in ocr if t <= ev.t}
        words = sorted({w.strip(".,;:") for w in TYPED_WORD.findall(ev.text)} | {ev.text.strip()}, key=len, reverse=True)
        words = [w for w in words if len(w) >= 3]
        for line, t in sorted(ocr, key=lambda x: x[1]):
            if not (ev.t < t <= until) or _norm(line) in before:
                continue  # outside the entry's window, or already on screen before it
            # The error wording must come from the software, not from the typed text echoed back.
            if not ERROR_TEXT.search(re.sub(re.escape(ev.text.strip()), " ", line, flags=re.I)):
                continue
            cited = next((w for w in words if _cites(line, w)), None)
            if cited:
                out.append(NearMiss(typed=cited, seen=line.strip(), typed_t=ev.t, seen_t=t, kind="rejected"))
                break
    return out


def annotate_steps(steps: list[Step], misses: list[NearMiss], fmt_ts) -> int:
    """Add a review note to the step that entered each flagged value. Returns notes added."""
    added = 0
    for m in misses:
        # Prefer the step that says it entered the value: model step times can be off by a
        # keyframe, so a neighbouring "click the field" step often contains the typing time.
        typed = _norm(m.typed)
        entering = [s for s in steps if typed in _norm(f"{s.title} {s.description} {s.value or ''}")]
        if entering:
            def rank(s: Step, t: float = m.typed_t) -> tuple[bool, float]:  # typing steps first, even merged
                return not set(s.action.split(" + ")) & TYPING_ACTIONS, abs(s.t_start - t)

            step = min(entering, key=rank)
        else:
            containing = [s for s in steps if s.t_start - 0.5 <= m.typed_t <= s.t_end + 0.5]
            earlier = [s for s in steps if s.t_start <= m.typed_t]
            step = (containing or earlier[-1:] or steps[:1] or [None])[0]
        if step is None:
            continue
        note = m.note(fmt_ts)
        if step.review_note and m.typed in step.review_note and m.seen in step.review_note:
            continue  # the model already said the same thing
        step.review_note = f"{step.review_note} {note}" if step.review_note else note
        added += 1
    return added

