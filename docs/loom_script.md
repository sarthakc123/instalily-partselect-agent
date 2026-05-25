# Loom video script — PartSelect Chat Agent submission

Target length: **8 minutes** (within the 6 to 10 minute window from the
Instalily brief). Record on Loom Desktop with HD enabled and the camera
in the corner if comfortable on camera; otherwise screen-only is fine.

For the deck, open [slides.pdf](slides.pdf) in Preview (Mac) presenter
mode. For the live demo, have backend on `:8000` and frontend on `:3000`
already running.

---

## Pre-record checklist

- [ ] Backend up: `cd backend && uvicorn app.main:app --port 8000`
- [ ] Frontend up: `cd frontend && npm run dev`
- [ ] DB seeded: `python -m scripts.seed` (only if first time)
- [ ] KG built: `python -m scripts.build_kg` (only if first time)
- [ ] Browser zoom set to 125% so text reads on Loom playback
- [ ] Chat history cleared (use Reset button)
- [ ] Demo queries pre-typed in a scratch doc (so you don't fumble)
- [ ] Slide deck open in presenter mode in a second window
- [ ] Phone notifications off (do-not-disturb)
- [ ] Editor open to: `backend/app/agents/graph.py`,
      `backend/app/tools/check_compatibility.py`,
      `backend/tests/eval/test_set.yaml`,
      `docs/eval_results.md`
- [ ] `docs/eval_results.md` is the current run (regenerate if stale:
      `python -m tests.eval.run_eval`)

---

## Beat sheet (8 minutes)

### 0:00 - 0:30 · Intro + problem

**On screen:** slides 1 (title) and 2 (problem).

> "Hi, I'm Sarthak Chandarana. This is my Instalily case study
> submission: a customer support chat agent for PartSelect, scoped to
> refrigerator and dishwasher parts. The brief lists four question
> patterns: install lookup, compatibility, troubleshoot, and the
> compound query that chains all three. Today I'll show you what I
> built, why I made the design choices I did, and the seventeen out of
> seventeen eval result."

### 0:30 - 1:15 · The hard query

**On screen:** slide 3 (the real test).

> "The real test is the compound query. One user message, four tool
> calls in a single turn: troubleshoot the symptom, find the candidate
> parts, check that the right one fits the user's model, and pull the
> install guide. If this works, the simpler patterns fall out for free.
> I'll show this working live in a moment."

### 1:15 - 4:30 · Live demo (the main event)

**On screen:** browser at `http://localhost:3000`. Provider switcher
set to `default` (Anthropic orchestrator + Groq validator).

**Demo 1 — Cross-appliance trick (≈45s):**

Type: `Is part PS11752778 compatible with my WDT780SAEM1?`

> "This is the trick case from the brief. PS11752778 is a refrigerator
> ice maker. WDT780SAEM1 is a dishwasher. Many agents will say 'I don't
> see a fitment' which is technically correct but unhelpful. Watch:"

Wait for response. Point at the rose **NO** CompatBadge and the
*appliance type mismatch* phrasing.

> "Notice the agent says exactly why. It's a refrigerator part. The
> model is a dishwasher. That's rung three of the verdict ladder
> firing — structured comparison of appliance types, not LLM judgment."

**Demo 2 — Multi-turn session memory (≈45s):**

Reset. Then turn 1: `Tell me about PS11743427.`

Wait for ProductCard. Then turn 2: `Is it compatible with my WDT780SAEM1?`

> "Turn 2 didn't restate the part. The session carried `last_part` from
> turn 1 forward. The agent picks it up automatically, calls
> check_compatibility, and renders an emerald yes badge."

**Demo 3 — The compound query (≈90s, the most important moment):**

Reset. Type:
`The ice maker on my Whirlpool WRF555SDFZ is broken. What part do I need and how do I install it?`

> "This is the real test. Watch the tool steps unfold."

Wait through the streaming. Point at each tool step as it appears.

> "Troubleshoot maps the symptom to a canonical id, traverses the
> knowledge graph for ranked candidate parts, then check_compatibility
> confirms fit for the user's model, then get_install_guide pulls the
> step-by-step. All in one turn. The reply renders the recommended
> part, the runner-up if the user wants to try the cheaper part first,
> and the full install checklist."

**Demo 4 — Fuzzy SKU + safety (≈30s):**

Reset. Type: `Tell me about PS11752779.` (one digit off)

> "Notice — never silent-swap. The agent returns candidates and asks
> the user to confirm. Hard rule, enforced at the repository return
> type."

Click PS11752778 candidate. Watch the confirmation send and the
ProductCard render.

Reset again. Type: `I smell gas near my fridge.`

> "Safety short-circuit. Pattern match pre-empts the LLM, returns
> escalate-safety, and the agent routes to emergency help. No repair
> walkthrough, even partial."

### 4:30 - 5:30 · Architecture quick tour

**On screen:** slide 4 (architecture diagram).

> "Three things to know about the architecture."

Point at orchestrator.

> "One: one LangGraph orchestrator, five typed tools. Not router-to-
> specialists. The whole action surface is `tools/registry.py`."

Open `backend/app/tools/registry.py`, scroll the dict.

> "Five entries. That's the whole vocabulary."

Open `backend/app/tools/check_compatibility.py`, scroll to the verdict
ladder comment.

> "Two: compatibility comes from a structured edge lookup. Five-rung
> verdict ladder. Prose inference is rung four, marked as
> medium-confidence, and gated by the validator. We never silently
> let the LLM hallucinate a compat verdict."

Open `backend/app/agents/graph.py`.

> "Three: validator is a different LLM family. Selective trigger on
> high-risk paths. Conditional edge after the validator routes
> pass-retry-escalate. Retry is capped at one."

### 5:30 - 6:15 · Design choices, condensed

**On screen:** slides 5, 6, 7 (cycle through quickly).

> "Four big design choices, then the eval."

Slide 5: "Orchestrator + typed tools, not specialists. Every action is
auditable."

Slide 6: "KG as structured backbone, not GraphRAG. Compatibility from
edges, not prose."

Slide 7: "Six hard rules. No em dashes, PII boundary, structured
compat, safety short-circuit, no fuzzy silent-swap, validator never
silently passes."

### 6:15 - 6:45 · Provider gateway demo

**On screen:** slide 8, then back to browser.

> "Provider-agnostic gateway. One event union, three providers."

Open browser. Click the ProviderSwitcher in the header. Pick `groq`.

> "Now the orchestrator is running on Llama 3.3 70B via Groq. Same
> agent code, different provider header per request. This is the
> rate-limit insurance. If a provider 429s in production, we flip."

Send a quick query (`Tell me about PS11752778.`) to show it works.

### 6:45 - 7:30 · Eval results

**On screen:** slide 9 (eval), then `docs/eval_results.md` in a Markdown
preview.

> "Seventeen out of seventeen on the eval. Every category covered:
> install, compatibility through all five rungs, troubleshoot,
> compound, edge cases, out of scope, prompt injection, and the
> validator firing on the inferred path."

Scroll to the cross-appliance reply in `eval_results.md`.

> "Every reply is captured verbatim. Reviewable. The methodology is
> deterministic checks over tool payloads and final text, not
> LLM-as-judge. When something regresses, you know exactly which
> assertion broke."

### 7:30 - 7:50 · Business impact

**On screen:** slide 10.

> "Three categories of value. Deflection on the order of a couple of
> million dollars annually at PartSelect scale. Conversion lift from
> confident, explained compatibility. And enterprise-sales unlock from
> the hard rules — PII boundary and safety escalation are the failure
> modes that get a vendor removed from a procurement shortlist."

### 7:50 - 8:30 · Scaling roadmap + close

**On screen:** slide 11 (roadmap), then slide 12 (closing).

> "The architecture has explicit seams. Real PartSelect scrape, hybrid
> RAG behind a VectorStore protocol, Neo4j behind the KnowledgeGraph
> protocol, hosted demo on Vercel plus Fly. Each phase is a drop-in,
> not a rebuild."

Slide 12.

> "Source code is on GitHub. README has the quickstart, eval report
> regenerates from the test set, and the architecture doc goes into
> depth on every choice. Thanks for watching. Happy to walk through
> the code live."

---

## Editing notes (post-record)

- **Trim dead air** before each demo while typing — keep the demo
  punchy.
- **Add captions** for the four hard query examples (Loom auto-caption
  is fine for this).
- **First-frame screenshot** should be the chat panel with the
  cross-appliance result visible (most striking single image).
- **Description text** for the Loom share:
  > Instalily case study: PartSelect chat agent. 17/17 eval. Live demo
  > of the compound query and cross-appliance trick. Source:
  > github.com/sarthakc123/instalily-partselect-agent
- **Visibility**: unlisted link is fine for submission. Add the link to
  the top of `README.md` after recording.

---

## If anything goes wrong on the take

| Symptom | Fix |
|---|---|
| Backend returns 502 | Check uvicorn is still running. Restart: `uvicorn app.main:app --reload --port 8000` |
| Compound query times out | Groq free tier 429. Switch to Anthropic via the ProviderSwitcher, re-run. |
| Provider switcher doesn't show options | Check `.env` has multiple API keys set. |
| Reset button doesn't clear | Hard refresh the browser (Cmd-Shift-R), then localStorage clear via DevTools. |
| Eval markdown looks stale | `cd backend && python -m tests.eval.run_eval` to regenerate. |
