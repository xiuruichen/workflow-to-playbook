"""The pilot kit: case generation, the offline page, and the report built from a downloaded log."""

import json

from playbook import __main__ as cli
from playbook import pilot


def person_log(n=60, seed=3, stated="I stop it when there are two or more spikes, unless I just raised the batch size."):
    """A scripted person for the test: stops when spikes >= 2 and the batch size did not just change."""
    cases = pilot.make_cases("run", n, seed)
    log, prev = [], None
    for i, c in enumerate(cases):
        changed = prev is not None and c["readouts"]["Batch size"] != prev["Batch size"]
        act = c["readouts"]["Spikes"] >= 2 and not changed
        log.append({"index": i, "readouts": c["readouts"], "cats": c["cats"], "choice": "act" if act else "leave",
                    "dwell_s": 6.0, "reason": "two spikes" if act and i % 7 == 0 else ""})
        prev = c["readouts"]
    return {"meta": {"theme": "run", "seed": seed, "act": "Stop the run", "leave": "Leave it running"}, "stated_rule": stated, "cases": log}


def test_cases_are_reproducible_and_items_come_back():
    a, b = pilot.make_cases("run", 40, 7), pilot.make_cases("run", 40, 7)
    assert a == b and a != pilot.make_cases("run", 40, 8)
    assert all(set(c["readouts"]) == {"Spikes", "Batch size", "Loss", "Hours since last check"} and c["cats"]["Dataset"] in ("clean", "new") for c in a)
    assert any(x["cats"] == y["cats"] and x["readouts"]["Loss"] == y["readouts"]["Loss"] for x, y in zip(a, a[1:])), "an item should come back"
    for theme in pilot.THEMES:
        assert len(pilot.make_cases(theme, 12, 1)) == 12


def test_page_is_offline_and_carries_the_cases():
    cases = pilot.make_cases("invoice", 5, 1)
    page = pilot.render_html(cases, "invoice", 1)
    assert "<script src" not in page and "http" not in page.replace("https://", "x").split("<script>")[0].replace("http-equiv", "")
    assert json.dumps(cases) in page and "Escalate" in page and "Download the log" in page
    assert "__" not in page.replace("__proto__", ""), "every placeholder is filled"


def test_report_recovers_a_scripted_persons_rule_and_compares_it_with_their_words(tmp_path):
    path = tmp_path / "pilot_log.json"
    path.write_text(json.dumps(person_log()), encoding="utf-8")
    decisions, raw = pilot.load_log(path)
    assert len(decisions) == 60 and {d.outcome for d in decisions} == {"none", "Stop the run"}
    text = pilot.report(decisions, raw)
    assert "## The rule we found" in text and "spikes" in text and "changed_batch_size" in text
    assert "you mention it" in text and "Reasons you wrote while deciding" in text
    silent = pilot.report(decisions, {**raw, "stated_rule": "I just go by feel."})
    assert "you did not mention it" in silent


def test_report_with_too_few_cases_says_so(tmp_path):
    log = person_log(n=5)
    path = tmp_path / "l.json"
    path.write_text(json.dumps(log), encoding="utf-8")
    d, raw = pilot.load_log(path)
    assert "Too few cases" in pilot.report(d, raw)


def test_cli_make_and_report(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert cli.main(["pilot", "make", "--theme", "ticket", "--cases", "10"]) == 0
    assert (tmp_path / "pilot.html").is_file()
    (tmp_path / "pilot_log.json").write_text(json.dumps(person_log()), encoding="utf-8")
    assert cli.main(["pilot", "report", str(tmp_path / "pilot_log.json")]) == 0
    assert "The rule we found" in (tmp_path / "pilot_report.md").read_text(encoding="utf-8")
    assert cli.main(["pilot", "report", str(tmp_path / "missing.json")]) == 1


def test_interview_turns_a_named_condition_into_a_feature(tmp_path):
    from playbook import elicit

    log = person_log(n=60)
    for c in log["cases"][:60]:  # the person also waits when the dataset is new, which nothing else explains
        if c["cats"]["Dataset"] == "new":
            c["choice"] = "leave"
    path = tmp_path / "l.json"
    path.write_text(json.dumps(log), encoding="utf-8")
    decisions, _ = pilot.load_log(path)
    asked = []

    def ask(prompt):
        asked.append(prompt)
        if prompt.startswith(">"):
            return "the data was new"
        if prompt.startswith("Name"):
            return "new data"
        return ""

    result = pilot.ask_loop(decisions, tmp_path / "answers.jsonl", ask=ask, say=lambda *_: None)
    saved = elicit.load_answers(tmp_path / "answers.jsonl")
    assert saved and saved[0].fact == "new data" and saved[0].reason == "the data was new"
    assert result["after"]["accuracy"] >= result["before"]["accuracy"]


def test_cli_elicit_runs_without_answers(tmp_path, monkeypatch, capsys):
    import io

    (tmp_path / "pilot_log.json").write_text(json.dumps(person_log()), encoding="utf-8")
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    assert cli.main(["pilot", "elicit", str(tmp_path / "pilot_log.json")]) == 0
    assert "Rule before your answers" in capsys.readouterr().out


def test_the_page_really_logs_choices_in_a_browser_like_runtime(tmp_path):
    """Drives the page's own JavaScript (node, with a small DOM stub): start, answer every case by key, save."""
    import shutil
    import subprocess
    from pathlib import Path

    import pytest

    node = shutil.which("node")
    if not node:
        pytest.skip("needs node")
    cases = pilot.make_cases("ticket", 8, 2)
    page = tmp_path / "p.html"
    page.write_text(pilot.render_html(cases, "ticket", 2), encoding="utf-8")
    picks = "ALLAALLA"
    out = subprocess.run([node, str(Path(__file__).parent / "pilot_page_driver.js"), str(page), picks],
                         capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    log = json.loads(out.stdout)
    assert [c["choice"] for c in log["cases"]] == ["act" if p == "A" else "leave" for p in picks]
    assert log["stated_rule"].startswith("I act") and log["meta"]["theme"] == "ticket"
    assert [c["readouts"] for c in log["cases"]] == [c["readouts"] for c in cases]
    path = tmp_path / "pilot_log.json"
    path.write_text(out.stdout, encoding="utf-8")
    decisions, _ = pilot.load_log(path)
    assert [d.outcome == "none" for d in decisions] == [p == "L" for p in picks]
