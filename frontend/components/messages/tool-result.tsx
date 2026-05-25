"use client";

/**
 * Per-tool rich rendering. Routes a tool_result payload to the right
 * card component. Unknown tools fall through to a JSON preview so we
 * can add new tools without breaking the UI.
 */

import { PackageX } from "lucide-react";

import type {
  CheckCompatibilityPayload,
  FindPartsBySymptomPayload,
  InstallGuidePayload,
  LookupPartPayload,
  ToolPayload,
  TroubleshootPayload,
} from "@/lib/types";

import { CompatBadge } from "./compat-badge";
import { FuzzyConfirmCard } from "./fuzzy-confirm-card";
import { InstallChecklist } from "./install-checklist";
import { ProductCard } from "./product-card";
import { TroubleshootCard } from "./troubleshoot-card";

export function ToolResultRenderer({
  name,
  payload,
}: {
  name: string;
  payload: ToolPayload;
}) {
  if (name === "lookup_part") {
    return <LookupPartResult p={payload as LookupPartPayload} />;
  }
  if (name === "check_compatibility") {
    return <CompatBadge p={payload as CheckCompatibilityPayload} />;
  }
  if (name === "get_install_guide") {
    return <InstallChecklist p={payload as InstallGuidePayload} />;
  }
  if (name === "troubleshoot") {
    return <TroubleshootCard p={payload as TroubleshootPayload} />;
  }
  if (name === "find_parts_by_symptom") {
    return <FindPartsBySymptomResult p={payload as FindPartsBySymptomPayload} />;
  }
  return <UnknownResult name={name} payload={payload} />;
}

function LookupPartResult({ p }: { p: LookupPartPayload }) {
  if (p.status === "exact" && p.part) {
    return <ProductCard part={p.part} />;
  }
  if (p.status === "fuzzy_candidates" && p.candidates.length > 0) {
    return <FuzzyConfirmCard candidates={p.candidates} />;
  }
  return (
    <div className="flex items-center gap-3 rounded-2xl border border-border bg-surface-muted p-4 text-sm text-muted-foreground">
      <PackageX size={18} className="shrink-0 text-rose-500" aria-hidden />
      <div>
        <div className="font-medium text-foreground">No part found</div>
        <div className="text-xs">
          That part number is not in our catalog. Double-check the number and
          try again.
        </div>
      </div>
    </div>
  );
}

function FindPartsBySymptomResult({ p }: { p: FindPartsBySymptomPayload }) {
  // This tool is mostly an intermediate call the orchestrator chains.
  // Compact rendering: just a small note, the troubleshoot card already
  // surfaces the rich version when both run.
  if (p.status === "symptom_unknown") {
    return (
      <div className="rounded-2xl border border-border bg-surface-muted p-3 text-xs text-muted-foreground">
        Found no parts mapped to that symptom.
      </div>
    );
  }
  const top = p.candidates.slice(0, 3);
  return (
    <div className="rounded-2xl border border-border bg-surface p-3 text-xs">
      <div className="mb-1 text-[10px] uppercase tracking-wider text-muted-foreground">
        Candidate parts for <code>{p.symptom_id}</code>
        {p.model_id ? (
          <>
            {" "}
            (model <code>{p.model_id}</code>)
          </>
        ) : null}
      </div>
      <ul className="divide-y divide-border">
        {top.map((c) => (
          <li key={c.part_id} className="flex items-center gap-2 py-1.5">
            <code className="rounded bg-surface-muted px-1.5 py-0.5 font-mono text-[11px]">
              {c.part_id}
            </code>
            <span className="truncate text-sm text-foreground">{c.part_name}</span>
            <span className="ml-auto text-muted-foreground">
              {(c.likelihood * 100).toFixed(0)}%
            </span>
            {c.fits_model === true ? (
              <span className="text-emerald-600">✓ fits</span>
            ) : c.fits_model === false ? (
              <span className="text-rose-600">✗ fits</span>
            ) : null}
          </li>
        ))}
      </ul>
    </div>
  );
}

function UnknownResult({
  name,
  payload,
}: {
  name: string;
  payload: ToolPayload;
}) {
  return (
    <div className="rounded-2xl border border-border bg-surface p-3 text-xs text-muted-foreground">
      <div className="mb-1 text-[10px] uppercase tracking-wider">
        {name} result
      </div>
      <pre className="overflow-x-auto font-mono text-[11px] text-foreground/80">
        {JSON.stringify(payload, null, 2)}
      </pre>
    </div>
  );
}
