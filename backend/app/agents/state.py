"""LangGraph state + the outward event union the FastAPI SSE endpoint consumes."""

from __future__ import annotations

from dataclasses import dataclass, field
from operator import add
from typing import Annotated, Any, Literal, TypedDict


class Session(TypedDict, total=False):
    """Session memory carried across turns. Persisted in `conversations.state`."""

    conversation_id: str
    last_part: str | None
    model_number: str | None
    brand: str | None
    appliance_type: str | None


class OrchestratorState(TypedDict, total=False):
    """LangGraph state for the orchestrator graph.

    `messages` uses LangGraph's append-reducer (operator.add) so each node
    returns a delta and the framework concatenates them.
    `validator_retries` is the per-turn retry counter (capped at 1).
    """

    messages: Annotated[list[dict[str, Any]], add]
    session: Session
    provider_override: str | None
    model_override: str | None
    validator_retries: int


# ---------------------------------------------------------------------------
# Outward event stream (what the FastAPI SSE endpoint will emit to the
# frontend). Distinct from app.llm.events.LLMEvent: this is post-processed
# and includes tool result payloads so the UI can render rich cards inline.
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class StreamTextDelta:
    content: str
    type: Literal["text_delta"] = "text_delta"


@dataclass(slots=True)
class StreamToolCall:
    """Emitted when the model has fully formed a tool call (ready to dispatch)."""

    id: str
    name: str
    arguments: dict[str, Any]
    type: Literal["tool_call"] = "tool_call"


@dataclass(slots=True)
class StreamToolResult:
    """Emitted right after a tool finishes. Carries the structured payload so
    the frontend can render a ProductCard / CompatBadge / etc."""

    id: str
    name: str
    payload: dict[str, Any]
    type: Literal["tool_result"] = "tool_result"


@dataclass(slots=True)
class StreamUsage:
    input_tokens: int
    output_tokens: int
    type: Literal["usage"] = "usage"


@dataclass(slots=True)
class StreamSession:
    """Updated session state. Frontend may use this to mirror state locally."""

    session: dict[str, Any] = field(default_factory=dict)
    type: Literal["session"] = "session"


@dataclass(slots=True)
class StreamValidator:
    """Emitted after the selective validator runs. Frontend renders a
    ValidatorBadge under the assistant message."""

    verdict: Literal["pass", "retry", "escalate"]
    faithfulness_score: float = 0.0
    relevance_score: float = 0.0
    unsupported_claims: list[str] = field(default_factory=list)
    reason: str = ""
    type: Literal["validator"] = "validator"


@dataclass(slots=True)
class StreamEscalation:
    """Emitted when the orchestrator routes to a human ticket workflow.
    Phase 4 wires the full ticket-bypass form; Phase 1 surfaces an
    acknowledgement so the user knows their case is being escalated."""

    reason: str
    summary: str = ""
    safety_match: str | None = None
    type: Literal["escalation"] = "escalation"


@dataclass(slots=True)
class StreamDone:
    stop_reason: str = "end_turn"
    type: Literal["done"] = "done"


@dataclass(slots=True)
class StreamError:
    message: str
    type: Literal["error"] = "error"


OrchestratorEvent = (
    StreamTextDelta
    | StreamToolCall
    | StreamToolResult
    | StreamUsage
    | StreamSession
    | StreamValidator
    | StreamEscalation
    | StreamDone
    | StreamError
)
