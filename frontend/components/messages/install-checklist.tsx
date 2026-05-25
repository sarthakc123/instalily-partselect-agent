"use client";

/**
 * Tool 3 (`get_install_guide`) render. Three sub-sections:
 *  - Meta strip (difficulty + time + part header).
 *  - Tools you'll need.
 *  - Safety warning callout (only when present, with an Alert icon).
 *  - Ordered, numbered steps.
 *  - Optional video link.
 */

import {
  AlertOctagon,
  CircleCheck,
  Clock,
  ExternalLink,
  Package,
  Wrench,
} from "lucide-react";

import type { InstallGuidePayload } from "@/lib/types";

const DIFFICULTY_COLOR: Record<string, string> = {
  Easy: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/50 dark:text-emerald-200",
  Moderate: "bg-amber-100 text-amber-800 dark:bg-amber-900/50 dark:text-amber-200",
  Hard: "bg-rose-100 text-rose-800 dark:bg-rose-900/50 dark:text-rose-200",
};

export function InstallChecklist({ p }: { p: InstallGuidePayload }) {
  if (p.status === "part_not_found") {
    return (
      <div className="rounded-2xl border border-border bg-surface-muted p-4 text-sm text-muted-foreground">
        No part found by that number. Please confirm the PS number from your appliance or your order.
      </div>
    );
  }
  if (p.status === "no_guide" || !p.guide) {
    return (
      <div className="rounded-2xl border border-border bg-surface-muted p-4 text-sm">
        <div className="font-medium text-foreground">
          {p.part?.name ?? "Part"} ({p.part?.id})
        </div>
        <div className="mt-1 text-muted-foreground text-xs">
          We do not have install steps for this part. Contact the manufacturer
          or check the part's product page.
        </div>
      </div>
    );
  }

  const g = p.guide;
  const difficultyStyle =
    DIFFICULTY_COLOR[g.difficulty] ?? "bg-surface-muted text-muted-foreground";

  return (
    <article className="overflow-hidden rounded-2xl border border-border bg-surface shadow-sm">
      <header className="flex items-center gap-2 bg-ps-blue/5 px-4 py-2 text-[11px] uppercase tracking-wider text-ps-blue">
        <Wrench size={14} />
        <span>Install guide</span>
      </header>

      {/* Meta strip */}
      <div className="border-b border-border bg-surface-muted/30 px-4 py-3">
        <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
          <Package size={14} className="opacity-70" />
          {p.part?.name}
          <code className="rounded bg-surface-muted px-1.5 py-0.5 font-mono text-[11px]">
            {p.part?.id}
          </code>
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
          <span
            className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${difficultyStyle}`}
          >
            {g.difficulty}
          </span>
          <span className="inline-flex items-center gap-1 text-muted-foreground">
            <Clock size={12} /> {g.estimated_minutes} min
          </span>
        </div>
      </div>

      {/* Tools required */}
      {g.tools_required.length > 0 ? (
        <div className="border-b border-border px-4 py-3">
          <div className="text-[10px] uppercase tracking-wider text-muted-foreground">
            Tools you&apos;ll need
          </div>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {g.tools_required.map((t) => (
              <span
                key={t}
                className="inline-flex items-center gap-1 rounded-md bg-surface-muted px-2 py-0.5 text-[11px] text-foreground"
              >
                <Wrench size={10} className="opacity-50" />
                {t}
              </span>
            ))}
          </div>
        </div>
      ) : null}

      {/* Safety callout */}
      {g.safety_warnings ? (
        <div className="flex items-start gap-2 border-b border-rose-300/40 bg-rose-50 px-4 py-3 text-xs text-rose-900 dark:bg-rose-950/30 dark:text-rose-100">
          <AlertOctagon size={14} className="mt-0.5 shrink-0" />
          <div>
            <div className="font-semibold uppercase tracking-wider text-[10px]">
              Before you start
            </div>
            <div className="mt-0.5 leading-relaxed">{g.safety_warnings}</div>
          </div>
        </div>
      ) : null}

      {/* Steps */}
      <ol className="divide-y divide-border">
        {g.steps.map((step, i) => (
          <li
            key={i}
            className="flex items-start gap-3 px-4 py-2.5 text-sm leading-relaxed"
          >
            <span className="mt-0.5 inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-ps-orange text-[10px] font-semibold text-white">
              {i + 1}
            </span>
            <span className="text-foreground">{step}</span>
          </li>
        ))}
      </ol>

      {/* Footer: video + fitment hint */}
      {(g.video_url || g.series_fitment_hint) ? (
        <footer className="space-y-1 border-t border-border bg-surface-muted/30 px-4 py-2.5 text-[11px]">
          {g.video_url ? (
            <a
              href={g.video_url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-ps-blue hover:underline"
            >
              <ExternalLink size={11} />
              Watch the install video
            </a>
          ) : null}
          {g.series_fitment_hint ? (
            <div className="flex items-start gap-1 text-muted-foreground">
              <CircleCheck size={11} className="mt-0.5 shrink-0 opacity-70" />
              <span>{g.series_fitment_hint}</span>
            </div>
          ) : null}
        </footer>
      ) : null}
    </article>
  );
}
