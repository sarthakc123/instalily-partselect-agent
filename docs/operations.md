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

## Deployment

The deploy artifacts ship in the repo. The mental model is three
independently-managed pieces:

- **Postgres**: Supabase (already cloud). Just paste `DATABASE_URL`.
- **Backend**: Fly.io. Built from [`backend/Dockerfile`](../backend/Dockerfile),
  configured by [`backend/fly.toml`](../backend/fly.toml). Single shared-cpu
  VM with 1 GB RAM; `min_machines_running = 1` so the first request after
  idle does not pay a cold-start (which the streaming UX would expose).
- **Frontend**: Vercel. Standard Next.js build. Env vars covered by
  [`frontend/.env.example`](../frontend/.env.example).

### Backend → Fly.io

First-time deploy (5 minutes once you have an account):

```bash
brew install flyctl                # or: curl -L https://fly.io/install.sh | sh
fly auth signup                    # or `fly auth login` if you already have one

cd backend
fly launch --no-deploy --copy-config --name partselect-chat-api
# When prompted: accept the existing fly.toml; pick the region nearest you
# (the default is iad). Skip the suggested Postgres/Redis (we have Supabase).

fly secrets set \
  DATABASE_URL='postgresql://...@db.<ref>.supabase.co:5432/postgres' \
  ANTHROPIC_API_KEY='sk-ant-...' \
  GROQ_API_KEY='gsk_...' \
  CORS_ORIGINS='https://<your-frontend>.vercel.app'

fly deploy
```

Subsequent deploys: `fly deploy` from the `backend/` directory.

Verify:

```bash
curl https://partselect-chat-api.fly.dev/health
# Expect: {"status":"ok","db_ok":true,"parts_in_db":50,"kg":{...}}
```

If `parts_in_db` is 0, the DB is empty (you pointed `DATABASE_URL` at a fresh
project rather than the dev one). One-time seed from inside the VM:

```bash
fly ssh console -C "python -m scripts.init_db"
fly ssh console -C "python -m scripts.seed"
fly ssh console -C "python -m scripts.build_kg"
# Re-check /health: parts_in_db should now be 50.
```

The schema is idempotent (`apply_schema()` runs on every boot anyway); the
seed loader uses `ON CONFLICT DO NOTHING` so re-runs are safe.

Useful commands:
- `fly logs` — tail structured logs.
- `fly ssh console` — drop into the running VM (smoke scripts are baked in).
- `fly status` — VM count, health, image SHA.

Image size is ~250 MB (production deps only; the Phase 2 retrieval and
Phase 4 PII deps are in optional pyproject groups not installed in the
production image). The KG is rebuilt from Postgres on boot via the FastAPI
lifespan (`app.main.lifespan`); no persistent volume is required.

### Frontend → Vercel

```bash
npm install -g vercel              # or use the Vercel dashboard "Import Project"

cd frontend
vercel link                        # one-time; pick "Create new project"
vercel env add NEXT_PUBLIC_BACKEND_URL production
# Paste the Fly.io URL, for example: https://partselect-chat-api.fly.dev

vercel --prod
```

Or via the dashboard: connect the GitHub repo, set the project root to
`frontend/`, and add `NEXT_PUBLIC_BACKEND_URL` under Environment Variables
(scope: Production + Preview).

Once the Vercel domain is known, set it on the backend so CORS allows it:

```bash
fly secrets set CORS_ORIGINS='https://<your-app>.vercel.app'
# Fly automatically restarts the VM after a secret change.
```

### Smoke test on the public URLs

```bash
BACKEND=https://partselect-chat-api.fly.dev
FRONTEND=https://<your-app>.vercel.app

# 1. Backend up?
curl -fsS "$BACKEND/health" | jq .status   # -> "ok"

# 2. Frontend up?
curl -fsS -o /dev/null -w "%{http_code}\n" "$FRONTEND"   # -> 200

# 3. End-to-end /chat stream
curl -sN -X POST "$BACKEND/chat" \
  -H "Content-Type: application/json" \
  -d '{"message":"Is part PS11743427 compatible with my WDT780SAEM1?"}' \
  | head -20
# Expect: conversation -> tool_call(check_compatibility) ->
#         tool_result(verdict=yes) -> text_delta(s) -> done
```

If end-to-end works on the public URLs, the full Phase 1 eval set is
expected to pass against the deployed backend; re-run with
`DATABASE_URL` pointed at production:

```bash
cd backend
DATABASE_URL='...supabase prod URL...' .venv/bin/python -m tests.eval.run_eval
```

### Other targets (not used in Phase 1)

- **Vector store (Phase 2)**: pgvector on the same Supabase instance.
  One extension call away.
- **KG (Phase 4)**: Neo4j AuraDB when NetworkX outgrows a single
  process. Behind the existing `KnowledgeGraph` protocol; tools don't
  change.
- **Observability**: LangSmith for LLM/tool tracing; standard
  Grafana/Loki for app metrics and logs.
