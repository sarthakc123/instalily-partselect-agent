"""Tool 3: get_install_guide.

Filter by part_id, NOT semantic search (architecture rule: part_id IS the
filter key for install content). Loads the guide row from Postgres and
also surfaces the parent part so the frontend can render a part header
above the install steps.

Skips the validator: install steps are deterministic by part_id, so there
is no LLM-judgment surface for the validator to grade.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.db import repository as repo
from app.llm.base import ToolSpec
from app.tools.base import ToolContext, ToolOutput
from app.tools.lookup_part import PartCard, _to_card


class InstallGuidePayload(BaseModel):
    id: str
    part_id: str
    difficulty: str
    estimated_minutes: int
    tools_required: list[str] = Field(default_factory=list)
    safety_warnings: str = ""
    steps: list[str] = Field(default_factory=list)
    video_url: str = ""
    series_fitment_hint: str | None = None


class GetInstallGuideOutput(ToolOutput):
    tool: Literal["get_install_guide"] = "get_install_guide"
    status: Literal["ok", "part_not_found", "no_guide"]
    part: PartCard | None = None
    guide: InstallGuidePayload | None = None


def _split_tools(raw: str) -> list[str]:
    if not raw:
        return []
    # Tools are comma-separated in the seed YAML. Trim and drop empties.
    return [t.strip() for t in raw.split(",") if t.strip()]


def _split_steps(raw: str) -> list[str]:
    if not raw:
        return []
    out: list[str] = []
    for line in raw.splitlines():
        s = line.strip()
        if not s:
            continue
        # Drop a leading "1." / "1)" if present so the frontend can number.
        for prefix_len in (3, 2):
            if (
                len(s) > prefix_len
                and s[: prefix_len - 1].isdigit()
                and s[prefix_len - 1] in {".", ")"}
            ):
                s = s[prefix_len:].strip()
                break
        out.append(s)
    return out


async def run_get_install_guide(
    ctx: ToolContext, args: dict[str, Any]
) -> GetInstallGuideOutput:
    raw = str(args.get("part_number", "")).strip().upper()
    if not raw:
        return GetInstallGuideOutput(status="part_not_found")
    # Same normalization as Tool 1: accept missing PS prefix on bare digits.
    if not raw.startswith("PS") and raw.isdigit():
        raw = "PS" + raw

    part = repo.get_part(raw)
    if part is None:
        return GetInstallGuideOutput(status="part_not_found")

    guide_row = repo.get_install_guide_by_part(raw)
    if guide_row is None:
        return GetInstallGuideOutput(status="no_guide", part=_to_card(part))

    return GetInstallGuideOutput(
        status="ok",
        part=_to_card(part),
        guide=InstallGuidePayload(
            id=guide_row.id,
            part_id=guide_row.part_id,
            difficulty=guide_row.difficulty,
            estimated_minutes=guide_row.estimated_minutes,
            tools_required=_split_tools(guide_row.tools_required),
            safety_warnings=guide_row.safety_warnings,
            steps=_split_steps(guide_row.steps),
            video_url=guide_row.video_url,
            series_fitment_hint=guide_row.series_fitment_hint,
        ),
    )


GET_INSTALL_GUIDE_SPEC = ToolSpec(
    name="get_install_guide",
    description=(
        "Look up the step-by-step install guide for a part by its PartSelect "
        "part number (e.g. PS11752778). Returns ordered steps, required "
        "tools, difficulty, estimated minutes, safety warnings, and an "
        "optional video URL. Use this when the user asks how to install or "
        "replace a part. The user must have given a specific part number; "
        "if they only described the problem, use the troubleshoot tool first "
        "to identify the part."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "part_number": {
                "type": "string",
                "description": "Part number, with or without 'PS' prefix.",
            }
        },
        "required": ["part_number"],
    },
)
