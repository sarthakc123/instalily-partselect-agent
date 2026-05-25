"""LLMProvider protocol and common message / tool types.

Tools (5 typed retrieval tools) describe themselves using ToolSpec; each
provider implementation translates ToolSpec into its native tool-definition
shape (Anthropic input_schema vs OpenAI/Groq function parameters).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from app.llm.events import LLMEvent


@dataclass(slots=True)
class Message:
    role: Literal["system", "user", "assistant", "tool"]
    content: str = ""
    # For tool results posted back to the model:
    tool_call_id: str | None = None
    tool_name: str | None = None
    # For assistant messages that issued tool calls:
    tool_calls: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class ToolSpec:
    """Provider-agnostic tool definition.

    `input_schema` follows JSON Schema (draft-07-compatible subset). Each
    concrete provider class is responsible for wrapping this in the
    provider's expected shape.
    """

    name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=lambda: {"type": "object", "properties": {}})


class LLMProvider(Protocol):
    """Provider-agnostic streaming completion interface.

    Implementations:
      - app.llm.anthropic_provider.AnthropicProvider
      - app.llm.openai_provider.OpenAIProvider
      - app.llm.groq_provider.GroqProvider
    """

    name: str          # e.g. "anthropic", "openai", "groq"
    model: str         # specific model id picked from settings

    async def complete(
        self,
        *,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.2,
    ) -> AsyncIterator[LLMEvent]:
        """Yield normalized events as the model streams.

        Contract:
        - exactly one Done event at the end (unless StreamError fatal).
        - Usage event optional but should be emitted when the provider reports it.
        - text deltas may interleave with tool-call deltas. Each tool call gets
          one ToolCallStart, zero or more ToolCallDeltas, and one
          ToolCallComplete with the fully-parsed arguments.
        """
        ...
