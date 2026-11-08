# Confirmatory runs H1-H4 (seeds [1, 2, 3, 4, 5]; commit 08625ca, `freeze-1`)

Mean (min-max) over 5 seeds. Held-out = chronological 30% (12 visits at n=40, 24 at n=80).

| domain | visits | induction | held-out agreement | without context | without non-actions | majority | recovery of planted rule |
|---|---|---|---|---|---|---|---|
| dashboard | 40 | greedy | 1.00 (1.00-1.00) | 0.78 (0.67-1.00) | 0.23 (0.17-0.33) | 0.40 (0.17-0.75) | 1.00 (1.00-1.00) |
| dashboard | 40 | lookahead | 1.00 (1.00-1.00) | 0.57 (0.17-1.00) | 0.23 (0.17-0.33) | 0.40 (0.17-0.75) | 1.00 (1.00-1.00) |
| dashboard | 80 | greedy | 1.00 (1.00-1.00) | 0.80 (0.58-0.92) | 0.44 (0.38-0.58) | 0.56 (0.42-0.62) | 1.00 (1.00-1.00) |
| dashboard | 80 | lookahead | 1.00 (1.00-1.00) | 0.77 (0.58-0.92) | 0.44 (0.38-0.58) | 0.56 (0.42-0.62) | 1.00 (1.00-1.00) |
| triage | 40 | greedy | 0.87 (0.67-1.00) | 0.87 (0.67-1.00) | 0.48 (0.33-0.58) | 0.40 (0.08-0.58) | 0.98 (0.95-1.00) |
| triage | 40 | lookahead | 0.87 (0.67-1.00) | 0.75 (0.50-0.92) | 0.48 (0.33-0.58) | 0.40 (0.08-0.58) | 0.99 (0.97-1.00) |
| triage | 80 | greedy | 0.89 (0.75-1.00) | 0.80 (0.58-0.96) | 0.48 (0.21-0.62) | 0.52 (0.38-0.79) | 0.95 (0.86-1.00) |
| triage | 80 | lookahead | 0.93 (0.79-1.00) | 0.86 (0.75-0.96) | 0.48 (0.21-0.62) | 0.52 (0.38-0.79) | 0.99 (0.96-1.00) |

## Verdicts against the protocol (criteria fixed in advance)

- dashboard, 40 visits, greedy: **H1 holds** (mean 1.00, min 1.00); H2 holds (context 1.00 vs without 0.78); H3 (descriptive): with non-actions 1.00, without 0.23.
- dashboard, 40 visits, lookahead: **H1 holds** (mean 1.00, min 1.00); H2 holds (context 1.00 vs without 0.57); H3 (descriptive): with non-actions 1.00, without 0.23.
- dashboard, 80 visits, greedy: **H1 holds** (mean 1.00, min 1.00); H2 holds (context 1.00 vs without 0.80); H3 (descriptive): with non-actions 1.00, without 0.44.
- dashboard, 80 visits, lookahead: **H1 holds** (mean 1.00, min 1.00); H2 holds (context 1.00 vs without 0.77); H3 (descriptive): with non-actions 1.00, without 0.44.
- triage, 40 visits, greedy: **H1 FAILS** (mean 0.87, min 0.67); H2 does not hold (context 0.87 vs without 0.87); H3 (descriptive): with non-actions 0.87, without 0.48.
- triage, 40 visits, lookahead: **H1 FAILS** (mean 0.87, min 0.67); H2 holds (context 0.87 vs without 0.75); H3 (descriptive): with non-actions 0.87, without 0.48.
- triage, 80 visits, greedy: **H1 FAILS** (mean 0.89, min 0.75); H2 holds (context 0.89 vs without 0.80); H3 (descriptive): with non-actions 0.89, without 0.48.
- triage, 80 visits, lookahead: **H1 FAILS** (mean 0.93, min 0.79); H2 holds (context 0.93 vs without 0.86); H3 (descriptive): with non-actions 0.93, without 0.48.

## H4: one elicitation round, simulated expert who always names the hidden fact (80 visits, hidden warmup, greedy)

| domain | seed | questions | answers | held-out before | after | unexplained before | after |
|---|---|---|---|---|---|---|---|
| dashboard | 1 | 14 | 0 | 0.75 | 0.75 | 14 | 14 |
| dashboard | 2 | 3 | 3 | 0.88 | 1.00 | 3 | 0 |
| dashboard | 3 | 1 | 1 | 0.83 | 0.83 | 1 | 1 |
| dashboard | 4 | 9 | 1 | 0.67 | 0.67 | 9 | 9 |
| dashboard | 5 | 6 | 6 | 0.92 | 1.00 | 6 | 0 |
| triage | 1 | 24 | 4 | 0.50 | 0.50 | 24 | 24 |
| triage | 2 | 24 | 4 | 0.67 | 0.67 | 24 | 24 |
| triage | 3 | 19 | 4 | 0.83 | 0.88 | 19 | 18 |
| triage | 4 | 17 | 1 | 0.58 | 0.58 | 17 | 17 |
| triage | 5 | 14 | 3 | 0.83 | 0.92 | 14 | 15 |

- dashboard: H4 **holds** (mean 0.81 -> 0.85).

- triage: H4 **holds** (mean 0.68 -> 0.71).
