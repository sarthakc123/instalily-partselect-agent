"""End-to-end smoke test for the FastAPI surface.

Boots uvicorn in-process on a random port, then:
  1. Hits /health and checks 'ok' + KG counts.
  2. Streams a /chat turn ('Tell me about PS11752778.') and asserts the
     expected event sequence (conversation, text deltas, tool_call,
     tool_result, session, done) plus that the tool result has the right
     part id.
  3. Streams a follow-up turn ('Is it compatible with my WDT780SAEM1?')
     using the same conversation_id and asserts the orchestrator picks
     up `last_part` from server-persisted session memory.
  4. GET /conversations/:id and confirms the persisted history matches.

Usage:
    cd backend && python -m scripts.smoke_api
"""

from __future__ import annotations

import asyncio
import json
import socket
import sys
import threading
import time
from contextlib import closing
from typing import Any

import httpx
import uvicorn

from app.config import settings
from app.main import create_app


def _ok(label: str, ok: bool, detail: str = "") -> None:
    status = "PASS" if ok else "FAIL"
    extra = f"  ({detail})" if detail else ""
    print(f"  [{status}] {label}{extra}")


def _free_port() -> int:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _pick_provider() -> str | None:
    if settings.anthropic_api_key:
        return None
    if settings.openai_api_key:
        return "openai"
    if settings.groq_api_key:
        return "groq"
    return None


async def _stream_chat(
    client: httpx.AsyncClient,
    *,
    url: str,
    message: str,
    conversation_id: str | None = None,
    provider: str | None = None,
) -> dict[str, Any]:
    """Open an SSE stream and collect all frames into a structured summary."""
    headers: dict[str, str] = {"Accept": "text/event-stream"}
    if provider:
        headers["X-LLM-Provider"] = provider
    body: dict[str, Any] = {"message": message}
    if conversation_id:
        body["conversation_id"] = conversation_id

    events: list[dict[str, Any]] = []
    async with client.stream("POST", url, json=body, headers=headers, timeout=60) as r:
        r.raise_for_status()
        async for line in r.aiter_lines():
            if not line:
                continue
            if line.startswith("data:"):
                payload = line[5:].strip()
                if not payload:
                    continue
                try:
                    events.append(json.loads(payload))
                except json.JSONDecodeError:
                    pass

    return {"events": events}


def _by_type(events: list[dict[str, Any]], etype: str) -> list[dict[str, Any]]:
    return [e for e in events if e.get("type") == etype]


def _run_uvicorn(port: int) -> threading.Thread:
    app = create_app()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)

    def _runner() -> None:
        asyncio.run(server.serve())

    t = threading.Thread(target=_runner, daemon=True)
    t.start()
    # Wait for the server to come up.
    deadline = time.time() + 15
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return t
        except OSError:
            time.sleep(0.1)
    raise RuntimeError("uvicorn never came up")


async def main() -> int:
    provider = _pick_provider()
    if not (settings.anthropic_api_key or settings.openai_api_key or settings.groq_api_key):
        print("No LLM API key set. Set ANTHROPIC_API_KEY, OPENAI_API_KEY, or GROQ_API_KEY.")
        return 1

    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"

    print(f"Booting uvicorn at {base_url} (provider override: {provider or 'default'})\n")
    _run_uvicorn(port)

    failures = 0
    async with httpx.AsyncClient() as client:
        # 1. /health
        r = await client.get(f"{base_url}/health", timeout=20)
        h = r.json()
        ok = r.status_code == 200 and h.get("status") == "ok" and h.get("parts_in_db", 0) >= 50
        _ok("/health returns ok + parts >= 50",
            ok, detail=f"status={h.get('status')} parts={h.get('parts_in_db')}")
        if not ok:
            failures += 1

        # 2. First /chat turn.
        print("\nScenario 1: 'Tell me about PS11752778.'")
        res1 = await _stream_chat(
            client,
            url=f"{base_url}/chat",
            message="Tell me about part PS11752778.",
            provider=provider,
        )
        evs = res1["events"]

        conv_events = _by_type(evs, "conversation")
        ok = len(conv_events) == 1 and isinstance(conv_events[0].get("id"), str)
        _ok("first frame is a 'conversation' event with an id", ok,
            detail=f"got={conv_events}")
        if not ok:
            failures += 1
        conversation_id = conv_events[0]["id"] if conv_events else None

        text_deltas = _by_type(evs, "text_delta")
        ok = len(text_deltas) > 0
        _ok("received text_delta events", ok, detail=f"n={len(text_deltas)}")
        if not ok:
            failures += 1

        tool_calls = _by_type(evs, "tool_call")
        ok = len(tool_calls) >= 1 and tool_calls[0].get("name") == "lookup_part"
        _ok("tool_call event for lookup_part", ok,
            detail=f"names={[t.get('name') for t in tool_calls]}")
        if not ok:
            failures += 1

        tool_results = _by_type(evs, "tool_result")
        lp_result = next((t for t in tool_results if t.get("name") == "lookup_part"), None)
        ok = (
            lp_result is not None
            and lp_result.get("payload", {}).get("status") == "exact"
            and lp_result.get("payload", {}).get("part", {}).get("id") == "PS11752778"
        )
        _ok("tool_result payload has status=exact and the right part id", ok,
            detail=f"payload_status={lp_result.get('payload', {}).get('status') if lp_result else None}")
        if not ok:
            failures += 1

        session_events = _by_type(evs, "session")
        ok = any(
            (e.get("session") or {}).get("last_part") == "PS11752778" for e in session_events
        )
        _ok("session event reports last_part=PS11752778", ok)
        if not ok:
            failures += 1

        done = _by_type(evs, "done")
        ok = len(done) == 1
        _ok("exactly one 'done' event terminates the stream", ok, detail=f"n={len(done)}")
        if not ok:
            failures += 1

        # 3. Follow-up turn using the same conversation_id; verify server-side context.
        if conversation_id:
            print(f"\nScenario 2 (same conv_id={conversation_id[:8]}...): 'Is it compatible with my WDT780SAEM1?'")
            res2 = await _stream_chat(
                client,
                url=f"{base_url}/chat",
                message="Is it compatible with my WDT780SAEM1?",
                conversation_id=conversation_id,
                provider=provider,
            )
            evs2 = res2["events"]

            tool_calls2 = _by_type(evs2, "tool_call")
            ok = any(t.get("name") == "check_compatibility" for t in tool_calls2)
            _ok("turn 2 called check_compatibility (server context retrieved last_part)",
                ok, detail=f"names={[t.get('name') for t in tool_calls2]}")
            if not ok:
                failures += 1

            cc_result = next(
                (t for t in _by_type(evs2, "tool_result") if t.get("name") == "check_compatibility"),
                None,
            )
            payload = (cc_result or {}).get("payload", {})
            # PS11752778 is the part, WDT780SAEM1 is the model. Expected: no/appliance_type_mismatch.
            ok = (
                payload.get("verdict") == "no"
                and payload.get("reason") == "appliance_type_mismatch"
                and payload.get("part_id") == "PS11752778"
                and payload.get("model_id") == "WDT780SAEM1"
            )
            _ok("compat verdict=no, reason=appliance_type_mismatch (part from server session)",
                ok, detail=f"verdict={payload.get('verdict')}, reason={payload.get('reason')}, "
                           f"part_id={payload.get('part_id')}, model_id={payload.get('model_id')}")
            if not ok:
                failures += 1

            # 4. GET /conversations/:id and confirm the persisted history.
            r = await client.get(f"{base_url}/conversations/{conversation_id}")
            conv = r.json()
            ok = (
                r.status_code == 200
                and conv.get("id") == conversation_id
                and len(conv.get("messages", [])) >= 4
                and (conv.get("session") or {}).get("last_part") in {"PS11752778"}
            )
            _ok("GET /conversations/:id returns persisted messages + session",
                ok, detail=f"n_messages={len(conv.get('messages', []))}, session={conv.get('session')}")
            if not ok:
                failures += 1

            # 5. Cleanup: DELETE the conversation so re-runs stay clean.
            r = await client.delete(f"{base_url}/conversations/{conversation_id}")
            ok = r.status_code == 204
            _ok("DELETE /conversations/:id returns 204", ok, detail=f"status={r.status_code}")
            if not ok:
                failures += 1

    print(f"\n{'-' * 60}")
    print(f"{'All API tests passed.' if failures == 0 else f'{failures} test(s) FAILED.'}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
