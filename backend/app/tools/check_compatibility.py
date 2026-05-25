"""Tool 2: check_compatibility.

Compatibility is a STRUCTURED EDGE LOOKUP. It is never LLM reasoning over
prose. The verdict ladder:

  1. Either entity missing  ->  unknown   (low confidence)
  2. KG edge (part FITS model) exists  ->  yes (high), carry metadata
  3. No edge AND appliance types differ ->  no (high, with reason)
  4. No edge AND install guide's series_fitment_hint matches the model's
     series  ->  inferred (low/medium), source = install_guide_inference,
                  triggers the validator in Phase 3
  5. No edge otherwise  ->  no (medium)
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel

from app.db import repository as repo
from app.llm.base import ToolSpec
from app.tools.base import ToolContext, ToolOutput


Verdict = Literal["yes", "no", "unknown", "inferred"]
Confidence = Literal["high", "medium", "low"]
NoReason = Literal[
    "appliance_type_mismatch",
    "no_edge_found",
    None,  # type: ignore[valid-type]
]
Source = Literal[
    "fitment_table",
    "install_guide_inference",
    "appliance_type",
    None,  # type: ignore[valid-type]
]


class CompatMetadata(BaseModel):
    sub_assembly_only: bool = False
    requires_adapter: bool = False
    supersedes: str | None = None


class CheckCompatibilityOutput(ToolOutput):
    tool: Literal["check_compatibility"] = "check_compatibility"
    verdict: Verdict
    confidence: Confidence
    part_id: str
    model_id: str
    metadata: CompatMetadata = CompatMetadata()
    source: Source = None
    reason: str | None = None
    explanation: str = ""


# Series tokens like "WDT78x", "WRF55x", "GFE28x".
_SERIES_TOKEN_RE = re.compile(r"\b([A-Z]{2,}\d+x)\b", re.IGNORECASE)


def _series_match(hint: str | None, series: str | None) -> bool:
    if not hint or not series:
        return False
    series_upper = series.upper()
    return any(tok.upper() == series_upper for tok in _SERIES_TOKEN_RE.findall(hint))


async def run_check_compatibility(
    ctx: ToolContext, args: dict[str, Any]
) -> CheckCompatibilityOutput:
    part_id = str(args.get("part_number", "")).strip().upper()
    model_id = str(args.get("model_number", "")).strip().upper()

    # Step 1: resolve both entities.
    part = repo.get_part(part_id) if part_id else None
    model = repo.get_model(model_id) if model_id else None

    if part is None or model is None:
        missing = []
        if part is None:
            missing.append(f"part '{part_id}'" if part_id else "part number")
        if model is None:
            missing.append(f"model '{model_id}'" if model_id else "model number")
        return CheckCompatibilityOutput(
            verdict="unknown",
            confidence="low",
            part_id=part_id,
            model_id=model_id,
            reason="entity_not_found",
            explanation=f"Could not find {', '.join(missing)} in the catalog.",
        )

    # Step 2: structured edge lookup via the KG (source of truth).
    edge = ctx.kg.fits(part.id, model.id)
    if edge is not None:
        return CheckCompatibilityOutput(
            verdict="yes",
            confidence="high",
            part_id=part.id,
            model_id=model.id,
            metadata=CompatMetadata(
                sub_assembly_only=edge.sub_assembly_only,
                requires_adapter=edge.requires_adapter,
                supersedes=edge.supersedes,
            ),
            source="fitment_table",
            explanation=(
                f"{part.name} is listed as compatible with {model.brand} {model.id}."
            ),
        )

    # Step 3: appliance-type mismatch is a definitive "no" with a clear reason.
    if part.appliance_type != model.appliance_type:
        return CheckCompatibilityOutput(
            verdict="no",
            confidence="high",
            part_id=part.id,
            model_id=model.id,
            source="appliance_type",
            reason="appliance_type_mismatch",
            explanation=(
                f"{part.name} is a {part.appliance_type} part, but {model.id} is a "
                f"{model.appliance_type}. They are not compatible."
            ),
        )

    # Step 4: prose-inference fallback via install guide series fitment hint.
    # Marked lower confidence; triggers the validator in Phase 3.
    guide = repo.get_install_guide_by_part(part.id)
    if guide is not None and _series_match(guide.series_fitment_hint, model.series):
        return CheckCompatibilityOutput(
            verdict="inferred",
            confidence="medium",
            part_id=part.id,
            model_id=model.id,
            source="install_guide_inference",
            explanation=(
                f"There is no explicit fitment entry, but the install guide for "
                f"{part.id} states it '{guide.series_fitment_hint}' and {model.id} "
                f"is in series {model.series}. Treat this as a likely but unverified fit."
            ),
        )

    # Step 5: no edge, same appliance type, no series hint. Honest "no" at medium confidence.
    return CheckCompatibilityOutput(
        verdict="no",
        confidence="medium",
        part_id=part.id,
        model_id=model.id,
        source=None,
        reason="no_edge_found",
        explanation=(
            f"{part.name} is not listed as compatible with {model.id} in our "
            f"fitment data. We cannot confirm fit."
        ),
    )


CHECK_COMPATIBILITY_SPEC = ToolSpec(
    name="check_compatibility",
    description=(
        "Check whether a specific part fits a specific appliance model. "
        "Uses the structured compatibility table as the source of truth. "
        "Verdict is one of: 'yes' (edge confirmed), 'no' (definitive non-fit, "
        "including cross-appliance mismatches), 'unknown' (one of the IDs is "
        "not in our catalog), or 'inferred' (no explicit edge but the install "
        "guide hints at fitment for the model's series; lower confidence)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "part_number": {"type": "string", "description": "Part number (e.g. PS11743427)"},
            "model_number": {"type": "string", "description": "Appliance model number (e.g. WDT780SAEM1)"},
        },
        "required": ["part_number", "model_number"],
    },
)
