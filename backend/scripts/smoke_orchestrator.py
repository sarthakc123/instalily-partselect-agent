"""End-to-end smoke test for the LangGraph orchestrator.

Drives the orchestrator with the three POC scenarios using whichever LLM
provider has a key. Prefers Anthropic (orchestrator default), falls back
to Groq (the key we currently have).

Scenarios:
  1. Single-turn part lookup: 'Tell me about part PS11752778'.
     Expect: lookup_part called with status=exact, assistant describes part.
  2. Multi-turn compatibility: turn 1 names a part, turn 2 asks about a model.
     Expect: lookup_part on turn 1, check_compatibility on turn 2 with verdict=yes.
  3. Case-study trick: 'Is PS11752778 compatible with WDT780SAEM1?'.
     Expect: check_compatibility verdict=no, reason=appliance_type_mismatch,
     and the assistant explains the appliance type mismatch in plain language.

Usage:
    cd backend && python -m scripts.smoke_orchestrator
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any

from app.agents.orchestrator import run_orchestrator
from app.agents.state import (
    StreamDone,
    StreamError,
    StreamSession,
    StreamTextDelta,
    StreamToolCall,
    StreamToolResult,
    StreamUsage,
)
from app.config import settings
from app.db.pool import close_pool


def _pick_provider() -> str | None:
    if settings.anthropic_api_key:
        return None  # default
    if settings.openai_api_key:
        return "openai"
    if settings.groq_api_key:
        return "groq"
    return None


def _ok(label: str, ok: bool, detail: str = "") -> None:
    status = "PASS" if ok else "FAIL"
    extra = f"  ({detail})" if detail else ""
    print(f"  [{status}] {label}{extra}")


async def _run(
    user: str,
    *,
    session: dict[str, Any] | None = None,
    history: list[dict[str, Any]] | None = None,
    provider_override: str | None = None,
) -> dict[str, Any]:
    """Drive one turn, collect events, return a structured summary."""
    text = ""
    tool_calls: list[StreamToolCall] = []
    tool_results: list[StreamToolResult] = []
    session_updates: list[StreamSession] = []
    usage: StreamUsage | None = None
    done: StreamDone | None = None
    error: StreamError | None = None
    history_after: list[dict[str, Any]] = list(history or [])
    history_after.append({"role": "user", "content": user})

    async for ev in run_orchestrator(
        user_message=user,
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
        elif isinstance(ev, StreamUsage):
            usage = ev
        elif isinstance(ev, StreamSession):
            session_updates.append(ev)
        elif isinstance(ev, StreamDone):
            done = ev
        elif isinstance(ev, StreamError):
            error = ev

    # Reconstruct what the assistant message looked like so callers can chain a follow-up turn.
    assistant_msg: dict[str, Any] = {"role": "assistant", "content": text}
    if tool_calls:
        assistant_msg["tool_calls"] = [
            {"id": tc.id, "name": tc.name, "arguments": tc.arguments} for tc in tool_calls
        ]
        for tc, tr in zip(tool_calls, tool_results):
            history_after.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "tool_name": tc.name,
                    "content": str(tr.payload),
                }
            )
    history_after.append({"role": "assistant", "content": text})

    final_session = session_updates[-1].session if session_updates else (session or {})

    return {
        "text": text,
        "tool_calls": tool_calls,
        "tool_results": tool_results,
        "usage": usage,
        "done": done,
        "error": error,
        "session": final_session,
        "history_after": history_after,
    }


async def main() -> int:
    failures = 0
    try:
        provider_override = _pick_provider()
        if not (settings.anthropic_api_key or settings.openai_api_key or settings.groq_api_key):
            print("No LLM API key set. Set ANTHROPIC_API_KEY, OPENAI_API_KEY, or GROQ_API_KEY.")
            return 1
        print(f"Orchestrator smoke test (provider override: {provider_override or 'default'})\n")

        # ----- Scenario 1: single-turn part lookup -----
        print("Scenario 1: 'Tell me about part PS11752778'")
        r1 = await _run(
            "Tell me about part PS11752778.",
            provider_override=provider_override,
        )
        if r1["error"]:
            print(f"  FAIL stream error: {r1['error'].message}")
            failures += 1
        else:
            tools_called = [tc.name for tc in r1["tool_calls"]]
            ok = "lookup_part" in tools_called
            _ok("called lookup_part", ok, detail=f"tools={tools_called}")
            if not ok:
                failures += 1
            results_by_name = {tr.name: tr.payload for tr in r1["tool_results"]}
            lp = results_by_name.get("lookup_part", {})
            ok = lp.get("status") == "exact" and lp.get("part", {}).get("id") == "PS11752778"
            _ok("lookup_part returned exact hit for PS11752778", ok,
                detail=f"status={lp.get('status')}")
            if not ok:
                failures += 1
            ok = "PS11752778" in r1["text"] or "ice maker" in r1["text"].lower()
            _ok("assistant text mentions the part or what it is", ok,
                detail=f"text[:120]={r1['text'][:120]!r}")
            if not ok:
                failures += 1
            ok = r1["session"].get("last_part") == "PS11752778"
            _ok("session updated with last_part = PS11752778", ok,
                detail=f"session={r1['session']}")
            if not ok:
                failures += 1
            print(f"  text: {r1['text'].strip()}\n")

        # ----- Scenario 2: multi-turn compatibility -----
        # Establish part in turn 1, then ask compat in turn 2 using session memory.
        print("Scenario 2: multi-turn -> 'is it compatible with my WDT780SAEM1?'")
        r2a = await _run(
            "Tell me about PS11743427.",
            provider_override=provider_override,
        )
        # Turn 2 uses the session + history from turn 1.
        r2b = await _run(
            "Is it compatible with my WDT780SAEM1 dishwasher?",
            session=r2a["session"],
            history=r2a["history_after"],
            provider_override=provider_override,
        )
        if r2b["error"]:
            print(f"  FAIL stream error: {r2b['error'].message}")
            failures += 1
        else:
            tools_called = [tc.name for tc in r2b["tool_calls"]]
            ok = "check_compatibility" in tools_called
            _ok("called check_compatibility on turn 2", ok, detail=f"tools={tools_called}")
            if not ok:
                failures += 1
            results_by_name = {tr.name: tr.payload for tr in r2b["tool_results"]}
            cc = results_by_name.get("check_compatibility", {})
            ok = cc.get("verdict") == "yes" and cc.get("part_id") == "PS11743427"
            _ok("compat verdict=yes, part_id=PS11743427 (session carried part across turns)",
                ok, detail=f"verdict={cc.get('verdict')}, part_id={cc.get('part_id')}")
            if not ok:
                failures += 1
            ok = any(
                w in r2b["text"].lower() for w in ["yes", "compatible", "fits", "confirmed"]
            )
            _ok("assistant says it fits", ok, detail=f"text[:120]={r2b['text'][:120]!r}")
            if not ok:
                failures += 1
            print(f"  text: {r2b['text'].strip()}\n")

        # ----- Scenario 3: case-study trick -----
        print("Scenario 3: cross-appliance trick -> 'Is PS11752778 compatible with WDT780SAEM1?'")
        r3 = await _run(
            "Is part PS11752778 compatible with my WDT780SAEM1?",
            provider_override=provider_override,
        )
        if r3["error"]:
            print(f"  FAIL stream error: {r3['error'].message}")
            failures += 1
        else:
            tools_called = [tc.name for tc in r3["tool_calls"]]
            ok = "check_compatibility" in tools_called
            _ok("called check_compatibility", ok, detail=f"tools={tools_called}")
            if not ok:
                failures += 1
            results_by_name = {tr.name: tr.payload for tr in r3["tool_results"]}
            cc = results_by_name.get("check_compatibility", {})
            ok = (
                cc.get("verdict") == "no"
                and cc.get("reason") == "appliance_type_mismatch"
            )
            _ok("compat verdict=no, reason=appliance_type_mismatch", ok,
                detail=f"verdict={cc.get('verdict')}, reason={cc.get('reason')}")
            if not ok:
                failures += 1
            lower = r3["text"].lower()
            ok = (
                "no" in lower or "not compatible" in lower
            ) and (
                "refrigerator" in lower or "fridge" in lower
            ) and (
                "dishwasher" in lower
            )
            _ok("assistant explains both appliance types in its reply",
                ok, detail=f"text[:200]={r3['text'][:200]!r}")
            if not ok:
                failures += 1
            print(f"  text: {r3['text'].strip()}\n")

        print(f"{'-' * 60}")
        print(f"{'All orchestrator tests passed.' if failures == 0 else f'{failures} test(s) FAILED.'}")
        return 0 if failures == 0 else 1
    finally:
        close_pool()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
