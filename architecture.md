# Architecture — PartSelect Chat Agent

> If you only read one document, read this one. It explains **what the system
> is, how a query flows through it, and why each piece exists**. For the
> running build log (what is done vs in progress, eval numbers, deviations),
> see [docs/build_log.md](docs/build_log.md). For the full evaluation matrices and stack
> reasoning, see the plan at
> `~/.claude/plans/case-study-instructions-congratulations-hashed-tower.md`.

---

## 1. What this is

A production-grade customer-support chat agent for an appliance parts e-commerce
site (PartSelect-style), scoped to **refrigerator and dishwasher** parts. It
answers four classes of user questions:

| # | Pattern | Example | Resolved by |
|---|---|---|---|
| 1 | Install lookup | "How can I install part number PS11752778?" | Tool 3 `get_install_guide` |
| 2 | Compatibility | "Is this part compatible with my WDT780SAEM1?" | Tool 2 `check_compatibility` |
| 3 | Troubleshoot | "My Whirlpool fridge ice maker is not working" | Tools 4 + 5 |
| 4 | Compound | "Ice maker on my Whirlpool WRF555SDFZ is broken, what part do I need and how do I install it?" | Tools 4 → 5 → 2 → 3 chained |

If the **compound query** works, the three examples fall out for free. That is
the real test, and the system is designed around it from day one.

---

## 2. High-level architecture

```
                           ┌───────────────────────────────────┐
   User browser            │  Next.js 14 (App Router, TS)      │
   (chat UI)   ────SSE────>│  Vercel AI SDK useChat            │
                           │  custom transport → FastAPI       │
                           │  Rich components:                 │
                           │    ProductCard, CompatBadge,      │
                           │    InstallChecklist, ToolStep,    │
                           │    EscalationForm                 │
                           └───────────────┬───────────────────┘
                                           │
                                           ▼
                           ┌───────────────────────────────────┐
                           │ FastAPI (Python 3.11)             │
                           │   /chat   (SSE)                   │
                           │   /ticket (PII bypass)            │
                           │   /health                         │
                           └───────────────┬───────────────────┘
                                           │
            ┌──────────────────────────────┴─────────────────────────┐
            │ PII Tokenizer (Presidio)  — runs BEFORE any LLM        │
            └──────────────────────────────┬─────────────────────────┘
                                           ▼
              ┌────────────────────────────────────────────────────┐
              │  LangGraph Orchestrator (Claude Sonnet 4.6)        │
              │   • Entity extraction (part_no, model_no, symptom) │
              │   • Intent classification + safety short-circuit   │
              │   • Tool dispatch (single or chained)              │
              │   • Stateful: session carries model, brand, last   │
              │     part across turns (LangGraph checkpointer)     │
              └─────────────────────────┬──────────────────────────┘
                                        │
                       ┌────────────────┼────────────────────────┐
                       ▼                ▼                        ▼
            ┌──────────────────┐ ┌──────────────────┐ ┌─────────────────────┐
            │ Tool 1           │ │ Tool 2           │ │ Tool 3              │
            │ lookup_part      │ │ check_compatib.  │ │ get_install_guide   │
            │ exact + fuzzy    │ │ STRUCTURED EDGE  │ │ filter by part_id   │
            │ (user confirms)  │ │ lookup, not RAG  │ │ (deterministic)     │
            └──────────────────┘ └──────────────────┘ └─────────────────────┘
                       ┌─────────────────────────┐  ┌─────────────────────────┐
                       │ Tool 4 troubleshoot     │  │ Tool 5 find_parts_by_   │
                       │ hybrid RAG + KG aug.    │  │ symptom                 │
                       │ BM25 + dense + RRF +    │  │ KG traversal:           │
                       │ rerank, metadata filter │  │ (symptom)→(part)→(model)│
                       └─────────────────────────┘  └─────────────────────────┘
                                        │
                                        ▼
              ┌────────────────────────────────────────────────────┐
              │  Data Layer                                        │
              │  • Postgres (Supabase) — structured, raw SQL       │
              │      parts, models, compatibility, symptoms,       │
              │      symptom_fixes, install_guides, repair_stories │
              │  • NetworkX KG — mirror of structured edges,       │
              │      enables multi-hop traversal in Python         │
              │  • Chroma — install guides, repair stories,        │
              │      hybrid retrieval (Phase 2)                    │
              └────────────────────────────────────────────────────┘
                                        │
                                        ▼  (only on high-risk paths)
              ┌────────────────────────────────────────────────────┐
              │  Validator Agent (GPT-4o)   — different LLM family │
              │  • Faithfulness + relevance scoring                │
              │  • Triggers: inferred compat, troubleshoot         │
              │    recommendations, low confidence                 │
              │  • Verdict: pass | retry | escalate                │
              └────────────────────────────────────────────────────┘
                                        │
                       ┌────────────────┴───────────────────┐
                       ▼                                    ▼
              ┌────────────────────┐         ┌──────────────────────────────┐
              │ Response to user   │         │ Escalation: ticket workflow  │
              │ (with rich cards)  │         │ (PII bypasses LLM entirely)  │
              └────────────────────┘         └──────────────────────────────┘
```

---

## 3. Agent topology

### One Orchestrator, five Tools, one selective Validator

This is the single most important design decision and is taken directly from
the build spec. The mental model:

- **Orchestrator** (Claude Sonnet 4.6): a tool-using LLM. Reads the user
  message, the session state, and the tool catalog. Decides which tools to
  call, in what order. Holds the conversation thread.
- **Tools**: typed Python functions with structured JSON inputs and outputs.
  No LLM inside a tool. Each tool resolves one retrieval pattern.
- **Validator** (GPT-4o, deliberately a different LLM family): receives the
  orchestrator's draft answer plus the retrieved evidence. Returns
  `pass | retry | escalate` with faithfulness + relevance scores. Runs on
  high-risk paths only (compat `inferred`, troubleshoot recommendations, low
  confidence). Never silently passes a failure.

**Why a different LLM family for the validator?** Diversity catches errors
one family makes that another does not. If Claude is overconfident on a
hallucinated compat verdict, GPT-4o reading the same evidence is far less
likely to be overconfident in the same direction.

**Why one orchestrator instead of router → specialists?** Because the
specialists would have to share state (the same `model_number`, the same
`last_part_referenced`) and would re-extract entities each hop. A single
orchestrator with a clean tool catalog gets the same modularity without the
duplication.

### The five tools, in detail

| Tool | Input | Output | Source | Validator? |
|---|---|---|---|---|
| 1. `lookup_part` | `part_number` | `{status: exact|fuzzy_candidates|not_found, part?, candidates?, confidence}` | Postgres exact + pg_trgm fuzzy | No (source is the answer) |
| 2. `check_compatibility` | `part_number, model_number` | `{verdict: yes|no|unknown|inferred, confidence, metadata, source}` | Postgres `compatibility` edge | Yes, **only** if `inferred` |
| 3. `get_install_guide` | `part_number` | guide steps, tools, difficulty, warnings, video | Postgres `install_guides` filtered by part_id | No (deterministic) |
| 4. `troubleshoot` | `symptom, brand?, appliance_type?, model_number?` | `{candidate_causes, recommended_fix, confidence, sources}` | Hybrid: BM25 + dense over repair stories, RRF, cross-encoder rerank, KG augmentation | Yes |
| 5. `find_parts_by_symptom` | `symptom, model_number?` | ranked candidate parts | KG traversal: `(symptom) -[FIXES]-> (part) -[FITS]-> (model)` mapped to a single SQL query in [backend/app/db/repository.py](backend/app/db/repository.py) | Yes |

**Compatibility is a structured edge lookup, NEVER LLM reasoning over prose.**
That is a hard rule from the spec. Prose inference (parsing a phrase like
"fits all WDT78x" out of an install guide) is a marked, lower-confidence
fallback that always triggers the validator. The `install_guides.series_fitment_hint`
column on a few seeded guides exists specifically to exercise this path.

---

## 4. Data layer (what is built, layer A+B)

### Postgres tables (Supabase)

The schema in [backend/app/db/schema.sql](backend/app/db/schema.sql) defines
10 tables. The ones a reviewer should understand first:

```
parts
├── id (PS-prefixed SKU, primary key)
├── name, manufacturer
├── appliance_type      ← used to detect cross-appliance mismatches
├── part_type
├── price_cents, in_stock
└── description
                                                              ┌──────────────┐
                                                              │ compatibility│
models                                                        │ part_id      │ ─┐
├── id                                                        │ model_id     │ ─┤
├── brand, appliance_type                                     │ sub_assembly │  │
├── series              ← "WDT78x"; powers series fitment     │ requires_    │  │  the workhorse
└── year                  inference fallback                  │   adapter    │  │  EDGE TABLE
                                                              │ supersedes   │ ─┘
symptoms                                                      └──────────────┘
├── id (SY_*)
├── canonical_label     ← normalizes "ice maker broken",
├── description           "no ice", "ice maker dead" → one row
└── appliance_type

                                  ┌──────────────────────────────┐
                                  │ symptom_fixes                │
                                  │ symptom_id ─→ part_id        │
                                  │ likelihood (0..1)            │  ← KG edge
                                  │ common_cause_rank            │     FIXES
                                  └──────────────────────────────┘

install_guides
├── part_id (one per part, unique)
├── difficulty, estimated_minutes
├── tools_required, safety_warnings
├── steps (newline-separated for v1)
├── video_url
└── series_fitment_hint   ← prose fitment marker that powers
                            the "inferred" compat fallback
```

Plus: `repair_stories` (Phase 2 hybrid RAG corpus), `conversations` +
`messages` (session memory), `tickets` (escalation; PII never visible to the
LLM, stored encrypted via `pgcrypto` later).

### Why symptoms exist (FAQ)

"Symptom" is the canonical taxonomy that bridges messy natural-language
problems to structured part recommendations. When a user says "my ice maker
stopped working" / "no ice coming out" / "ice maker dead", all three map to
`SY_ICE_MAKER_NOT_WORKING`. That single ID then has:

- A small set of `symptom_fixes` edges to candidate parts.
- Each edge carries `common_cause_rank` (most common cause = 1) and
  `likelihood` (0..1), so the agent can honestly present the top 2–3
  candidates rather than guessing one.

This is **why we don't just RAG over repair articles**:
- The agent's recommendation is auditable (we can show *which row* drove it).
- Multiple causes per symptom are first-class, not buried in prose.
- Compound queries are short SQL joins, not multi-hop LLM reasoning.

### Knowledge graph (Layer C, coming)

The KG is a NetworkX in-memory graph built from the same Postgres tables.
Nodes: `Part`, `Model`, `Brand`, `ApplianceType`, `Symptom`, `InstallGuide`.
Edges: `FITS` (with metadata), `MADE_BY`, `BELONGS_TO`, `FIXES` (with
likelihood + rank), `OCCURS_IN`, `INSTALLED_VIA`.

The KG and Postgres are kept in sync from a single source (the seed YAML for
the POC; the scraper for Phase 2). The KG enables fast multi-hop traversals
in Python that would be awkward in SQL (e.g., "given this symptom and this
brand, return parts that fix it across all models of this brand"). Postgres
remains the source of truth for compatibility verdicts.

Production target: Neo4j with Cypher. The `KnowledgeGraph` protocol behind
the NetworkX impl makes that swap a single-file change.

### Repository layer

[backend/app/db/repository.py](backend/app/db/repository.py) holds one
function per query. No ORM. Notable picks:

- `fuzzy_search_parts` uses pg_trgm `similarity()` and returns *candidates*,
  never a single rewritten answer. Caller (Tool 1) must require user
  confirmation. Enforced at the type level by returning `list[Part]`, not
  `Part`.
- `parts_fixing_symptom(symptom_id, model_id?)` is the KG-as-SQL multi-hop
  query: a `LEFT JOIN compatibility ON c.part_id = p.id AND c.model_id = ?`
  surfaces a `fits_model` boolean per candidate part, sorted so fitting parts
  come first. This single query powers both Tool 5 and most of the compound
  query path.

---

## 5. Retrieval pipeline (Phase 2, planned)

Tool 4 `troubleshoot` is the hybrid path:

```
   query (symptom, brand?, appliance_type?, model_no?)
            │
            ├──► query rewriting (if symptom is sparse)
            │
            ├──► metadata pre-filter (brand, appliance_type, model_series)
            │       ↓
            ├──► BM25 top-50  (rank_bm25)         ┐
            │                                     ├─► Reciprocal Rank Fusion
            ├──► dense top-50 (Chroma + MiniLM)   ┘
            │       ↓
            ├──► cross-encoder rerank → top 5–8
            │
            ├──► KG augmentation: for each cause, traverse
            │     (cause) -[FIXES]-> (part), surface parts
            │
            └──► Validator (selective trigger fires)
```

Every dense query uses at least one metadata filter, or quality collapses.
Production swaps Chroma for pgvector; the `VectorStore` protocol abstracts
the call site.

---

## 6. PII isolation pattern

**Hard rule: PII never enters the LLM context window.** Implementation:

```
   user message ─► Presidio analyzer ─► PII detected?
                                        │
                                        ├── no  → orchestrator (clean text)
                                        │
                                        └── yes → replace with tokens
                                                  [EMAIL_001], [PHONE_001]
                                                  per-session token map
                                                  held in API layer
                                                  (NOT in LLM context)
                                                  │
                                                  ▼
                                          orchestrator (tokens)
                                          │
                                          ├── normal flow
                                          │
                                          └── escalation:
                                               tool call: escalate_to_ticket(
                                                 issue_summary,
                                                 model_number,
                                                 symptom_tags,
                                                 conversation_id
                                               )       ← no PII fields
                                               │
                                               ▼
                                          frontend renders EscalationForm
                                          │
                                          ▼
                                          form POSTs name/email/phone
                                          DIRECTLY to /ticket
                                          (bypasses LLM)
                                          │
                                          ▼
                                          /ticket returns ticket_id
                                          (the only thing the LLM sees)
```

Logs route through the same redactor. The most common leak path is logs,
not LLM context.

---

## 7. Frontend

Built fresh in Next.js 14 (App Router, TypeScript). **Not** based on the
Instalily CRA template.

- **Chat surface**: Vercel AI SDK `useChat` with a custom transport pointing
  at FastAPI SSE. Agent logic stays in the Python backend; the Next route is
  a thin pass-through.
- **Rich in-chat components** picked per tool output:
  - `ProductCard` for `lookup_part` hits.
  - `CompatBadge` (✅ / ❌ / ⚠️ inferred) for `check_compatibility`.
  - `InstallChecklist` for `get_install_guide`.
  - `RepairStoryCard` for `troubleshoot` evidence.
  - `ToolStep` collapsible (so users can inspect what the agent searched).
  - `EscalationForm` (POSTs directly to `/ticket`, bypassing the LLM).
- **ProviderSwitcher** in the header for the demo: live-flip orchestrator
  between Claude, OpenAI, Groq via an `X-LLM-Provider` request header.
- **Styling**: Tailwind + shadcn/ui + framer-motion. PartSelect-style theme
  (deep blue + orange accents).

---

## 8. Per-query flows

### Flow 1 — install lookup
```
"How can I install PS11752778?"
   ↓
orchestrator extracts part_no, intent=install
   ↓
lookup_part(PS11752778) → status=exact, part metadata
   ↓
get_install_guide(PS11752778) → steps, tools, warnings, video
   ↓
compose answer (validator skipped, deterministic source)
   ↓
render InstallChecklist + ProductCard
```

### Flow 2 — compatibility (multi-turn)
```
turn 1: "Tell me about PS11743427"
   ↓ session state: last_part = PS11743427

turn 2: "Is it compatible with my WDT780SAEM1?"
   ↓
orchestrator picks part from session, extracts model
   ↓
check_compatibility(PS11743427, WDT780SAEM1)
   ↓
   verdict = yes (edge exists)
   metadata = {requires_adapter: false, supersedes: null}
   ↓
render CompatBadge ✅ + show metadata
```

### Flow 3 — troubleshoot
```
"The ice maker on my Whirlpool fridge is not working"
   ↓
orchestrator: brand=Whirlpool, appliance_type=refrigerator,
              symptom="ice maker not working"
   ↓
safety check (not on critical list) → proceed
   ↓
ask for model? yes if not in session ("which Whirlpool fridge?")
   ↓ user replies WRF555SDFZ
   ↓
troubleshoot(symptom, brand, appliance_type, model_number)
   → top causes + recommended fix
find_parts_by_symptom(symptom, model)
   → ranked parts with fits_model
   ↓
validator runs (faithfulness + relevance scored)
   ↓
   pass → render top 2-3 RepairStoryCards + recommended ProductCard
   fail → escalate
```

### Flow 4 — compound (the real test)
```
"Ice maker on my Whirlpool WRF555SDFZ is broken, what part do I need
 and how do I install it?"
   ↓
single orchestrator turn, chained tools:
   ↓
troubleshoot(symptom, brand, appliance_type, model_number)
   ↓
find_parts_by_symptom(symptom, WRF555SDFZ)
   → top candidate: PS11752778 (rank 1, likelihood 0.60, fits)
   ↓
check_compatibility(PS11752778, WRF555SDFZ)
   → verdict=yes, confidence=high
   ↓
get_install_guide(PS11752778)
   → steps, tools, warnings
   ↓
validator runs on the recommendation
   ↓
compose full answer:
  - identified cause + 2 alternates
  - recommended part PS11752778
  - compat confirmed for your model
  - install checklist
```

### Edge case — the case study trick
```
"Is PS11752778 compatible with my WDT780SAEM1?"
   ↓
check_compatibility(PS11752778, WDT780SAEM1)
   ↓
   no edge found, BUT also check appliance types:
   PS11752778.appliance_type = refrigerator
   WDT780SAEM1.appliance_type = dishwasher
   ↓
   verdict = no (with explicit reason: "this is a refrigerator
   part, your model is a dishwasher")
   ↓
render CompatBadge ❌ with the appliance-type explanation
```

---

## 9. Hard rules (non-negotiable)

These are enforced throughout the codebase, including in this document
(no em dashes anywhere).

1. **No em dashes** in any user-facing text. Use commas, periods, or rewrite.
2. **PII never enters the LLM context window** outside the tokenized fallback.
3. **Compatibility comes from structured edges.** Prose inference is a
   marked, lower-confidence fallback that always triggers the validator.
4. **Safety-critical symptoms** (gas, electrical, water damage, human/pet
   safety) short-circuit to escalation. No self-resolution attempt.
5. **Fuzzy SKU matches require explicit user confirmation.** Never
   silent-swap. Enforced at the repository return type.
6. **Validator never silently passes a failure.** Every fail has a defined
   downstream action (retry once or escalate).

---

## 10. What is built today

| Layer | Status | Path / artifact |
|---|---|---|
| Postgres schema (10 tables) | done | [backend/app/db/schema.sql](backend/app/db/schema.sql) |
| psycopg3 connection pool + idempotent schema apply | done | [backend/app/db/pool.py](backend/app/db/pool.py) |
| Raw-SQL repository (no ORM) | done | [backend/app/db/repository.py](backend/app/db/repository.py) |
| Pydantic entity models | done | [backend/app/schemas/entities.py](backend/app/schemas/entities.py) |
| Synthetic seed dataset (YAML) | done | [backend/data/seed/seed.yaml](backend/data/seed/seed.yaml) |
| Seed loader script | done | `python -m scripts.seed` |
| Repository smoke test (10 assertions, all pass) | done | `python -m scripts.smoke_repository` |
| Init script (apply schema, report counts) | done | `python -m scripts.init_db` |
| LLM provider gateway (Anthropic + OpenAI + Groq, normalized event union) | done (Groq verified live; Anthropic + OpenAI structure-only) | [backend/app/llm/](backend/app/llm/) |
| NetworkX KG built from Postgres tables (100 nodes, 176 edges, 11/11 smoke) | done | [backend/app/kg/](backend/app/kg/) |
| Tool 1 `lookup_part` (exact + fuzzy + normalize, never silent-swap) | done | [backend/app/tools/lookup_part.py](backend/app/tools/lookup_part.py) |
| Tool 2 `check_compatibility` (5-rung verdict ladder, 13/13 smoke) | done | [backend/app/tools/check_compatibility.py](backend/app/tools/check_compatibility.py) |
| Tools 3–5 + retrieval pipeline | pending | Phase 2 |
| LangGraph orchestrator + system prompt (3/3 end-to-end via Groq, multi-turn session memory works) | done | [backend/app/agents/](backend/app/agents/) |
| FastAPI `/chat` SSE endpoint + persistent context (11/11 API smoke) | done | [backend/app/api/](backend/app/api/) + [backend/app/conversation/](backend/app/conversation/) |
| Validator (selective trigger) | pending | Phase 3 |
| Next.js scaffold (Next 16 + React 19 + Tailwind 4, PartSelect theme, header, ProviderSwitcher, health proxy) | done | [frontend/](frontend/) |
| ChatPanel + custom FastAPI SSE transport (resumable conversations, live provider flip, streaming) | done | [frontend/components/chat-panel.tsx](frontend/components/chat-panel.tsx), [frontend/hooks/use-chat.ts](frontend/hooks/use-chat.ts), [frontend/lib/](frontend/lib/) |
| Rich in-chat components (ProductCard, CompatBadge with cross-appliance visual, FuzzyConfirmCard with click-to-confirm) | done | [frontend/components/messages/](frontend/components/messages/) |
| InstallChecklist + repair-story card | pending (Phase 2: Tools 3/4 land first) | |
| PII isolation (Presidio + ticket bypass) | pending | Phase 4 |
| Eval set + POC numbers (12 cases, 12/12 PASS via Groq) | done | [backend/tests/eval/test_set.yaml](backend/tests/eval/test_set.yaml), [docs/eval_results.md](docs/eval_results.md) |
| Scraper (deep fridge + dishwasher, light adjacent) | pending | Phase 2 |
| Deploy (Vercel + Fly.io + Supabase) | pending | Phase 5 |

---

## 11. File map

```
InstalillyCaseStudy/
  architecture.md            ← you are here
  docs/build_log.md          ← running build log
  .gitignore

  backend/
    pyproject.toml           Python deps (psycopg3, fastapi, langgraph, ...)
    .env / .env.example      DATABASE_URL + LLM keys (gitignored)
    app/
      config.py              pydantic-settings, role-based LLM defaults
      db/
        schema.sql           Postgres DDL (idempotent)
        pool.py              psycopg3 ConnectionPool + apply_schema()
        repository.py        raw-SQL repo; one function per query
      schemas/
        entities.py          Pydantic entities mirroring the SQL schema
      api/        (pending)  FastAPI routes (/chat, /ticket, /health)
      agents/     (pending)  LangGraph orchestrator + validator
      tools/      (pending)  5 typed tool implementations
      llm/        (pending)  LLMProvider protocol + 3 providers
      retrieval/  (pending)  Chroma + BM25 + RRF + rerank (Phase 2)
      kg/         (pending)  NetworkX KG built from Postgres tables
      pii/        (pending)  Presidio inbound pre-pass + log redactor
    scripts/
      init_db.py             apply schema, report counts
      seed.py                load seed YAML into Postgres
      smoke_repository.py    10-assertion repo smoke test
    data/seed/seed.yaml      synthetic seed data
    tests/                   pytest unit + integration + eval

  frontend/   (pending)
    Next.js 14 App Router, TS, Tailwind, shadcn, Vercel AI SDK

  docs/
    architecture.svg         (Phase 5) exported diagram from this doc
    eval_results.md          (Phase 5) per-query eval numbers
```
