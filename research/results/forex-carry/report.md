# FX carry walk-forward

- Prices: Yahoo daily midpoint proxy, 2016-09-08 through 2026-09-09, 15 pairs.
- Rates: OECD immediate/interbank monthly series distributed by FRED, delayed 45 days at every decision.
- Train through 2023-09-05; untouched validation from 2023-09-06.
- Tested 384 carry, carry+momentum and carry-on-pullback variants.

Selected on training: `carry|lb=60d|carrygap=1|stop=1.5atr|rr=1|hold=20d|cards=1|monthly`

- Train: 60 trades, 10.78R, avg 0.180R, PF 1.46.
- Validation: 37 trades, 10.73R, avg 0.290R, PF 1.88, max DD 3.03R.
- Double-cost validation: 10.39R.
- Bootstrap 95% interval for mean validation R: [-0.0168, 0.5755].
- Gate: **PASS — candidate for independent demo forward test** — All conditions passed.

| Family | Training-selected config | Train R/PF | Validation R/PF |
|---|---|---:|---:|
| carry | `carry|lb=60d|carrygap=1|stop=1.5atr|rr=1|hold=20d|cards=1|monthly` | 10.78 / 1.46 | 10.73 / 1.88 |
| carry_with_momentum | `carry_with_momentum|lb=60d|carrygap=1|stop=1.5atr|rr=1|hold=60d|cards=1|monthly` | 13.30 / 1.63 | 10.57 / 1.80 |
| carry_on_pullback | `carry_on_pullback|lb=60d|carrygap=0|stop=1.5atr|rr=1.5|hold=60d|cards=3|monthly` | 24.51 / 1.27 | 9.24 / 1.33 |

| Frequency | Training-selected config | Validation trades | Validation R/PF |
|---|---|---:|---:|
| weekly | `carry_on_pullback|lb=60d|carrygap=1|stop=1.5atr|rr=1.5|hold=20d|cards=1|weekly` | 88 | -3.93 / 0.92 |
| monthly | `carry|lb=60d|carrygap=1|stop=1.5atr|rr=1|hold=20d|cards=1|monthly` | 37 | 10.73 / 1.88 |

| Card cap | Training-selected config | Validation trades | Validation R/PF | Double-cost R |
|---:|---|---:|---:|---:|
| 1 | `carry|lb=60d|carrygap=1|stop=1.5atr|rr=1|hold=20d|cards=1|monthly` | 37 | 10.73 / 1.88 | 10.39 |
| 3 | `carry|lb=60d|carrygap=0|stop=1.5atr|rr=1.5|hold=60d|cards=3|monthly` | 96 | 6.63 / 1.12 | 5.39 |

## Robustness diagnostics

- Effective parameter neighbors positive in validation: 16/16; median neighbor R 9.44.
- Leave-one-currency-out positive cases: 8/8.
- Same winning rule with a three-card cap: train 2.29R/PF 1.03; validation 8.46R/PF 1.21, max DD 11.28R over 92 fills.
- Calendar-year totals: 2017=-0.14R, 2018=3.84R, 2019=3.15R, 2020=-0.42R, 2022=1.40R, 2023=1.92R, 2024=1.92R, 2025=5.29R, 2026=3.57R.


Swap/carry cash income is intentionally not added because FBS CFD swap schedules differ from interbank rates. This tests whether the macro ranking improves entry direction itself. No production setting changed.
