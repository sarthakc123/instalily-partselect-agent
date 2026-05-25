"""Tool runner protocol + shared types for the 5 typed tools.

Tools are the *only* place where the data layer is touched on behalf of the
LLM. The orchestrator (Layer F) dispatches by name, never importing tool
functions directly. Outputs are Pydantic models so they serialize the same
way for both:
  - the LLM (JSON content of a tool-result message)
  - the frontend (rendered as ProductCard / CompatBadge / etc.)
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from app.kg.base import KnowledgeGraph


class ToolOutput(BaseModel):
    """Base for all tool outputs. The `tool` discriminator lets the frontend
    dispatch to the right rich card component."""

    tool: str


@dataclass(slots=True)
class ToolContext:
    """Per-request handles passed to every tool. Stays small on purpose;
    new shared deps land here so tools don't reach into globals."""

    kg: KnowledgeGraph


# Async tool runner signature.
ToolRunner = Callable[[ToolContext, dict[str, Any]], Awaitable[ToolOutput]]
