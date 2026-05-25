# HTTP + SSE API reference

Backend: FastAPI on `http://localhost:8000` by default. CORS-allow-listed for
`http://localhost:3000` (override with `CORS_ORIGINS=` in `backend/.env`).

For the SSE event schema, see [../backend/app/agents/state.py](../backend/app/agents/state.py).

---

## `GET /health`

Liveness + readiness. Confirms DB connectivity and reports KG stats.

```bash
curl -s http://localhost:8000/health | jq
```

Response (`200 OK`):

```json
{
  "status": "ok",
  "db_ok": true,
  "parts_in_db": 50,
  "kg": {
    "nodes": 100,
    "edges": 178,
    "node_types": {"Part": 50, "Model": 21, "Symptom": 10, "InstallGuide": 10, "Brand": 8, "ApplianceType": 2},
    "edge_types": {"FITS": 38, "FIXES": 28, "MADE_BY": 71, "BELONGS_TO": 21, "OCCURS_IN": 10, "INSTALLED_VIA": 10}
  }
}
```

Degraded response (DB unreachable, `200 OK` with `status=degraded`):

```json
{"status": "degraded", "db_ok": false, "error": "..."}
```

---

## `POST /chat` (SSE)

The main agent endpoint. Returns a `text/event-stream` carrying typed
events from the orchestrator graph.

### Request

```http
POST /chat HTTP/1.1
Content-Type: application/json
Accept: text/event-stream
X-LLM-Provider: anthropic | openai | groq      (optional, default: anthropic)
X-LLM-Model:    <model-id>                     (optional, role default applies)

{
  "message": "Is PS11743427 compatible with my WDT780SAEM1?",
  "conversation_id": "optional-uuid-for-resume"
}
```

`message` is 1-4000 characters. `conversation_id` is optional; omit on the
first turn, and the server returns a freshly minted UUID in the first SSE
frame. Reuse that id on subsequent turns to keep session memory and history.

### Curl example

```bash
curl -N -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -H "X-LLM-Provider: groq" \
  -d '{"message":"Tell me about PS11752778."}'
```

The `-N` flag disables buffering so frames stream incrementally.

### Event sequence

A typical lookup_part turn streams approximately:

```
event: conversation
data: {"type":"conversation","id":"<uuid>"}

event: tool_call
data: {"type":"tool_call","id":"...","name":"lookup_part","arguments":{"part_number":"PS11752778"}}

event: tool_result
data: {"type":"tool_result","id":"...","name":"lookup_part","payload":{...}}

event: session
data: {"type":"session","session":{"last_part":"PS11752778","brand":"Whirlpool","appliance_type":"refrigerator"}}

event: text_delta
data: {"type":"text_delta","content":"The"}

event: text_delta
data: {"type":"text_delta","content":" part"}

... (more text_delta frames)

event: usage
data: {"type":"usage","input_tokens":1234,"output_tokens":98}

event: done
data: {"type":"done","stop_reason":"end_turn"}
```

### Event union

Source of truth: [../backend/app/agents/state.py](../backend/app/agents/state.py).

| `type` | Shape | When |
|---|---|---|
| `conversation` | `{id}` | First frame. Persist the id client-side. |
| `text_delta` | `{content}` | Streaming assistant text (concatenate in order). |
| `tool_call` | `{id, name, arguments}` | Model emitted a complete tool call (before dispatch). |
| `tool_result` | `{id, name, payload}` | Tool finished. `payload` is the structured output (typed per tool, see [tools.md](tools.md)). |
| `session` | `{session: {...}}` | Session memory updated (carried across turns). |
| `usage` | `{input_tokens, output_tokens}` | LLM usage on this turn. |
| `validator` | `{verdict, faithfulness_score, relevance_score, unsupported_claims, reason}` | After the selective validator runs. Only on high-risk paths (inferred compat, troubleshoot recommendations). |
| `escalation` | `{reason, summary, safety_match?}` | Orchestrator routed to human ticket workflow (safety, validator escalate). |
| `done` | `{stop_reason}` | Stream finished cleanly. |
| `error` | `{message}` | Mid-stream failure. The client should surface a retry affordance. |

### Persistence rule (critical)

The `/chat` route persists assistant tool-call messages and the assistant
final-text messages as **separate rows** in `messages`. On the SSE wire this
shows up as a `tool_result` event arriving between two `text_delta` bursts;
the frontend's `use-chat` hook closes the current assistant bubble and opens
a new one on every `tool_result`. Collapsing the two breaks tool-call
replay on the next turn (`tool_result.tool_call_id` becomes orphan).

---

## `GET /conversations`

List recent conversations (most recent first).

```bash
curl -s "http://localhost:8000/conversations?limit=20" | jq
```

Response (`200 OK`):

```json
{
  "conversations": [
    {"id": "...", "created_at": "2026-05-24T...", "preview": "Tell me about PS11752778."}
  ]
}
```

---

## `GET /conversations/{id}`

Hydrate a stored conversation: session state + full message history.

```bash
curl -s "http://localhost:8000/conversations/<uuid>" | jq
```

Response (`200 OK`):

```json
{
  "id": "<uuid>",
  "session": {"last_part": "PS11743427", "model_number": "WDT780SAEM1", ...},
  "messages": [
    {"role": "user", "content": "...", "created_at": "..."},
    {"role": "assistant", "content": "", "tool_calls": [...], "created_at": "..."},
    {"role": "tool", "content": "<json payload>", "tool_calls": {"tool_call_id": "...", "tool_name": "lookup_part"}, "created_at": "..."},
    {"role": "assistant", "content": "The part is...", "created_at": "..."}
  ]
}
```

The frontend uses this to rehydrate on page load when a stored
`ps.conversation_id` exists in localStorage.

---

## `DELETE /conversations/{id}`

Hard-delete a conversation and its messages. Returns `204 No Content`.
Used by the "Reset" button in the chat panel.

```bash
curl -X DELETE http://localhost:8000/conversations/<uuid>
```

`404` if the conversation does not exist.

---

## Headers

| Header | Purpose |
|---|---|
| `X-LLM-Provider` | Override the orchestrator's provider for this request. Allowed: `anthropic`, `openai`, `groq`. The header is read in [chat.py](../backend/app/api/chat.py) and threaded to the registry. |
| `X-LLM-Model` | Override the model for the chosen provider. Falls back to the registry's per-(role, provider) default. |
| `X-Conversation-Id` | Exposed for CORS (`expose_headers`). Currently informational; the canonical id arrives in the first SSE `conversation` frame. |

---

## Errors

The route validates `message` via Pydantic (1-4000 chars). A validation
failure returns `422` before the SSE stream opens. Once the stream is open,
mid-stream errors surface as `event: error` frames; the HTTP status remains
`200` (SSE is a long-lived response).

| Surface | Code | When |
|---|---|---|
| Pre-stream `422` | bad request | empty message, message > 4000 chars |
| Pre-stream `500` | DB unreachable | failure persisting the user message |
| SSE `error` frame | provider error | upstream LLM 429 / timeout / refused tool call |
| HTTP `404` | unknown conversation | `GET /conversations/{id}` against a non-existent id |
