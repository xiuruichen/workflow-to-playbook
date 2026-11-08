# Amendment 10, H19: an executable judgment for the agent (Qwen3-VL 4B, text only, seeds 11-15, 40 visits, 3 repeats)

Agreement with the person's later decisions: mean over seeds (min-max of the per-seed repeat means).

| domain | arm | agreement | ask a human | wrong actions | missed actions |
|---|---|---|---|---|---|
| dashboard | majority | 0.57 (0.33-0.83) | 0 | 8 | 22 |
| dashboard | rules | 0.83 (0.58-1.00) | 0 | 0 | 10 |
| dashboard | skill | 0.63 (0.50-0.83) | 0 | 0 | 26 |
| dashboard | skill+judgment | 0.52 (0.25-0.58) | 10 | 10 | 19 |
| dashboard | skill+evaluator | 0.75 (0.58-1.00) | 0 | 0 | 19 |
| triage | majority | 0.45 (0.25-0.58) | 0 | 9 | 24 |
| triage | rules | 0.67 (0.42-1.00) | 5 | 5 | 10 |
| triage | skill | 0.43 (0.33-0.58) | 0 | 34 | 0 |
| triage | skill+judgment | 0.43 (0.33-0.58) | 10 | 12 | 12 |
| triage | skill+evaluator | 0.67 (0.42-1.00) | 5 | 5 | 10 |
| service | majority | 0.70 (0.58-0.75) | 0 | 0 | 18 |
| service | rules | 0.70 (0.17-0.92) | 15 | 1 | 2 |
| service | skill | 0.70 (0.58-0.75) | 0 | 0 | 18 |
| service | skill+judgment | 0.92 (0.75-1.00) | 0 | 2 | 3 |
| service | skill+evaluator | 0.70 (0.17-0.92) | 15 | 1 | 2 |

Readouts the model copied correctly from the screen text: 381/612.

## Verdict against the bar (evaluator arm within 0.05 of the mechanical reader and at least 0.10 above procedure only)

- dashboard: evaluator 0.75, mechanical 0.83 (gap +0.08), procedure only 0.63 (gain +0.12) -> **FAILS**
- triage: evaluator 0.67, mechanical 0.67 (gap +0.00), procedure only 0.43 (gain +0.23) -> **holds**
- service: evaluator 0.70, mechanical 0.70 (gap +0.00), procedure only 0.70 (gain +0.00) -> **FAILS**

Code at commit 898045a.
