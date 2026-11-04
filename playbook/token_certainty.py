"""How firmly the model chose what it wrote, from its token probabilities (no extra model call).

A local model's self-reported confidence barely varies (0.9 for nearly every step), but while writing
it weighs each token against the alternatives. A step's score is the smallest gap between a chosen token
and its best rival in the fields that say what happened: 1.0 is a firm choice, near 0 a coin flip.

Most hesitation is wording ("cursor" vs "pointer", where to end a phrase), so descriptions and evidence
aren't scored, and filler words and rivals that are only punctuation or a different case don't count. This shows
hesitation, not truth: the model can firmly misread text, and a person's typo won't show up at all
(consistency.py handles those).
"""

from __future__ import annotations

import math
import re
from typing import Any

FIELDS = (b"target", b"value")
TOP_LOGPROBS = 3  # the chosen token can be one of them, and the best rival may not count
_JSON_TOKEN = re.compile(rb'"(?:[^"\\]|\\.)*"|[{}\[\]]')
_FILLER = {"a", "an", "and", "at", "by", "for", "from", "in", "into", "is", "of", "on", "or", "that", "the", "this", "to", "with"}


def _field_spans(raw: bytes) -> list[tuple[int, str, int, int]]:
    """(step index, field, start, end) of the scored string values in a pass-1 reply. Strings are matched
    whole, so braces inside them can't confuse the nesting."""
    spans: list[tuple[int, str, int, int]] = []
    depth, step, in_steps, key = 0, -1, False, None
    for m in _JSON_TOKEN.finditer(raw):
        tok = m.group()
        if tok in (b"{", b"["):
            depth += 1
            if in_steps and depth == 3:
                step += 1
        elif tok in (b"}", b"]"):
            depth -= 1
            in_steps = in_steps and depth >= 2
        elif raw[m.end():m.end() + 8].lstrip()[:1] == b":":
            key = tok[1:-1]
            if depth == 1 and key == b"steps":
                in_steps = True
        else:
            if in_steps and depth == 3 and key in FIELDS and len(tok) > 2:
                spans.append((step, key.decode(), m.start() + 1, m.end() - 1))
            key = None
    return spans


def _meaningful(token: str) -> bool:
    return any(c.isalnum() for c in token) and token.casefold() not in _FILLER


def _firmness(entry: Any) -> tuple[float, str] | None:
    """(gap to the best rival that changes the meaning, that rival), or None if there is no such rival."""
    chosen = entry.token.strip()
    if not _meaningful(chosen):
        return None
    for rival in sorted(entry.top_logprobs or [], key=lambda r: -r.logprob):
        other = rival.token.strip()
        if _meaningful(other) and other.casefold() != chosen.casefold():
            return max(0.0, math.exp(entry.logprob) - math.exp(rival.logprob)), other
    return None


def weakest_tokens(content: str, tokens: list[Any] | None) -> dict[str, dict] | None:
    """For each step of a pass-1 reply (keyed by its position, as a string so it survives JSON): the least
    firm token in its scored fields. Steps with nothing to score are left out. None means the server gave
    no usable probabilities, which is different from a reply where every choice was firm."""
    if not tokens:
        return None
    pieces = [bytes(t.bytes) if t.bytes is not None else t.token.encode("utf-8") for t in tokens]
    raw = b"".join(pieces)
    # Positions come from the tokens themselves: llama-server strips a ```json fence from the reply's text only.
    if content.encode("utf-8").strip() not in raw:
        return None  # not the same text, so scoring would blame the wrong tokens
    spans = _field_spans(raw)
    out: dict[str, dict] = {}
    pos, i = 0, 0
    for entry, piece in zip(tokens, pieces):
        start, pos = pos, pos + len(piece)
        while i < len(spans) and spans[i][3] <= start:
            i += 1
        if i == len(spans):
            break
        step, field, a, b = spans[i]
        if start >= b or pos <= a:
            continue
        scored = _firmness(entry)
        if scored and (str(step) not in out or scored[0] < out[str(step)]["certainty"]):
            out[str(step)] = {"certainty": round(scored[0], 3), "field": field, "token": entry.token.strip(), "rival": scored[1]}
    return out
