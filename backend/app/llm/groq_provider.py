"""Groq provider. Llama 3.1 8B / 3.3 70B with sub-second token latency.

Default role: utility (cheap, fast). Also a great "live-flip" demo: swap
the orchestrator from Claude to Groq mid-conversation and the latency
drop is immediately visible.

Groq's API is OpenAI-compatible at the streaming layer.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from groq import AsyncGroq

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


_STOP_REASON_MAP = {
    "stop": "stop",
    "length": "max_tokens",
    "tool_calls": "tool_use",
    "end_turn": "end_turn",
}


def _convert_messages(messages: list[Message]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for m in messages:
        if m.role == "tool":
            out.append(
                {
                    "role": "tool",
                    "tool_call_id": m.tool_call_id or "",
                    "content": m.content,
                }
            )
            continue
        if m.role == "assistant" and m.tool_calls:
            out.append(
                {
                    "role": "assistant",
                    "content": m.content or None,
                    "tool_calls": [
                        {
                            "id": tc["id"],
                            "type": "function",
                            "function": {
                                "name": tc["name"],
                                "arguments": json.dumps(tc.get("arguments", {})),
                            },
                        }
                        for tc in m.tool_calls
                    ],
                }
            )
            continue
        out.append({"role": m.role, "content": m.content})
    return out


def _convert_tools(tools: list[ToolSpec] | None) -> list[dict[str, Any]] | None:
    if not tools:
        return None
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.input_schema,
            },
        }
        for t in tools
    ]


class GroqProvider(LLMProvider):
    name = "groq"

    def __init__(self, model: str | None = None) -> None:
        if not settings.groq_api_key:
            raise RuntimeError("GROQ_API_KEY not set")
        self.model = model or settings.llm_utility_model
        self._client = AsyncGroq(api_key=settings.groq_api_key)

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

        # OpenAI-style tool calls arrive across multiple delta chunks. Key by index.
        active_tools: dict[int, dict[str, Any]] = {}

        try:
            kwargs: dict[str, Any] = {
                "model": self.model,
                "messages": msgs,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "stream": True,
            }
            if tool_defs:
                kwargs["tools"] = tool_defs

            stream = await self._client.chat.completions.create(**kwargs)

            finish_reason: str | None = None

            async for chunk in stream:
                # Usage chunks (final): no choices, only usage payload.
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
                            # Tool-call start: id + name arrive on the first delta
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
                        # name may continue arriving on later chunks for some providers
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

            # Flush completed tool calls.
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
