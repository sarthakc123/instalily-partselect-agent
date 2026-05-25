"use client";

/**
 * Collapsible "the agent called X" step. Renders before the assistant's
 * text reply so the user can see what the agent looked up.
 *
 * Layer J replaces the raw-JSON arguments view with a richer per-tool
 * preview; for now we show the function name + a one-line summary of
 * the first argument value.
 */

import { useState } from "react";
import { ChevronRight, Wrench } from "lucide-react";
import { motion } from "framer-motion";

const TOOL_LABELS: Record<string, string> = {
  lookup_part: "Looking up part",
  check_compatibility: "Checking compatibility",
  get_install_guide: "Fetching install guide",
  troubleshoot: "Diagnosing the symptom",
  find_parts_by_symptom: "Finding parts for symptom",
};

export function ToolStep({
  name,
  args,
}: {
  name: string;
  args: Record<string, unknown>;
}) {
  const [open, setOpen] = useState(false);
  const label = TOOL_LABELS[name] ?? name;
  const summary = summarizeArgs(args);

  return (
    <div className="rounded-xl border border-border bg-surface px-3 py-2 text-xs text-muted-foreground">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 text-left"
      >
        <Wrench size={14} className="text-ps-orange shrink-0" />
        <span className="font-medium text-foreground">{label}</span>
        {summary ? <span className="truncate">{summary}</span> : null}
        <motion.span
          animate={{ rotate: open ? 90 : 0 }}
          transition={{ duration: 0.15 }}
          className="ml-auto"
        >
          <ChevronRight size={14} />
        </motion.span>
      </button>
      {open ? (
        <pre className="mt-2 overflow-x-auto rounded-md bg-surface-muted p-2 font-mono text-[11px] text-foreground/80">
          {JSON.stringify(args, null, 2)}
        </pre>
      ) : null}
    </div>
  );
}

function summarizeArgs(args: Record<string, unknown>): string | null {
  const keys = Object.keys(args);
  if (keys.length === 0) return null;
  const parts: string[] = [];
  for (const k of keys) {
    const v = args[k];
    if (typeof v === "string" || typeof v === "number" || typeof v === "boolean") {
      parts.push(`${k}=${v}`);
    }
  }
  return parts.length > 0 ? parts.join("  ") : null;
}
