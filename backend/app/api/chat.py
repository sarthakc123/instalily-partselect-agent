"""POST /chat returning text/event-stream.

Request body:
    {
      "message": "Tell me about PS11752778.",
      "conversation_id": "optional-uuid"
    }

Headers (optional, live demo flip):
    X-LLM-Provider: anthropic | openai | groq
    X-LLM-Model:    a model id; falls back to the provider's role-default

Response: SSE frames, one per OrchestratorEvent, JSON-encoded.

    data: {"type":"text_delta","content":"Hello"}\n\n
    data: {"type":"tool_call","id":"...","name":"lookup_part","arguments":{...}}\n\n
    data: {"type":"tool_result","id":"...","name":"lookup_part","payload":{...}}\n\n
    data: {"type":"session","session":{...}}\n\n
    data: {"type":"done","stop_reason":"end_turn"}\n\n

Persistence:
- User message saved at request start (so it survives crashes mid-stream).
- Tool results saved as they arrive.
- Assistant message saved at end of stream (or on error, with whatever text we collected).
- Session JSONB updated when StreamSession events fire.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any, AsyncIterator

from fastapi import APIRouter, Header, Request
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from app.agents.orchestrator import run_orchestrator
from app.agents.state import (
    StreamDone,
    StreamError,
    StreamEscalation,
    StreamSession,
    StreamTextDelta,
    StreamToolCall,
    StreamToolResult,
    StreamUsage,
    StreamValidator,
)
from app.conversation import store
from app.conversation.history import truncate_history


router = APIRouter(tags=["chat"])


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    conversation_id: str | None = None


def _event_dict(ev: Any) -> dict[str, Any]:
    """Convert an OrchestratorEvent dataclass into a plain JSON-serializable dict."""
    return asdict(ev)


@router.post("/chat")
async def chat(
    body: ChatRequest,
    request: Request,
    x_llm_provider: str | None = Header(default=None, alias="X-LLM-Provider"),
    x_llm_model: str | None = Header(default=None, alias="X-LLM-Model"),
) -> EventSourceResponse:
    # 1. Load or create the conversation row.
    provider_hint = x_llm_provider or "anthropic"
    conv = store.get_or_create_conversation(body.conversation_id, llm_provider=provider_hint)
    conversation_id = conv["id"]
    session = conv["session"]
    history = truncate_history(conv["messages"])

    # 2. Persist the user message immediately.
    store.save_user_message(conversation_id, body.message)

    async def event_source() -> AsyncIterator[dict[str, str]]:
        # Open the connection with the conversation id so the client can
        # reuse it on the next turn.
        yield {
            "event": "conversation",
            "data": json.dumps({"type": "conversation", "id": conversation_id}),
        }

        # Per-assistant-message buffer. We flush to Postgres when a tool_result
        # arrives (the boundary signaling the assistant message that issued
        # those tool calls is complete) and again at end of stream.
        #
        # This produces the correct persisted shape for OpenAI/Anthropic-style
        # tool-calling histories:
        #   user -> assistant (tool_calls) -> tool (result) -> assistant (text)
        # rather than collapsing the two assistant messages into one row, which
        # would make `tool_result.tool_call_id` an orphan on replay.
        assistant_text = ""
        assistant_tool_calls: list[dict[str, Any]] = []
        latest_session: dict[str, Any] = dict(session)

        def _flush_assistant() -> None:
            nonlocal assistant_text, assistant_tool_calls
            if assistant_text or assistant_tool_calls:
                store.save_assistant_message(
                    conversation_id,
                    assistant_text,
                    assistant_tool_calls if assistant_tool_calls else None,
                )
                assistant_text = ""
                assistant_tool_calls = []

        try:
            async for ev in run_orchestrator(
                user_message=body.message,
                session=session,
                provider_override=x_llm_provider,
                model_override=x_llm_model,
                history=history,
                conversation_id=conversation_id,
            ):
                # Detect client disconnect to abort cleanly.
                if await request.is_disconnected():
                    break

                if isinstance(ev, StreamTextDelta):
                    assistant_text += ev.content
                elif isinstance(ev, StreamToolCall):
                    assistant_tool_calls.append(
                        {"id": ev.id, "name": ev.name, "arguments": ev.arguments}
                    )
                elif isinstance(ev, StreamToolResult):
                    # First tool_result of a batch flushes the assistant message
                    # that issued the tool calls. Subsequent tool_results in the
                    # same batch see an empty buffer and skip the flush.
                    _flush_assistant()
                    store.save_tool_message(
                        conversation_id,
                        tool_call_id=ev.id,
                        tool_name=ev.name,
                        content=json.dumps(ev.payload),
                    )
                elif isinstance(ev, StreamSession):
                    latest_session = ev.session
                elif isinstance(ev, StreamUsage):
                    pass  # passed through to client; nothing to persist for v1
                elif isinstance(ev, StreamValidator):
                    pass  # passed through; UI renders ValidatorBadge
                elif isinstance(ev, StreamEscalation):
                    pass  # passed through; UI renders escalation affordance
                elif isinstance(ev, StreamDone):
                    pass  # final flush happens in finally
                elif isinstance(ev, StreamError):
                    pass  # passed through; client renders the error

                yield {"event": ev.type, "data": json.dumps(_event_dict(ev))}

        finally:
            # End of stream: persist the final assistant message (the one
            # produced after all tool dispatch rounds completed).
            _flush_assistant()
            if latest_session != session:
                store.update_session(conversation_id, latest_session)

    return EventSourceResponse(event_source(), media_type="text/event-stream")
