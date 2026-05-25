# Operations

Running this in something resembling production. The Phase 1 POC is
demo-ready on a single laptop; this doc names the gaps and the path to
horizontal scale.

For configuration, see [../README.md § Configuration reference](../README.md).
For monitoring data shapes, see [api.md](api.md).

---

## What to monitor

| Signal | Source | Threshold (suggested) |
|---|---|---|
| `/health` `db_ok` | health endpoint | alert immediately on `false` |
| `parts_in_db` | health endpoint | alert if 0 unexpectedly (data wipe) |
| KG node/edge counts | health endpoint | alert on >5% deviation between deploys (build script regression) |
| Per-tool latency | `tool_call` -> `tool_result` time delta in SSE | p95: `lookup_part` < 1s, `check_compatibility` < 500ms, `troubleshoot` < 5s, `compound` chain < 30s |
| LLM provider 4xx rate | provider gateway error events | alert if `rate >5%` for 5 min (rotate provider via header / fallback) |
| LLM 429 rate | `groq` SDK retries logged | flag for capacity planning |
| Eval pass rate on CI | `python -m tests.eval.run_eval` exit code | hard fail on any regression |
| Hard-rule violations | dedicated structlog event when an em dash, PII pattern, or safety bypass is detected in an assistant reply | PagerDuty page (this is the "fire alarm" category) |

---

## Logging

- Structlog JSON to stdout in production. Log level `INFO` by default;
  `DEBUG` enabled per-request via a `?debug=1` query param in a hardened
  build (not in Phase 1).
- Every request emits, in order: `chat_request_received`,
  `kg_loaded`, one `tool_call` per dispatch, one `tool_result` per
  return, optional `validator_run`, `chat_response_sent` with
  cumulative `input_tokens` + `output_tokens` + wall-clock.
- PII redaction processor (Phase 4): scrub matched email / phone /
  US-formatted SSN patterns from every log line before write.
- Conversation id is in every log line for that request.

---

## Failure modes and recovery

### Supabase / Postgres unreachable

- `/health` reports `degraded`. `/chat` returns `500` before opening the
  SSE stream (the route persists the user message first).
- **Recovery**: psycopg pool is auto-reconnecting; manual recovery is
  rarely needed beyond restoring DB reachability.
- **Cost of failure**: total agent outage. No graceful degradation in
  Phase 1.
- **Phase 4 hardening**: a read-only mode that serves cached answers
  for the last N hot queries (Redis or in-process LRU).

### LLM provider rate limit (429)

- Provider SDK auto-retries with exponential backoff. Most blips clear.
- If a 429 reaches the orchestrator, the route emits an SSE `error`
  frame and the frontend renders a retry affordance.
- **Recovery**: ProviderSwitcher in the header lets a user flip to a
  different provider mid-session via `X-LLM-Provider`.
- **Phase 4 hardening**: server-side provider fallback chain
  (Groq -> Anthropic -> OpenAI on 429) without the user needing to click
  anything.

### Tool errors

- The orchestrator graph catches per-tool exceptions and emits a
  `tool_result` with an error payload (`{status: "error", message:
  "..."}`). The LLM is told to surface the error to the user and offer
  to try again or escalate.
- **Recovery**: usually transient (DB blip, JSON parse on a malformed
  symptom mapping).
- **Phase 4 hardening**: dead-letter queue for tool errors so they
  surface in an ops dashboard, not just logs.

### Validator escalate

- The validator returns `escalate` on an unfixable faithfulness or
  relevance failure. The orchestrator routes to the escalation node,
  which emits a `StreamEscalation` event and an assistant message
  apologizing and asking for human help.
- **Recovery**: the user opens the EscalationForm (Phase 4) or
  contacts support directly.
- **Phase 4 hardening**: auto-create a ticket via `/ticket` with the
  conversation_id + summary; the LLM never sees the contact info.

### Frontend can't reach backend

- Health proxy at `/api/health` returns `502` with the backend error.
- Chat composer renders an inline error banner; messages are not lost
  client-side (typed in the textarea persist).
- **Recovery**: check `NEXT_PUBLIC_BACKEND_URL` env var; check backend
  is running and CORS origin includes the frontend origin.

---

## Rollback

The orchestrator graph is a single Python module
([graph.py](../backend/app/agents/graph.py)). Deploys are atomic at the
process level. A bad deploy is a `git revert` + redeploy; no schema
migration is rolled back since schema changes are additive (idempotent
`IF NOT EXISTS` clauses).

**Step-by-step rollback:**

```bash
# Identify the last known-good commit
git log --oneline --grep="eval: 17/17"

# Revert to it
git revert <bad-commit-sha>

# Or roll the branch back if you control the deploy
git reset --hard <good-commit-sha>

# Redeploy (whatever your platform uses; for Fly.io: fly deploy)
```

**Database rollback policy**: never destructive on rollback. If a
column was added in the bad deploy, leave it; the schema is idempotent
and the new column is unused after the code revert.

---

## Phase 4 hardening checklist

When this leaves Phase 1 POC and goes near customers, do **all** of:

- [ ] Move Supabase connection from direct -> pooler (transaction
      mode). Cap `ConnectionPool.max_size` at 20 per app instance.
- [ ] Add `python-cors` env-driven middleware in front of FastAPI to
      cover preflight on `/chat` for any non-localhost origin.
- [ ] Wire Presidio at the inbound boundary of `/chat`.
      Token-replace PII; persist the token<->value map in
      conversation-scoped memory (Redis, expires with the session).
- [ ] Implement the EscalationForm POST `/ticket` path. The form
      bypasses the LLM-routed `/chat` entirely.
- [ ] Enable `pgcrypto` on `tickets.contact_blob` write/read.
- [ ] Per-IP rate limit on `/chat` (suggest 30 req/min).
- [ ] Provider fallback chain on 429 (Groq -> Anthropic -> OpenAI),
      retry budget 2.
- [ ] LangSmith tracing or equivalent (OpenTelemetry on each tool +
      LLM call).
- [ ] PagerDuty integration for hard-rule violations.
- [ ] Quarterly red-team eval pass with new adversarial cases.

---

## Capacity sketch

Per-request cost on the default (Anthropic orchestrator + Groq validator):

| Case | Wall clock | Input tokens | Output tokens | Approx cost |
|---|---|---|---|---|
| Simple lookup | 5-10s | ~1.5k | ~150 | $0.005 |
| Compatibility | 7-13s | ~2k | ~200 | $0.008 |
| Troubleshoot | 17s | ~3k | ~400 | $0.015 |
| Compound (chained tools) | 47s | ~6k | ~800 | $0.030 |

(Numbers are illustrative; real rates depend on provider pricing.)

A 50k contacts/month deflection target at, say, 30% compound queries and
70% simple-or-medium queries averages ~$0.012/contact. At 50k/month that
is ~$600/month in LLM spend before any caching. The break-even versus
live-agent contact cost ($5-8/contact) is dramatic; the cost line should
look invisible against the savings line.

---

## Deployment targets (Phase 5)

Not built; documented so the choice is reviewable.

- **Backend**: Fly.io or Render for the FastAPI process. Single region
  to start; multi-region requires sticky sessions or Redis for the
  conversation cache (Postgres already shares state).
- **Frontend**: Vercel. Set `NEXT_PUBLIC_BACKEND_URL` to the backend
  public URL.
- **Database**: Supabase managed Postgres. Direct connection in single
  region; pooler in transaction mode if scaling out.
- **Vector store (Phase 2)**: pgvector on the same Supabase instance.
  One extension call away.
- **KG (Phase 4)**: Neo4j AuraDB when NetworkX outgrows a single
  process. Behind the existing `KnowledgeGraph` protocol; tools don't
  change.
- **Observability**: LangSmith for LLM/tool tracing; standard
  Grafana/Loki for app metrics and logs.
