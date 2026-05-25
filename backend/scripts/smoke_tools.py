"""Smoke test for Tools 1 & 2 going through the public tool dispatcher.

Validates the verdict ladder for check_compatibility (yes / no-mismatch /
no-edge / unknown / inferred) and the exact / fuzzy / not_found ladder
for lookup_part. Hard rule asserted: fuzzy never silent-swaps.

Usage:
    cd backend && python -m scripts.smoke_tools
"""

from __future__ import annotations

import asyncio
import sys

from app.config import settings
from app.db.pool import close_pool
from app.kg.builder import build_kg_from_postgres
from app.tools.base import ToolContext
from app.tools.check_compatibility import CheckCompatibilityOutput
from app.tools.find_parts_by_symptom import FindPartsBySymptomOutput
from app.tools.get_install_guide import GetInstallGuideOutput
from app.tools.lookup_part import LookupPartOutput
from app.tools.registry import all_tool_specs, dispatch
from app.tools.troubleshoot import TroubleshootOutput


def _ok(label: str, ok: bool, detail: str = "") -> None:
    status = "PASS" if ok else "FAIL"
    extra = f"  ({detail})" if detail else ""
    print(f"  [{status}] {label}{extra}")


async def main() -> int:
    failures = 0
    try:
        print("Tools smoke test\n")
        kg = build_kg_from_postgres()
        ctx = ToolContext(kg=kg)

        # Tool registry advertises all five tools.
        specs = all_tool_specs()
        names = {s.name for s in specs}
        expected_tools = {
            "lookup_part",
            "check_compatibility",
            "get_install_guide",
            "troubleshoot",
            "find_parts_by_symptom",
        }
        ok = names == expected_tools
        _ok("registry advertises all 5 tools", ok, detail=f"got={names}")
        if not ok:
            failures += 1

        # ----- Tool 1: lookup_part -----

        # 1. Exact match.
        out = await dispatch("lookup_part", ctx, {"part_number": "PS11752778"})
        assert isinstance(out, LookupPartOutput)
        ok = out.status == "exact" and out.part is not None and out.part.id == "PS11752778"
        _ok("lookup_part(PS11752778) -> exact hit",
            ok, detail=f"status={out.status}, confidence={out.confidence}")
        if not ok:
            failures += 1

        # 2. Lowercase + no PS prefix should still resolve via normalization.
        out = await dispatch("lookup_part", ctx, {"part_number": "ps11752778"})
        assert isinstance(out, LookupPartOutput)
        ok = out.status == "exact"
        _ok("lookup_part normalizes lowercase 'ps11752778' -> exact", ok)
        if not ok:
            failures += 1

        # 3. Fuzzy: one digit off must return candidates, NOT auto-swap to exact.
        out = await dispatch("lookup_part", ctx, {"part_number": "PS11752779"})
        assert isinstance(out, LookupPartOutput)
        ok = (
            out.status == "fuzzy_candidates"
            and out.part is None  # hard rule: no silent swap to a single part
            and any(c.id == "PS11752778" for c in out.candidates)
        )
        _ok("lookup_part(PS11752779) -> fuzzy_candidates incl. PS11752778, no silent swap",
            ok, detail=f"status={out.status}, n_candidates={len(out.candidates)}")
        if not ok:
            failures += 1

        # 4. Not found.
        out = await dispatch("lookup_part", ctx, {"part_number": "PS00000000"})
        assert isinstance(out, LookupPartOutput)
        ok = out.status == "not_found" and out.confidence == 0.0
        _ok("lookup_part(PS00000000) -> not_found",
            ok, detail=f"status={out.status}")
        if not ok:
            failures += 1

        # 5. Empty input is gracefully not_found, not an exception.
        out = await dispatch("lookup_part", ctx, {"part_number": ""})
        assert isinstance(out, LookupPartOutput)
        ok = out.status == "not_found"
        _ok("lookup_part('') -> not_found (no exception)", ok)
        if not ok:
            failures += 1

        # ----- Tool 2: check_compatibility -----

        # 6. yes (positive edge).
        out = await dispatch(
            "check_compatibility", ctx,
            {"part_number": "PS11743427", "model_number": "WDT780SAEM1"},
        )
        assert isinstance(out, CheckCompatibilityOutput)
        ok = (
            out.verdict == "yes"
            and out.confidence == "high"
            and out.source == "fitment_table"
        )
        _ok("check_compatibility(PS11743427, WDT780SAEM1) -> yes/high/fitment_table",
            ok, detail=f"verdict={out.verdict}, source={out.source}")
        if not ok:
            failures += 1

        # 7. no via cross-appliance mismatch (the case-study trick).
        out = await dispatch(
            "check_compatibility", ctx,
            {"part_number": "PS11752778", "model_number": "WDT780SAEM1"},
        )
        assert isinstance(out, CheckCompatibilityOutput)
        ok = (
            out.verdict == "no"
            and out.confidence == "high"
            and out.reason == "appliance_type_mismatch"
            and "refrigerator" in out.explanation
            and "dishwasher" in out.explanation
        )
        _ok("check_compatibility(fridge part, dishwasher model) -> no/appliance_type_mismatch",
            ok, detail=f"verdict={out.verdict}, reason={out.reason}")
        if not ok:
            failures += 1

        # 8. unknown when the part isn't in the catalog.
        out = await dispatch(
            "check_compatibility", ctx,
            {"part_number": "PS99999999", "model_number": "WDT780SAEM1"},
        )
        assert isinstance(out, CheckCompatibilityOutput)
        ok = out.verdict == "unknown" and out.reason == "entity_not_found"
        _ok("check_compatibility(unknown part, real model) -> unknown",
            ok, detail=f"verdict={out.verdict}, reason={out.reason}")
        if not ok:
            failures += 1

        # 9. unknown when the model isn't in the catalog.
        out = await dispatch(
            "check_compatibility", ctx,
            {"part_number": "PS11743427", "model_number": "FAKE_MODEL_1"},
        )
        assert isinstance(out, CheckCompatibilityOutput)
        ok = out.verdict == "unknown" and out.reason == "entity_not_found"
        _ok("check_compatibility(real part, unknown model) -> unknown", ok)
        if not ok:
            failures += 1

        # 10. supersedes metadata carried through (PS11752778 fits KRFC704FSS supersedes PS11750000).
        out = await dispatch(
            "check_compatibility", ctx,
            {"part_number": "PS11752778", "model_number": "KRFC704FSS"},
        )
        assert isinstance(out, CheckCompatibilityOutput)
        ok = (
            out.verdict == "yes"
            and out.metadata.supersedes == "PS11750000"
        )
        _ok("check_compatibility carries supersedes metadata in the output",
            ok, detail=f"supersedes={out.metadata.supersedes}")
        if not ok:
            failures += 1

        # 11. no edge, no series match, same appliance -> no/no_edge_found.
        out = await dispatch(
            "check_compatibility", ctx,
            {"part_number": "PS11743427", "model_number": "DW80R7060US"},  # Samsung, series DW80x
        )
        assert isinstance(out, CheckCompatibilityOutput)
        ok = (
            out.verdict == "no"
            and out.reason == "no_edge_found"
            and out.source is None
        )
        _ok("check_compatibility(no edge, no series match, same appliance) -> no/no_edge_found",
            ok, detail=f"verdict={out.verdict}, reason={out.reason}")
        if not ok:
            failures += 1

        # 11b. inferred via install guide series fitment hint.
        # PS11743427's guide says "fits all Whirlpool WDT78x and WDT73x dishwashers".
        # WDT789SAKZ is a Whirlpool dishwasher in series WDT78x with NO direct compat
        # edge -> should return inferred (low-confidence, source=install_guide_inference,
        # triggers the Phase 3 validator).
        out = await dispatch(
            "check_compatibility", ctx,
            {"part_number": "PS11743427", "model_number": "WDT789SAKZ"},
        )
        assert isinstance(out, CheckCompatibilityOutput)
        ok = (
            out.verdict == "inferred"
            and out.source == "install_guide_inference"
            and out.confidence == "medium"
            and "WDT78x" in out.explanation
        )
        _ok("check_compatibility(no edge, series matches install guide hint) -> inferred",
            ok, detail=f"verdict={out.verdict}, source={out.source}, confidence={out.confidence}")
        if not ok:
            failures += 1

        # ----- Tool 3: get_install_guide -----

        # G1. Exact part with a seeded guide.
        out = await dispatch("get_install_guide", ctx, {"part_number": "PS11752778"})
        assert isinstance(out, GetInstallGuideOutput)
        ok = (
            out.status == "ok"
            and out.guide is not None
            and out.guide.part_id == "PS11752778"
            and out.guide.difficulty == "Moderate"
            and len(out.guide.steps) >= 5
            and any("ice maker" in s.lower() for s in out.guide.steps)
            and "Phillips screwdriver" in out.guide.tools_required
            and out.guide.series_fitment_hint is not None
        )
        _ok("get_install_guide(PS11752778) -> full guide with steps/tools/hint",
            ok, detail=f"status={out.status}, n_steps={len(out.guide.steps) if out.guide else 0}")
        if not ok:
            failures += 1

        # G2. Part exists but has no seeded guide.
        out = await dispatch("get_install_guide", ctx, {"part_number": "PS12348107"})
        assert isinstance(out, GetInstallGuideOutput)
        ok = out.status == "no_guide" and out.part is not None and out.guide is None
        _ok("get_install_guide(part w/o guide) -> no_guide w/ part hydrated",
            ok, detail=f"status={out.status}")
        if not ok:
            failures += 1

        # G3. Part not found.
        out = await dispatch("get_install_guide", ctx, {"part_number": "PS00000000"})
        assert isinstance(out, GetInstallGuideOutput)
        ok = out.status == "part_not_found"
        _ok("get_install_guide(unknown) -> part_not_found", ok)
        if not ok:
            failures += 1

        # ----- Tool 5: find_parts_by_symptom -----

        # F1. Ice maker symptom against a Whirlpool fridge: PS11752778 ranks first AND fits.
        out = await dispatch(
            "find_parts_by_symptom", ctx,
            {"symptom_id": "SY_ICE_MAKER_NOT_WORKING", "model_id": "WRF555SDFZ"},
        )
        assert isinstance(out, FindPartsBySymptomOutput)
        top = out.candidates[0] if out.candidates else None
        ok = (
            out.status == "ok"
            and top is not None
            and top.part_id == "PS11752778"
            and top.fits_model is True
            and top.common_cause_rank == 1
        )
        _ok("find_parts_by_symptom(ice_maker, WRF555SDFZ) ranks PS11752778 first & fits",
            ok, detail=f"top={top}")
        if not ok:
            failures += 1

        # F2. Same symptom, dishwasher model: PS11752778 still appears but fits_model=false.
        out = await dispatch(
            "find_parts_by_symptom", ctx,
            {"symptom_id": "SY_ICE_MAKER_NOT_WORKING", "model_id": "WDT780SAEM1"},
        )
        assert isinstance(out, FindPartsBySymptomOutput)
        ps = next((c for c in out.candidates if c.part_id == "PS11752778"), None)
        ok = ps is not None and ps.fits_model is False
        _ok("find_parts_by_symptom marks fridge part as not fitting a dishwasher",
            ok, detail=f"got={ps}")
        if not ok:
            failures += 1

        # F3. Unknown symptom id.
        out = await dispatch("find_parts_by_symptom", ctx, {"symptom_id": "SY_DOES_NOT_EXIST"})
        assert isinstance(out, FindPartsBySymptomOutput)
        ok = out.status == "symptom_unknown"
        _ok("find_parts_by_symptom(unknown symptom) -> symptom_unknown", ok)
        if not ok:
            failures += 1

        # ----- Tool 4: troubleshoot -----
        # The natural-language path needs an LLM (utility role). Skip LLM-dependent
        # assertions if no key is set; always test the safety short-circuit since
        # that path is pure pattern matching.

        # T1. Safety short-circuit: gas smell. No LLM call required.
        out = await dispatch(
            "troubleshoot", ctx,
            {"symptom": "I smell gas near my fridge.", "appliance_type": "refrigerator"},
        )
        assert isinstance(out, TroubleshootOutput)
        ok = (
            out.status == "escalate_safety"
            and out.safety_match is not None
            and out.candidate_causes == []
        )
        _ok("troubleshoot(gas smell) -> escalate_safety, no candidates",
            ok, detail=f"status={out.status}, match={out.safety_match}")
        if not ok:
            failures += 1

        # T2. Natural-language ice-maker symptom maps to SY_ICE_MAKER_NOT_WORKING
        # and recommends PS11752778. Needs the utility LLM (Groq).
        has_any_key = (
            settings.groq_api_key or settings.openai_api_key or settings.anthropic_api_key
        )
        if not has_any_key:
            print("  [SKIP] troubleshoot(natural language) - no LLM key set")
        else:
            out = await dispatch(
                "troubleshoot", ctx,
                {
                    "symptom": "the ice maker on my fridge stopped making ice",
                    "brand": "Whirlpool",
                    "appliance_type": "refrigerator",
                    "model_number": "WRF555SDFZ",
                },
            )
            assert isinstance(out, TroubleshootOutput)
            ok = (
                out.status == "ok"
                and out.matched_symptom is not None
                and out.matched_symptom.symptom_id == "SY_ICE_MAKER_NOT_WORKING"
                and out.recommended_fix is not None
                and out.recommended_fix.part_id == "PS11752778"
                and out.recommended_fix.fits_model is True
                and len(out.sources) >= 1
            )
            _ok("troubleshoot(natural language) -> SY_ICE_MAKER_NOT_WORKING + PS11752778",
                ok, detail=f"matched={out.matched_symptom}, rec={out.recommended_fix}")
            if not ok:
                failures += 1

        # 12. JSON round-trip (orchestrator will serialize this).
        out = await dispatch(
            "check_compatibility", ctx,
            {"part_number": "PS11743427", "model_number": "WDT780SAEM1"},
        )
        payload = out.model_dump_json()
        ok = '"verdict":"yes"' in payload and '"tool":"check_compatibility"' in payload
        _ok("tool output serializes to JSON cleanly (orchestrator hand-off shape)",
            ok, detail=payload[:100] + "...")
        if not ok:
            failures += 1

        print(f"\n{'-' * 60}")
        print(f"{'All tool tests passed.' if failures == 0 else f'{failures} test(s) FAILED.'}")
        return 0 if failures == 0 else 1
    finally:
        close_pool()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
