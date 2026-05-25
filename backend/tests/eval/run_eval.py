"""POC evaluation runner. Reads tests/eval/test_set.yaml, runs every case
through the orchestrator, asserts the expectations block, writes a
markdown table to docs/eval_results.md.

Usage:
    cd backend && python -m tests.eval.run_eval
    cd backend && python -m tests.eval.run_eval --filter compat
    cd backend && python -m tests.eval.run_eval --provider groq
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path
from typing import Any

import yaml

from app.agents.orchestrator import run_orchestrator
from app.agents.state import (
    StreamDone,
    StreamError,
    StreamSession,
    StreamTextDelta,
    StreamToolCall,
    StreamToolResult,
)
from app.config import settings
from app.db.pool import close_pool


REPO_ROOT = Path(__file__).resolve().parents[3]
TEST_SET_PATH = Path(__file__).parent / "test_set.yaml"
RESULTS_PATH = REPO_ROOT / "docs" / "eval_results.md"
EM_DASH = "—"


# ---------------------------------------------------------------------------
# Attr wrapper so YAML checks can use dot syntax: p.part.id == 'PS11752778'
# ---------------------------------------------------------------------------


class Attr(dict):
    def __getattr__(self, key: str) -> Any:
        v = self.get(key)
        if isinstance(v, dict):
            return Attr(v)
        return v


def _wrap(payload: dict[str, Any]) -> Attr:
    return Attr(payload)


def _eval_check(expr: str, payload: dict[str, Any]) -> tuple[bool, str | None]:
    """Evaluate a single check expression. Returns (passed, error_message)."""
    p = _wrap(payload)
    try:
        result = bool(eval(expr, {"__builtins__": {"any": any, "all": all, "len": len}}, {"p": p}))
        return result, None
    except Exception as exc:  # noqa: BLE001
        return False, f"check raised {type(exc).__name__}: {exc}"


# ---------------------------------------------------------------------------
# Drive one turn
# ---------------------------------------------------------------------------


async def drive_turn(
    *,
    user_message: str,
    session: dict[str, Any] | None,
    history: list[dict[str, Any]] | None,
    provider_override: str | None,
) -> dict[str, Any]:
    """Run a single turn through the orchestrator and collect events."""
    text = ""
    tool_calls: list[StreamToolCall] = []
    tool_results: list[StreamToolResult] = []
    session_updates: list[StreamSession] = []
    error: StreamError | None = None
    done: StreamDone | None = None

    history_after = list(history or [])
    history_after.append({"role": "user", "content": user_message})

    async for ev in run_orchestrator(
        user_message=user_message,
        session=session,
        provider_override=provider_override,
        history=history,
    ):
        if isinstance(ev, StreamTextDelta):
            text += ev.content
        elif isinstance(ev, StreamToolCall):
            tool_calls.append(ev)
        elif isinstance(ev, StreamToolResult):
            tool_results.append(ev)
        elif isinstance(ev, StreamSession):
            session_updates.append(ev)
        elif isinstance(ev, StreamDone):
            done = ev
        elif isinstance(ev, StreamError):
            error = ev

    # Reconstruct history for the next turn (matches what /chat persists).
    # CRITICAL: assistant-with-tool-calls must be a SEPARATE row before the
    # tool result rows, otherwise Anthropic rejects with
    # "unexpected tool_use_id found in tool_result blocks". Same shape the
    # chat API persists.
    import json
    if tool_calls:
        history_after.append(
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                    for tc in tool_calls
                ],
            }
        )
        for tc, tr in zip(tool_calls, tool_results):
            history_after.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "tool_name": tc.name,
                    "content": json.dumps(tr.payload),
                }
            )
    history_after.append({"role": "assistant", "content": text})

    return {
        "text": text,
        "tool_calls": tool_calls,
        "tool_results": tool_results,
        "session": session_updates[-1].session if session_updates else (session or {}),
        "history_after": history_after,
        "done": done,
        "error": error,
    }


# ---------------------------------------------------------------------------
# Evaluate one case
# ---------------------------------------------------------------------------


async def evaluate_case(case: dict[str, Any], provider_override: str | None) -> dict[str, Any]:
    turns: list[str] = case["turns"]
    session: dict[str, Any] | None = None
    history: list[dict[str, Any]] | None = None
    last_turn: dict[str, Any] | None = None

    started = time.perf_counter()
    for i, user_msg in enumerate(turns):
        last_turn = await drive_turn(
            user_message=user_msg,
            session=session,
            history=history,
            provider_override=provider_override,
        )
        session = last_turn["session"]
        history = last_turn["history_after"]
    elapsed = time.perf_counter() - started

    assert last_turn is not None
    expectations: dict[str, Any] = case.get("expectations", {})
    text = last_turn["text"]
    tool_names_called = [tc.name for tc in last_turn["tool_calls"]]
    tool_results_by_name = {tr.name: tr.payload for tr in last_turn["tool_results"]}

    failures: list[str] = []

    # tools_called: every name listed must appear in the final-turn tool calls.
    for required in expectations.get("tools_called", []) or []:
        if required not in tool_names_called:
            failures.append(
                f"tool '{required}' was not called (got: {tool_names_called or 'none'})"
            )

    # no_tool_called
    if expectations.get("no_tool_called") and tool_names_called:
        failures.append(
            f"expected NO tool calls but got: {tool_names_called}"
        )

    # tool_results checks
    for tr_spec in expectations.get("tool_results", []) or []:
        tool_name = tr_spec["tool"]
        payload = tool_results_by_name.get(tool_name)
        if payload is None:
            failures.append(f"no tool result for '{tool_name}'")
            continue
        for check in tr_spec.get("checks", []) or []:
            ok, err = _eval_check(check, payload)
            if not ok:
                detail = f": {err}" if err else ""
                failures.append(f"[{tool_name}] check failed: {check}{detail}")

    # text_contains (ALL must appear)
    for needle in expectations.get("text_contains", []) or []:
        if needle.lower() not in text.lower():
            failures.append(
                f"text missing required phrase: {needle!r} (text='{text[:140]}...')"
            )

    # text_contains_any (at least one must appear)
    contains_any = expectations.get("text_contains_any") or []
    if contains_any and not any(n.lower() in text.lower() for n in contains_any):
        failures.append(
            f"text did not contain any of: {contains_any} (text='{text[:140]}...')"
        )

    # text_not_contains (none may appear)
    for forbidden in expectations.get("text_not_contains", []) or []:
        if forbidden.lower() in text.lower():
            failures.append(
                f"text contained forbidden phrase: {forbidden!r}"
            )

    # no_em_dashes
    if expectations.get("no_em_dashes") and EM_DASH in text:
        failures.append("hard rule violated: assistant text contains an em-dash")

    # stream error?
    if last_turn["error"]:
        failures.append(f"stream error: {last_turn['error'].message}")

    return {
        "id": case["id"],
        "category": case["category"],
        "description": case.get("description", ""),
        "passed": len(failures) == 0,
        "failures": failures,
        "tools_called": tool_names_called,
        "elapsed_s": round(elapsed, 2),
        "final_text": text,
    }


# ---------------------------------------------------------------------------
# Top-level
# ---------------------------------------------------------------------------


def _pick_provider() -> str | None:
    if settings.anthropic_api_key:
        return None
    if settings.openai_api_key:
        return "openai"
    if settings.groq_api_key:
        return "groq"
    return None


def _write_report(
    results: list[dict[str, Any]], provider_label: str, total_elapsed: float
) -> None:
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    passed = sum(1 for r in results if r["passed"])
    total = len(results)

    lines: list[str] = []
    lines.append("# POC Evaluation Results\n")
    lines.append(
        f"_Generated by `python -m tests.eval.run_eval`. "
        f"Provider: **{provider_label}**. Pass rate: **{passed}/{total}**. "
        f"Total wall clock: {total_elapsed:.1f}s._\n"
    )
    lines.append("## Summary\n")
    lines.append("| # | Case | Category | Result | Time | Tools called |")
    lines.append("|---|---|---|---|---|---|")
    for i, r in enumerate(results, 1):
        status = "PASS" if r["passed"] else "FAIL"
        tools = ", ".join(r["tools_called"]) if r["tools_called"] else "_(none)_"
        lines.append(
            f"| {i} | `{r['id']}` | {r['category']} | **{status}** | {r['elapsed_s']}s | {tools} |"
        )

    lines.append("\n## Failures\n")
    fails = [r for r in results if not r["passed"]]
    if not fails:
        lines.append("_None._\n")
    else:
        for r in fails:
            lines.append(f"### `{r['id']}` ({r['category']})\n")
            lines.append(f"{r['description']}\n")
            for f in r["failures"]:
                lines.append(f"- {f}")
            lines.append("")
            lines.append("Assistant text:\n")
            lines.append(f"> {r['final_text'][:400]!r}\n")

    lines.append("\n## All assistant replies\n")
    for r in results:
        status = "✓" if r["passed"] else "✗"
        lines.append(f"### {status} `{r['id']}` ({r['elapsed_s']}s)\n")
        lines.append(f"_{r['description']}_\n")
        lines.append(f"Tools: {', '.join(r['tools_called']) if r['tools_called'] else 'none'}\n")
        lines.append("```")
        lines.append(r["final_text"].strip() or "(no text)")
        lines.append("```\n")

    RESULTS_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nReport written: {RESULTS_PATH}")


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--filter", help="substring filter on case id")
    parser.add_argument("--provider", help="override provider", default=None)
    args = parser.parse_args()

    try:
        with TEST_SET_PATH.open("r", encoding="utf-8") as f:
            test_set = yaml.safe_load(f)

        cases = test_set.get("cases", [])
        if args.filter:
            cases = [c for c in cases if args.filter in c["id"]]

        if not cases:
            print("No cases matched.")
            return 1

        provider_override = args.provider or _pick_provider()
        provider_label = provider_override or "default (per role)"
        print(f"Running {len(cases)} case(s) with provider: {provider_label}\n")

        results: list[dict[str, Any]] = []
        started = time.perf_counter()
        for i, case in enumerate(cases, 1):
            print(f"  [{i}/{len(cases)}] {case['id']} ({case['category']}) ... ", end="", flush=True)
            try:
                r = await evaluate_case(case, provider_override)
            except Exception as exc:  # noqa: BLE001
                r = {
                    "id": case["id"],
                    "category": case["category"],
                    "description": case.get("description", ""),
                    "passed": False,
                    "failures": [f"runner exception: {type(exc).__name__}: {exc}"],
                    "tools_called": [],
                    "elapsed_s": 0.0,
                    "final_text": "",
                }
            results.append(r)
            print(f"{'PASS' if r['passed'] else 'FAIL'} ({r['elapsed_s']}s)")
            if not r["passed"]:
                for f in r["failures"]:
                    print(f"      - {f}")
        total_elapsed = time.perf_counter() - started

        passed = sum(1 for r in results if r["passed"])
        total = len(results)
        print(f"\n{'-' * 60}")
        print(f"PASS {passed}/{total}    FAIL {total - passed}/{total}    wall: {total_elapsed:.1f}s")

        _write_report(results, provider_label, total_elapsed)
        return 0 if passed == total else 1
    finally:
        close_pool()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
