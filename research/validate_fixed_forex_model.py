#!/usr/bin/env python3
"""Validate the frozen candidate on an independent Dukascopy period."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

import backtest_forex_strategies as research


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=Path("research/.cache/dukascopy-bars"))
    parser.add_argument("--output-dir", type=Path, default=Path("research/results/forex-independent-dukascopy"))
    args = parser.parse_args()

    files = sorted(args.data_dir.glob("*-m15-bid.json"))
    data = {path.name.split("-", 1)[0]: research.Indicators(research.load_dukascopy_bars(path)) for path in files}
    if len(data) < 4:
        raise RuntimeError(f"At least four independent symbols are required; found {sorted(data)}")
    dates = research.trading_dates(data)
    date_set = set(dates)
    config = research.StrategyConfig(
        "pullback_limit", "overlap", 1.4, 2.0, lookback=12,
        threshold=0.25, min_strength=0.75, management="fixed",
    )

    scenarios = []
    primary_trades = []
    for horizon in (4, 8, 12):
        for daily_cap in (1, 2, 3):
            for cost_scale in (1.0, 1.5, 2.0):
                trades = research.simulate(data, config, date_set, horizon, daily_cap, cost_scale)
                row = {
                    "horizon_hours": horizon, "daily_cap": daily_cap, "cost_scale": cost_scale,
                    **research.metrics(trades, len(dates)),
                }
                scenarios.append(row)
                if (horizon, daily_cap, cost_scale) == (4, 3, 1.0):
                    primary_trades = trades

    monthly: dict[str, list[dict]] = defaultdict(list)
    for trade in primary_trades:
        monthly[str(trade["signal_at"])[:7]].append(trade)
    monthly_metrics = [
        {"month": month, **research.metrics(trades, len({str(item["signal_at"])[:10] for item in trades}))}
        for month, trades in sorted(monthly.items())
    ]
    primary = next(row for row in scenarios if (row["horizon_hours"], row["daily_cap"], row["cost_scale"]) == (4, 3, 1.0))
    double_cost = next(row for row in scenarios if (row["horizon_hours"], row["daily_cap"], row["cost_scale"]) == (4, 3, 2.0))
    conditions = {
        "at_least_50_fills": primary["trades"] >= 50,
        "coverage_at_least_50pct": primary["coverage_percent"] >= 50,
        "avg_r_at_least_0_10": primary["avg_r"] >= 0.10,
        "profit_factor_at_least_1_20": primary["profit_factor"] >= 1.20,
        "positive_at_double_cost": double_cost["avg_r"] > 0,
        "majority_positive_months": sum(row["total_r"] > 0 for row in monthly_metrics) > len(monthly_metrics) / 2,
    }
    passed = all(conditions.values())
    payload = {
        "metadata": {
            "provider": "Dukascopy m15 bid candles", "symbols": sorted(data),
            "start": dates[0].isoformat(), "end": dates[-1].isoformat(),
            "trading_days": len(dates), "frozen_config": config.key,
            "parameters_changed_after_data_access": False,
        },
        "primary": primary,
        "double_cost": double_cost,
        "scenarios": scenarios,
        "monthly": monthly_metrics,
        "gate": {
            "status": "PASS — independent validation" if passed else "FAIL — reject production change",
            "conditions": conditions,
        },
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "results.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    lines = [
        "# Independent Dukascopy validation", "",
        f"- Frozen model: `{config.key}`.",
        f"- Period: {dates[0]} to {dates[-1]}; {len(dates)} trading days.",
        f"- Symbols: {', '.join(sorted(data))}.",
        f"- Gate: **{payload['gate']['status']}**.", "",
        "| Horizon | Daily cap | Cost | Signals/Fills | Coverage | Avg R | Total R | PF | Max DD |", 
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in scenarios:
        lines.append(
            f"| {row['horizon_hours']}h | {row['daily_cap']} | {row['cost_scale']}x | {row['signals']}/{row['trades']} | "
            f"{row['coverage_percent']}% | {row['avg_r']} | {row['total_r']} | {row['profit_factor']} | {row['max_drawdown_r']}R |"
        )
    lines.extend(["", "## Monthly primary scenario", "", "| Month | Fills | Avg R | Total R | PF |", "| --- | ---: | ---: | ---: | ---: |"])
    for row in monthly_metrics:
        lines.append(f"| {row['month']} | {row['trades']} | {row['avg_r']} | {row['total_r']} | {row['profit_factor']} |")
    (args.output_dir / "report.md").write_text("\n".join(lines) + "\n")
    print(json.dumps({"report": str(args.output_dir / "report.md"), "primary": primary, "double_cost": double_cost, "gate": payload["gate"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
