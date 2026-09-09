# Intraday carry-conditioned walk-forward

- Hourly Yahoo prices from 2024-09-09 through 2026-09-09; lagged OECD/FRED rates for eight currencies.
- Train through 2026-02-02; untouched validation from 2026-02-03.
- Tested 864 carry-only, carry+momentum and carry-on-pullback combinations with 1/3 card caps.

Selected on training: `carry_on_pullback|lb=120h|carrygap=1|stop=1.2atr|rr=1|hold=48h|cards=1|utc=7|disjoint`

- Train: 352 trades, 20.47R, avg 0.058R, PF 1.13, coverage 96.2%.
- Validation: 156 trades, 3.61R, avg 0.023R, PF 1.05, DD 18.18R, coverage 99.4%.
- Double-cost validation: -11.98R.
- Gate: **FAIL — do not deploy** — Failed: avg_r_at_least_0_08, profit_factor_at_least_1_20, max_drawdown_below_12r, positive_at_double_cost

| Card cap | Training-selected config | Validation trades | Validation R/PF/DD |
|---:|---|---:|---:|
| 1 | `carry_on_pullback|lb=120h|carrygap=1|stop=1.2atr|rr=1|hold=48h|cards=1|utc=7|disjoint` | 156 | 3.61 / 1.05 / 18.18 |
| 3 | `carry_with_momentum|lb=72h|carrygap=1|stop=1.2atr|rr=1|hold=12h|cards=3|utc=7|disjoint` | 265 | -2.34 / 0.98 / 17.17 |

The test does not add theoretical carry income; it asks whether the rate differential improves intraday direction and TP attainment. No production setting changed.
