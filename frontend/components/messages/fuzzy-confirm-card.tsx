"use client";

/**
 * When lookup_part returns fuzzy_candidates, render an actionable list.
 * Clicking a candidate sends a confirmation message ("Use PS11752778")
 * back through the chat, which the orchestrator interprets as the user
 * picking that part.
 *
 * This makes the spec's "never silent-swap on fuzzy match" rule
 * user-friendly: the user is in the loop, but the UX is one click.
 */

import { ChevronRight, HelpCircle, Package } from "lucide-react";

import { useChatActions } from "@/components/chat-actions";
import type { PartCard } from "@/lib/types";

export function FuzzyConfirmCard({ candidates }: { candidates: PartCard[] }) {
  const { send, isStreaming } = useChatActions();

  function pick(part: PartCard) {
    if (isStreaming) return;
    // Phrase the follow-up so the orchestrator can disambiguate cleanly.
    send(`I meant ${part.id} (${part.name}). Please continue with that one.`);
  }

  return (
    <article className="overflow-hidden rounded-2xl border border-amber-300 bg-amber-50 text-amber-900 shadow-sm dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-100">
      <header className="flex items-center gap-2 border-b border-amber-200 px-4 py-2 text-[11px] uppercase tracking-wider dark:border-amber-800/60">
        <HelpCircle size={14} />
        <span>Did you mean one of these?</span>
      </header>
      <ul className="divide-y divide-amber-200 dark:divide-amber-800/60">
        {candidates.map((c) => (
          <li key={c.id}>
            <button
              type="button"
              onClick={() => pick(c)}
              disabled={isStreaming}
              className="group flex w-full items-center gap-3 px-4 py-2.5 text-left hover:bg-amber-100/70 disabled:cursor-not-allowed disabled:opacity-60 dark:hover:bg-amber-900/40"
            >
              <Package size={14} className="shrink-0 opacity-70" />
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2 text-xs">
                  <code className="rounded bg-white/70 px-1.5 py-0.5 font-mono text-[11px] dark:bg-black/20">
                    {c.id}
                  </code>
                  <span className="text-amber-700 dark:text-amber-300">
                    {c.manufacturer}
                  </span>
                </div>
                <div className="mt-0.5 truncate text-sm font-medium">
                  {c.name}
                </div>
              </div>
              <ChevronRight
                size={14}
                className="opacity-50 transition-transform group-hover:translate-x-0.5 group-hover:opacity-100"
              />
            </button>
          </li>
        ))}
      </ul>
      <footer className="px-4 py-2 text-[11px] opacity-70">
        Pick a part to confirm. We never assume a fuzzy match.
      </footer>
    </article>
  );
}
