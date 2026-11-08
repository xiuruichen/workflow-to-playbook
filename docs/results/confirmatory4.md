# Amendment 4: elicitation guard, seeds [6, 7, 8, 9, 10] (commit 62e1b3c)

Held-out agreement after one round, mean over seeds.

| domain | expert | before | after, no guard | after, guard |
|---|---|---|---|---|
| dashboard | (a) perfect expert | 0.850 | 0.967 | 0.967 |
| dashboard | (b) right 60%, otherwise tags wrong decisions | 0.850 | 0.892 | 0.892 |
| dashboard | (c) always tags wrong decisions | 0.850 | 0.850 | 0.850 |
| triage | (a) perfect expert | 0.717 | 0.742 | 0.742 |
| triage | (b) right 60%, otherwise tags wrong decisions | 0.717 | 0.717 | 0.717 |
| triage | (c) always tags wrong decisions | 0.717 | 0.717 | 0.717 |

**perfect expert: guard minus no guard +0.000 (bar: not below -0.01); wrong-tag cells: +0.000 (bar: at least +0.01) -> guard is NOT adopted.**
