"""Smoke test for the repository layer using the seed data.

Exercises the queries that Tools 1 & 2 will rely on. Run after `seed.py`.

Usage:
    cd backend && python -m scripts.smoke_repository
"""

from __future__ import annotations

import sys

from app.db import repository as repo
from app.db.pool import close_pool


def _ok(label: str, ok: bool, detail: str = "") -> None:
    status = "PASS" if ok else "FAIL"
    extra = f"  ({detail})" if detail else ""
    print(f"  [{status}] {label}{extra}")


def main() -> int:
    failures = 0

    try:
        print("Repository smoke test\n")

        # 1. Exact part lookup: PS11752778 (Whirlpool ice maker).
        part = repo.get_part("PS11752778")
        ok = part is not None and part.appliance_type == "refrigerator"
        _ok("get_part(PS11752778) -> Whirlpool fridge ice maker",
            ok, detail=f"name={part.name if part else None}")
        if not ok:
            failures += 1

        # 2. Exact model lookup: WDT780SAEM1 (Whirlpool dishwasher).
        model = repo.get_model("WDT780SAEM1")
        ok = model is not None and model.appliance_type == "dishwasher"
        _ok("get_model(WDT780SAEM1) -> Whirlpool dishwasher",
            ok, detail=f"brand={model.brand if model else None}, series={model.series if model else None}")
        if not ok:
            failures += 1

        # 3. Compatibility: PS11752778 (fridge part) vs WDT780SAEM1 (dishwasher model).
        # Should return None (no edge). Tool 2 will use appliance_type mismatch
        # to render a clear 'no' verdict rather than 'unknown'.
        edge = repo.check_compat_edge("PS11752778", "WDT780SAEM1")
        ok = edge is None
        _ok("check_compat_edge(fridge part, dishwasher model) -> None (no edge)",
            ok, detail=f"got={edge}")
        if not ok:
            failures += 1

        # 4. Compatibility (positive): PS11743427 (dishwasher water inlet valve) fits WDT780SAEM1.
        edge = repo.check_compat_edge("PS11743427", "WDT780SAEM1")
        ok = edge is not None and edge.part_id == "PS11743427"
        _ok("check_compat_edge(PS11743427, WDT780SAEM1) -> edge exists", ok)
        if not ok:
            failures += 1

        # 5. Compatibility (with supersedes metadata): PS11752778 fits KRFC704FSS with supersedes set.
        edge = repo.check_compat_edge("PS11752778", "KRFC704FSS")
        ok = edge is not None and edge.supersedes == "PS11750000"
        _ok("check_compat_edge carries supersedes metadata",
            ok, detail=f"supersedes={edge.supersedes if edge else None}")
        if not ok:
            failures += 1

        # 6. Fuzzy SKU search: PS11752779 (one digit off from PS11752778) -> candidates.
        # Hard rule: caller must require user confirmation, never silent-swap.
        candidates = repo.fuzzy_search_parts("PS11752779", limit=3)
        ok = any(c.id == "PS11752778" for c in candidates)
        _ok("fuzzy_search_parts(PS11752779) returns PS11752778 as candidate",
            ok, detail=f"got={[c.id for c in candidates]}")
        if not ok:
            failures += 1

        # 7. Install guide lookup by part.
        guide = repo.get_install_guide_by_part("PS11752778")
        ok = guide is not None and "ice maker" in guide.steps.lower()
        _ok("get_install_guide_by_part(PS11752778) -> guide present", ok,
            detail=f"difficulty={guide.difficulty if guide else None}, "
                   f"hint='{guide.series_fitment_hint if guide else None}'")
        if not ok:
            failures += 1

        # 8. KG-as-SQL: parts that fix the ice-maker symptom for WRF555SDFZ (Whirlpool fridge).
        # Should rank PS11752778 first (likelihood 0.60, rank 1) and mark it as fitting.
        rows = repo.parts_fixing_symptom("SY_ICE_MAKER_NOT_WORKING", model_id="WRF555SDFZ")
        top = rows[0] if rows else None
        ok = top is not None and top["part_id"] == "PS11752778" and top["fits_model"] is True
        _ok("parts_fixing_symptom(ice maker, WRF555SDFZ) ranks PS11752778 first & fits",
            ok, detail=f"top={top}")
        if not ok:
            failures += 1

        # 9. Same symptom, dishwasher model. PS11752778 fixes ice maker BUT does not fit
        # WDT780SAEM1 (different appliance type). fits_model should be False.
        rows = repo.parts_fixing_symptom("SY_ICE_MAKER_NOT_WORKING", model_id="WDT780SAEM1")
        ps11752778_row = next((r for r in rows if r["part_id"] == "PS11752778"), None)
        ok = ps11752778_row is not None and ps11752778_row["fits_model"] is False
        _ok("parts_fixing_symptom marks fridge part as NOT fitting a dishwasher",
            ok, detail=f"got={ps11752778_row}")
        if not ok:
            failures += 1

        # 10. Sanity: positive dishwasher compat returns parts that fit.
        rows = repo.list_compat_models_for_part("PS11743427")
        ok = len(rows) >= 5 and any(r.model_id == "WDT780SAEM1" for r in rows)
        _ok("list_compat_models_for_part(PS11743427) returns >= 5 models incl. WDT780SAEM1",
            ok, detail=f"count={len(rows)}, models={[r.model_id for r in rows]}")
        if not ok:
            failures += 1

        print(f"\n{'-' * 60}")
        print(f"{'All tests passed.' if failures == 0 else f'{failures} test(s) FAILED.'}")
        return 0 if failures == 0 else 1
    finally:
        close_pool()


if __name__ == "__main__":
    sys.exit(main())
