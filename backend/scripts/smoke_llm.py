"""Smoke test for the LLM provider gateway.

Exercises each available provider:
  1. Plain text completion.
  2. Tool-calling: model is asked to call a trivial echo tool.

Skips cleanly if a provider's API key isn't set.

Usage:
    cd backend && python -m scripts.smoke_llm
"""

from __future__ import annotations

import asyncio
import sys
import time
from typing import Any

from app.config import settings
from app.llm.base import LLMProvider, Message, ToolSpec
from app.llm.events import (
    Done,
    StreamError,
    TextDelta,
    ToolCallComplete,
    Usage,
)


# Trivial test tool: prove tool-calling works end-to-end without touching real tools.
ECHO_TOOL = ToolSpec(
    name="echo",
    description="Echo the given message back. Use this when explicitly asked to echo.",
    input_schema={
        "type": "object",
        "properties": {
            "message": {"type": "string", "description": "Text to echo back"},
        },
        "required": ["message"],
    },
)


async def _consume_stream(
    provider: LLMProvider,
    *,
    messages: list[Message],
    tools: list[ToolSpec] | None = None,
    max_tokens: int = 256,
) -> dict[str, Any]:
    """Drain a provider stream into a structured summary."""
    text_chunks: list[str] = []
    tool_calls: list[ToolCallComplete] = []
    usage: Usage | None = None
    done: Done | None = None
    error: StreamError | None = None
    started = time.perf_counter()
    first_token_at: float | None = None

    async for ev in provider.complete(
        messages=messages, tools=tools, max_tokens=max_tokens, temperature=0.0
    ):
        if isinstance(ev, TextDelta):
            if first_token_at is None:
                first_token_at = time.perf_counter()
            text_chunks.append(ev.content)
        elif isinstance(ev, ToolCallComplete):
            if first_token_at is None:
                first_token_at = time.perf_counter()
            tool_calls.append(ev)
        elif isinstance(ev, Usage):
            usage = ev
        elif isinstance(ev, Done):
            done = ev
        elif isinstance(ev, StreamError):
            error = ev
            break

    elapsed = time.perf_counter() - started
    ttft = (first_token_at - started) if first_token_at else None
    return {
        "text": "".join(text_chunks),
        "tool_calls": tool_calls,
        "usage": usage,
        "done": done,
        "error": error,
        "elapsed_s": round(elapsed, 3),
        "ttft_s": round(ttft, 3) if ttft is not None else None,
    }


async def _test_provider(name: str, provider: LLMProvider) -> tuple[int, int]:
    """Returns (passes, fails) for this provider."""
    passes = fails = 0
    print(f"\n[{name}] model = {provider.model}")

    # 1. Plain text.
    print("  1. plain text")
    res = await _consume_stream(
        provider,
        messages=[
            Message(role="system", content="You are a terse assistant."),
            Message(role="user", content="Reply with exactly: 'gateway ok'."),
        ],
        max_tokens=20,
    )
    if res["error"]:
        print(f"     FAIL stream error: {res['error'].message}")
        fails += 1
    elif "gateway ok" not in res["text"].lower():
        print(f"     FAIL got: {res['text']!r}")
        fails += 1
    else:
        print(
            f"     PASS text={res['text']!r}  "
            f"ttft={res['ttft_s']}s  total={res['elapsed_s']}s  "
            f"usage={res['usage']}"
        )
        passes += 1

    # 2. Tool calling.
    print("  2. tool call (echo)")
    res = await _consume_stream(
        provider,
        messages=[
            Message(
                role="system",
                content="When asked to echo something, call the echo tool with that exact text.",
            ),
            Message(role="user", content="Please echo: hello world"),
        ],
        tools=[ECHO_TOOL],
        max_tokens=256,
    )
    if res["error"]:
        print(f"     FAIL stream error: {res['error'].message}")
        fails += 1
    elif not res["tool_calls"]:
        print(f"     FAIL no tool calls. text={res['text']!r}")
        fails += 1
    else:
        tc = res["tool_calls"][0]
        msg = tc.arguments.get("message", "")
        if tc.name != "echo" or "hello world" not in str(msg).lower():
            print(f"     FAIL tool={tc.name} args={tc.arguments}")
            fails += 1
        else:
            print(
                f"     PASS tool={tc.name} args={tc.arguments}  "
                f"ttft={res['ttft_s']}s  total={res['elapsed_s']}s  "
                f"usage={res['usage']}  done={res['done']}"
            )
            passes += 1

    return passes, fails


async def main() -> int:
    print("LLM gateway smoke test")
    total_pass = total_fail = total_skip = 0

    # Anthropic
    if settings.anthropic_api_key:
        from app.llm.anthropic_provider import AnthropicProvider
        p, f = await _test_provider("anthropic", AnthropicProvider())
        total_pass += p
        total_fail += f
    else:
        print("\n[anthropic] SKIP (ANTHROPIC_API_KEY not set)")
        total_skip += 1

    # OpenAI
    if settings.openai_api_key:
        from app.llm.openai_provider import OpenAIProvider
        p, f = await _test_provider("openai", OpenAIProvider())
        total_pass += p
        total_fail += f
    else:
        print("\n[openai] SKIP (OPENAI_API_KEY not set)")
        total_skip += 1

    # Groq
    if settings.groq_api_key:
        from app.llm.groq_provider import GroqProvider
        p, f = await _test_provider("groq", GroqProvider())
        total_pass += p
        total_fail += f
    else:
        print("\n[groq] SKIP (GROQ_API_KEY not set)")
        total_skip += 1

    print(f"\n{'-' * 60}")
    print(f"PASS {total_pass}   FAIL {total_fail}   SKIP {total_skip}")
    return 0 if total_fail == 0 and total_pass > 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
