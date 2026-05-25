"""Smoke test for the NetworkX KG, mirroring the repository smoke test but
going through KG traversals. Confirms that the KG and Postgres tell the
same story (no drift).

Usage:
    cd backend && python -m scripts.smoke_kg
"""

from __future__ import annotations

import sys
from pathlib import Path

from app.config import settings
from app.db.pool import close_pool
from app.kg.builder import build_kg_from_postgres
from app.kg.networkx_kg import NetworkXKG


def _ok(label: str, ok: bool, detail: str = "") -> None:
    status = "PASS" if ok else "FAIL"
    extra = f"  ({detail})" if detail else ""
    print(f"  [{status}] {label}{extra}")


def main() -> int:
    failures = 0
    try:
        print("KG smoke test\n")

        # Build, snapshot, and round-trip-load to exercise both code paths.
        kg = build_kg_from_postgres()
        snapshot_path = Path(settings.kg_path).resolve()
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        kg.save_snapshot(snapshot_path)
        kg = NetworkXKG.load_snapshot(snapshot_path)
        print(f"Snapshot round-trip OK at {snapshot_path}\n")

        # 1. Compatibility (positive): PS11743427 fits WDT780SAEM1.
        edge = kg.fits("PS11743427", "WDT780SAEM1")
        ok = edge is not None and edge.part_id == "PS11743427"
        _ok("fits(PS11743427, WDT780SAEM1) -> edge exists", ok)
        if not ok:
            failures += 1

        # 2. Compatibility (negative cross-appliance): fridge part vs dishwasher model.
        edge = kg.fits("PS11752778", "WDT780SAEM1")
        ok = edge is None
        _ok("fits(fridge part, dishwasher model) -> None", ok, detail=f"got={edge}")
        if not ok:
            failures += 1

        # 3. Supersedes metadata round-trips through JSON snapshot.
        edge = kg.fits("PS11752778", "KRFC704FSS")
        ok = edge is not None and edge.supersedes == "PS11750000"
        _ok("fits edge carries supersedes metadata after snapshot round-trip",
            ok, detail=f"supersedes={edge.supersedes if edge else None}")
        if not ok:
            failures += 1

        # 4. Models fitting PS11743427: should be the 5 dishwashers we seeded.
        models = kg.models_fitting_part("PS11743427")
        ok = len(models) == 5 and "WDT780SAEM1" in models
        _ok("models_fitting_part(PS11743427) -> 5 models incl. WDT780SAEM1",
            ok, detail=f"count={len(models)}")
        if not ok:
            failures += 1

        # 5. Brand lookup via MADE_BY edge.
        brand = kg.brand_of_part("PS11752778")
        ok = brand == "Whirlpool"
        _ok("brand_of_part(PS11752778) -> Whirlpool", ok, detail=f"got={brand}")
        if not ok:
            failures += 1

        # 6. Appliance type of model.
        appliance = kg.appliance_of_model("WDT780SAEM1")
        ok = appliance == "dishwasher"
        _ok("appliance_of_model(WDT780SAEM1) -> dishwasher",
            ok, detail=f"got={appliance}")
        if not ok:
            failures += 1

        # 7. KG traversal: parts fixing ice-maker symptom for WRF555SDFZ.
        # Should rank PS11752778 first AND mark it as fitting.
        candidates = kg.parts_fixing_symptom("SY_ICE_MAKER_NOT_WORKING", model_id="WRF555SDFZ")
        top = candidates[0] if candidates else None
        ok = (
            top is not None
            and top.part_id == "PS11752778"
            and top.fits_model is True
            and top.common_cause_rank == 1
            and 0.55 <= top.likelihood <= 0.65
        )
        _ok("parts_fixing_symptom(ice maker, WRF555SDFZ) ranks PS11752778 first & fits",
            ok, detail=f"top={top}")
        if not ok:
            failures += 1

        # 8. Same symptom, but model is a dishwasher. PS11752778 still fixes the
        # symptom but should be marked as NOT fitting (different appliance type).
        candidates = kg.parts_fixing_symptom("SY_ICE_MAKER_NOT_WORKING", model_id="WDT780SAEM1")
        ps11752778 = next((c for c in candidates if c.part_id == "PS11752778"), None)
        ok = ps11752778 is not None and ps11752778.fits_model is False
        _ok("parts_fixing_symptom marks fridge part as NOT fitting a dishwasher",
            ok, detail=f"got={ps11752778}")
        if not ok:
            failures += 1

        # 9. Symptoms occurring in dishwasher should include the 5 we seeded.
        symptoms = kg.symptoms_occurring_in("dishwasher")
        ok = (
            len(symptoms) == 5
            and "SY_DISHWASHER_NOT_FILLING" in symptoms
            and "SY_DISHWASHER_NOT_DRAINING" in symptoms
        )
        _ok("symptoms_occurring_in(dishwasher) -> 5 dishwasher symptoms",
            ok, detail=f"count={len(symptoms)}")
        if not ok:
            failures += 1

        # 10. Install guide lookup via INSTALLED_VIA edge.
        guide_id = kg.install_guide_id_for_part("PS11752778")
        ok = guide_id == "IG_PS11752778"
        _ok("install_guide_id_for_part(PS11752778) -> IG_PS11752778",
            ok, detail=f"got={guide_id}")
        if not ok:
            failures += 1

        # 11. Stats sanity check.
        stats = kg.stats()
        ok = (
            stats.get("node_NodeType.PART", 0) == 50
            and stats.get("node_NodeType.MODEL", 0) == 20
            and stats.get("edge_EdgeType.FITS", 0) == 38
            and stats.get("edge_EdgeType.FIXES", 0) == 28
        )
        _ok("stats() matches seed counts (50 parts, 20 models, 38 FITS, 28 FIXES)",
            ok, detail=str({k: v for k, v in stats.items() if "node_" in k or "edge_" in k}))
        if not ok:
            failures += 1

        print(f"\n{'-' * 60}")
        print(f"{'All KG tests passed.' if failures == 0 else f'{failures} test(s) FAILED.'}")
        return 0 if failures == 0 else 1
    finally:
        close_pool()


if __name__ == "__main__":
    sys.exit(main())
