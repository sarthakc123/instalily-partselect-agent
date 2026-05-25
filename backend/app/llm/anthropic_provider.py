"""Anthropic Claude provider. Default for the orchestrator role.

Translates the Anthropic streaming event sequence into the normalized
LLMEvent union. Anthropic emits:
  - message_start
  - content_block_start {type: text|tool_use}
  - content_block_delta {delta: text_delta|input_json_delta}
  - content_block_stop
  - message_delta {delta.stop_reason, usage}
  - message_stop
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from anthropic import AsyncAnthropic

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
    "end_turn": "end_turn",
    "tool_use": "tool_use",
    "max_tokens": "max_tokens",
    "stop_sequence": "stop",
}


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, model: str | None = None) -> None:
        if not settings.anthropic_api_key:
            raise RuntimeError("ANTHROPIC_API_KEY not set")
        self.model = model or settings.llm_orchestrator_model
        self._client = AsyncAnthropic(api_key=settings.anthropic_api_key)

    @staticmethod
    def _convert_tools(tools: list[ToolSpec] | None) -> list[dict[str, Any]] | None:
        if not tools:
            return None
        return [
            {"name": t.name, "description": t.description, "input_schema": t.input_schema}
            for t in tools
        ]

    @staticmethod
    def _split_system(messages: list[Message]) -> tuple[str, list[dict[str, Any]]]:
        """Anthropic takes `system` as a top-level param, not a message."""
        system_text = ""
        out: list[dict[str, Any]] = []
        for m in messages:
            if m.role == "system":
                system_text = (system_text + "\n\n" + m.content).strip() if system_text else m.content
                continue
            if m.role == "tool":
                # Tool results are user-role messages with content blocks of type "tool_result".
                out.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": m.tool_call_id or "",
                                "content": m.content,
                            }
                        ],
                    }
                )
                continue
            if m.role == "assistant" and m.tool_calls:
                blocks: list[dict[str, Any]] = []
                if m.content:
                    blocks.append({"type": "text", "text": m.content})
                for tc in m.tool_calls:
                    blocks.append(
                        {
                            "type": "tool_use",
                            "id": tc["id"],
                            "name": tc["name"],
                            "input": tc.get("arguments", {}),
                        }
                    )
                out.append({"role": "assistant", "content": blocks})
                continue
            out.append({"role": m.role, "content": m.content})
        return system_text, out

    async def complete(
        self,
        *,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.2,
    ) -> AsyncIterator[LLMEvent]:
        system_text, msgs = self._split_system(messages)
        tool_defs = self._convert_tools(tools)

        # In-flight tool-call assembly state (index -> partial state).
        active_tools: dict[int, dict[str, Any]] = {}

        try:
            kwargs: dict[str, Any] = {
                "model": self.model,
                "messages": msgs,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
            if system_text:
                kwargs["system"] = system_text
            if tool_defs:
                kwargs["tools"] = tool_defs

            async with self._client.messages.stream(**kwargs) as stream:
                async for event in stream:
                    etype = getattr(event, "type", None)

                    if etype == "content_block_start":
                        block = event.content_block
                        if block.type == "tool_use":
                            idx = event.index
                            active_tools[idx] = {
                                "id": block.id,
                                "name": block.name,
                                "json_acc": "",
                            }
                            yield ToolCallStart(id=block.id, name=block.name)

                    elif etype == "content_block_delta":
                        delta = event.delta
                        dtype = getattr(delta, "type", None)
                        if dtype == "text_delta":
                            yield TextDelta(content=delta.text)
                        elif dtype == "input_json_delta":
                            idx = event.index
                            state = active_tools.get(idx)
                            if state:
                                state["json_acc"] += delta.partial_json
                                yield ToolCallDelta(
                                    id=state["id"],
                                    arguments_delta=delta.partial_json,
                                )

                    elif etype == "content_block_stop":
                        idx = event.index
                        state = active_tools.pop(idx, None)
                        if state is not None:
                            try:
                                parsed = json.loads(state["json_acc"] or "{}")
                            except json.JSONDecodeError:
                                parsed = {}
                            yield ToolCallComplete(
                                id=state["id"],
                                name=state["name"],
                                arguments=parsed,
                            )

                    elif etype == "message_delta":
                        usage = getattr(event, "usage", None)
                        if usage is not None and hasattr(usage, "output_tokens"):
                            yield Usage(
                                input_tokens=getattr(usage, "input_tokens", 0) or 0,
                                output_tokens=usage.output_tokens or 0,
                            )

                final_message = await stream.get_final_message()
                stop_reason = _STOP_REASON_MAP.get(final_message.stop_reason or "end_turn", "other")
                yield Done(stop_reason=stop_reason)

        except Exception as exc:  # noqa: BLE001
            yield StreamError(message=f"{type(exc).__name__}: {exc}", fatal=True)
