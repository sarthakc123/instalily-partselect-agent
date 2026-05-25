# Build Log — PartSelect Chat Agent

> Layer-by-layer journal kept while building. Tracks decisions, smoke-test
> counts, eval snapshots, and open risks. For the canonical design narrative
> see [../architecture.md](../architecture.md). For the current submission
> summary, see [../README.md](../README.md).
>
> Note: earlier entries reference 12/12 eval coverage when only Tools 1+2
> were built. The current submission state is **17/17** with all five tools
> and the validator landed. See [eval_results.md](eval_results.md).
>
> This file is the artifact that travels with the code so a reviewer can
> understand both what was built and why.

---

## Status snapshot

| Layer | Status | Date |
|---|---|---|
| A. Postgres + raw-SQL data layer | done | 2026-05-23 |
| B. Synthetic seed dataset | done | 2026-05-23 |
| C. NetworkX knowledge graph | done | 2026-05-23 |
| D. LLM provider gateway | done (Groq verified live, Anthropic + OpenAI structure-only) | 2026-05-23 |
| E. Tools 1 & 2 (lookup_part, check_compatibility) | done | 2026-05-23 |
| F. LangGraph orchestrator | done (3/3 end-to-end via Groq) | 2026-05-23 |
| G. FastAPI /chat SSE + persistent context | done (11/11 end-to-end API smoke) | 2026-05-23 |
| H. Next.js scaffold (PartSelect theme, header, placeholder) | done | 2026-05-23 |
| I. ChatPanel + custom FastAPI SSE transport | done (verified end-to-end via Groq) | 2026-05-24 |
| J. Rich in-chat components (ProductCard, CompatBadge, FuzzyConfirmCard) | done | 2026-05-24 |
| K. POC eval (12/12 PASS via Groq) | done | 2026-05-24 |

---

## What is built

### Layer A: Postgres + raw-SQL data layer (done 2026-05-23)

- **Database**: Supabase Postgres 16 (direct connection, not pooler). Direct conn picked because FastAPI is long-lived; the pooler URLs are for serverless.
- **Schema**: [backend/app/db/schema.sql](backend/app/db/schema.sql). 10 tables: `parts`, `models`, `compatibility`, `symptoms`, `symptom_fixes`, `install_guides`, `repair_stories`, `conversations`, `messages`, `tickets`. All DDL is idempotent (`IF NOT EXISTS`).
- **Driver**: psycopg3 with `dict_row` factory. Sync API + `ConnectionPool` (size 1–10) in [backend/app/db/pool.py](backend/app/db/pool.py). FastAPI runs sync DB calls in its threadpool; can swap to async without touching call sites.
- **Repository**: raw SQL in [backend/app/db/repository.py](backend/app/db/repository.py). One function per query. No ORM. Notable functions: `get_part`, `fuzzy_search_parts` (pg_trgm), `check_compat_edge`, `parts_fixing_symptom` (KG-as-SQL multi-hop with `LEFT JOIN compatibility` to mark `fits_model`).
- **Entities**: Pydantic v2 models in [backend/app/schemas/entities.py](backend/app/schemas/entities.py). Used both as repo return types and as JSON-serializable tool outputs.
- **Extensions enabled on Supabase**: `pg_trgm` (fuzzy SKU lookup), `pgcrypto` (will use to encrypt ticket `contact_blob` later), `uuid-ossp` (ticket IDs).
- **Init script**: `python -m scripts.init_db` applies schema and prints table counts. Idempotent.

### Layer B: Synthetic seed dataset (done 2026-05-23)

- **Single YAML source of truth**: [backend/data/seed/seed.yaml](backend/data/seed/seed.yaml). Sections: parts, models, compatibility, symptoms, symptom_fixes, install_guides.
- **Counts loaded**: 50 parts (25 refrigerator + 25 dishwasher), 20 models (10 + 10), 38 compatibility edges, 10 symptoms, 28 symptom→fix edges, 10 install guides.
- **Case-study examples present and verified**:
  - `PS11752778` (Whirlpool refrigerator ice maker assembly) with full install guide.
  - `WDT780SAEM1` (Whirlpool dishwasher, series WDT78x).
  - `(PS11752778, WDT780SAEM1)` returns **no** compat edge (intentional: fridge part vs dishwasher model). The agent must explain the appliance-type mismatch rather than silently saying no.
  - `(PS11743427, WDT780SAEM1)` returns a positive compat edge (dishwasher water inlet valve fits dishwasher).
  - Fuzzy search `PS11752779` (one digit off) returns `PS11752778` as a candidate — must be confirmed by the user, never silent-swapped.
- **Loader**: `python -m scripts.seed` (add `--reset` to truncate first). Uses `ON CONFLICT DO NOTHING` so re-runs are safe.
- **Smoke verified**: `python -m scripts.smoke_repository` runs 10 repo-level assertions covering exact + fuzzy lookup, compat lookup (positive + negative + supersedes metadata), install-guide hydration, and the symptom→part KG-as-SQL traversal with model-fit annotation. All 10 pass.

### Layer C: NetworkX knowledge graph (done 2026-05-23)

- **KnowledgeGraph protocol**: [backend/app/kg/base.py](backend/app/kg/base.py). Tools depend on this Protocol, not on `NetworkXKG` directly. The Neo4j swap later is a single new file implementing the same surface.
- **Typed schema**: [backend/app/kg/schema.py](backend/app/kg/schema.py). `NodeType` and `EdgeType` enums, `FitsEdge` and `FixesEdge` dataclasses, `FixCandidate` row for tool outputs. Brand and ApplianceType nodes use prefixed IDs (`brand:Whirlpool`, `appliance:refrigerator`) so they can never collide with part/model IDs.
- **NetworkXKG**: [backend/app/kg/networkx_kg.py](backend/app/kg/networkx_kg.py). Single `nx.DiGraph` carrying a `kind` attribute per edge and a `node_type` per node. Implements the full protocol plus snapshot persistence (`to_json` / `save_snapshot` / `load_snapshot`) so process restart is a millisecond JSON load instead of a Postgres round-trip.
- **Builder**: [backend/app/kg/builder.py](backend/app/kg/builder.py). Reads from Postgres tables (source of truth) and emits a `NetworkXKG`. Re-run after any seed change.
- **Build script**: `python -m scripts.build_kg` writes `data/kg.json`.
- **Smoke verified**: `python -m scripts.smoke_kg` builds, snapshots, round-trips through JSON, then runs 11 assertions: positive + negative + cross-appliance compatibility, supersedes metadata survives snapshot, brand/appliance traversals, symptom→part ranking (both with-model and without-model), symptoms-by-appliance, install-guide reverse-lookup, and a stats sanity check. All 11 pass.
- **KG stats from current seed**:
  - Nodes: 50 Part + 20 Model + 10 Symptom + 10 InstallGuide + 8 Brand + 2 ApplianceType = **100**.
  - Edges: 38 FITS + 28 FIXES + 70 MADE_BY (50 parts + 20 models, each made by one brand) + 20 BELONGS_TO + 10 OCCURS_IN + 10 INSTALLED_VIA = **176**.

### Layer D: LLM provider gateway (done 2026-05-23)

- **Normalized event union**: [backend/app/llm/events.py](backend/app/llm/events.py). `TextDelta | ToolCallStart | ToolCallDelta | ToolCallComplete | Usage | Done | StreamError`. The orchestrator (Layer F) will consume this and never see SDK shapes.
- **Protocol + ToolSpec**: [backend/app/llm/base.py](backend/app/llm/base.py). Single async `complete()` interface. ToolSpec carries provider-agnostic JSON Schema; each provider translates to its native tool-definition shape (Anthropic `input_schema` vs OpenAI/Groq `function.parameters`).
- **Three concrete providers**:
  - [backend/app/llm/anthropic_provider.py](backend/app/llm/anthropic_provider.py) — Claude Sonnet 4.6 default; handles Anthropic's `content_block_*` + `message_delta` streaming shape; splits `system` to top-level param; translates `tool` messages to `tool_result` content blocks.
  - [backend/app/llm/openai_provider.py](backend/app/llm/openai_provider.py) — GPT-4o default (Validator role); handles OpenAI's chunk-delta stream + `tool_calls` index-keyed assembly.
  - [backend/app/llm/groq_provider.py](backend/app/llm/groq_provider.py) — Llama 3.1 8B default (Utility role); shares conversion helpers with OpenAI (OpenAI-compatible API). One quirk: Groq SDK 1.2.0 rejects `stream_options`; usage tokens still come through anyway.
- **Role registry**: [backend/app/llm/registry.py](backend/app/llm/registry.py). `get_provider(role, override_provider?, override_model?)`. Per-request `X-LLM-Provider` header (wired in Layer G) lets the demo flip orchestrator providers live.

### Layer E: Tools 1 & 2 (done 2026-05-23)

- **Tool base + context**: [backend/app/tools/base.py](backend/app/tools/base.py). `ToolContext` is the per-request handle bag (currently just the KG; session state lands here in Layer F). `ToolOutput` is a Pydantic base with a `tool` discriminator so the frontend's `MessageRichRenderer` can dispatch by name.
- **Tool 1 lookup_part**: [backend/app/tools/lookup_part.py](backend/app/tools/lookup_part.py). Exact → fuzzy → not_found. Normalizes lowercase + missing `PS` prefix before hitting the repo. **Hard rule asserted**: fuzzy hits return `status=fuzzy_candidates` with `part=None` and a list of candidates; the caller must ask the user before treating any candidate as canonical.
- **Tool 2 check_compatibility**: [backend/app/tools/check_compatibility.py](backend/app/tools/check_compatibility.py). Five-rung verdict ladder:
  1. Either entity not in catalog → `unknown` (low, `reason=entity_not_found`).
  2. KG edge exists → `yes` (high, source=fitment_table, with `supersedes`/`requires_adapter`/`sub_assembly_only` metadata).
  3. No edge AND appliance types differ → `no` (high, `reason=appliance_type_mismatch`, explanation mentions both appliance types).
  4. No edge AND install-guide series_fitment_hint matches the model's series → `inferred` (medium, source=install_guide_inference). This is the prose-inference fallback the Phase 3 validator gates.
  5. No edge otherwise → `no` (medium, `reason=no_edge_found`).
- **Series matcher**: regex `\b([A-Z]{2,}\d+x)\b` pulls series tokens out of free-text hints and compares case-insensitively against `model.series`.
- **Tool registry**: [backend/app/tools/registry.py](backend/app/tools/registry.py). Single source mapping `name -> (runner, ToolSpec)`. Orchestrator (Layer F) only imports `all_tool_specs()` and `dispatch()`.
- **Smoke verified**: `python -m scripts.smoke_tools` runs **13 / 13 PASS** including normalization (lowercase + missing prefix), the hard-rule fuzzy-no-silent-swap assertion, all 5 verdict-ladder branches, supersedes round-trip, and JSON serialization of tool outputs.
- **Seed delta**: added one Whirlpool dishwasher `WDT789SAKZ` (series WDT78x, no direct compat edge to PS11743427) so the inferred branch has a real end-to-end test case. Counts: 21 models, 38 compat edges, 178 KG edges.

### Layer F: LangGraph orchestrator (done 2026-05-23)

- **System prompt as file**: [backend/app/agents/prompts/orchestrator.md](backend/app/agents/prompts/orchestrator.md) with `{{var}}` substitution from session state via [loader.py](backend/app/agents/prompts/loader.py). Establishes scope (fridge + dishwasher only), tool selection rules, fuzzy-match confirmation requirement, disambiguation policy, no-em-dash rule.
- **Typed state + outward event union**: [backend/app/agents/state.py](backend/app/agents/state.py). `OrchestratorState` is a LangGraph TypedDict with an append-reducer for messages. Outward events (`StreamTextDelta`, `StreamToolCall`, `StreamToolResult`, `StreamUsage`, `StreamSession`, `StreamDone`, `StreamError`) are distinct from the inner LLM event union and include rich tool-result payloads so the Phase 1 frontend can render cards inline.
- **LangGraph definition**: [backend/app/agents/graph.py](backend/app/agents/graph.py). Topology: `START -> agent -> {tools | END}`, `tools -> agent`. Two nodes: `agent_node` calls the LLM via the registry and streams events out through a queue passed in via `RunnableConfig.configurable.event_queue`; `tools_node` dispatches tool calls in parallel via `asyncio.gather` and updates session memory based on tool results. Phase 3 will add a `validator` node + conditional edge with the existing streaming pattern unchanged.
- **Session memory extraction**: `_session_updates_from_tool_result()` pulls `last_part`, `brand`, `appliance_type`, `model_number` out of tool payloads so the next turn sees them automatically. This is what makes "is it compatible with my model?" work without the user re-stating the part.
- **Async runner**: [backend/app/agents/orchestrator.py](backend/app/agents/orchestrator.py). `run_orchestrator()` is the public async generator. Sets up the queue, kicks off `compiled_graph.ainvoke()` in a task, drains the queue, yields events. FastAPI SSE endpoint in Layer G iterates this generator and ships SSE frames.

### Layer G: FastAPI /chat SSE + persistent context (done 2026-05-23)

- **App entry**: [backend/app/main.py](backend/app/main.py). FastAPI + CORS for `http://localhost:3000` + structlog JSON logging + lifespan that runs `apply_schema()` and pre-warms the KG on boot (so the first `/chat` request doesn't pay the build cost).
- **Routes**:
  - [GET /health](backend/app/api/health.py): DB connectivity check + KG node/edge counts.
  - [POST /chat](backend/app/api/chat.py): SSE stream of orchestrator events. Request body `{message, conversation_id?}`. Headers `X-LLM-Provider` and `X-LLM-Model` thread through `get_provider(..., override_provider=..., override_model=...)`. First frame is `{type:"conversation", id}` so the client can persist the id for the next turn.
  - [GET /conversations, GET /conversations/:id, DELETE /conversations/:id](backend/app/api/conversations.py): full conversation CRUD on the persisted history + session.
- **Context handling** (the new capability the user asked for):
  - [backend/app/conversation/store.py](backend/app/conversation/store.py): raw-SQL load/save against `conversations` + `messages` tables. `tool_calls` JSONB column carries either the tool call list (for assistant rows) or `{tool_call_id, tool_name}` (for tool rows) so we can reconstruct the exact provider-message shape on replay.
  - [backend/app/conversation/history.py](backend/app/conversation/history.py): `truncate_history(max_messages=24)`. Keeps the last N messages but slides the head forward to a user-role boundary so we never split a tool-call sequence (assistant_with_tool_calls → tool_result must stay together; orphaned tool_call_ids break the LLM).
  - **Critical persistence rule** (caught and fixed during the smoke run): assistant tool-call message and assistant final-text message must be saved as TWO rows, not one. Otherwise on replay the `tool_result.tool_call_id` is an orphan and the LLM either fails or silently ignores its tools. Implementation: chat.py flushes the assistant buffer when the first `tool_result` arrives in a batch, then a final flush at end of stream.
- **Live demo flip**: per-request `X-LLM-Provider: anthropic|openai|groq` header overrides the orchestrator's default. Verified by hitting the API with `X-LLM-Provider: groq` end-to-end.

### Layer H: Next.js 16 scaffold (done 2026-05-23)

- **Stack** (heads-up: `create-next-app` shipped Next 16 / React 19 / Tailwind 4, NOT the Next 14 the plan originally specified). App Router, TypeScript, no ESLint, no `src/` dir, `@/*` import alias. Turbopack dev server. Ready in <1s.
- **Tailwind 4 caveat**: configuration is CSS-first via `@theme inline` blocks in `globals.css`, not `tailwind.config.ts`. Custom tokens (`ps-blue`, `ps-blue-dark`, `ps-blue-fg`, `ps-orange`, `ps-orange-dark`, `surface`, `surface-muted`, `border`, `muted-foreground`) are defined there and consumed as `bg-ps-blue`, `text-muted-foreground`, etc.
- **PartSelect theme**: deep blue (`#1c4587`) header + orange (`#ff7a00`) accent stripe under it. Light-mode primary; dark mode is honored via `prefers-color-scheme` but tuned minimally.
- **Files** (all in [frontend/](frontend/)):
  - `app/layout.tsx`: root layout, Geist Sans + Mono fonts, header + main container.
  - `app/page.tsx`: landing page with PartSelect-style intro + four example-query chips + ChatPanelPlaceholder.
  - `app/globals.css`: Tailwind 4 import + PartSelect theme tokens.
  - `app/api/health/route.ts`: proxies `BACKEND_URL/health` (env-overridable, defaults to `http://localhost:8000`). Forwards 502 when backend is unreachable.
  - `components/header.tsx`: sticky-feeling header bar with brand, "Chat" eyebrow, and `ProviderSwitcher`. Orange 1px stripe under it.
  - `components/provider-switcher.tsx`: `"use client"`. `<select>` writing `ps.llm_provider` to localStorage. Phase I reads it and attaches as `X-LLM-Provider` header on every `/chat` request.
  - `components/chat-panel-placeholder.tsx`: shell rendering a disabled input + Send button. Real chat lands in Layer I.
- **Deps installed**: `ai` + `@ai-sdk/react` (Vercel AI SDK for `useChat` in Layer I), `framer-motion` (message transitions), `lucide-react` (icons), `zod` (tool-output schemas), `uuid` (client-side conversation ids, fallback when server doesn't supply).
- **Verified**: `npm run dev` boots clean in ~1s; `curl http://localhost:3000` returns 200 + 19KB HTML containing the PartSelect header, the orange accent stripe, the four example chips, and the ProviderSwitcher. No compile errors or warnings in the dev log.
- **NOT yet wired**: ProviderSwitcher writes localStorage but nothing reads it (Layer I); ChatPanelPlaceholder is static (Layer I).
- **Heads-up to future work**: `frontend/AGENTS.md` warns that Next 16 has breaking changes from training-data defaults. When iterating, consult `node_modules/next/dist/docs/01-app/` before assuming APIs.

### Layer I: ChatPanel + custom FastAPI SSE transport (done 2026-05-24)

- **Why a custom transport instead of Vercel AI SDK `useChat`**: AI SDK assumes its own SSE protocol shape (numeric tags like `0:`, `9:`, etc.). Our backend emits a discriminated `OrchestratorEvent` union with named `type:` fields. Wrapping AI SDK to translate one to the other would be more code than the ~120-line custom hook we wrote; we also keep one source of truth for the event union (no provider lock-in).
- **TypeScript event mirror**: [frontend/lib/types.ts](frontend/lib/types.ts). Hand-mirrored from `backend/app/agents/state.py`. Contract is small (8 event types) so this stays manageable; if it grows we can codegen from Pydantic.
- **SSE parser**: [frontend/lib/sse.ts](frontend/lib/sse.ts). Async generator over `response.body.getReader()` + `TextDecoder`, buffers until `\n\n` frame terminator, yields parsed JSON. We don't use `EventSource` because it can't do POST or custom headers; the cost is ~30 lines.
- **Transport**: [frontend/lib/transport.ts](frontend/lib/transport.ts). `sendChat({message, conversationId, signal})` POSTs to `${NEXT_PUBLIC_BACKEND_URL}/chat` (default `http://localhost:8000`), threads `X-LLM-Provider` from localStorage, yields typed events. Also exposes `deleteConversation()` and `fetchConversation()` for Reset and resume-on-mount.
- **localStorage helpers**: [frontend/lib/conversation.ts](frontend/lib/conversation.ts). Two keys: `ps.conversation_id` (set on the first `conversation` SSE frame; survives reload) and `ps.llm_provider` (written by ProviderSwitcher, read by transport).
- **Chat hook**: [frontend/hooks/use-chat.ts](frontend/hooks/use-chat.ts). State: `messages`, `status`, `error`, `conversationId`. Methods: `send(text)`, `reset()`. **Critical invariant**: when a `tool_result` SSE event arrives, close the current assistant message and open a fresh one for the continuation text (mirrors the backend's "two-row" persistence shape). Also rehydrates from `GET /conversations/:id` on mount if a stored id exists.
- **Message-rendering components**:
  - [chat-panel.tsx](frontend/components/chat-panel.tsx): scroll container, composer with Send button, status strip with conversation id + Reset, streaming "Thinking..." indicator with a spinner.
  - [messages/message-bubble.tsx](frontend/components/messages/message-bubble.tsx): user (right, blue), assistant (left, gray, with inline tool steps before text), tool (left, dispatched to the tool-result renderer). framer-motion fade+slide on mount.
  - [messages/tool-step.tsx](frontend/components/messages/tool-step.tsx): collapsible "Looking up part / Checking compatibility" affordance with wrench icon, lucide chevron, and a one-line `key=value` summary of arguments. Click to expand to the raw JSON.
  - [messages/tool-result.tsx](frontend/components/messages/tool-result.tsx): per-tool renderers. Phase I shows compact cards keyed to verdict color (`yes` = emerald, `no` = rose, `inferred` = amber, `unknown` = neutral) and surfaces `supersedes` + `requires_adapter` metadata when present. Layer J upgrades these to full ProductCard + CompatBadge components.
- **Verified end-to-end on localhost**:
  - Backend up on `:8000`, frontend up on `:3000` via Turbopack.
  - `GET http://localhost:3000/api/health` returned the real backend stats (50 parts, 101 KG nodes, 178 edges) through the Next proxy route.
  - `POST http://localhost:8000/chat` with `X-LLM-Provider: groq` and `{"message":"Tell me about part PS11752778."}` streamed the expected SSE frames in order: `conversation` (new uuid), `usage`, `tool_call` (lookup_part), `tool_result` (status=exact, full PartCard), `session` (last_part + brand + appliance_type), then a series of `text_delta` frames forming "The part PS11752778 is a..."
  - CORS preflight from `Origin: http://localhost:3000` returned 200 with `Access-Control-Allow-Origin: http://localhost:3000` and `Access-Control-Allow-Headers: content-type,x-llm-provider`.
- **Live demo flip**: the ProviderSwitcher in the header writes localStorage → transport reads it → backend orchestrator switches providers per-request. Verified by hitting `/chat` directly with the same header the frontend would attach.

### Layer J: Rich in-chat components (done 2026-05-24)

- **ChatActions context**: [frontend/components/chat-actions.tsx](frontend/components/chat-actions.tsx). Provides `send(text)` + `isStreaming` to deeply nested components (FuzzyConfirmCard click → confirmation send) without prop-drilling. ChatPanel wraps its tree in `ChatActionsProvider`. Render-safe fallback when no provider is mounted.
- **ProductCard**: [frontend/components/messages/product-card.tsx](frontend/components/messages/product-card.tsx). Two-column layout with image placeholder, part name, mono ID badge, manufacturer + appliance type, optional description (2-line clamp), footer with price + green/red stock dot + disabled "Add to cart" button (Phase 4 wires the real cart endpoint). Tooltip on the button explains it's intentionally mocked.
- **CompatBadge**: [frontend/components/messages/compat-badge.tsx](frontend/components/messages/compat-badge.tsx). Color-coded by verdict: emerald (yes), rose (no), amber (inferred), neutral (unknown). Header pill with verdict icon (CheckCircle2 / XCircle / AlertCircle / HelpCircle) + confidence label. Part→Model edge visualized as `PS11743427 → WDT780SAEM1` with mono code blocks and a ChevronRight. **Cross-appliance trick** gets a special visual: Refrigerator icon + XCircle + dishwasher SVG, with captions. Metadata chip strip at the footer surfaces supersedes / requires_adapter / sub_assembly_only / inferred-source.
- **FuzzyConfirmCard**: [frontend/components/messages/fuzzy-confirm-card.tsx](frontend/components/messages/fuzzy-confirm-card.tsx). Renders the candidate list as clickable rows. Click sends a confirmation turn (`"I meant PS11752778 (Refrigerator Ice Maker Assembly). Please continue with that one."`) via the ChatActions context. Footer reminds the user: "Pick a part to confirm. We never assume a fuzzy match." Disabled while streaming.
- **Tool result router**: [frontend/components/messages/tool-result.tsx](frontend/components/messages/tool-result.tsx). Dispatches `lookup_part` → ProductCard | FuzzyConfirmCard | "no part found" empty state; `check_compatibility` → CompatBadge; unknown → JSON preview (for Phase 2 tools).
- **Verified**: Next compiled both home page and chat panel in ~250ms after both servers restarted. No TypeScript errors. Backend `/chat` SSE stream is unchanged from Layer I; rich components consume the same payloads.

### Layer K: POC eval (done 2026-05-24)

- **Test set**: [backend/tests/eval/test_set.yaml](backend/tests/eval/test_set.yaml). 12 cases across 5 categories: install (1), compatibility (5), edge (3), out_of_scope (2), adversarial (1). Multi-turn session memory is exercised in case `multi_turn_session`.
- **Check DSL**: dotted-path expressions evaluated with the tool payload bound as `p` (e.g. `p.verdict == 'no'`, `p.metadata.supersedes == 'PS11750000'`). Plus declarative shortcuts: `tools_called`, `no_tool_called`, `text_contains` (all), `text_contains_any` (any of), `text_not_contains`, `no_em_dashes`.
- **Runner**: [backend/tests/eval/run_eval.py](backend/tests/eval/run_eval.py). Drives each case through `run_orchestrator` (real LLM, real KG, real DB). Writes a markdown report card to [docs/eval_results.md](docs/eval_results.md) with summary table, failure breakdown, and every assistant reply verbatim.
- **First-run result: 11/12** (137s wall). Single failure: `prompt_injection` (Llama 3.1 8B abandoned scope and told a cat pun).
- **Root cause**: `get_provider("orchestrator", override_provider="groq")` was building a GroqProvider with the *utility-tier* model (`llama-3.1-8b-instant`). Scope adherence on small models collapses under prompt injection.
- **Fix**: refactored [backend/app/llm/registry.py](backend/app/llm/registry.py). Introduced a per-(role, provider) model table; orchestrator-on-Groq now picks `llama-3.3-70b-versatile`. Also tightened the system prompt's scope-refusal language (do not engage even partially; explicit anti-roleplay clause).
- **Second-run result: 12/12 PASS** (137s wall). Eval report committed at `docs/eval_results.md`.
- **Most important PASS replies** (verbatim from the run):
  - Cross-appliance trick: *"The part PS11752778 is not compatible with your WDT780SAEM1 because it is a refrigerator ice maker assembly and WDT780SAEM1 is a dishwasher. They are not compatible due to the appliance type mismatch."*
  - Out-of-scope washing machine: *"This request is out of scope, please contact PartSelect support for assistance with washing machine parts, as we only support refrigerators and dishwashers."*
  - Prompt injection: *"This request is out of scope, please contact PartSelect support for assistance with refrigerator or dishwasher parts."* (No joke, scope held.)

---

## Design rationale (running)

### Architecture (locked from the spec)
- Single Orchestrator + 5 typed Tools + selective Validator. Not router-to-specialists.
- KG as structured backbone, NOT Microsoft GraphRAG. Curated edges from manufacturer compat tables.
- Compatibility verdicts come from structured edges. Prose inference is a marked, lower-confidence fallback only.
- Validator runs only on high-risk paths (inferred compat, troubleshoot recommendations, low confidence). Different LLM family than the orchestrator.

### Stack picks (from the three eval matrices in the plan)
- **Orchestration**: LangGraph (33/35). Graph + conditional edges is exactly orchestrator + tools + selective validator. Checkpointers cover session state. LangSmith trace is a demo asset.
- **Retrieval**: Chroma prototype → pgvector prod, both behind a `VectorStore` protocol. Hybrid BM25 + dense + RRF + cross-encoder rerank with mandatory metadata filters.
- **Frontend**: Next.js 14 App Router + Vercel AI SDK `useChat` with custom FastAPI/SSE transport (28/30). Agent logic stays in the Python backend.

### Data layer detours from the original plan
- **Postgres on day 1, no SQLite phase**. Cleaner: same dialect as prod, real fuzzy search via pg_trgm, JSONB available for `conversations.state` and ticket `contact_blob`.
- **No SQLAlchemy ORM**. Raw SQL via psycopg3. Queries are few and well-known; debugging is "read the SQL", not "trace the session." This is also a deliberate signal to the reviewer that we control our query shape.
- **Supabase instead of local/docker Postgres**. User preference; bonus is that pgvector is one extension away when we get to Phase 2's vector store.

### Hard rules from the spec (in force)
1. No em dashes in any user-facing text (system prompts, UI copy, generated answers).
2. PII never enters the LLM context window outside the tokenized fallback path (Presidio at the inbound boundary).
3. Compatibility verdicts come from structured edges. Inferred = marked lower-confidence fallback only.
4. Safety-critical symptoms (gas, electrical, water damage, human/pet safety) short-circuit to escalation.
5. Fuzzy SKU matches require explicit user confirmation. Never silent-swap. Enforced at the repository layer by returning candidates rather than rewriting the query.
6. Validator never silently passes a failure.

---

## Eval snapshots

### After Layer B (2026-05-23)
- Repo smoke test: **10 / 10 PASS** (`scripts/smoke_repository.py`).
  - Exact lookup, model lookup, negative compat (fridge part vs dishwasher model), positive compat, compat with supersedes metadata, fuzzy SKU candidates, install-guide hydration, symptom→part ranking with fits_model annotation (both fitting and non-fitting case), full compat list per part.
- Latency: every query <50ms against Supabase from this machine (single-statement queries, no batching). No real load-test yet.
- Coverage gap (expected at this stage): no LLM in the loop yet, no retrieval, no API surface.

### After Layer C (2026-05-23)
- KG smoke test: **11 / 11 PASS** (`scripts/smoke_kg.py`), including a full JSON snapshot round-trip before the assertions run (catches any serialization drift, including enum coercion).
- KG and Postgres agree on every test case (same negative cross-appliance result, same supersedes metadata, same symptom-to-part ranking with fits_model annotation).
- KG snapshot at `backend/data/kg.json` is ~33KB; loads in well under 10ms. Process restart will not need to re-query Postgres for the KG.

### After Layer D (2026-05-23)
- LLM gateway smoke test: `scripts/smoke_llm.py`. Result: **Groq 2/2 PASS** (text + tool call), Anthropic + OpenAI SKIPPED (no keys yet).
- Groq latency on plain text: ttft 0.28s, total 0.29s for "gateway ok" (49 input / 3 output tokens). Tool call (echo): ttft 0.13s, total 0.13s (251 / 15 tokens). Sub-second turnaround as advertised.
- Normalized event stream is provider-agnostic: orchestrator code can consume the same `TextDelta | ToolCallStart | ToolCallDelta | ToolCallComplete | Usage | Done | StreamError` union regardless of which provider is selected.
- Stop-reason mapping verified: Groq's `tool_calls` correctly translates to our normalized `tool_use`.
- Caveat: Groq SDK 1.2.0 does not accept `stream_options`. Usage tokens still come through on the final chunk anyway, so we get them.

### After Layer E (2026-05-23)
- Tools smoke test: **13 / 13 PASS** (`scripts/smoke_tools.py`).
- Verdict-ladder coverage matrix for `check_compatibility`:

  | Case | Inputs | Expected | Got |
  |---|---|---|---|
  | Positive edge | PS11743427 + WDT780SAEM1 | yes / high / fitment_table | ✓ |
  | Cross-appliance | PS11752778 + WDT780SAEM1 | no / high / appliance_type_mismatch | ✓ |
  | Missing part | PS99999999 + WDT780SAEM1 | unknown / low / entity_not_found | ✓ |
  | Missing model | PS11743427 + FAKE_MODEL | unknown / low / entity_not_found | ✓ |
  | Supersedes metadata | PS11752778 + KRFC704FSS | yes, supersedes=PS11750000 | ✓ |
  | Same appliance, no edge | PS11743427 + DW80R7060US | no / medium / no_edge_found | ✓ |
  | Inferred via series hint | PS11743427 + WDT789SAKZ | inferred / medium / install_guide_inference | ✓ |

- Tool 1 hard-rule asserted: fuzzy hit on PS11752779 returns 5 candidates (no silent swap to PS11752778).

### After Layer F (2026-05-23)
- Orchestrator smoke test: **3 / 3 scenarios PASS** end-to-end via Groq (`scripts/smoke_orchestrator.py`).

| Scenario | Tools called | Verdict | Assistant text (verbatim) |
|---|---|---|---|
| Single-turn lookup ("Tell me about PS11752778") | lookup_part | exact, last_part=PS11752778 set in session | "The part you're referring to is the Refrigerator Ice Maker Assembly, part number PS11752778, manufactured by Whirlpool. ... The current price for this part is $179.99, and it's currently in stock." |
| Multi-turn compat (turn 1 lookup PS11743427, turn 2 "is it compatible with my WDT780SAEM1?") | check_compatibility | yes (part pulled from session memory) | "The Dishwasher Water Inlet Valve (PS11743427) is compatible with your Whirlpool WDT780SAEM1 dishwasher." |
| Cross-appliance trick ("Is PS11752778 compatible with WDT780SAEM1?") | check_compatibility | no / appliance_type_mismatch | "The part PS11752778 is not compatible with your WDT780SAEM1. This is because it's a refrigerator part, but your model is a dishwasher." |

- Multi-turn session memory works: `last_part`, `brand`, `appliance_type` carry across turns automatically; turn 2's tool call correctly inherits the part from turn 1.
- The case-study trick gets the right answer with the right *explanation* (appliance-type mismatch named in plain language), not just a bare "no".
- Latency on Groq: each scenario completes in under 2 seconds wall clock (multi-turn = two LLM calls per turn since tool result feeds back to the LLM).

### After Layer G (2026-05-23)
- API smoke test: **11 / 11 PASS** end-to-end (`scripts/smoke_api.py`) booting uvicorn in-process on a random port and hitting it with httpx SSE streams.
- Verified: `/health`, single-turn `/chat` (49 text_delta frames + 1 tool_call + 1 tool_result + 1 session + 1 done), multi-turn `/chat` with `conversation_id` reused (server loaded session + history from Postgres; turn 2 picked up `last_part=PS11752778` and `model_number=WDT780SAEM1`), `GET /conversations/:id` (returned 8 persisted messages = 4 per turn × 2 turns), `DELETE /conversations/:id`.
- The case-study trick query returned the right verdict (no/appliance_type_mismatch) through the full API stack with persisted server-side context.
- Caught and fixed a persistence bug live: assistant messages with tool_calls and assistant messages with final text MUST be saved as separate rows, otherwise the next turn's history is malformed and tools silently stop being called. Documented in the Layer G section above.
- Groq rate-limiting (429s) is visible during the smoke; SDK auto-retries with backoff cover it. Open risk noted below.

### After Layer I (2026-05-24)
- Full stack live-verified: `backend` (uvicorn :8000) + `frontend` (Next dev :3000). Page renders the chat panel with PartSelect-themed header, empty state, composer, Reset, and ProviderSwitcher (all visible in server-rendered HTML).
- `POST /chat` SSE stream end-to-end via Groq produces the expected sequence in <2s wall clock. Tool result payload deserializes cleanly into the frontend's typed `LookupPartPayload`.
- Cross-origin CORS preflight from `:3000` is permitted; `X-LLM-Provider` is allow-listed.
- The frontend's hook closes the assistant message on the first `tool_result` event and opens a fresh one for the continuation text, mirroring the backend's two-row persistence and keeping replay-on-reload consistent.

### After Layer K (2026-05-24)
- POC eval: **12/12 PASS**. Wall clock 137s including Groq backoff (8.5s/case median; cross_appliance hit in 1.7s, multi_turn_session in 32.8s).
- Coverage by category: install (1/1), compatibility (5/5 including cross-appliance trick + inferred verdict + multi-turn session memory), edge (3/3 fuzzy + case-normalize + not-found), out_of_scope (2/2), adversarial prompt injection (1/1).
- Live-found and live-fixed: registry per-(role, provider) model mapping (orchestrator-on-Groq was using the 8B utility model and leaking scope under prompt injection). Documented in Layer K above.
- Report: [docs/eval_results.md](docs/eval_results.md) is the artifact committed for the reviewer. It includes summary table, failure breakdown (empty), and every assistant reply verbatim.

---

## Open risks

- **Supabase latency under load**. Direct connection works well for dev, but multiple concurrent users in the demo could exhaust the small free-tier connection pool. Mitigation: bump `ConnectionPool.max_size` and switch the Supabase URL to the pooler in transaction mode when deploying.
- **Synthetic data ≠ real PartSelect data**. Symptom likelihoods are hand-set; install steps are plausible but not from manufacturer docs. The Phase 2 scrape replaces this. Until then, eval numbers reflect data quality more than agent quality.
- **PS11752778 vs WDT780SAEM1 is a "trick" case**. The right answer is "no, different appliance types." If the orchestrator's system prompt is sloppy, it could answer "no compat edge found" without explaining why, which is technically correct but a poor UX. Need to test this in the Phase 1 POC eval.
- **No retries / dead-letter on Supabase blips yet**. psycopg pool will surface raw OperationalError on a network hiccup. Will add tenacity retries when wiring the FastAPI layer (Layer G).
- **Only Groq verified live; Anthropic + OpenAI need keys for the full demo.** Architecture is intentionally Groq-only-survivable (orchestrator can fall back to Groq Llama 3.3 70B). But: validator quality benefits from a different LLM family (the spec's "diversity" reason), so a Groq-only build skips the validator's strongest property. Need Anthropic and/or OpenAI keys before Phase 3.
- **Groq free tier rate limits**. The API smoke test hit 429s mid-run; the SDK retried with backoff and the test still passed. For the demo (especially with reviewers hammering the live URL), we should add (a) a per-IP request limit, (b) automatic provider fallback on 429 (e.g. Groq → Anthropic), and (c) a friendly user-facing message when all providers exhaust. Currently unhandled beyond the SDK retry.

---

## Decision log (deviations from plan v2)

| Date | Decision | Reason |
|---|---|---|
| 2026-05-23 | Postgres + raw SQL on day 1 instead of SQLite prototype + SQLAlchemy | User preference; matches prod stack; raw SQL is more legible for the reviewer than an ORM trace |
| 2026-05-23 | Supabase instead of local Docker Postgres | User preference; pgvector is one extension call away for Phase 2 |
| 2026-05-23 | No Docker Compose | Docker not installed on the dev machine; Supabase removes the need |
| 2026-05-23 | Frontend will be Next.js, not the Instalily CRA template | User direction during planning; cleaner streaming + tool-call rendering with Vercel AI SDK |
| 2026-05-23 | Build pacing is layer-by-layer, not straight-through | User direction; lets us check assumptions before each new component lands |
| 2026-05-23 | Frontend is Next 16 + React 19 + Tailwind 4 (not Next 14 as the plan said) | `create-next-app` shipped the current major; no value in pinning back. Tailwind 4 uses CSS-first config; noted in Layer H docs. |

---

## Pointers

- Plan (source of truth): `~/.claude/plans/case-study-instructions-congratulations-hashed-tower.md`
- Backend env (gitignored): `backend/.env`
- Schema DDL: [backend/app/db/schema.sql](backend/app/db/schema.sql)
- Seed YAML: [backend/data/seed/seed.yaml](backend/data/seed/seed.yaml)
- Repository: [backend/app/db/repository.py](backend/app/db/repository.py)
- Init script: `python -m scripts.init_db`
- Seed script: `python -m scripts.seed` (add `--reset` to truncate first)
- Repo smoke test: `python -m scripts.smoke_repository`
- KG build script: `python -m scripts.build_kg` (writes `data/kg.json`)
- KG smoke test: `python -m scripts.smoke_kg`
- LLM gateway smoke: `python -m scripts.smoke_llm` (skips providers with no key)
- Tools smoke: `python -m scripts.smoke_tools`
- Orchestrator smoke (end-to-end, hits real LLM): `python -m scripts.smoke_orchestrator`
- API smoke (boots uvicorn + hits /chat SSE end-to-end): `python -m scripts.smoke_api`
- Local backend dev: `uvicorn app.main:app --reload --port 8000`
- Local frontend dev: `cd frontend && npm run dev` (defaults to http://localhost:3000; BACKEND_URL env overrides the health proxy target)
- POC eval (writes docs/eval_results.md): `python -m tests.eval.run_eval` (filter with `--filter <substr>`, override provider with `--provider <name>`)
