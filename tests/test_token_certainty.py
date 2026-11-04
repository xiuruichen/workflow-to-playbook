import json
import math
import re
from types import SimpleNamespace

import pytest

from playbook.analyzer import Analyzer
from playbook.token_certainty import weakest_tokens
from tests.conftest import FakeClient

REPLY = {"window_context": "value: {not a step}", "visible_values": ["186,412"], "steps": [
    {"action": "read", "description": "Read 168,412", "target": "Population cell", "value": "168,412", "start_image": 1,
     "end_image": 2, "confidence": 0.9, "evidence": "shown"},
    {"action": "click", "description": "Click Save", "target": "Save", "value": None, "start_image": 2,
     "end_image": 3, "confidence": 0.9, "evidence": "ring"},
]}
PASS2 = {"title": "t", "steps": [{"title": "Read", "source_ids": ["c1"], "confidence": 0.9},
                                 {"title": "Save", "source_ids": ["c2"], "confidence": 0.9}]}


def token(text, p=0.99, rivals=(("x", 0.005),)):
    """A token as the OpenAI client returns it; `p` is the chosen token's probability."""
    tops = [(text, p), *rivals]
    return SimpleNamespace(token=text, bytes=list(text.encode()), logprob=math.log(p),
                           top_logprobs=[SimpleNamespace(token=t, logprob=math.log(q)) for t, q in tops])


def tokenize(content, unsure=None):
    """Split a reply like a tokenizer, with the given {piece: (p, rivals)} hesitations."""
    pieces = re.findall(r"\d|[A-Za-z]+|\s+|.", content, re.S)
    return [token(t, *(unsure or {}).get(t, ())) for t in pieces]


def score(unsure=None, content=None):
    content = content or json.dumps(REPLY)
    return weakest_tokens(content, tokenize(content, unsure))


def test_near_tie_in_a_value_scores_low_and_names_both_tokens():
    out = score({"6": (0.41, (("8", 0.38),))})
    assert out["0"] == {"certainty": pytest.approx(0.03), "field": "value", "token": "6", "rival": "8"}


def test_firm_choices_score_high():
    out = score()
    assert out["0"]["certainty"] > 0.9 and out["1"]["certainty"] > 0.9


def test_wording_in_descriptions_and_evidence_is_not_scored():
    assert score({"shown": (0.3, (("visible", 0.29),))})["0"]["certainty"] > 0.9


def test_text_outside_steps_and_null_values_are_not_scored():
    assert set(score()) == {"0", "1"}
    assert score({"not": (0.3, (("a", 0.29),))})["0"]["certainty"] > 0.9  # "value:" inside window_context


def test_punctuation_and_case_rivals_do_not_count():
    out = score({"cell": (0.4, (('"', 0.39), ("Cell", 0.2)))})
    assert out["0"]["certainty"] > 0.9
    # with a real rival behind them, that one counts
    out = score({"cell": (0.4, (('"', 0.39), ("box", 0.2)))})
    assert out["0"]["certainty"] == pytest.approx(0.2) and out["0"]["rival"] == "box"


def test_filler_words_do_not_count_as_hesitation():
    assert score({"cell": (0.4, (("the", 0.39),))})["0"]["certainty"] > 0.9  # "the line" vs "print(...)" is wording
    content = json.dumps({"steps": [{"description": "d", "target": "line of code", "value": None}]})
    assert weakest_tokens(content, tokenize(content, {"of": (0.4, (("in", 0.39),))}))["0"]["certainty"] > 0.9


def test_chosen_token_below_its_rival_scores_zero():
    assert score({"6": (0.2, (("8", 0.7),))})["0"]["certainty"] == 0.0


def test_markdown_fence_in_tokens_only_is_handled():
    """llama-server removes a ```json fence from the reply text but not from the token stream."""
    content = json.dumps(REPLY)
    tokens = [token("```"), token("json\n"), *tokenize(content, {"6": (0.41, (("8", 0.38),))}), token("\n```")]
    assert weakest_tokens(content, tokens)["0"]["rival"] == "8"


def test_non_ascii_values_keep_their_offsets():
    content = json.dumps({"steps": [{"description": "é", "target": "Prénom", "value": "Zoë"}]}, ensure_ascii=False)
    tokens = [token(c) for c in content]
    tokens[content.index("Z")] = token("Z", 0.4, (("X", 0.35),))
    assert weakest_tokens(content, tokens)["0"]["token"] == "Z"


def test_missing_or_mismatched_tokens_mean_no_data():
    assert weakest_tokens("{}", None) is None and weakest_tokens("{}", []) is None
    assert weakest_tokens(json.dumps(REPLY), [token("something else")]) is None


# ---------------------------------------------------------------------- pipeline
def run(settings, session, unsure=None, pass1=REPLY, pass2=PASS2):
    client = FakeClient((pass1,), (pass2,))
    client.logprobs = lambda text: tokenize(text, unsure)
    return Analyzer(settings, client=client).analyze(session), client


def test_hesitation_flags_a_step_the_model_called_confident(settings, make_session):
    pb, client = run(settings, make_session(), {"6": (0.41, (("8", 0.38),))})
    read, save = pb.steps
    assert read.needs_review and read.confidence < settings.confidence_threshold
    assert read.model_confidence == pytest.approx(0.9)
    assert '"6" over "8"' in read.uncertainty_reason and any('"6" over "8"' in n for n in read.calibration_notes)
    assert read.token_certainty == pytest.approx(0.03)
    assert not save.needs_review and save.token_certainty > 0.9


def test_only_pass1_asks_for_probabilities(settings, make_session):
    _, client = run(settings, make_session())
    first, last = client.requests[0], client.requests[-1]
    assert first["logprobs"] is True and first["top_logprobs"] >= 2
    assert "logprobs" not in last


def test_cloud_models_are_not_asked(settings, make_session):
    settings.provider, settings.allow_cloud = "gemini", True
    _, client = run(settings, make_session())
    assert all("logprobs" not in r for r in client.requests)


def test_cached_replies_keep_the_score_small_and_change_the_cutoff_for_free(settings, make_session):
    session = make_session()
    run(settings, session, {"6": (0.41, (("8", 0.38),))})
    sizes = [p.stat().st_size for p in settings.cache_dir.glob("*.json")]
    assert all("top_logprobs" not in p.read_text(encoding="utf-8") for p in settings.cache_dir.glob("*.json"))
    assert max(sizes) < 3000
    settings.token_certainty_min = 0.0  # re-running needs no model call and gives the same scores
    pb, client = run(settings, session)
    assert client.requests == []
    assert pb.steps[0].token_certainty == pytest.approx(0.03) and not pb.steps[0].needs_review


def test_replies_cached_before_this_still_hit_and_say_so(settings, make_session):
    session = make_session()
    client = FakeClient((REPLY,), (PASS2,))  # a server that doesn't report probabilities
    pb = Analyzer(settings, client=client).analyze(session)
    assert [s.token_certainty for s in pb.steps] == [None, None] and not any(s.needs_review for s in pb.steps)
    assert any("no token probabilities" in n for n in pb.notes)
    pb, client = run(settings, session)
    assert client.requests == []
    assert any("no token probabilities" in n for n in pb.notes)


def test_merging_does_not_settle_a_hesitation(settings, make_session):
    merged = {"title": "t", "steps": [{"title": "Read and save", "source_ids": ["c1", "c2"], "confidence": 0.95}]}
    pb, _ = run(settings, make_session(), {"6": (0.41, (("8", 0.38),))}, pass2=merged)
    assert pb.steps[0].needs_review and pb.steps[0].token_certainty == pytest.approx(0.03)


def test_old_playbooks_load_without_the_field(settings, make_session):
    pb, _ = run(settings, make_session())
    data = json.loads(pb.model_dump_json())
    for step in data["steps"]:
        del step["token_certainty"]
    assert type(pb).model_validate(data).steps[0].token_certainty is None
