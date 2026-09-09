# Swing currency-strength walk-forward

- Data: Yahoo daily midpoint proxy, 2016-09-08 through 2026-09-09, 15 pairs.
- Train through 2023-09-05; untouched validation from 2023-09-06.
- Tested 768 predeclared momentum/reversal variants at daily, weekly and monthly frequency.

Selected on training: `reversal|lb=20d|min=0|stop=1.5atr|rr=1.5|hold=20d|cards=1|monthly`

- Train: 83 trades, 32.49R, avg 0.391R, PF 2.06.
- Validation: 37 trades, 1.79R, avg 0.048R, PF 1.09, max DD 8.46R.
- Double-cost validation: 1.35R.
- Gate: **FAIL — do not deploy** — Failed: avg_r_at_least_0_08, profit_factor_at_least_1_20

## Best training choice by frequency

| Frequency | Configuration | Train R/PF | Validation R/PF | Validation fills |
|---|---|---:|---:|---:|
| daily | `reversal|lb=60d|min=0|stop=1.5atr|rr=1.5|hold=60d|cards=1|daily` | 38.31 / 1.19 | -12.43 / 0.89 | 175 |
| weekly | `reversal|lb=20d|min=1|stop=2.5atr|rr=1.5|hold=60d|cards=1|weekly` | 34.43 / 1.56 | 3.16 / 1.09 | 70 |
| monthly | `reversal|lb=20d|min=0|stop=1.5atr|rr=1.5|hold=20d|cards=1|monthly` | 32.49 / 2.06 | 1.79 / 1.09 | 37 |

This long-horizon test is closer to published currency-momentum portfolio horizons, but still uses spot proxies and explicit retail-style TP/SL exits. No production setting changed.
