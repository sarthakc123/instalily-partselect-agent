"""Public orchestrator entry point. Async generator yielding OrchestratorEvents.

The FastAPI SSE endpoint in Layer G iterates this generator and ships each
event as a `data: {...}\\n\\n` SSE frame.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from app.agents.graph import compiled_graph
from app.agents.state import (
    OrchestratorEvent,
    Session,
    StreamDone,
    StreamError,
)


async def run_orchestrator(
    *,
    user_message: str,
    session: Session | None = None,
    provider_override: str | None = None,
    model_override: str | None = None,
    history: list[dict[str, Any]] | None = None,
    conversation_id: str = "default",
) -> AsyncIterator[OrchestratorEvent]:
    """Drive the LangGraph orchestrator and yield outward events.

    `history` is the prior turn list (already in state-message dict shape).
    `session` is the small dict of remembered facts (last_part / model_no / ...).
    """
    queue: asyncio.Queue[OrchestratorEvent | None] = asyncio.Queue()

    initial_messages: list[dict[str, Any]] = list(history or []) + [
        {"role": "user", "content": user_message}
    ]
    initial_state: dict[str, Any] = {
        "messages": initial_messages,
        "session": session or {},
        "provider_override": provider_override,
        "model_override": model_override,
    }
    config: dict[str, Any] = {
        "configurable": {
            "event_queue": queue,
            "thread_id": conversation_id,
        }
    }

    stop_reason = "end_turn"

    async def runner() -> None:
        nonlocal stop_reason
        try:
            await compiled_graph.ainvoke(initial_state, config=config)  # type: ignore[arg-type]
        except Exception as exc:  # noqa: BLE001
            await queue.put(StreamError(message=f"{type(exc).__name__}: {exc}"))
            stop_reason = "error"
        finally:
            await queue.put(None)  # sentinel

    task = asyncio.create_task(runner())
    try:
        while True:
            ev = await queue.get()
            if ev is None:
                break
            yield ev
    finally:
        await task

    yield StreamDone(stop_reason=stop_reason)
