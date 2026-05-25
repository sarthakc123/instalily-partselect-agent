"""LangGraph orchestrator. Single agent + tool-dispatch node + conditional edge.

Phase 1 topology:

    START -> agent -> [tools | END]
                        |
                        v
                       tools -> agent

Phase 3 will add a `validator` node and a second conditional edge:
agent -> validator -> [agent (retry) | END]. Both extensions are local
edits to this file; the streaming pattern (queue in config) survives.

Streaming: each node receives the LangGraph `config` and pulls an
`asyncio.Queue` from `config["configurable"]["event_queue"]`. Nodes put
`OrchestratorEvent` instances onto the queue as text streams in and as
tools complete. The outer `orchestrator.run_orchestrator` async generator
drains the queue and yields events to the FastAPI SSE endpoint.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph

from app.agents.prompts.loader import render
from app.agents.state import (
    OrchestratorEvent,
    OrchestratorState,
    Session,
    StreamEscalation,
    StreamSession,
    StreamTextDelta,
    StreamToolCall,
    StreamToolResult,
    StreamUsage,
    StreamValidator,
)
from app.agents.validator import (
    CONFIDENCE_THRESHOLD,
    should_validate,
    validate as run_validator,
)
from app.kg.networkx_kg import NetworkXKG
from app.llm.base import Message
from app.llm.events import (
    Done,
    StreamError as LLMStreamError,
    TextDelta,
    ToolCallComplete,
    Usage,
)
from app.llm.registry import get_provider
from app.tools.base import ToolContext
from app.tools.registry import all_tool_specs, dispatch


# Singleton KG. In production this rebuilds on schedule from Postgres.
_kg: NetworkXKG | None = None


def get_kg() -> NetworkXKG:
    global _kg
    if _kg is None:
        # Always rebuild from Postgres on first call so the data is fresh
        # relative to the live schema. The JSON snapshot is for fast process
        # restart in deployed environments; tests build directly.
        from app.kg.builder import build_kg_from_postgres
        _kg = build_kg_from_postgres()
    return _kg


def reset_kg() -> None:
    """Test/utility hook to force a rebuild on the next get_kg() call."""
    global _kg
    _kg = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_system_prompt(session: Session | None) -> str:
    s = session or {}
    return render(
        "orchestrator",
        last_part=s.get("last_part"),
        model_number=s.get("model_number"),
        brand=s.get("brand"),
        appliance_type=s.get("appliance_type"),
    )


def _to_provider_messages(
    state_messages: list[dict[str, Any]], session: Session | None
) -> list[Message]:
    """Convert state's dict-shaped messages back into the provider Message type,
    prepending the rendered system prompt."""
    out: list[Message] = [Message(role="system", content=_build_system_prompt(session))]
    for m in state_messages:
        role = m["role"]
        if role == "tool":
            out.append(
                Message(
                    role="tool",
                    content=m.get("content", ""),
                    tool_call_id=m.get("tool_call_id"),
                    tool_name=m.get("tool_name"),
                )
            )
        elif role == "assistant" and m.get("tool_calls"):
            out.append(
                Message(
                    role="assistant",
                    content=m.get("content", "") or "",
                    tool_calls=m["tool_calls"],
                )
            )
        else:
            out.append(Message(role=role, content=m.get("content", "")))
    return out


def _session_updates_from_tool_result(
    tool_name: str, payload: dict[str, Any]
) -> dict[str, Any]:
    """Pull stable session-relevant facts out of a tool result.

    For example: when lookup_part succeeds on an exact match, remember the
    part for the next turn. When check_compatibility runs, remember the
    model + brand + appliance type. This is how 'is THIS part compatible
    with my model' on a later turn finds the part.
    """
    updates: dict[str, Any] = {}
    if tool_name == "lookup_part":
        if payload.get("status") == "exact" and payload.get("part"):
            part = payload["part"]
            updates["last_part"] = part["id"]
            updates.setdefault("brand", part.get("manufacturer"))
            updates.setdefault("appliance_type", part.get("appliance_type"))
    elif tool_name == "check_compatibility":
        if payload.get("model_id"):
            updates["model_number"] = payload["model_id"]
        if payload.get("part_id"):
            updates["last_part"] = payload["part_id"]
    return updates


async def _emit(config: RunnableConfig | None, event: OrchestratorEvent) -> None:
    if not config:
        return
    queue = (config.get("configurable") or {}).get("event_queue")
    if queue is not None:
        await queue.put(event)


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------


async def agent_node(state: OrchestratorState, config: RunnableConfig) -> dict[str, Any]:
    """Call the LLM with the conversation so far and the tool catalog. Stream
    text out via the queue, accumulate assistant message + any tool calls."""

    provider = get_provider(
        "orchestrator",
        override_provider=state.get("provider_override"),  # type: ignore[arg-type]
        override_model=state.get("model_override"),
    )
    msgs = _to_provider_messages(state.get("messages", []), state.get("session"))

    text_acc = ""
    tool_calls: list[dict[str, Any]] = []

    async for ev in provider.complete(messages=msgs, tools=all_tool_specs(), max_tokens=1024):
        if isinstance(ev, TextDelta):
            text_acc += ev.content
            await _emit(config, StreamTextDelta(content=ev.content))
        elif isinstance(ev, ToolCallComplete):
            tool_calls.append({"id": ev.id, "name": ev.name, "arguments": ev.arguments})
            await _emit(config, StreamToolCall(id=ev.id, name=ev.name, arguments=ev.arguments))
        elif isinstance(ev, Usage):
            await _emit(config, StreamUsage(input_tokens=ev.input_tokens, output_tokens=ev.output_tokens))
        elif isinstance(ev, Done):
            # Done is emitted at the outer wrapper, not per-node.
            pass
        elif isinstance(ev, LLMStreamError):
            from app.agents.state import StreamError
            await _emit(config, StreamError(message=ev.message))
            # Stop here; the final assistant message will be whatever we have.
            break

    assistant: dict[str, Any] = {
        "role": "assistant",
        "content": text_acc,
    }
    if tool_calls:
        assistant["tool_calls"] = tool_calls
    return {"messages": [assistant]}


async def tools_node(state: OrchestratorState, config: RunnableConfig) -> dict[str, Any]:
    """Execute every tool call from the last assistant message in parallel.
    Emit StreamToolResult for each so the UI can render rich cards."""

    last = state["messages"][-1]
    tool_calls = last.get("tool_calls", []) or []
    if not tool_calls:
        return {}

    ctx = ToolContext(kg=get_kg())

    async def _run_one(tc: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        try:
            result = await dispatch(tc["name"], ctx, tc.get("arguments", {}))
            payload = result.model_dump()
        except Exception as exc:  # noqa: BLE001
            payload = {"tool": tc["name"], "error": f"{type(exc).__name__}: {exc}"}
        await _emit(
            config,
            StreamToolResult(id=tc["id"], name=tc["name"], payload=payload),
        )
        tool_message = {
            "role": "tool",
            "tool_call_id": tc["id"],
            "tool_name": tc["name"],
            "content": json.dumps(payload),
        }
        session_updates = _session_updates_from_tool_result(tc["name"], payload)
        return tool_message, session_updates

    results = await asyncio.gather(*(_run_one(tc) for tc in tool_calls))

    tool_messages = [r[0] for r in results]
    session_updates: dict[str, Any] = {}
    for _, su in results:
        session_updates.update(su)

    out: dict[str, Any] = {"messages": tool_messages}
    if session_updates:
        merged_session: Session = {**(state.get("session") or {}), **session_updates}  # type: ignore[misc]
        out["session"] = merged_session
        await _emit(config, StreamSession(session=dict(merged_session)))

    return out


def _gather_recent_tool_batch(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Walk back from the final assistant-text message and collect the
    contiguous tool messages immediately preceding it. That batch is what
    the validator should grade the final assistant draft against."""
    if not messages:
        return []
    # Find the last assistant message with no tool_calls (the "final draft").
    end = None
    for i in range(len(messages) - 1, -1, -1):
        m = messages[i]
        if m.get("role") == "assistant" and not m.get("tool_calls"):
            end = i
            break
    if end is None:
        return []
    batch: list[dict[str, Any]] = []
    i = end - 1
    while i >= 0 and messages[i].get("role") == "tool":
        batch.append(messages[i])
        i -= 1
    batch.reverse()
    return batch


def _find_last_user_message(messages: list[dict[str, Any]]) -> str:
    for m in reversed(messages):
        if m.get("role") == "user":
            return m.get("content", "") or ""
    return ""


def _should_continue(state: OrchestratorState) -> str:
    last = state["messages"][-1]
    if last.get("role") == "assistant" and last.get("tool_calls"):
        return "tools"
    # Final assistant message produced. Decide whether the validator should
    # grade it. Skip if we've already validated once this turn.
    if state.get("validator_retries", 0) >= 1:
        return END
    batch = _gather_recent_tool_batch(state["messages"])
    if not batch:
        return END
    triggered, _ = should_validate(batch)
    if triggered:
        return "validator"
    return END


async def validator_node(state: OrchestratorState, config: RunnableConfig) -> dict[str, Any]:
    """Selective grader. Runs on a different LLM family from the orchestrator
    when the tool batch contains an inferred-compat or troubleshoot result.
    Emits StreamValidator (always) and StreamEscalation (on escalate verdict).

    Phase 1 simplification: surfaces verdict as a badge. The retry verdict
    appears as a 'lower confidence' badge but does NOT loop back to the
    agent for a re-prompt. Phase 2 adds the full retry loop with a synthetic
    user message carrying the validator's reason as a re-prompt hint.
    """
    messages = state.get("messages", [])
    batch = _gather_recent_tool_batch(messages)
    triggered_flag, triggered = should_validate(batch)
    if not triggered_flag:
        return {}  # nothing to do

    # Final assistant draft text + originating user message.
    assistant_draft = ""
    for i in range(len(messages) - 1, -1, -1):
        m = messages[i]
        if m.get("role") == "assistant" and not m.get("tool_calls"):
            assistant_draft = m.get("content", "") or ""
            break
    user_msg = _find_last_user_message(messages)

    provider_override = state.get("provider_override")
    result = await run_validator(
        user_message=user_msg,
        assistant_draft=assistant_draft,
        triggered=triggered,
        override_provider=provider_override,  # type: ignore[arg-type]
    )

    await _emit(
        config,
        StreamValidator(
            verdict=result.verdict,
            faithfulness_score=result.faithfulness_score,
            relevance_score=result.relevance_score,
            unsupported_claims=list(result.unsupported_claims),
            reason=result.reason,
        ),
    )

    if result.verdict == "escalate":
        await _emit(
            config,
            StreamEscalation(
                reason=result.reason,
                summary=assistant_draft[:280],
                safety_match=(triggered[0]["payload"].get("safety_match") if triggered else None),
            ),
        )

    # Mark that the validator has run this turn (caps retry to 0 here; Phase 2
    # raises this).
    return {"validator_retries": state.get("validator_retries", 0) + 1}


# ---------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------


def build_graph():
    builder = StateGraph(OrchestratorState)
    builder.add_node("agent", agent_node)
    builder.add_node("tools", tools_node)
    builder.add_node("validator", validator_node)
    builder.add_edge(START, "agent")
    builder.add_conditional_edges(
        "agent",
        _should_continue,
        {"tools": "tools", "validator": "validator", END: END},
    )
    builder.add_edge("tools", "agent")
    builder.add_edge("validator", END)
    return builder.compile()


compiled_graph = build_graph()
