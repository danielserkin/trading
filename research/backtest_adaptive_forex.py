#!/usr/bin/env python3
"""Nested walk-forward test of adaptive FX strategy selection.

All base configurations are simulated once. At every rebalance date the selector
can see only the trailing outcomes that preceded that date. Selector
hyperparameters are chosen on an earlier meta-training segment, then frozen for
the final chronological validation segment.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from backtest_forex_strategies import (
    Indicators, StrategyConfig, configs, load_dukascopy_bars, metrics, simulate,
    trading_dates,
)


@dataclass(frozen=True)
class SelectorConfig:
    trailing_days: int
    rebalance_days: int
    min_fills: int
    require_both_halves_positive: bool

    @property
    def key(self) -> str:
        stability = "two_positive_halves" if self.require_both_halves_positive else "full_positive"
        return f"trail={self.trailing_days}|rebalance={self.rebalance_days}|minfills={self.min_fills}|{stability}"


def rows_in_dates(rows: list[dict[str, Any]], allowed: set[date]) -> list[dict[str, Any]]:
    return [row for row in rows if datetime.fromisoformat(row["signal_at"]).date() in allowed]


def selection_score(
    rows: list[dict[str, Any]], window_dates: list[date], selector: SelectorConfig,
) -> tuple[float, dict[str, Any]] | None:
    allowed = set(window_dates)
    chosen = rows_in_dates(rows, allowed)
    full = metrics(chosen, len(window_dates))
    if full["trades"] < selector.min_fills or full["avg_r"] <= 0.03 or full["profit_factor"] <= 1.05:
        return None
    midpoint = len(window_dates) // 2
    first = metrics(rows_in_dates(chosen, set(window_dates[:midpoint])), max(midpoint, 1))
    second = metrics(rows_in_dates(chosen, set(window_dates[midpoint:])), max(len(window_dates) - midpoint, 1))
    if selector.require_both_halves_positive and (first["avg_r"] <= 0 or second["avg_r"] <= 0):
        return None
    stability = min(first["avg_r"], second["avg_r"])
    score = (
        full["avg_r"] * 2.5 + stability * 4.0
        + min(full["profit_factor"], 3.0) * 0.03
        + full["coverage_percent"] * 0.001
        - full["max_drawdown_r"] * 0.012
    )
    return score, {"full": full, "first_half": first, "second_half": second}


def run_selector(
    trade_map: dict[str, list[dict[str, Any]]], config_map: dict[str, StrategyConfig],
    all_dates: list[date], evaluation_dates: list[date], selector: SelectorConfig,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    evaluation = set(evaluation_dates)
    output: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []
    for offset in range(0, len(evaluation_dates), selector.rebalance_days):
        block = evaluation_dates[offset:offset + selector.rebalance_days]
        block_start = block[0]
        history = [day for day in all_dates if day < block_start]
        window = history[-selector.trailing_days:]
        ranked = []
        if len(window) >= selector.trailing_days:
            for key, rows in trade_map.items():
                scored = selection_score(rows, window, selector)
                if scored:
                    score, detail = scored
                    ranked.append((score, detail["full"]["total_r"], key, detail))
        ranked.sort(reverse=True)
        if ranked:
            score, _, key, detail = ranked[0]
            block_rows = rows_in_dates(trade_map[key], set(block) & evaluation)
            output.extend(block_rows)
            decisions.append({
                "block_start": block_start.isoformat(), "block_end": block[-1].isoformat(),
                "selected": key, "family": config_map[key].family,
                "selection_score": round(score, 5), "trailing": detail["full"],
                "block": metrics(block_rows, len(block)),
            })
        else:
            decisions.append({
                "block_start": block_start.isoformat(), "block_end": block[-1].isoformat(),
                "selected": None, "family": None, "selection_score": None,
                "trailing": None, "block": metrics([], len(block)),
            })
    output.sort(key=lambda row: row["signal_at"])
    return output, decisions


def stressed(rows: list[dict[str, Any]], scale: float) -> list[dict[str, Any]]:
    output = []
    for row in rows:
        copied = dict(row)
        if copied.get("gross_r") is not None and copied.get("cost_r") is not None:
            copied["net_r"] = round(float(copied["gross_r"]) - scale * float(copied["cost_r"]), 5)
        output.append(copied)
    return output


def oracle_blocks(
    trade_map: dict[str, list[dict[str, Any]]], evaluation_dates: list[date],
    rebalance_days: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Impossible hindsight ceiling, kept separate from candidate selection."""
    output = []
    choices = []
    for offset in range(0, len(evaluation_dates), rebalance_days):
        block = evaluation_dates[offset:offset + rebalance_days]
        ranked = []
        for key, rows in trade_map.items():
            selected = rows_in_dates(rows, set(block))
            result = metrics(selected, len(block))
            if result["trades"] >= 2:
                ranked.append((result["total_r"], result["avg_r"], key, selected, result))
        ranked.sort(reverse=True)
        if ranked:
            _, _, key, selected, result = ranked[0]
            output.extend(selected)
            choices.append({"start": block[0].isoformat(), "end": block[-1].isoformat(), "config": key, "result": result})
    output.sort(key=lambda row: row["signal_at"])
    return output, choices


def render_report(payload: dict[str, Any]) -> str:
    meta = payload["metadata"]
    winner = payload["selected_meta_rule"]
    validation = payload["validation"]
    lines = [
        "# Adaptive FX nested walk-forward", "",
        f"- Data: Dukascopy M15 bid, {meta['start']} through {meta['end']} ({', '.join(meta['symbols'])}).",
        f"- Base search space: {meta['base_configurations']} configurations across {meta['families']} families.",
        f"- Meta-training evaluation: {meta['meta_evaluation_start']} through {meta['meta_train_end']}.",
        f"- Untouched final validation: {meta['validation_start']} through {meta['validation_end']}.",
        f"- Frozen adaptive rule: `{winner['selector']}`.", "",
        "## Result", "",
        f"- Meta-training: {winner['metrics']['signals']} signals / {winner['metrics']['trades']} fills, {winner['metrics']['total_r']:.2f}R, avg {winner['metrics']['avg_r']:.3f}R, PF {winner['metrics']['profit_factor']:.2f}.",
        f"- Final validation: {validation['metrics']['signals']} signals / {validation['metrics']['trades']} fills, {validation['metrics']['total_r']:.2f}R, avg {validation['metrics']['avg_r']:.3f}R, PF {validation['metrics']['profit_factor']:.2f}, max DD {validation['metrics']['max_drawdown_r']:.2f}R.",
        f"- Validation coverage: {validation['metrics']['coverage_percent']:.1f}% of trading days; double-cost total {validation['double_cost']['total_r']:.2f}R.",
        f"- Production gate: **{payload['production_gate']['status']}** — {payload['production_gate']['reason']}", "",
        "## Point-in-time decisions", "",
        "| Test block | Selected family/config | Prior fills / avg R | Block fills / R |",
        "|---|---|---:|---:|",
    ]
    for row in validation["decisions"]:
        if row["selected"]:
            lines.append(
                f"| {row['block_start']}–{row['block_end']} | {row['family']} / `{row['selected']}` | "
                f"{row['trailing']['trades']} / {row['trailing']['avg_r']:.3f} | {row['block']['trades']} / {row['block']['total_r']:.2f} |"
            )
        else:
            lines.append(f"| {row['block_start']}–{row['block_end']} | abstain | — | 0 / 0.00 |")
    oracle = payload["hindsight_ceiling"]
    lines.extend([
        "", "## Hindsight diagnostic (not tradable)", "",
        f"Choosing the best configuration only after seeing each validation block would produce {oracle['metrics']['total_r']:.2f}R over {oracle['metrics']['trades']} fills. This proves that profitable paths existed, not that they were identifiable beforehand.", "",
        "## Limits", "",
        "- Only four pairs were available in the independent Dukascopy download because the remaining requests were rate-limited.",
        "- Repeated testing across many configurations creates selection risk; the nested final segment reduces but does not remove it.",
        "- Spread and slippage are estimates; no macroeconomic-calendar or order-book inputs are modeled.",
        "- No production setting is changed by this research.", "",
    ])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=Path("research/.cache/dukascopy-bars"))
    parser.add_argument("--output-dir", type=Path, default=Path("research/results/forex-adaptive-nested"))
    parser.add_argument("--horizon-hours", type=int, default=8)
    parser.add_argument("--max-daily-trades", type=int, default=3)
    args = parser.parse_args()

    raw = {}
    for path in sorted(args.data_dir.glob("*-m15-bid.json")):
        symbol = path.name.split("-", 1)[0]
        bars = load_dukascopy_bars(path)
        if len(bars) >= 1200:
            raw[symbol] = bars
    if len(raw) < 4:
        raise SystemExit("Need at least four complete Dukascopy symbols")
    data = {symbol: Indicators(bars) for symbol, bars in raw.items()}
    dates = trading_dates(data)
    base_configs = configs()
    config_map = {config.key: config for config in base_configs}
    all_date_set = set(dates)
    trade_map = {
        config.key: simulate(data, config, all_date_set, args.horizon_hours, args.max_daily_trades)
        for config in base_configs
    }

    final_index = int(len(dates) * 0.70)
    meta_dates, validation_dates = dates[:final_index], dates[final_index:]
    common_warmup = 60
    meta_evaluation_dates = meta_dates[common_warmup:]
    selector_configs = [
        SelectorConfig(window, rebalance, minimum, strict)
        for window in (30, 45, 60)
        for rebalance in (5, 10)
        for minimum in (10, 15)
        for strict in (False, True)
    ]
    meta_results = []
    for selector in selector_configs:
        selected, decisions = run_selector(trade_map, config_map, dates, meta_evaluation_dates, selector)
        result = metrics(selected, len(meta_evaluation_dates))
        score = -999.0 if result["trades"] < 8 else (
            result["avg_r"] * 4 + min(result["profit_factor"], 3.0) * 0.05
            + result["coverage_percent"] * 0.001 - result["max_drawdown_r"] * 0.01
        )
        meta_results.append({"selector": selector, "rows": selected, "decisions": decisions, "metrics": result, "score": score})
    meta_results.sort(key=lambda item: (item["score"], item["metrics"]["total_r"]), reverse=True)
    winner = meta_results[0]

    validation_rows, validation_decisions = run_selector(
        trade_map, config_map, dates, validation_dates, winner["selector"],
    )
    validation_metrics = metrics(validation_rows, len(validation_dates))
    double_cost = metrics(stressed(validation_rows, 2.0), len(validation_dates))
    oracle_rows, oracle_choices = oracle_blocks(trade_map, validation_dates, winner["selector"].rebalance_days)
    oracle_metrics = metrics(oracle_rows, len(validation_dates))
    conditions = {
        "at_least_15_fills": validation_metrics["trades"] >= 15,
        "coverage_at_least_50pct": validation_metrics["coverage_percent"] >= 50,
        "avg_r_at_least_0_10": validation_metrics["avg_r"] >= 0.10,
        "profit_factor_at_least_1_20": validation_metrics["profit_factor"] >= 1.20,
        "positive_at_double_cost": double_cost["total_r"] > 0,
    }
    passed = all(conditions.values())
    failed = [name for name, okay in conditions.items() if not okay]
    family_counts = Counter(row["family"] for row in validation_decisions if row["family"])
    payload = {
        "metadata": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "start": dates[0].isoformat(), "end": dates[-1].isoformat(),
            "symbols": sorted(data), "base_configurations": len(base_configs),
            "families": len({config.family for config in base_configs}),
            "horizon_hours": args.horizon_hours, "max_daily_trades": args.max_daily_trades,
            "meta_evaluation_start": meta_evaluation_dates[0].isoformat(), "meta_train_end": meta_dates[-1].isoformat(),
            "validation_start": validation_dates[0].isoformat(), "validation_end": validation_dates[-1].isoformat(),
        },
        "meta_top_five": [
            {"selector": item["selector"].key, "score": round(item["score"], 5), "metrics": item["metrics"], "decisions": item["decisions"]}
            for item in meta_results[:5]
        ],
        "selected_meta_rule": {
            "selector": winner["selector"].key, "selector_parameters": asdict(winner["selector"]),
            "score": round(winner["score"], 5), "metrics": winner["metrics"], "decisions": winner["decisions"],
        },
        "validation": {
            "metrics": validation_metrics, "double_cost": double_cost,
            "family_selection_counts": dict(family_counts), "decisions": validation_decisions,
            "trades": validation_rows,
        },
        "hindsight_ceiling": {"metrics": oracle_metrics, "choices": oracle_choices},
        "production_gate": {
            "status": "PASS — candidate for demo forward test" if passed else "FAIL — do not deploy",
            "conditions": conditions,
            "reason": "All robustness conditions passed." if passed else "Failed: " + ", ".join(failed),
        },
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "results.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    (args.output_dir / "report.md").write_text(render_report(payload))
    print(json.dumps({
        "report": str(args.output_dir / "report.md"), "selector": winner["selector"].key,
        "meta": winner["metrics"], "validation": validation_metrics,
        "double_cost": double_cost, "family_counts": dict(family_counts),
        "oracle": oracle_metrics, "gate": payload["production_gate"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
