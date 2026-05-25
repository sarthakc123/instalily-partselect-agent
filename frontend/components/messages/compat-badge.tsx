"use client";

import {
  AlertCircle,
  ArrowRight,
  CheckCircle2,
  HelpCircle,
  Refrigerator,
  ShieldQuestion,
  XCircle,
} from "lucide-react";

import type { CheckCompatibilityPayload } from "@/lib/types";

const VERDICT_STYLES = {
  yes: {
    border: "border-emerald-300",
    bg: "bg-emerald-50",
    text: "text-emerald-900",
    pill: "bg-emerald-600 text-white",
    icon: CheckCircle2,
    label: "Compatible",
    dark: "dark:border-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-100",
  },
  no: {
    border: "border-rose-300",
    bg: "bg-rose-50",
    text: "text-rose-900",
    pill: "bg-rose-600 text-white",
    icon: XCircle,
    label: "Not compatible",
    dark: "dark:border-rose-800 dark:bg-rose-950/40 dark:text-rose-100",
  },
  inferred: {
    border: "border-amber-300",
    bg: "bg-amber-50",
    text: "text-amber-900",
    pill: "bg-amber-600 text-white",
    icon: AlertCircle,
    label: "Likely fits (unverified)",
    dark: "dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-100",
  },
  unknown: {
    border: "border-border",
    bg: "bg-surface-muted",
    text: "text-muted-foreground",
    pill: "bg-muted-foreground text-white",
    icon: HelpCircle,
    label: "Cannot confirm",
    dark: "",
  },
} as const;

export function CompatBadge({ p }: { p: CheckCompatibilityPayload }) {
  const style = VERDICT_STYLES[p.verdict];
  const Icon = style.icon;
  const isMismatch = p.reason === "appliance_type_mismatch";

  return (
    <article
      className={`overflow-hidden rounded-2xl border ${style.border} ${style.bg} ${style.text} ${style.dark} shadow-sm`}
    >
      {/* Verdict pill */}
      <div className="flex items-center gap-2 px-4 pt-3 pb-1">
        <span
          className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[11px] font-semibold uppercase tracking-wider ${style.pill}`}
        >
          <Icon size={12} />
          {style.label}
        </span>
        <span className="text-[11px] uppercase tracking-wider opacity-70">
          {p.confidence} confidence
        </span>
      </div>

      {/* Part -> Model edge visualization */}
      <div className="flex items-center gap-2 px-4 pt-1 pb-3 text-sm">
        <code className="rounded bg-white/60 px-2 py-0.5 font-mono text-xs dark:bg-white/10">
          {p.part_id}
        </code>
        <ArrowRight size={14} className="opacity-60" />
        <code className="rounded bg-white/60 px-2 py-0.5 font-mono text-xs dark:bg-white/10">
          {p.model_id}
        </code>
      </div>

      {/* Cross-appliance callout (the case-study trick) */}
      {isMismatch ? <MismatchVisual /> : null}

      {/* Explanation */}
      {p.explanation ? (
        <p className="px-4 pb-3 text-xs leading-relaxed">{p.explanation}</p>
      ) : null}

      {/* Metadata chips */}
      {(p.metadata.supersedes ||
        p.metadata.requires_adapter ||
        p.metadata.sub_assembly_only ||
        p.source === "install_guide_inference") && (
        <div className="flex flex-wrap gap-1.5 border-t border-current/20 bg-white/30 px-4 py-2 text-[11px] dark:bg-black/10">
          {p.metadata.supersedes ? (
            <Chip>Supersedes {p.metadata.supersedes}</Chip>
          ) : null}
          {p.metadata.requires_adapter ? <Chip>Requires adapter</Chip> : null}
          {p.metadata.sub_assembly_only ? (
            <Chip>Sub-assembly only</Chip>
          ) : null}
          {p.source === "install_guide_inference" ? (
            <Chip>
              <ShieldQuestion size={10} className="inline" /> Inferred from install guide
            </Chip>
          ) : null}
        </div>
      )}
    </article>
  );
}

function Chip({ children }: { children: React.ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-white/70 px-2 py-0.5 dark:bg-black/20">
      {children}
    </span>
  );
}

function MismatchVisual() {
  return (
    <div className="mx-4 mb-3 rounded-lg border border-current/20 bg-white/40 p-2 text-[11px] dark:bg-black/15">
      <div className="flex items-center justify-around">
        <div className="flex flex-col items-center gap-0.5">
          <Refrigerator size={20} aria-hidden />
          <span className="opacity-80">Refrigerator part</span>
        </div>
        <XCircle size={16} className="opacity-60" />
        <div className="flex flex-col items-center gap-0.5">
          <svg
            width="20"
            height="20"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.8"
            aria-hidden
          >
            <rect x="4" y="3" width="16" height="18" rx="2" />
            <line x1="4" y1="9" x2="20" y2="9" />
            <circle cx="8" cy="6" r="0.7" fill="currentColor" />
          </svg>
          <span className="opacity-80">Dishwasher model</span>
        </div>
      </div>
    </div>
  );
}
