"use client";

/**
 * Tool 4 (`troubleshoot`) render. Three visual states:
 *   - status='ok'              -> matched symptom + top 3 candidate causes + recommended fix
 *   - status='symptom_unknown' -> compact neutral card
 *   - status='escalate_safety' -> rose safety callout, no troubleshooting
 *
 * Each candidate row is clickable: clicking it asks the orchestrator to
 * check compatibility for that part against the current model (if known)
 * or to fetch its install guide. That keeps the user in the loop without
 * forcing them to re-type the part number.
 */

import {
  AlertOctagon,
  ChevronRight,
  CircleAlert,
  ListChecks,
  Stethoscope,
} from "lucide-react";

import { useChatActions } from "@/components/chat-actions";
import type { FixCandidate, TroubleshootPayload } from "@/lib/types";


export function TroubleshootCard({ p }: { p: TroubleshootPayload }) {
  if (p.status === "escalate_safety") {
    return (
      <div className="flex items-start gap-2 rounded-2xl border border-rose-300 bg-rose-50 p-4 text-sm text-rose-900 dark:border-rose-800 dark:bg-rose-950/40 dark:text-rose-100 shadow-sm">
        <AlertOctagon size={18} className="mt-0.5 shrink-0" />
        <div>
          <div className="font-semibold uppercase tracking-wider text-[11px]">
            Safety-critical: stop and call for help
          </div>
          <div className="mt-1 leading-relaxed">{p.explanation}</div>
          {p.safety_match ? (
            <div className="mt-1 text-[11px] opacity-80">
              Pattern matched: <code>{p.safety_match}</code>
            </div>
          ) : null}
        </div>
      </div>
    );
  }

  if (p.status === "symptom_unknown") {
    return (
      <div className="flex items-start gap-2 rounded-2xl border border-border bg-surface-muted p-3 text-sm text-muted-foreground">
        <CircleAlert size={16} className="mt-0.5 shrink-0" />
        <div>
          <div className="font-medium text-foreground">
            Could not identify the problem
          </div>
          <div className="mt-0.5 text-xs">{p.explanation}</div>
        </div>
      </div>
    );
  }

  const top = p.candidate_causes.slice(0, 3);

  return (
    <article className="overflow-hidden rounded-2xl border border-border bg-surface shadow-sm">
      <header className="flex items-center gap-2 bg-ps-blue/5 px-4 py-2 text-[11px] uppercase tracking-wider text-ps-blue">
        <Stethoscope size={14} />
        <span>Troubleshoot</span>
        <span className="ml-auto opacity-70">
          confidence {(p.confidence * 100).toFixed(0)}%
        </span>
      </header>

      {/* Matched symptom + recommended fix */}
      <div className="space-y-2 px-4 py-3">
        {p.matched_symptom ? (
          <div className="text-sm">
            <span className="text-muted-foreground">Matched symptom: </span>
            <span className="font-medium text-foreground">
              {p.matched_symptom.canonical_label}
            </span>
            <span className="ml-2 text-[11px] text-muted-foreground">
              ({p.matched_symptom.symptom_id})
            </span>
          </div>
        ) : null}
        {p.recommended_fix ? (
          <RecommendedRow c={p.recommended_fix} />
        ) : null}
      </div>

      {/* Other candidate causes */}
      {top.length > 1 ? (
        <div className="border-t border-border">
          <div className="px-4 pt-3 text-[10px] uppercase tracking-wider text-muted-foreground">
            <ListChecks size={11} className="inline opacity-70 mr-1" />
            Other likely causes
          </div>
          <ul className="divide-y divide-border">
            {top
              .filter(
                (c) => p.recommended_fix && c.part_id !== p.recommended_fix.part_id,
              )
              .map((c) => (
                <CandidateRow key={c.part_id} c={c} muted />
              ))}
          </ul>
        </div>
      ) : null}

      {/* Auditable sources footer */}
      {p.sources.length > 0 ? (
        <footer className="border-t border-border bg-surface-muted/30 px-4 py-2 text-[10px] text-muted-foreground">
          Ranking sourced from {p.sources.length} row(s) in{" "}
          <code className="font-mono">symptom_fixes</code> (likelihood +
          common-cause rank).
        </footer>
      ) : null}
    </article>
  );
}

function RecommendedRow({ c }: { c: FixCandidate }) {
  const { send, isStreaming } = useChatActions();
  return (
    <div className="rounded-lg border border-ps-orange/40 bg-ps-orange/5 p-3">
      <div className="flex items-center gap-2 text-[10px] uppercase tracking-wider text-ps-orange">
        <span>Most likely fix</span>
        <span className="opacity-70">
          rank #{c.common_cause_rank} · likelihood {(c.likelihood * 100).toFixed(0)}%
        </span>
        {c.fits_model === true ? (
          <span className="ml-auto rounded-full bg-emerald-600 px-2 py-0.5 text-[10px] font-semibold text-white">
            fits your model
          </span>
        ) : c.fits_model === false ? (
          <span className="ml-auto rounded-full bg-rose-600 px-2 py-0.5 text-[10px] font-semibold text-white">
            does NOT fit your model
          </span>
        ) : null}
      </div>
      <div className="mt-1 text-sm font-semibold text-foreground">
        {c.part_name}
      </div>
      <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
        <code className="rounded bg-surface-muted px-1.5 py-0.5 font-mono text-[11px] text-foreground">
          {c.part_id}
        </code>
        <span>{c.brand}</span>
        <span aria-hidden>·</span>
        <span>${(c.price_cents / 100).toFixed(2)}</span>
        <span aria-hidden>·</span>
        <span className={c.in_stock ? "text-emerald-600" : "text-rose-600"}>
          {c.in_stock ? "in stock" : "out of stock"}
        </span>
      </div>
      <div className="mt-2 flex flex-wrap gap-1.5">
        <button
          type="button"
          disabled={isStreaming}
          onClick={() => send(`How do I install part ${c.part_id}?`)}
          className="inline-flex items-center gap-1 rounded-md bg-ps-blue px-2.5 py-1 text-[11px] font-medium text-white hover:bg-ps-blue-dark disabled:opacity-60 disabled:cursor-not-allowed"
        >
          Show install steps
          <ChevronRight size={11} />
        </button>
      </div>
    </div>
  );
}

function CandidateRow({ c, muted }: { c: FixCandidate; muted?: boolean }) {
  const { send, isStreaming } = useChatActions();
  return (
    <li>
      <button
        type="button"
        disabled={isStreaming}
        onClick={() => send(`Tell me about part ${c.part_id}.`)}
        className={`group flex w-full items-center gap-3 px-4 py-2.5 text-left hover:bg-surface-muted disabled:cursor-not-allowed disabled:opacity-60 ${
          muted ? "text-foreground" : ""
        }`}
      >
        <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-surface-muted text-[10px] font-semibold text-muted-foreground">
          {c.common_cause_rank}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 text-xs">
            <code className="rounded bg-surface-muted px-1.5 py-0.5 font-mono text-[11px] text-foreground">
              {c.part_id}
            </code>
            <span className="text-muted-foreground">
              {(c.likelihood * 100).toFixed(0)}% likely
            </span>
            {c.fits_model === false ? (
              <span className="rounded-full bg-rose-100 px-1.5 py-0.5 text-[10px] font-medium text-rose-700 dark:bg-rose-900/40 dark:text-rose-200">
                does not fit
              </span>
            ) : null}
          </div>
          <div className="mt-0.5 truncate text-sm text-foreground">
            {c.part_name}
          </div>
        </div>
        <ChevronRight
          size={14}
          className="opacity-50 transition-transform group-hover:translate-x-0.5 group-hover:opacity-100"
        />
      </button>
    </li>
  );
}

