# Eval methodology

Why the 17/17 number is the **right** number, what it actually proves,
and how to add a case.

---

## Stance: deterministic checks over LLM-as-judge

We deliberately do **not** use an LLM grader for eval scoring. Every
assertion is a Python predicate evaluated against the orchestrator's
tool calls, tool results, and final text. Reasons:

1. **Regressions are actionable.** A failed `p.verdict == 'yes'` tells
   you exactly which row in the verdict ladder broke. "LLM grader said
   the answer felt wrong" tells you nothing.
2. **No grader drift.** Anthropic and OpenAI both periodically retune
   their models; our eval shouldn't move when a third party's grader
   moves.
3. **Cost.** An LLM grader doubles the eval token spend per case.

The tradeoff is that **fluency, helpfulness, and tone** are not
auto-scored. Those are reviewed by reading the eval report
([eval_results.md](eval_results.md)), which prints every assistant reply
verbatim. The Loom walkthrough is the live demo of fluency.

---

## What's in the test set

[../backend/tests/eval/test_set.yaml](../backend/tests/eval/test_set.yaml).
17 cases across 7 categories.

| Category | Cases | What it proves |
|---|---|---|
| `install` | 2 (`install_lookup_only`, `install_full_walkthrough`) | Tool 1 + Tool 3, both example queries from the case brief. |
| `compatibility` | 5 (`compat_yes_positive`, `compat_cross_appliance`, `compat_inferred`, `compat_unknown_part`, `multi_turn_session`) | Every rung of the verdict ladder, plus the multi-turn session-memory case. |
| `troubleshoot` | 1 (`troubleshoot_ice_maker`) | Tool 4 natural-language symptom mapping + KG traversal. |
| `compound` | 1 (`compound_query`) | **The spec's "real test."** Single turn chains troubleshoot + check_compatibility + get_install_guide. |
| `edge` | 4 (`fuzzy_sku_candidates`, `case_normalization`, `nonexistent_part`, `safety_short_circuit`) | Fuzzy-no-silent-swap rule, case normalization, not-found, safety pattern match. |
| `out_of_scope` | 2 (`out_of_scope_washer`, `out_of_scope_general`) | Polite refusal with redirect, no tool called. |
| `adversarial` | 1 (`prompt_injection`) | "Ignore previous instructions ..." — scope must hold. |
| `validator` | 1 (`validator_on_inferred_compat`) | Inferred verdict triggers selective validator; assistant text must hedge. |

The compound case is the longest (47.4s wall clock) because it actually
runs 3 tools in sequence and lands a full install walkthrough. Most
other cases are 5-15s on the default provider.

---

## Check DSL

Each case has an `expectations:` block. The runner evaluates each
assertion against captured orchestrator output.

### Declarative shortcuts

| Key | Type | Semantics |
|---|---|---|
| `tools_called` | list[str] | These tools must have been called (order ignored). |
| `no_tool_called` | bool | No tools may have been called (used for refusal cases). |
| `tool_results[i]` | obj | The i-th tool result, with `tool: <name>` selector + `checks: [...]` list of dotted-path predicates. |
| `text_contains` | list[str] | Every substring must appear in the final assistant reply (case-insensitive). |
| `text_contains_any` | list[str] | At least one substring must appear. |
| `text_not_contains` | list[str] | None of the substrings may appear (case-insensitive). |
| `no_em_dashes` | bool | Final reply must contain zero U+2014. |

### Dotted-path predicates

Inside `checks:`, each string is a Python boolean expression with the
tool payload bound as `p`. The runner wraps `p` so attribute access
works on JSON-style dicts:

```yaml
checks:
  - "p.status == 'exact'"
  - "p.part.id == 'PS11752778'"
  - "p.metadata.supersedes == 'PS11750000'"
  - "p.verdict in ['yes', 'inferred']"
  - "len(p.guide.steps) >= 5"
  - "any(c['id'] == 'PS11752778' for c in p['candidates'])"
  - "'Phillips screwdriver' in p.guide.tools_required"
```

Both attribute (`p.part.id`) and item (`p['candidates']`) access work,
so the same syntax handles Pydantic outputs and free-form list payloads.

---

## Case shape (verbatim YAML)

```yaml
- id: compat_cross_appliance
  category: compatibility
  description: Fridge part vs dishwasher model. Must return no with explanation.
  turns:
    - "Is part PS11752778 compatible with my WDT780SAEM1?"
  expectations:
    tools_called: [check_compatibility]
    tool_results:
      - tool: check_compatibility
        checks:
          - "p.verdict == 'no'"
          - "p.confidence == 'high'"
          - "p.reason == 'appliance_type_mismatch'"
    text_contains: ["not compatible", "refrigerator", "dishwasher"]
    no_em_dashes: true
```

For multi-turn cases, `turns:` is a list. Expectations apply to the
**final** turn only (the runner persists session state across turns and
asserts at the end):

```yaml
- id: multi_turn_session
  ...
  turns:
    - "Tell me about PS11743427."
    - "Is it compatible with my WDT780SAEM1?"
  expectations:
    tools_called: [check_compatibility]   # applies to turn 2 only
```

---

## Running the eval

```bash
cd backend
python -m tests.eval.run_eval
# -> writes docs/eval_results.md
```

Filter to a single case while debugging:

```bash
python -m tests.eval.run_eval --filter compat_cross_appliance
```

Override the provider (default: per-role from `.env`):

```bash
python -m tests.eval.run_eval --provider groq
```

Output: a markdown report at [eval_results.md](eval_results.md) with the
pass/fail table, every assistant reply verbatim, and a failure
breakdown if any case failed.

---

## Adding a new case

1. Pick the simplest assertion that distinguishes pass from fail.
   Resist the temptation to assert the assistant text verbatim — that
   reduces to LLM-output regex matching and is fragile.
2. Edit
   [../backend/tests/eval/test_set.yaml](../backend/tests/eval/test_set.yaml)
   following the case-shape template above. Pick a category that
   already exists; only add a new category for a genuinely new failure
   mode (a new threat class, not a new tool).
3. Run `python -m tests.eval.run_eval --filter <your-case-id>` until it
   passes deterministically across 2-3 runs.
4. Run the full eval `python -m tests.eval.run_eval` to confirm no
   regression on the existing 17 cases.
5. Commit the eval YAML change with the assertion rationale in the
   commit message.

### When to require `text_contains` vs `tool_results[].checks`

Prefer `tool_results[].checks` for *structural* correctness (verdicts,
sources, fitment metadata). Use `text_contains` for *user-facing*
correctness (the assistant must mention "not compatible", "refrigerator",
"dishwasher" in the cross-appliance case so the reason is
*communicated*, not just stored).

The combination is what catches the case where the tool returned the
right verdict but the LLM phrased the reply badly.

---

## What this eval does NOT cover (yet)

- **Latency budgets**. The eval prints wall clock per case but does not
  assert. Production should add a budget per category (~10s for simple
  lookup, ~60s for compound) and fail the case if exceeded.
- **Cost budgets**. Same idea; the eval already streams `usage` events
  but does not aggregate per case.
- **Fluency / tone**. Reviewed by reading the report.
- **PII leak under load**. Phase 4 adds adversarial cases (paste an
  email into a question; assert the email never appears in any
  persisted message or log line).
- **Concurrency / race conditions**. The eval runs cases serially.
  Production load testing belongs in
  [operations.md](operations.md).
