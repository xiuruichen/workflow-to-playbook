# Amendment 2: variant C vs default A, seeds [6, 7, 8, 9, 10] (commit 157cb89)

Held-out agreement, mean (min-max) over seeds.

| domain | visits | label noise | A greedy leaf2 | C lookahead leaf3 |
|---|---|---|---|---|
| dashboard | 40 | 0.0 | 0.88 (0.42-1.00) | 0.95 (0.83-1.00) |
| dashboard | 80 | 0.0 | 1.00 (1.00-1.00) | 1.00 (1.00-1.00) |
| dashboard | 60 | 0.1 | 0.88 (0.78-0.94) | 0.88 (0.78-0.94) |
| triage | 40 | 0.0 | 0.75 (0.50-1.00) | 0.75 (0.58-1.00) |
| triage | 80 | 0.0 | 0.88 (0.75-1.00) | 0.97 (0.88-1.00) |
| triage | 60 | 0.1 | 0.72 (0.56-0.83) | 0.74 (0.56-0.89) |

**C at least A in every cell: True; mean gain +0.030 -> C is NOT adopted as the default.**
