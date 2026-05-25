"""Tool 1: lookup_part.

Exact -> fuzzy -> not_found. **Hard rule: never silent-swap on fuzzy hits.**
Returns candidates and the caller (orchestrator + UI) must confirm with the
user before treating any candidate as the canonical part.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.db import repository as repo
from app.llm.base import ToolSpec
from app.tools.base import ToolContext, ToolOutput


class PartCard(BaseModel):
    """Minimal part payload safe to render in chat."""

    id: str
    name: str
    manufacturer: str
    appliance_type: str
    part_type: str
    price_cents: int
    in_stock: bool
    image_url: str = ""
    description: str = ""


class LookupPartOutput(ToolOutput):
    tool: Literal["lookup_part"] = "lookup_part"
    status: Literal["exact", "fuzzy_candidates", "not_found"]
    part: PartCard | None = None
    candidates: list[PartCard] = Field(default_factory=list)
    confidence: float


def _to_card(part: Any) -> PartCard:
    return PartCard(
        id=part.id,
        name=part.name,
        manufacturer=part.manufacturer,
        appliance_type=part.appliance_type,
        part_type=part.part_type,
        price_cents=part.price_cents,
        in_stock=part.in_stock,
        image_url=part.image_url,
        description=part.description,
    )


async def run_lookup_part(ctx: ToolContext, args: dict[str, Any]) -> LookupPartOutput:
    raw = str(args.get("part_number", "")).strip()
    if not raw:
        return LookupPartOutput(status="not_found", confidence=0.0)

    # Normalize: PartSelect numbers are case-insensitive and may arrive without the PS prefix.
    normalized = raw.upper()
    if not normalized.startswith("PS") and normalized.isdigit():
        normalized = "PS" + normalized

    exact = repo.get_part(normalized)
    if exact is not None:
        return LookupPartOutput(status="exact", part=_to_card(exact), confidence=1.0)

    candidates = repo.fuzzy_search_parts(normalized, limit=5)
    if candidates:
        return LookupPartOutput(
            status="fuzzy_candidates",
            candidates=[_to_card(c) for c in candidates],
            confidence=0.7,
        )

    return LookupPartOutput(status="not_found", confidence=0.0)


LOOKUP_PART_SPEC = ToolSpec(
    name="lookup_part",
    description=(
        "Find a part by its PartSelect part number (e.g. PS11752778). "
        "Returns the part's metadata if found exactly. If only similar numbers "
        "exist, returns candidates and you MUST ask the user to confirm which "
        "one they meant before continuing. Never assume a fuzzy match."
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
