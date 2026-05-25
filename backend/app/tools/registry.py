"""Tool registry. Single source of truth mapping tool name -> (runner, ToolSpec).

The orchestrator (Layer F) uses `all_tool_specs()` to advertise tools to the
LLM, and `dispatch(name, ctx, args)` to run a tool. New tools land here and
nowhere else.
"""

from __future__ import annotations

from typing import Any

from app.llm.base import ToolSpec
from app.tools.base import ToolContext, ToolOutput, ToolRunner
from app.tools.check_compatibility import CHECK_COMPATIBILITY_SPEC, run_check_compatibility
from app.tools.find_parts_by_symptom import (
    FIND_PARTS_BY_SYMPTOM_SPEC,
    run_find_parts_by_symptom,
)
from app.tools.get_install_guide import GET_INSTALL_GUIDE_SPEC, run_get_install_guide
from app.tools.lookup_part import LOOKUP_PART_SPEC, run_lookup_part
from app.tools.troubleshoot import TROUBLESHOOT_SPEC, run_troubleshoot


_REGISTRY: dict[str, tuple[ToolRunner, ToolSpec]] = {
    "lookup_part": (run_lookup_part, LOOKUP_PART_SPEC),
    "check_compatibility": (run_check_compatibility, CHECK_COMPATIBILITY_SPEC),
    "get_install_guide": (run_get_install_guide, GET_INSTALL_GUIDE_SPEC),
    "troubleshoot": (run_troubleshoot, TROUBLESHOOT_SPEC),
    "find_parts_by_symptom": (run_find_parts_by_symptom, FIND_PARTS_BY_SYMPTOM_SPEC),
}


def all_tool_specs() -> list[ToolSpec]:
    return [spec for _, spec in _REGISTRY.values()]


def get_runner(name: str) -> ToolRunner | None:
    entry = _REGISTRY.get(name)
    return entry[0] if entry else None


async def dispatch(name: str, ctx: ToolContext, args: dict[str, Any]) -> ToolOutput:
    runner = get_runner(name)
    if runner is None:
        raise KeyError(f"Unknown tool: {name}")
    return await runner(ctx, args)
