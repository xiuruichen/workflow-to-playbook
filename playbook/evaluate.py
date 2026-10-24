"""Measure how well the pipeline generalises across kinds of computer work.

    python -m playbook.evaluate                 # build + analyze all scenarios, print a scorecard
    python -m playbook.evaluate --no-api        # only build the scenario sessions
    python -m playbook.evaluate coding email    # selected scenarios

Each scenario in scenarios.py has ground truth: the steps a correct playbook must contain
and (optionally) a planted mistake that must be flagged. Responses are cached, so re-running
costs no quota unless prompts or scenarios change.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass

from .config import get_settings
from .models import Playbook, Step
from .scenarios import SCENARIOS, Scenario, simulate


@dataclass
class Score:
    scenario: str
    steps: int
    expected_found: int
    expected_total: int
    missing: list[str]
    mistake_planted: bool
    mistake_flagged: bool
    false_flags: int
    api_calls: int
    model: str

    @property
    def recall(self) -> float:
        return self.expected_found / self.expected_total if self.expected_total else 1.0


def _step_text(s: Step) -> str:
    """What the step says it does (not the review fields, so they can't satisfy recall)."""
    return " ".join(x for x in (s.title, s.description, s.target or "", s.value or "", s.expected_result or "", s.app or "")).lower()


def _matches(text: str, keywords: list[str]) -> bool:
    return all(any(alt in text for alt in kw.split("|")) for kw in keywords)


def score(sc: Scenario, pb: Playbook, api_calls: int = 0) -> Score:
    texts = [_step_text(s) for s in pb.steps]
    missing = [" + ".join(kw) for kw in sc.expected_steps if not any(_matches(t, kw) for t in texts)]

    def mentions_mistake(s: Step) -> bool:
        """The step performs the mistaken action (not merely a note that refers to it)."""
        return any(re.search(re.escape(w.lower()), _step_text(s)) for w in sc.mistake)

    flagged = [s for s in pb.steps if s.needs_review]
    mistake_flagged = bool(sc.mistake) and any(mentions_mistake(s) for s in flagged)
    false_flags = sum(1 for s in flagged if not (sc.mistake and mentions_mistake(s)))
    return Score(
        scenario=sc.name, steps=len(pb.steps), expected_found=len(sc.expected_steps) - len(missing),
        expected_total=len(sc.expected_steps), missing=missing, mistake_planted=bool(sc.mistake),
        mistake_flagged=mistake_flagged, false_flags=false_flags, api_calls=api_calls, model=pb.model,
    )


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(prog="python -m playbook.evaluate", description=__doc__.split("\n\n")[0])
    p.add_argument("scenarios", nargs="*", choices=[[], *SCENARIOS], help="default: all")
    p.add_argument("--no-api", action="store_true", help="only build the scenario sessions")
    args = p.parse_args(argv)
    settings = get_settings()
    names = args.scenarios or list(SCENARIOS)
    eval_dir = settings.sessions_dir / "_eval"

    scores: list[Score] = []
    for name in names:
        sc = SCENARIOS[name]
        # Kept apart from real recordings so they don't show up as the "latest" session.
        session = simulate(sc, settings, eval_dir / name)
        print(f"[{name}] built {session}")
        if args.no_api:
            continue
        from .analyzer import AnalysisError, Analyzer
        from .generator import write_playbook

        analyzer = Analyzer(settings, progress=lambda f, m, n=name: print(f"\r[{n}] {m[:90]:<90}", end="", flush=True))
        try:
            pb = analyzer.analyze(session)
        except AnalysisError as exc:
            print(f"\n[{name}] analysis failed: {exc}")
            return 1
        write_playbook(pb, session)
        print()
        scores.append(score(sc, pb, analyzer.vc.calls))

    if not scores:
        return 0
    print(f"\n{'scenario':<10} {'steps':>5} {'expected found':>15} {'mistake':>9} {'false flags':>12} {'calls':>6}  model")
    for s in scores:
        mistake = ("caught" if s.mistake_flagged else "MISSED") if s.mistake_planted else "n/a"
        print(f"{s.scenario:<10} {s.steps:>5} {s.expected_found:>9}/{s.expected_total:<5} {mistake:>9} {s.false_flags:>12} {s.api_calls:>6}  {s.model}")
        for m in s.missing:
            print(f"{'':<10} missing: {m}")
    out = eval_dir / "eval_results.json"
    out.write_text(json.dumps([asdict(s) | {"recall": s.recall} for s in scores], indent=2), encoding="utf-8")
    print(f"\nSaved {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
