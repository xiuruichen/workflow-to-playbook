# LLM-driven interview, test seeds (amendment 7; 10 interviews; file `test.jsonl`)

| bar | measured | verdict |
|---|---|---|
| H8 extraction on clear answers >= 80% | 3/6 = 50% | FAILS |
| H8 no condition for vague/irrelevant >= 80% | 30/30 = 100% | holds |
| H9 interview gain >= 70% of structured gain | +0.033 vs +0.071 (47%) | FAILS |
| Leakage: 0 questions with the hidden terms | 0 of 22 model-written questions | holds |
| H10 (exploratory) Spearman rating vs measured effect >= 0.3 | 0.79 over 22 answers | holds |

Per domain (mean over seeds):

| domain | before | after (interview) | gain | structured gain | questions |
|---|---|---|---|---|---|
| dashboard | 0.850 | 0.908 | +0.058 | +0.117 | 2.8 |
| triage | 0.717 | 0.725 | +0.008 | +0.025 | 4.4 |

Question quality with an LLM persona as the expert (exploratory):

| strategy | interviews | gain | questions | first matching condition at question |
|---|---|---|---|---|
| template | 10 | +0.067 | 3.1 | 1.0 (found in 2 of 10) |
| v0_context | 10 | +0.071 | 3.7 | 1.2 (found in 4 of 10) |
| v0_counterfactual | 10 | +0.029 | 4.1 | 2.0 (found in 5 of 10) |
| v0_open | 10 | +0.071 | 3.6 | 1.0 (found in 5 of 10) |

Code at tag `freeze-5` (commit 9717b88). Raw data: `interview/test.jsonl` (free-text scripted expert), `interview/test_llm_expert.jsonl` (LLM persona), development runs `interview/dev_patience2.jsonl` and `dev_patience4.jsonl`.
