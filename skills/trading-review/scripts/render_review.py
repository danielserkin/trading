#!/usr/bin/env python3
"""Render a stable Markdown trading review from structured JSON outcomes."""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any


def render_review(outcomes: list[dict[str, Any]]) -> str:
    counts: dict[str, int] = {}
    pnl = 0.0
    for item in outcomes:
        outcome = str(item.get("outcome", "unknown"))
        counts[outcome] = counts.get(outcome, 0) + 1
        if item.get("pnl_usd") not in (None, ""):
            pnl += float(item["pnl_usd"])

    lines = [
        f"# Trading Review - {date.today().isoformat()}",
        "",
        "## Outcome Summary",
        "",
        f"- Trades reviewed: {len(outcomes)}",
        f"- Net PnL USD: {pnl:.2f}",
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
