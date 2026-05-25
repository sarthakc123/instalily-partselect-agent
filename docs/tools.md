# Tool contracts

All five tools are built and verified end-to-end (17/17 eval, see
[eval_results.md](eval_results.md)). Each tool is a typed Python function
behind a JSON Schema spec; the orchestrator never sees raw Python.

Registry: [../backend/app/tools/registry.py](../backend/app/tools/registry.py).
Base types: [../backend/app/tools/base.py](../backend/app/tools/base.py).

Every tool output inherits from `ToolOutput`, a Pydantic model with a
`tool: Literal[...]` discriminator. The frontend's `tool-result.tsx`
dispatches on `tool` to render the matching rich card.

---

## 1. `lookup_part`

Find a part by PartSelect part number. Exact, then fuzzy, then not found.

**Source:** [../backend/app/tools/lookup_part.py](../backend/app/tools/lookup_part.py)

### Input

```json
{
  "part_number": "PS11752778"
}
```

The runner normalizes case (`ps11752778` -> `PS11752778`) and adds a
missing `PS` prefix if the user typed bare digits.

### Output

```json
{
  "tool": "lookup_part",
  "status": "exact" | "fuzzy_candidates" | "not_found",
  "part": <PartCard | null>,
  "candidates": [<PartCard>...],
  "confidence": 0.0 - 1.0
}
```

### Hard rule

On a fuzzy hit, `part` is `null` and `candidates` is the list. The caller
**must** confirm with the user before treating any candidate as canonical.
This is enforced by the repo returning `list[Part]` (never a single Part)
for fuzzy queries, the eval case `fuzzy_sku_candidates`, and the
orchestrator system prompt.

### Example: exact hit

```bash
curl -N -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"Tell me about PS11752778."}'
```

Tool payload (excerpt):

```json
{
  "status": "exact",
  "part": {
    "id": "PS11752778",
    "name": "Refrigerator Ice Maker Assembly",
    "manufacturer": "Whirlpool",
    "appliance_type": "refrigerator",
    "part_type": "ice_maker",
    "price_cents": 17999,
    "in_stock": true
  },
  "confidence": 1.0
}
```

### Example: fuzzy candidates

User types `PS11752779` (one digit off):

```json
{
  "status": "fuzzy_candidates",
  "part": null,
  "candidates": [{"id": "PS11752778", ...}, {"id": "PS11756879", ...}, ...],
  "confidence": 0.7
}
```

The frontend renders a `FuzzyConfirmCard`; clicking a candidate sends a
confirmation message ("I meant PS11752778, please continue with that one.").

---

## 2. `check_compatibility`

Verdict on whether a part fits a model. Structured edge lookup, never
LLM reasoning over prose.

**Source:** [../backend/app/tools/check_compatibility.py](../backend/app/tools/check_compatibility.py)

### Input

```json
{
  "part_number": "PS11743427",
  "model_number": "WDT780SAEM1"
}
```

### Output

```json
{
  "tool": "check_compatibility",
  "verdict": "yes" | "no" | "unknown" | "inferred",
  "confidence": "high" | "medium" | "low",
  "part_id": "PS11743427",
  "model_id": "WDT780SAEM1",
  "metadata": {
    "sub_assembly_only": false,
    "requires_adapter": false,
    "supersedes": null | "PS11750000"
  },
  "source": "fitment_table" | "install_guide_inference" | "appliance_type" | null,
  "reason": "appliance_type_mismatch" | "no_edge_found" | "entity_not_found" | null,
  "explanation": "human-readable sentence the LLM uses to phrase the reply"
}
```

### Five-rung verdict ladder

The runner walks these rungs in order; first match wins.

| # | Condition | Verdict | Confidence | Source / reason |
|---|---|---|---|---|
| 1 | Either entity not in catalog | `unknown` | low | `reason=entity_not_found` |
| 2 | KG edge exists | `yes` | high | `source=fitment_table` (carries metadata) |
| 3 | No edge AND appliance types differ | `no` | high | `source=appliance_type`, `reason=appliance_type_mismatch` |
| 4 | No edge AND install guide series-fitment-hint matches model series | `inferred` | medium | `source=install_guide_inference` (triggers validator) |
| 5 | No edge otherwise | `no` | medium | `reason=no_edge_found` |

### Example: cross-appliance trick

PS11752778 (refrigerator part) vs WDT780SAEM1 (dishwasher model) hits
rung 3:

```json
{
  "verdict": "no",
  "confidence": "high",
  "source": "appliance_type",
  "reason": "appliance_type_mismatch",
  "explanation": "Refrigerator Ice Maker Assembly is a refrigerator part, but WDT780SAEM1 is a dishwasher. They are not compatible."
}
```

### Example: inferred verdict (Phase 3 validator gate)

PS11743427 vs WDT789SAKZ (no direct edge, but the install guide says
"fits all WDT78x" and WDT789SAKZ is series `WDT78x`):

```json
{
  "verdict": "inferred",
  "confidence": "medium",
  "source": "install_guide_inference",
  "explanation": "There is no explicit fitment entry, but the install guide for PS11743427 states it 'fits all WDT78x' and WDT789SAKZ is in series WDT78x. Treat this as a likely but unverified fit."
}
```

The orchestrator hedges the reply ("likely fits", "not 100% confirmed"),
and the validator runs to grade faithfulness.

---

## 3. `get_install_guide`

Step-by-step install for a part. Deterministic filter by `part_id`, no
RAG (architecture rule: `part_id` IS the filter key for install content).

**Source:** [../backend/app/tools/get_install_guide.py](../backend/app/tools/get_install_guide.py)

### Input

```json
{
  "part_number": "PS11752778"
}
```

### Output

```json
{
  "tool": "get_install_guide",
  "status": "ok" | "part_not_found" | "no_guide",
  "part": <PartCard | null>,
  "guide": {
    "id": "...",
    "part_id": "PS11752778",
    "difficulty": "Moderate",
    "estimated_minutes": 45,
    "tools_required": ["Phillips screwdriver", "1/4-inch nut driver"],
    "safety_warnings": "Unplug the refrigerator before beginning...",
    "steps": ["Unplug the refrigerator from the wall outlet.", ...],
    "video_url": "https://www.partselect.com/Installation/...",
    "series_fitment_hint": "fits all WRF55x"
  }
}
```

### Validator stance

This tool **skips** the validator. Install steps are deterministic by
`part_id`; there is no LLM-judgment surface to grade. If the part_id is
right, the steps are right.

---

## 4. `troubleshoot`

Maps natural-language symptom -> canonical `SY_*` -> ranked candidate
parts. Carries the **safety short-circuit**: gas, electrical, water
damage, injury keywords return `status=escalate_safety` without calling
the LLM mapper or the KG.

**Source:** [../backend/app/tools/troubleshoot.py](../backend/app/tools/troubleshoot.py)

### Input

```json
{
  "symptom": "ice maker stopped working",
  "brand": "Whirlpool",
  "appliance_type": "refrigerator",
  "model_number": "WRF555SDFZ"
}
```

Only `symptom` is required. The other fields scope the symptom mapping
(by appliance type) and enable per-candidate fitment annotation.

### Output

```json
{
  "tool": "troubleshoot",
  "status": "ok" | "symptom_unknown" | "escalate_safety" | "ambiguous",
  "user_symptom_text": "ice maker stopped working",
  "matched_symptom": {
    "symptom_id": "SY_ICE_MAKER_NOT_WORKING",
    "canonical_label": "ice maker not working",
    "confidence": 0.92
  },
  "candidate_causes": [
    {"part_id": "PS11752778", "part_name": "Refrigerator Ice Maker Assembly", "likelihood": 0.60, "common_cause_rank": 1, "fits_model": true, ...},
    {"part_id": "PS11757654", "part_name": "Water Inlet Valve", "likelihood": 0.20, "common_cause_rank": 2, "fits_model": true, ...},
    ...
  ],
  "recommended_fix": <CandidateCause>,
  "confidence": 0.71,
  "sources": [{"table": "symptom_fixes", "row": {...}}, ...],
  "safety_match": null,
  "explanation": "The symptom maps to 'ice maker not working'. Most common cause: ..."
}
```

### Auditable provenance

Every candidate is accompanied by a `sources[i]` row pointing at the exact
`symptom_fixes` row that drove the ranking. The validator (Phase 3) reads
these.

### Safety short-circuit (hard rule)

Pattern match against:

- `\bgas (smell|leak|odor)\b` / `\bsmell(ing)? gas\b`
- `\bsmoke|smoking|burning smell\b`
- `\b(fire|flames?|sparking|electrical (?:shock|burn))\b`
- `\bflood(ing|ed)?\b|\bactive water (?:damage|leak)\b`
- `\bshock(ed|ing)?\b`
- `\b(child|pet|baby) (stuck|trapped|hurt|injured)\b`
- `\b(injur|hurt|bleeding)\b`

Match -> `status=escalate_safety`, `safety_match=<matched-phrase>`,
no LLM call, no KG traversal. Orchestrator system prompt enforces "no
repair walkthrough, even partial".

### Validator stance

Runs on every `troubleshoot` output that surfaces a recommended fix. The
validator reads `sources` to verify the recommendation is supported.

---

## 5. `find_parts_by_symptom`

Thin wrapper over the KG traversal. Used when the orchestrator already
has a canonical `symptom_id` in hand from a prior turn (so the LLM
mapping in Tool 4 is skipped).

**Source:** [../backend/app/tools/find_parts_by_symptom.py](../backend/app/tools/find_parts_by_symptom.py)

### Input

```json
{
  "symptom_id": "SY_ICE_MAKER_NOT_WORKING",
  "model_id": "WRF555SDFZ"
}
```

`symptom_id` is required. `model_id` is optional; when supplied, each
candidate's `fits_model` is annotated true/false via the `LEFT JOIN
compatibility` in the underlying SQL (see [data_model.md § Multi-hop
query](data_model.md)).

### Output

```json
{
  "tool": "find_parts_by_symptom",
  "status": "ok" | "symptom_unknown",
  "symptom_id": "SY_ICE_MAKER_NOT_WORKING",
  "model_id": "WRF555SDFZ",
  "candidates": [<FixCandidatePayload>...]
}
```

---

## Tool selection guidance (in the system prompt)

The orchestrator system prompt at
[../backend/app/agents/prompts/orchestrator.md](../backend/app/agents/prompts/orchestrator.md)
tells the LLM:

- Use `lookup_part` whenever the user gives a part number.
- Use `check_compatibility` whenever a `(part, model)` pair is in scope
  (including pulled from session memory across turns).
- Use `get_install_guide` only when the user explicitly asks how to
  install or replace a specific part.
- Use `troubleshoot` when the user describes a problem in natural
  language without a part number.
- Use `find_parts_by_symptom` only when you already have a canonical
  symptom id (rare; mostly internal to compound queries).

Tool selection is logged in every SSE `tool_call` event so the reviewer
can audit the path the orchestrator took.

---

## Adding a new tool

1. Create `backend/app/tools/<your_tool>.py` defining:
   - A Pydantic output model inheriting `ToolOutput` with `tool:
     Literal["your_tool"] = "your_tool"`.
   - An async `run_<your_tool>(ctx, args)` runner.
   - A `<YOUR_TOOL>_SPEC: ToolSpec` with name + description + JSON Schema input.
2. Register in [registry.py](../backend/app/tools/registry.py).
3. Add a renderer in
   [`frontend/components/messages/tool-result.tsx`](../frontend/components/messages/tool-result.tsx)
   (the discriminator value is `tool`).
4. Add at least one eval case in
   [`backend/tests/eval/test_set.yaml`](../backend/tests/eval/test_set.yaml).
5. Run `python -m scripts.smoke_tools` and `python -m tests.eval.run_eval`
   to confirm the tool works in isolation and end-to-end.

The orchestrator system prompt picks up new tools automatically via
`all_tool_specs()`, but you may want to add explicit guidance for when to
prefer your tool over an existing one.
