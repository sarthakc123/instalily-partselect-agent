"""OpenAI provider. Default for the Validator role (different LLM family
from the Claude orchestrator, per spec).

OpenAI's chat-completion streaming format matches Groq's (they intentionally
mimic OpenAI's API). The wire shapes diverge only in subtle places, so we
share the message + tool conversion helpers with the Groq provider.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from openai import AsyncOpenAI

from app.config import settings
from app.llm.base import LLMProvider, Message, ToolSpec
from app.llm.events import (
    Done,
    LLMEvent,
    StreamError,
    TextDelta,
    ToolCallComplete,
    ToolCallDelta,
    ToolCallStart,
    Usage,
)
from app.llm.groq_provider import _convert_messages, _convert_tools


_STOP_REASON_MAP = {
    "stop": "stop",
    "length": "max_tokens",
    "tool_calls": "tool_use",
    "end_turn": "end_turn",
}


class OpenAIProvider(LLMProvider):
    name = "openai"

    def __init__(self, model: str | None = None) -> None:
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY not set")
        self.model = model or settings.llm_validator_model
        self._client = AsyncOpenAI(api_key=settings.openai_api_key)

    async def complete(
        self,
        *,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.2,
    ) -> AsyncIterator[LLMEvent]:
        msgs = _convert_messages(messages)
        tool_defs = _convert_tools(tools)

        active_tools: dict[int, dict[str, Any]] = {}

        try:
            kwargs: dict[str, Any] = {
                "model": self.model,
                "messages": msgs,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "stream": True,
                "stream_options": {"include_usage": True},
            }
            if tool_defs:
                kwargs["tools"] = tool_defs

            stream = await self._client.chat.completions.create(**kwargs)

            finish_reason: str | None = None

            async for chunk in stream:
                if chunk.usage is not None:
                    yield Usage(
                        input_tokens=chunk.usage.prompt_tokens or 0,
                        output_tokens=chunk.usage.completion_tokens or 0,
                    )

                if not chunk.choices:
                    continue

                choice = chunk.choices[0]
                delta = choice.delta

                if delta and getattr(delta, "content", None):
                    yield TextDelta(content=delta.content)

                if delta and getattr(delta, "tool_calls", None):
                    for tc in delta.tool_calls:
                        idx = tc.index
                        if idx not in active_tools:
                            active_tools[idx] = {
                                "id": tc.id or "",
                                "name": (tc.function.name if tc.function else "") or "",
                                "args_acc": "",
                            }
                            if active_tools[idx]["name"]:
                                yield ToolCallStart(
                                    id=active_tools[idx]["id"],
                                    name=active_tools[idx]["name"],
                                )
                        state = active_tools[idx]
                        if tc.function and tc.function.name and not state["name"]:
                            state["name"] = tc.function.name
                            yield ToolCallStart(id=state["id"], name=state["name"])
                        if tc.id and not state["id"]:
                            state["id"] = tc.id
                        if tc.function and tc.function.arguments:
                            state["args_acc"] += tc.function.arguments
                            yield ToolCallDelta(
                                id=state["id"],
                                arguments_delta=tc.function.arguments,
                            )

                if choice.finish_reason:
                    finish_reason = choice.finish_reason

            for state in active_tools.values():
                try:
                    parsed = json.loads(state["args_acc"] or "{}")
                except json.JSONDecodeError:
                    parsed = {}
                yield ToolCallComplete(
                    id=state["id"],
                    name=state["name"],
                    arguments=parsed,
                )

            yield Done(stop_reason=_STOP_REASON_MAP.get(finish_reason or "stop", "other"))

        except Exception as exc:  # noqa: BLE001
            yield StreamError(message=f"{type(exc).__name__}: {exc}", fatal=True)
