#!/usr/bin/env python3
"""Render a stable Markdown trading review from structured JSON outcomes."""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any


def outcome_metrics(outcomes: list[dict[str, Any]]) -> dict[str, float | int | None]:
    closed = [item for item in outcomes if item.get("outcome") in {"win", "loss", "breakeven", "manual_close"}]
    pnl_values = [float(item.get("pnl_usd") or 0.0) for item in closed]
    wins = [value for item, value in zip(closed, pnl_values) if item.get("outcome") == "win"]
    losses = [value for item, value in zip(closed, pnl_values) if item.get("outcome") == "loss"]
    gross_profit = sum(value for value in wins if value > 0)
    gross_loss = -sum(value for value in losses if value < 0)
    average_win = gross_profit / len(wins) if wins else 0.0
    average_loss = gross_loss / len(losses) if losses else 0.0
    payoff = average_win / average_loss if average_loss else None
    return {
        "closed": len(closed), "wins": len(wins), "losses": len(losses),
        "win_rate": len(wins) / len(closed) if closed else 0.0,
        "gross_profit": gross_profit, "gross_loss": gross_loss, "net_pnl": sum(pnl_values),
        "average_win": average_win, "average_loss": average_loss,
        "profit_factor": gross_profit / gross_loss if gross_loss else None,
        "expectancy": sum(pnl_values) / len(closed) if closed else 0.0,
        "payoff_ratio": payoff, "breakeven_win_rate": 1 / (1 + payoff) if payoff else None,
    }


def render_review(outcomes: list[dict[str, Any]]) -> str:
    counts: dict[str, int] = {}
    pnl = 0.0
    for item in outcomes:
        outcome = str(item.get("outcome", "unknown"))
        counts[outcome] = counts.get(outcome, 0) + 1
        if item.get("pnl_usd") not in (None, ""):
            pnl += float(item["pnl_usd"])

    metrics = outcome_metrics(outcomes)
    lines = [
        f"# Trading Review - {date.today().isoformat()}",
        "",
        "## Outcome Summary",
        "",
        f"- Trades reviewed: {len(outcomes)}",
        f"- Net PnL USD: {pnl:.2f}",
        f"- Win rate: {float(metrics['win_rate']):.2%}",
        f"- Gross profit/loss: {float(metrics['gross_profit']):.2f} / -{float(metrics['gross_loss']):.2f} USD",
        f"- Average win/loss: {float(metrics['average_win']):.2f} / -{float(metrics['average_loss']):.2f} USD",
        f"- Profit factor: {float(metrics['profit_factor']):.3f}" if metrics["profit_factor"] is not None else "- Profit factor: N/A",
        f"- Expectancy: {float(metrics['expectancy']):.2f} USD/trade",
        f"- Break-even win rate: {float(metrics['breakeven_win_rate']):.2%}" if metrics["breakeven_win_rate"] is not None else "- Break-even win rate: N/A",
    ]
    for outcome, count in sorted(counts.items()):
        lines.append(f"- {outcome}: {count}")

    lines.extend([
        "",
        "## Trades Reviewed",
        "",
        "| Rank | Asset | Direction | Planned Entry | Actual Entry | Exit/Result | Outcome | PnL USD | Notes |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ])
    for item in outcomes:
        lines.append(
            "| {rank} | {asset} | {direction} | {planned} | {actual} | {exit_result} | {outcome} | {pnl} | {notes} |".format(
                rank=item.get("rank", ""),
                asset=item.get("asset", ""),
                direction=item.get("direction", ""),
                planned=item.get("planned_entry", ""),
                actual=item.get("actual_entry", ""),
                exit_result=item.get("exit_result", ""),
                outcome=item.get("outcome", ""),
                pnl=item.get("pnl_usd", ""),
                notes=str(item.get("notes", "")).replace("|", "/"),
            )
        )

    lines.extend([
        "",
        "## Signal Quality",
        "",
        "- Add hindsight-separated notes about whether the original setup was valid.",
        "",
        "## Execution Notes",
        "",
        "- Add timing, fill, slippage, and manual decision notes.",
        "",
        "## Suggested Adjustments",
        "",
        "- Channel filters: TBD",
        "- Symbol filters: TBD",
        "- Scoring weights: TBD",
        "- Execution timing: TBD",
        "- Risk settings: TBD",
        "",
        "## Next Session Defaults",
        "",
        "- Keep current defaults unless repeated evidence supports a change.",
    ])
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("outcomes_json", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    outcomes = json.loads(args.outcomes_json.read_text())
    if not isinstance(outcomes, list):
        raise SystemExit("outcomes_json must contain a list of outcome objects")
    review = render_review(outcomes)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(review)
    else:
        print(review)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
