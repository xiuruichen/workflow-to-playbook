"""The wording of the interview, kept apart from the code that runs it.

Everything here is **v0**: plain placeholders written to make the pipeline work end to end, not a considered
design. How to ask people about choices the recording does not explain, and what counts as a good answer, are
open design questions (docs/interview-guide.md). To try a different question, add an entry to STRATEGIES and select
it by name (`--questions NAME`); nothing else needs to change. `scripts/compare_question_sets.py` runs several
strategies against the same simulated experts so that they can be compared on the same footing.

Rules the code enforces whatever the wording (see interview.py): a question must be short and may not contain a
digit or a threshold; the model is never told the fitted rule; a condition extracted from an answer must be short;
tags may only name cases that were offered.
"""

from __future__ import annotations

QUESTION_SYSTEM = (
    "You are interviewing a person about one choice they made while watching something on a computer. "
    "You will be shown what was on screen and what they did. Write ONE short question (at most 25 words) in plain "
    "language. Do not suggest a reason, a rule, a number or a threshold, and do not explain how the choice was "
    "analysed. Reply as JSON: {\"question\": \"...\"}."
)

# name -> {"description": for people reading this file, "instruction": appended to the system prompt}
STRATEGIES: dict[str, dict[str, str]] = {
    "v0_open": {
        "description": "Ask what the person knew or considered that the screen does not show.",
        "instruction": "Ask what they knew or were thinking at that moment that the screen does not show.",
    },
    "v0_counterfactual": {
        "description": "Ask what would have made them choose differently.",
        "instruction": "Ask what would have had to be different for them to choose otherwise here.",
    },
    "v0_context": {
        "description": "Ask what happened earlier that shaped this choice.",
        "instruction": "Ask what had happened before this check, earlier that day or on earlier days, that shaped the choice.",
    },
}
DEFAULT_STRATEGY = "v0_open"

INTERPRET_SYSTEM = (
    "A person was asked why they made a choice. Extract the CONDITION they say mattered: the specific situation, state "
    "or event they give as the reason, in their own words, as a short phrase of at most five words (for example "
    "'customer on a trial plan' or 'end of the month'). If they give such a reason, even briefly, report it. Only if "
    "the answer gives no reason at all (a shrug, 'I don't know', 'not sure') or only remarks on the "
    "person's own mood, schedule or distractions rather than on the thing they were checking, set condition to null. If the condition means the same as one of the KNOWN conditions, reuse that exact "
    "wording. kind is 'off_screen' if the condition is something not visible on the screen they were shown, "
    "'on_screen' if it was visible, 'none' if there is no condition. Reply as JSON."
)

CRITIQUE_SYSTEM = (
    "A person answered a question about a choice they made. Rate from 0 to 1 how specifically the answer explains "
    "that choice: 0 means vague or off topic, 1 means it names a concrete condition that would let someone predict "
    "the choice. Reply as JSON: {\"rating\": 0.0}."
)

FOLLOW_UP = ("You said '{fact}'. Did it also hold in any of these other cases? Give the numbers, or say none.\n{cases}")

# Used when the model fails or breaks a rule above.
FALLBACK_QUESTION = "In this case you chose '{did}', while in similar situations you chose '{expected}'. What did you know that the screen does not show?"
