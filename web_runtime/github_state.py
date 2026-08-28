#!/usr/bin/env python3
"""Read and atomically update dashboard state stored on a GitHub branch."""

from __future__ import annotations

import argparse
import base64
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

STATE_PATH = "runtime/state.json"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_state() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "updated_at": now(),
        "session": {"status": "idle", "cards": [], "backups": []},
        "monitors": {},
        "events": [],
    }


class GitHubState:
    def __init__(self, repository: str, token: str, branch: str = "runtime-data") -> None:
        self.repository = repository
        self.token = token
        self.branch = branch
        self.url = f"https://api.github.com/repos/{repository}/contents/{STATE_PATH}"

    def request(self, method: str, url: str, body: dict[str, Any] | None = None) -> Any:
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(
            url,
            method=method,
            data=data,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "trading-dashboard-runtime/1.0",
            },
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read()
            return json.loads(raw) if raw else {}

    def read(self) -> tuple[dict[str, Any], str | None]:
        url = f"{self.url}?{urllib.parse.urlencode({'ref': self.branch})}"
        try:
            result = self.request("GET", url)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return default_state(), None
            raise
        content = base64.b64decode(result["content"]).decode()
        return json.loads(content), result.get("sha")

    def update(self, message: str, mutate: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
        for attempt in range(4):
            state, sha = self.read()
            mutate(state)
            state["updated_at"] = now()
            body: dict[str, Any] = {
                "message": message,
                "branch": self.branch,
                "content": base64.b64encode((json.dumps(state, ensure_ascii=False, indent=2) + "\n").encode()).decode(),
            }
            if sha:
                body["sha"] = sha
            try:
                self.request("PUT", self.url, body)
                return state
            except urllib.error.HTTPError as exc:
                if exc.code not in {409, 422} or attempt == 3:
                    raise
                time.sleep(0.4 * (attempt + 1))
        raise RuntimeError("state update failed")


def add_event(state: dict[str, Any], level: str, message: str) -> None:
    events = state.setdefault("events", [])
    events.append({"at": now(), "level": level, "message": message})
    state["events"] = events[-150:]


def client() -> GitHubState:
    repository = os.getenv("GITHUB_REPOSITORY", "").strip()
    token = (os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN") or "").strip()
    if not repository or not token:
        raise RuntimeError("GITHUB_REPOSITORY and GH_TOKEN/GITHUB_TOKEN are required")
    return GitHubState(repository, token, os.getenv("RUNTIME_BRANCH", "runtime-data"))


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    fetch = sub.add_parser("fetch")
    fetch.add_argument("--output", required=True, type=Path)
    running = sub.add_parser("session-running")
    running.add_argument("--run-id", required=True)
    running.add_argument("--workflow-url", default="")
    complete = sub.add_parser("session-complete")
    complete.add_argument("--result", required=True, type=Path)
    complete.add_argument("--review", type=Path)
    failed = sub.add_parser("session-failed")
    failed.add_argument("--message", required=True)
    session_event = sub.add_parser("session-event")
    session_event.add_argument("--level", default="info", choices=("info", "success", "warning", "error"))
    session_event.add_argument("--message", required=True)
    monitor = sub.add_parser("monitor-results")
    monitor.add_argument("--results", required=True, type=Path)
    args = parser.parse_args()

    store = client()
    if args.command == "fetch":
        state, _ = store.read()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n")
        return 0

    if args.command == "session-running":
        def mutation(state: dict[str, Any]) -> None:
            state["session"] = {
                **state.get("session", {}),
                "status": "running",
                "run_id": args.run_id,
                "started_at": now(),
                "workflow_url": args.workflow_url,
            }
            add_event(state, "info", "🚀 Codex y el analizador iniciaron una nueva sesión")
        store.update("runtime: session running", mutation)
        return 0

    if args.command == "session-complete":
        result = json.loads(args.result.read_text())
        review: Any = None
        if args.review and args.review.exists():
            try:
                review = json.loads(args.review.read_text())
            except json.JSONDecodeError:
                review = {"status": "unstructured", "message": args.review.read_text()[:2000]}

        def mutation(state: dict[str, Any]) -> None:
            state["session"] = {**result, "status": "completed", "review": review, "completed_at": now()}
            if isinstance(review, dict):
                review_status = str(review.get("status") or "received")
                review_level = "success" if review_status == "approved" else "warning"
                add_event(state, review_level, f"🤖 Revisión Codex: {review_status}")
            else:
                add_event(state, "warning", "🤖 Revisión Codex no disponible; se publicó el resultado determinista")
            add_event(state, "success", "✅ Sesión completada y cards publicadas")
            telegram_status = str((result.get("telegram") or {}).get("status") or "unknown")
            add_event(state, "success" if telegram_status == "sent" else "warning", f"📲 Telegram: {telegram_status}")
        store.update("runtime: session completed", mutation)
        return 0

    if args.command == "session-failed":
        def mutation(state: dict[str, Any]) -> None:
            state["session"] = {**state.get("session", {}), "status": "failed", "failed_at": now(), "error": args.message}
            add_event(state, "error", f"❌ Sesión fallida: {args.message}")
        store.update("runtime: session failed", mutation)
        return 0

    if args.command == "session-event":
        store.update("runtime: session event", lambda state: add_event(state, args.level, args.message))
        return 0

    results = json.loads(args.results.read_text())

    def merge_monitor_results(state: dict[str, Any]) -> None:
        monitors = state.setdefault("monitors", {})
        for result in results.get("results", []):
            trade_id = str(result.get("trade_id") or "")
            current = monitors.get(trade_id)
            if not current or not current.get("enabled"):
                continue
            if result.get("activation_id") != current.get("activation_id"):
                continue
            history = current.setdefault("history", [])
            history.append(result["decision"])
            current["history"] = history[-100:]
            current["last_decision"] = result["decision"]
            current["last_check_at"] = result["decision"].get("evaluated_at")
            action = str(result["decision"].get("action") or "ACTUALIZADO").replace("_", " ")
            price = result["decision"].get("current_price")
            price_text = f" · proxy {price}" if price is not None else ""
            add_event(state, "warning" if action == "EVIDENCIA INSUFICIENTE" else "info", f"📈 {current.get('asset', trade_id)}: {action}{price_text}")
            if result.get("terminal"):
                current["enabled"] = False
                current["status"] = "closed_or_expired"
        for event in results.get("events", []):
            add_event(state, event.get("level", "info"), event.get("message", "Monitor actualizado"))
    store.update("runtime: monitor results", merge_monitor_results)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
