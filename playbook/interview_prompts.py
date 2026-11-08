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

# --- Gated extraction (amendment 8) --------------------------------------------------------------------------
# Step 1 classifies the answer three ways; only ITEM goes on. A yes/no "does this give a reason?" gate was tried first
# and rejected many clear answers (the 4B model read first-person answers about the item as being about the person);
# the three-way choice, with first-person examples about the item, did much better on the development paraphrases.
# Step 2 (below) quotes the phrase, by a majority of three wordings. The worked examples are unrelated to any domain
# used in testing.
CLASSIFY_SYSTEM = (
    "A person was asked why they made a choice about an item they were checking (a job, an invoice, a ticket, an "
    "account). Classify their answer. Reply as JSON {\"category\": \"ITEM\" or \"SELF\" or \"NONE\"}.\n"
    "ITEM = the reason is about the item itself or what happened to it (its state, history, age, type), even if the "
    "answer is written in the first person.\n"
    "SELF = the reason is about the person or their surroundings (hunger, time of day, meetings, noise, weather).\n"
    "NONE = no reason is given (a shrug, instinct, 'not sure').\n"
    "Examples:\n'I was waiting for the invoice to clear approval.' -> ITEM\n'The account was brand new, so I gave it room.' -> ITEM\n"
    "'I always wait a week on these.' -> ITEM\n'It was almost lunchtime.' -> SELF\n'My train was delayed.' -> SELF\n"
    "'I was tired that afternoon.' -> SELF\n'Can't say, just felt right.' -> NONE\n'No particular reason.' -> NONE"
)

PHRASE_VARIANTS = (
    ("Copy, from the person's answer, the shortest phrase (at most five words) that names the circumstance they say "
     "mattered. Use their own words; the phrase must appear in the answer. If the condition is the same idea as one of "
     "the KNOWN conditions, reply with that exact KNOWN wording instead. Reply as JSON: {\"phrase\": \"...\"}."),
    ("Which words in the answer name the circumstance that explains the choice? Give at most five consecutive words "
     "taken from the answer. If it matches a KNOWN condition, give that KNOWN condition exactly. "
     "Reply as JSON: {\"phrase\": \"...\"}."),
    ("From the answer, quote the part that says what was going on (at most five words, copied from the answer). "
     "Reuse a KNOWN condition's wording if it is the same thing. Reply as JSON: {\"phrase\": \"...\"}."),
)

CRITIQUE_SYSTEM = (
    "A person answered a question about a choice they made. Rate from 0 to 1 how specifically the answer explains "
    "that choice: 0 means vague or off topic, 1 means it names a concrete condition that would let someone predict "
    "the choice. Reply as JSON: {\"rating\": 0.0}."
)

FOLLOW_UP = ("You said '{fact}'. Did it also hold in any of these other cases? Give the numbers, or say none.\n{cases}")

# Used when the model fails or breaks a rule above.
FALLBACK_QUESTION = "In this case you chose '{did}', while in similar situations you chose '{expected}'. What did you know that the screen does not show?"

# One question about several similar misfits at once (amendment 8). v0 wording: a placeholder for the question design.
GROUP_QUESTION = ("In these {n} cases you chose '{did}', while in similar situations you chose '{expected}':\n{cases}\n"
                  "What do they have in common that the screen does not show? Say which of them it applies to.")
