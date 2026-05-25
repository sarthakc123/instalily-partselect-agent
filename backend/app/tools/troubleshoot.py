"""Tool 4: troubleshoot.

Maps a natural-language symptom to a canonical SY_* id, then traverses the
KG (symptom -[FIXES]-> part -[FITS]-> model?) to surface ranked candidate
parts with auditable per-row sources.

Phase 1 simplification: this is NOT yet full hybrid RAG over repair stories.
The corpus is too small (10 symptoms) for BM25 + dense + rerank to add
signal over the structured symptom_fixes edges. Phase 2 swaps the symptom
mapping for a hybrid retrieval pass when we have a real repair-story corpus.

Safety-critical short-circuit lives here: if the user's symptom matches a
safety-keyword pattern (gas smell, electrical sparking, water damage,
human/pet injury), return verdict='escalate_safety' without calling the
LLM or the KG.
"""

from __future__ import annotations

import json
import re
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.db.pool import connection
from app.llm.base import Message, ToolSpec
from app.llm.events import (
    Done,
    StreamError,
    TextDelta,
    Usage,
)
from app.llm.registry import get_provider
from app.tools.base import ToolContext, ToolOutput


# Safety-critical keyword patterns. Hard rule: short-circuit, never attempt repair.
_SAFETY_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"\bgas (smell|leak|odor)\b",
        r"\bsmell(ing)? gas\b",
        r"\bsmoke|smoking|burning smell\b",
        r"\b(fire|flames?|sparking|electrical (?:shock|burn))\b",
        r"\bflood(ing|ed)?\b|\bactive (?:water (?:damage|leak))\b",
        r"\bshock(ed|ing)?\b",
        r"\b(child|pet|baby) (stuck|trapped|hurt|injured)\b",
        r"\b(injur|hurt|bleeding)\b",
    ]
]


def _looks_safety_critical(text: str) -> str | None:
    """Return the matched phrase if the symptom hits a safety pattern."""
    for pat in _SAFETY_PATTERNS:
        m = pat.search(text)
        if m:
            return m.group(0)
    return None


class SymptomMatch(BaseModel):
    symptom_id: str
    canonical_label: str
    description: str
    confidence: float


class CandidateCause(BaseModel):
    part_id: str
    part_name: str
    price_cents: int
    in_stock: bool
    likelihood: float
    common_cause_rank: int
    fits_model: bool | None = None
    appliance_type: str = ""
    brand: str = ""


class TroubleshootSource(BaseModel):
    """Auditable provenance for the candidate ranking."""

    table: str
    row: dict[str, Any]


class TroubleshootOutput(ToolOutput):
    tool: Literal["troubleshoot"] = "troubleshoot"
    status: Literal[
        "ok",
        "symptom_unknown",
        "escalate_safety",
        "ambiguous",
    ]
    user_symptom_text: str = ""
    matched_symptom: SymptomMatch | None = None
    candidate_causes: list[CandidateCause] = Field(default_factory=list)
    recommended_fix: CandidateCause | None = None
    confidence: float = 0.0
    sources: list[TroubleshootSource] = Field(default_factory=list)
    safety_match: str | None = None
    explanation: str = ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_symptoms() -> list[dict[str, Any]]:
    """Pull every symptom row from Postgres so the mapper prompt always
    reflects current data."""
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, canonical_label, description, appliance_type "
            "FROM symptoms ORDER BY appliance_type, id"
        )
        return list(cur.fetchall())


_MAP_SYMPTOM_PROMPT = """You are mapping a user's appliance problem to one of the canonical \
symptoms below. Output JSON ONLY in this exact shape:
{{"symptom_id": "<SY_...>", "confidence": 0.0-1.0}}

If none of the symptoms below clearly fits, output:
{{"symptom_id": null, "confidence": 0.0}}

Confidence is your subjective certainty that the chosen symptom is what the \
user means. Use 0.9+ for unambiguous matches, 0.6-0.8 for clear-but-rephrased \
matches, below 0.5 means you should probably output null.

Canonical symptoms (id | appliance | label | description):
{catalog}

User's problem (and any brand/appliance context):
{user_text}

Output the JSON now, nothing else.
"""


def _format_catalog(rows: list[dict[str, Any]]) -> str:
    return "\n".join(
        f"{r['id']} | {r['appliance_type']} | {r['canonical_label']} | {r['description']}"
        for r in rows
    )


async def _map_symptom_llm(user_text: str, *, override_provider: str | None) -> SymptomMatch | None:
    """Call the utility LLM with the symptom catalog and parse its JSON."""
    rows = _load_symptoms()
    by_id = {r["id"]: r for r in rows}

    provider = get_provider(
        "utility",
        override_provider=override_provider,  # type: ignore[arg-type]
    )

    prompt = _MAP_SYMPTOM_PROMPT.format(
        catalog=_format_catalog(rows),
        user_text=user_text.strip(),
    )
    msgs = [Message(role="user", content=prompt)]

    text = ""
    async for ev in provider.complete(messages=msgs, tools=None, max_tokens=120, temperature=0.0):
        if isinstance(ev, TextDelta):
            text += ev.content
        elif isinstance(ev, (Done, Usage)):
            continue
        elif isinstance(ev, StreamError):
            return None

    parsed = _safe_json(text)
    if not parsed:
        return None
    sid = parsed.get("symptom_id")
    if not isinstance(sid, str) or sid not in by_id:
        return None
    row = by_id[sid]
    return SymptomMatch(
        symptom_id=sid,
        canonical_label=row["canonical_label"],
        description=row["description"],
        confidence=float(parsed.get("confidence", 0.5) or 0.5),
    )


def _safe_json(text: str) -> dict[str, Any] | None:
    """Find a JSON object anywhere in the text and parse it."""
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


# ---------------------------------------------------------------------------
# Tool runner
# ---------------------------------------------------------------------------


async def run_troubleshoot(ctx: ToolContext, args: dict[str, Any]) -> TroubleshootOutput:
    symptom_text = str(args.get("symptom") or args.get("symptom_text") or "").strip()
    brand = (args.get("brand") or "").strip() or None
    appliance_type = (args.get("appliance_type") or "").strip().lower() or None
    raw_model = args.get("model_number") or args.get("model_id")
    model_id = str(raw_model).strip().upper() if raw_model else None
    provider_override = args.get("_provider_override")  # not LLM-visible; threaded by orchestrator

    # 1. Safety short-circuit. Hard rule.
    safety = _looks_safety_critical(symptom_text)
    if safety:
        return TroubleshootOutput(
            status="escalate_safety",
            user_symptom_text=symptom_text,
            safety_match=safety,
            explanation=(
                "This sounds like a safety-critical situation. Please stop using "
                "the appliance, ensure everyone is safe, and contact the manufacturer "
                "or your utility company directly. Do not attempt a repair."
            ),
        )

    if not symptom_text:
        return TroubleshootOutput(
            status="symptom_unknown",
            user_symptom_text=symptom_text,
            explanation="Tell me what is going wrong with the appliance and I can suggest causes.",
        )

    # 2. Map natural language to a canonical symptom id.
    # Include brand + appliance type in the user text so the mapper can scope correctly.
    enriched = symptom_text
    if appliance_type:
        enriched = f"{enriched} (appliance: {appliance_type})"
    if brand:
        enriched = f"{enriched} (brand: {brand})"
    match = await _map_symptom_llm(enriched, override_provider=provider_override)

    if match is None or match.confidence < 0.4:
        return TroubleshootOutput(
            status="symptom_unknown",
            user_symptom_text=symptom_text,
            explanation=(
                "I could not match this to a known symptom in our catalog. "
                "Try describing it differently, or share the model number so I can scope to your appliance."
            ),
        )

    # 3. KG traversal: ranked candidate parts, annotated with fitment.
    rows = ctx.kg.parts_fixing_symptom(match.symptom_id, model_id=model_id)
    if not rows:
        return TroubleshootOutput(
            status="symptom_unknown",
            user_symptom_text=symptom_text,
            matched_symptom=match,
            explanation=(
                f"We recognize the symptom but have no parts mapped to fix it yet."
            ),
        )

    causes: list[CandidateCause] = [
        CandidateCause(
            part_id=r.part_id,
            part_name=r.part_name,
            price_cents=r.price_cents,
            in_stock=r.in_stock,
            likelihood=r.likelihood,
            common_cause_rank=r.common_cause_rank,
            fits_model=r.fits_model,
            appliance_type=r.appliance_type,
            brand=r.brand,
        )
        for r in rows
    ]

    # Recommended fix: top-ranked candidate that fits the model when we have one,
    # else the top-ranked candidate overall.
    recommended: CandidateCause | None = None
    if model_id:
        recommended = next((c for c in causes if c.fits_model is True), None)
    if recommended is None:
        recommended = causes[0]

    sources = [
        TroubleshootSource(
            table="symptom_fixes",
            row={
                "symptom_id": match.symptom_id,
                "part_id": c.part_id,
                "likelihood": c.likelihood,
                "common_cause_rank": c.common_cause_rank,
            },
        )
        for c in causes
    ]

    # Confidence: blend the symptom-match confidence with the top candidate's likelihood.
    confidence = round(min(0.99, 0.5 * match.confidence + 0.5 * recommended.likelihood), 3)

    expl = (
        f"The symptom maps to '{match.canonical_label}'. "
        f"Most common cause: {recommended.part_name} ({recommended.part_id})."
    )
    if model_id and recommended.fits_model is False:
        expl += (
            f" Note: this part is not in our fitment table for {model_id}. "
            "Confirm before ordering."
        )

    return TroubleshootOutput(
        status="ok",
        user_symptom_text=symptom_text,
        matched_symptom=match,
        candidate_causes=causes,
        recommended_fix=recommended,
        confidence=confidence,
        sources=sources,
        explanation=expl,
    )


TROUBLESHOOT_SPEC = ToolSpec(
    name="troubleshoot",
    description=(
        "Given a natural-language description of an appliance problem (and "
        "optionally brand/appliance type/model number), identify the most "
        "likely failing parts ranked by probability. Returns candidate "
        "causes with per-row provenance (which symptom_fixes row drove the "
        "ranking) and a recommended fix. Use this when the user describes "
        "a symptom in plain English instead of giving you a part number. "
        "Safety-critical symptoms (gas smell, electrical sparking, water "
        "damage, injury) are returned with status='escalate_safety' and "
        "you MUST NOT try to walk the user through a repair, even partially."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "symptom": {
                "type": "string",
                "description": "What the user said is going wrong (in their own words).",
            },
            "brand": {
                "type": "string",
                "description": "Brand if known (Whirlpool, GE, Samsung, ...).",
            },
            "appliance_type": {
                "type": "string",
                "description": "'refrigerator' or 'dishwasher' if known.",
            },
            "model_number": {
                "type": "string",
                "description": "Model number if known; enables fitment annotation.",
            },
        },
        "required": ["symptom"],
    },
)
