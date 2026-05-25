"""Tool 5: find_parts_by_symptom.

KG traversal: (symptom) -[FIXES]-> (part) -[FITS]-> (model if known).
Returns ranked candidate parts annotated with whether they fit the user's
model. Thin wrapper over `NetworkXKG.parts_fixing_symptom()`.

Distinct from Tool 4 (troubleshoot): this takes a canonical symptom_id
directly. Tool 4 does the natural-language to canonical mapping first,
then can call this (or duplicate the traversal inline). The orchestrator
calls this when it already has a symptom in hand from a prior turn.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.llm.base import ToolSpec
from app.tools.base import ToolContext, ToolOutput


class FixCandidatePayload(BaseModel):
    """One row of the ranked candidate list. Mirrors kg.schema.FixCandidate
    but is a Pydantic model so it serializes cleanly to the frontend."""

    part_id: str
    part_name: str
    price_cents: int
    in_stock: bool
    likelihood: float
    common_cause_rank: int
    fits_model: bool | None = None
    appliance_type: str = ""
    brand: str = ""


class FindPartsBySymptomOutput(ToolOutput):
    tool: Literal["find_parts_by_symptom"] = "find_parts_by_symptom"
    status: Literal["ok", "symptom_unknown"]
    symptom_id: str
    model_id: str | None = None
    candidates: list[FixCandidatePayload] = Field(default_factory=list)


async def run_find_parts_by_symptom(
    ctx: ToolContext, args: dict[str, Any]
) -> FindPartsBySymptomOutput:
    symptom_id = str(args.get("symptom_id", "")).strip().upper()
    model_id_raw = args.get("model_id")
    model_id = str(model_id_raw).strip().upper() if model_id_raw else None

    if not symptom_id:
        return FindPartsBySymptomOutput(
            status="symptom_unknown", symptom_id=symptom_id, model_id=model_id
        )

    rows = ctx.kg.parts_fixing_symptom(symptom_id, model_id=model_id)
    if not rows:
        return FindPartsBySymptomOutput(
            status="symptom_unknown", symptom_id=symptom_id, model_id=model_id
        )

    return FindPartsBySymptomOutput(
        status="ok",
        symptom_id=symptom_id,
        model_id=model_id,
        candidates=[
            FixCandidatePayload(
                part_id=c.part_id,
                part_name=c.part_name,
                price_cents=c.price_cents,
                in_stock=c.in_stock,
                likelihood=c.likelihood,
                common_cause_rank=c.common_cause_rank,
                fits_model=c.fits_model,
                appliance_type=c.appliance_type,
                brand=c.brand,
            )
            for c in rows
        ],
    )


FIND_PARTS_BY_SYMPTOM_SPEC = ToolSpec(
    name="find_parts_by_symptom",
    description=(
        "Given a canonical symptom id (e.g. 'SY_ICE_MAKER_NOT_WORKING') and "
        "optionally a model number, return parts known to fix that symptom, "
        "ranked by common-cause rank and likelihood. When a model is "
        "supplied, each candidate is annotated with whether it fits that "
        "model (fits_model=true/false). Use this when you already know the "
        "symptom id (e.g. resolved by the troubleshoot tool); use the "
        "troubleshoot tool first if the user described the problem in "
        "natural language."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "symptom_id": {
                "type": "string",
                "description": "Canonical symptom id like SY_ICE_MAKER_NOT_WORKING",
            },
            "model_id": {
                "type": "string",
                "description": "Optional appliance model number; enables fitment annotation",
            },
        },
        "required": ["symptom_id"],
    },
)
