"use client";

/**
 * Surfaces the cross-family validator's verdict under an assistant message.
 *
 * Verdicts:
 *   - pass     -> green "Verified" badge
 *   - retry    -> amber "Reviewed with concerns" badge (Phase 1 surfaces the
 *                  warning; Phase 2 re-prompts the orchestrator)
 *   - escalate -> red "Escalated for review" badge
 *
 * Includes faithfulness + relevance scores and (on click) the reason string.
 * This is the most visible architectural choice the case study commits to,
 * so the badge is deliberately readable rather than a tiny pill.
 */

import { useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronRight,
  ShieldAlert,
  ShieldCheck,
} from "lucide-react";
import { motion } from "framer-motion";

import type { ValidatorEvent } from "@/lib/types";

const STYLE = {
  pass: {
    wrap: "border-emerald-300 bg-emerald-50 text-emerald-900 dark:border-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-100",
    chip: "bg-emerald-600 text-white",
    Icon: ShieldCheck,
    label: "Verified",
  },
  retry: {
    wrap: "border-amber-300 bg-amber-50 text-amber-900 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-100",
    chip: "bg-amber-600 text-white",
    Icon: AlertTriangle,
    label: "Reviewed with concerns",
  },
  escalate: {
    wrap: "border-rose-300 bg-rose-50 text-rose-900 dark:border-rose-800 dark:bg-rose-950/40 dark:text-rose-100",
    chip: "bg-rose-600 text-white",
    Icon: ShieldAlert,
    label: "Escalated for review",
  },
} as const;


export function ValidatorBadge({ event }: { event: ValidatorEvent }) {
  const style = STYLE[event.verdict];
  const Icon = style.Icon;
  const [open, setOpen] = useState(false);

  return (
    <div
      className={`rounded-xl border px-3 py-2 text-xs shadow-sm ${style.wrap}`}
    >
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 text-left"
      >
        <span
          className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider ${style.chip}`}
        >
          <Icon size={11} />
          {style.label}
        </span>
        <span className="opacity-80">
          faith {fmt(event.faithfulness_score)} · rel {fmt(event.relevance_score)}
        </span>
        <span className="opacity-60 text-[10px]">
          (cross-family grader)
        </span>
        <motion.span
          animate={{ rotate: open ? 90 : 0 }}
          transition={{ duration: 0.15 }}
          className="ml-auto opacity-60"
        >
          <ChevronRight size={12} />
        </motion.span>
      </button>
      {open ? (
        <div className="mt-2 space-y-1 leading-relaxed">
          <div>
            <span className="opacity-70">Reason:</span> {event.reason || "(none)"}
          </div>
          {event.unsupported_claims.length > 0 ? (
            <div>
              <span className="opacity-70">Unsupported claims:</span>
              <ul className="ml-4 list-disc">
                {event.unsupported_claims.map((c, i) => (
                  <li key={i}>{c}</li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function fmt(score: number): string {
  if (!Number.isFinite(score)) return "n/a";
  return score.toFixed(2);
}


export function EscalationBanner({
  reason,
  safety_match,
}: {
  reason: string;
  safety_match: string | null;
}) {
  return (
    <div className="flex items-start gap-2 rounded-xl border border-rose-300 bg-rose-50 px-3 py-2 text-xs text-rose-900 dark:border-rose-800 dark:bg-rose-950/40 dark:text-rose-100">
      <ShieldAlert size={14} className="mt-0.5 shrink-0" />
      <div>
        <div className="font-semibold uppercase tracking-wider text-[10px]">
          Routed for human review
        </div>
        <div className="mt-0.5 leading-relaxed">{reason}</div>
        {safety_match ? (
          <div className="mt-0.5 opacity-80">
            Safety pattern matched: <code>{safety_match}</code>
          </div>
        ) : null}
        <div className="mt-1 text-[10px] opacity-70">
          A full ticket form will land in Phase 2. For now, please contact
          PartSelect support directly.
        </div>
      </div>
    </div>
  );
}
