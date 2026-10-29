import json
from pathlib import Path

import pytest

from playbook.models import InputVariable, Playbook, Step
from playbook.skill import build_skill, render_skill_md, skill_name, write_skill

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "city-population-lookup"


def step(i, title, action="click", value=None, target=None, conf=0.9, note=None, review="unreviewed"):
    return Step(index=i, title=title, description=title, action=action, value=value, target=target,
                t_start=float(i), t_end=float(i) + 1, model_confidence=conf, confidence=conf,
                review_note=note, review=review)


def playbook(steps, inputs=()):
    return Playbook(title="Send the Q3 report", goal="Email the Q3 report to a colleague.", apps=["Outlook"],
                    inputs=list(inputs), steps=steps, session_id="s1", source="live", duration=28.0,
                    model="test", threshold=0.7, generated_at="2026-10-28T00:00:00")


def test_input_examples_become_placeholders_longest_first():
    pb = playbook([step(1, "Type john.doe@example.com into To", "type", "john.doe@example.com", "To"),
                   step(2, "Open report.pdf from Reports", "double_click", "report.pdf")],
                  [InputVariable(name="domain", example="example.com"),
                   InputVariable(name="recipient", example="john.doe@example.com"),
                   InputVariable(name="file", example="report.pdf")])
    s1, s2 = build_skill(pb)["steps"]
    assert s1["value"] == "{{recipient}}" and s1["title"] == "Type {{recipient}} into To"
    assert s1["value_kind"] == "input"
    assert s2["value"] == "{{file}}"


def test_placeholders_do_not_match_inside_longer_tokens():
    pb = playbook([step(1, "Select cell B23", "click", "B23")], [InputVariable(name="cell", example="B2")])
    assert build_skill(pb)["steps"][0]["value"] == "B23"


def test_value_read_on_screen_flows_into_the_typed_step_even_with_a_typo():
    pb = playbook([step(1, "Read the population", "read", "Population: 168,412"),
                   step(2, "Type the population", "type", "186,412", "Cell B2", note="Typed 186,412 but 168,412 was seen.")])
    read, typed = build_skill(pb)["steps"]
    assert read["value_kind"] == "observed"
    assert typed["value_kind"] == "from_step" and typed["value"] == "{{step-1}}"
    assert typed["value_from"] == {"step": "step-1", "recorded_source": "168,412", "recorded_value": "186,412"}
    assert typed["requires_confirmation"] and "168,412" in typed["confirmation_reason"]


def test_gates_follow_review_state():
    pb = playbook([step(1, "Unsure click", conf=0.4),
                   step(2, "Unsure but confirmed", conf=0.4, review="correct"),
                   step(3, "A mistake", review="wrong"),
                   step(4, "Fine")])
    sk = build_skill(pb)
    assert [(s["title"], s["requires_confirmation"]) for s in sk["steps"]] == [
        ("Unsure click", True), ("Unsure but confirmed", False), ("Fine", False)]
    assert sk["steps"][0]["confirmation_reason"].startswith("Low confidence (0.40)")
    assert sk["excluded_steps"] == [{"playbook_step": 3, "title": "A mistake", "reason": "Marked wrong in review"}]
    assert [s["id"] for s in sk["steps"]] == ["step-1", "step-2", "step-3"]  # renumbered without the excluded step
    assert sk["provenance"]["steps_needing_confirmation"] == 1


def test_skill_md_frontmatter_is_valid():
    yaml = pytest.importorskip("yaml")
    pb = playbook([step(1, "Click Send")])
    pb.title = "Send: the Q3 report — \"final\" version!" * 4
    md = render_skill_md(pb)
    _, front, body = md.split("---\n", 2)
    meta = yaml.safe_load(front)
    assert meta["name"] == skill_name(pb.title)
    assert len(meta["name"]) <= 64 and meta["name"].replace("-", "").isalnum() and meta["name"].islower()
    assert 0 < len(meta["description"]) <= 1024
    assert "## Steps" in body


def test_example_playbook_exports(tmp_path):
    pb = Playbook.load(EXAMPLE)
    path = write_skill(pb, tmp_path / "skill")
    sk = json.loads((tmp_path / "skill" / "skill.json").read_text(encoding="utf-8"))
    assert path.read_text(encoding="utf-8").startswith("---\nname: ")
    typo = next(s for s in sk["steps"] if s["value_kind"] == "from_step")
    assert typo["requires_confirmation"] and typo["value_from"]["recorded_value"] == "186,412"
    assert "{{city_name}}" in json.dumps(sk)


def test_typed_values_become_inputs_when_the_model_listed_none():
    """Small models in low-power mode return no inputs; what was typed is what varies."""
    pb = playbook([step(1, "Read the population", "read", "168,412"),
                   step(2, "Type the city", "type", "Springfield", "Search"),
                   step(3, "Type the population", "type", "168,412", "Cell B2"),
                   step(4, "Type another search", "type", "Shelbyville", "Search")])
    sk = build_skill(pb)
    assert list(sk["parameters"]["properties"]) == ["search", "search_2"]  # not the copied number
    assert [s["value"] for s in sk["steps"][1:]] == ["{{search}}", "{{step-1}}", "{{search_2}}"]
