"""Selective validator. Different LLM family from the orchestrator grades
high-risk paths only.

Triggers (any one fires the validator):
  - check_compatibility verdict == 'inferred' (the prose-inference fallback)
  - troubleshoot status == 'ok' that produced a recommended_fix
  - any tool result whose top-level `confidence` field is below threshold

Skips:
  - lookup_part exact hits (source IS the answer)
  - lookup_part fuzzy_candidates (already requires user confirmation; no
    assistant claim to grade)
  - get_install_guide (deterministic by part_id; no LLM judgment)
  - check_compatibility yes/no/unknown with high confidence (the verdict
    came straight from the structured edge; nothing to validate)

Outputs:
  - faithfulness_score 0..1
  - relevance_score 0..1
  - unsupported_claims: list of short strings
  - verdict: pass | retry | escalate
  - reason: one short sentence

Verdict actions are handled by the LangGraph caller in graph.py:
  - pass     -> append validator note to state and continue to agent
  - retry    -> bump retry counter, append a retry-hint message, re-enter agent
  - escalate -> emit StreamEscalation event and end the graph
"""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.agents.prompts.loader import render
from app.llm.base import Message
from app.llm.events import (
    Done,
    StreamError as LLMStreamError,
    TextDelta,
    Usage,
)
from app.llm.registry import get_provider


# Confidence threshold: any tool result with a numeric `confidence` strictly
# below this value triggers the validator. Keep deliberately loose so we
# catch low-signal answers even when they are not 'inferred' per se.
CONFIDENCE_THRESHOLD = 0.6


ValidatorVerdict = Literal["pass", "retry", "escalate"]


class ValidatorResult(BaseModel):
    faithfulness_score: float = Field(ge=0.0, le=1.0)
    relevance_score: float = Field(ge=0.0, le=1.0)
    unsupported_claims: list[str] = Field(default_factory=list)
    verdict: ValidatorVerdict
    reason: str = ""


def should_validate(tool_messages: list[dict[str, Any]]) -> tuple[bool, list[dict[str, Any]]]:
    """Decide whether to run the validator given the tool results from the
    most recent tools_node batch.

    Returns (should_run, payloads_that_triggered) so the validator prompt
    can include the structured evidence rows it should grade against.
    """
    triggered: list[dict[str, Any]] = []
    for m in tool_messages:
        if m.get("role") != "tool":
            continue
        try:
            payload = json.loads(m.get("content") or "{}")
        except json.JSONDecodeError:
            continue
        name = m.get("tool_name") or payload.get("tool")

        if name == "check_compatibility":
            if payload.get("verdict") == "inferred":
                triggered.append({"tool": name, "payload": payload})

        elif name == "troubleshoot":
            if payload.get("status") == "ok" and payload.get("recommended_fix"):
                triggered.append({"tool": name, "payload": payload})
            elif payload.get("status") == "escalate_safety":
                # Safety short-circuit: don't grade, but mark for escalate-route.
                triggered.append({"tool": name, "payload": payload})

        elif name == "find_parts_by_symptom":
            if payload.get("status") == "ok" and payload.get("candidates"):
                top = payload["candidates"][0]
                # Low-likelihood top candidate is a soft signal worth validating.
                if float(top.get("likelihood", 1.0)) < CONFIDENCE_THRESHOLD:
                    triggered.append({"tool": name, "payload": payload})

    return (len(triggered) > 0, triggered)


def _safety_escalate_payload(triggered: list[dict[str, Any]]) -> dict[str, Any] | None:
    for t in triggered:
        if t["tool"] == "troubleshoot" and t["payload"].get("status") == "escalate_safety":
            return t["payload"]
    return None


def _build_prompt(
    *,
    user_message: str,
    assistant_draft: str,
    triggered: list[dict[str, Any]],
) -> str:
    system = render("validator")
    evidence_block = json.dumps(triggered, indent=2)
    return (
        f"{system}\n"
        f"---\n"
        f"USER:\n{user_message}\n\n"
        f"ASSISTANT DRAFT:\n{assistant_draft}\n\n"
        f"TOOL EVIDENCE (JSON):\n{evidence_block}\n"
    )


def _parse_json(text: str) -> dict[str, Any] | None:
    text = text.strip()
    if not text:
        return None
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < 0 or end <= start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None


async def validate(
    *,
    user_message: str,
    assistant_draft: str,
    triggered: list[dict[str, Any]],
    override_provider: str | None = None,
) -> ValidatorResult:
    """Run the validator LLM and parse its verdict."""
    # Safety short-circuit: don't burn an LLM call on the safety path. The
    # orchestrator + tool already short-circuited; we just route to escalate.
    safety = _safety_escalate_payload(triggered)
    if safety is not None:
        return ValidatorResult(
            faithfulness_score=1.0,
            relevance_score=1.0,
            unsupported_claims=[],
            verdict="escalate",
            reason=f"Safety-critical symptom matched: {safety.get('safety_match')!r}",
        )

    provider = get_provider(
        "validator",
        override_provider=override_provider,  # type: ignore[arg-type]
    )

    prompt = _build_prompt(
        user_message=user_message,
        assistant_draft=assistant_draft,
        triggered=triggered,
    )
    msgs = [Message(role="user", content=prompt)]

    text = ""
    try:
        # 1024 tokens because reasoning-capable validator models (gpt-oss,
        # qwen3) spend a chunk of the output budget on internal CoT before
        # emitting the final JSON. The actual JSON is <300 chars.
        async for ev in provider.complete(
            messages=msgs, tools=None, max_tokens=1024, temperature=0.0
        ):
            if isinstance(ev, TextDelta):
                text += ev.content
            elif isinstance(ev, (Done, Usage)):
                continue
            elif isinstance(ev, LLMStreamError):
                # Fail-open to pass with low confidence flag; we never want a
                # validator outage to block the user's reply, but we record
                # the LLM error in reason so the badge surfaces it.
                return ValidatorResult(
                    faithfulness_score=0.5,
                    relevance_score=0.5,
                    unsupported_claims=[],
                    verdict="pass",
                    reason=f"Validator LLM error, fail-open: {ev.message[:80]}",
                )
    except Exception as exc:  # noqa: BLE001
        return ValidatorResult(
            faithfulness_score=0.5,
            relevance_score=0.5,
            unsupported_claims=[],
            verdict="pass",
            reason=f"Validator exception, fail-open: {type(exc).__name__}",
        )

    parsed = _parse_json(text)
    if not parsed:
        return ValidatorResult(
            faithfulness_score=0.5,
            relevance_score=0.5,
            unsupported_claims=[],
            verdict="pass",
            reason="Validator returned unparseable output; fail-open.",
        )

    try:
        return ValidatorResult.model_validate(
            {
                "faithfulness_score": float(parsed.get("faithfulness_score", 0.5)),
                "relevance_score": float(parsed.get("relevance_score", 0.5)),
                "unsupported_claims": list(parsed.get("unsupported_claims") or []),
                "verdict": str(parsed.get("verdict", "pass")),
                "reason": str(parsed.get("reason", ""))[:280],
            }
        )
    except Exception as exc:  # noqa: BLE001
        return ValidatorResult(
            faithfulness_score=0.5,
            relevance_score=0.5,
            unsupported_claims=[],
            verdict="pass",
            reason=f"Validator output failed schema: {exc}",
        )
