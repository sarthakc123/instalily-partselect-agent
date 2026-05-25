/**
 * TypeScript mirror of the backend's OrchestratorEvent union
 * (see `backend/app/agents/state.py`). Kept in lockstep by hand
 * because the contract is small and changes infrequently.
 */

export type LookupPartPayload = {
  tool: "lookup_part";
  status: "exact" | "fuzzy_candidates" | "not_found";
  part: PartCard | null;
  candidates: PartCard[];
  confidence: number;
};

export type PartCard = {
  id: string;
  name: string;
  manufacturer: string;
  appliance_type: string;
  part_type: string;
  price_cents: number;
  in_stock: boolean;
  image_url?: string;
  description?: string;
};

export type CompatVerdict = "yes" | "no" | "unknown" | "inferred";
export type CompatConfidence = "high" | "medium" | "low";

export type CheckCompatibilityPayload = {
  tool: "check_compatibility";
  verdict: CompatVerdict;
  confidence: CompatConfidence;
  part_id: string;
  model_id: string;
  metadata: {
    sub_assembly_only: boolean;
    requires_adapter: boolean;
    supersedes: string | null;
  };
  source: "fitment_table" | "install_guide_inference" | "appliance_type" | null;
  reason: string | null;
  explanation: string;
};

export type InstallGuidePayload = {
  tool: "get_install_guide";
  status: "ok" | "part_not_found" | "no_guide";
  part: PartCard | null;
  guide: {
    id: string;
    part_id: string;
    difficulty: string;
    estimated_minutes: number;
    tools_required: string[];
    safety_warnings: string;
    steps: string[];
    video_url: string;
    series_fitment_hint: string | null;
  } | null;
};

export type FixCandidate = {
  part_id: string;
  part_name: string;
  price_cents: number;
  in_stock: boolean;
  likelihood: number;
  common_cause_rank: number;
  fits_model: boolean | null;
  appliance_type: string;
  brand: string;
};

export type TroubleshootPayload = {
  tool: "troubleshoot";
  status: "ok" | "symptom_unknown" | "escalate_safety" | "ambiguous";
  user_symptom_text: string;
  matched_symptom: {
    symptom_id: string;
    canonical_label: string;
    description: string;
    confidence: number;
  } | null;
  candidate_causes: FixCandidate[];
  recommended_fix: FixCandidate | null;
  confidence: number;
  sources: { table: string; row: Record<string, unknown> }[];
  safety_match: string | null;
  explanation: string;
};

export type FindPartsBySymptomPayload = {
  tool: "find_parts_by_symptom";
  status: "ok" | "symptom_unknown";
  symptom_id: string;
  model_id: string | null;
  candidates: FixCandidate[];
};

export type ToolPayload =
  | LookupPartPayload
  | CheckCompatibilityPayload
  | InstallGuidePayload
  | TroubleshootPayload
  | FindPartsBySymptomPayload
  | { tool: string; [key: string]: unknown };

// --- Discriminated event union from the SSE stream ---

export type OrchestratorEvent =
  | { type: "conversation"; id: string }
  | { type: "text_delta"; content: string }
  | { type: "tool_call"; id: string; name: string; arguments: Record<string, unknown> }
  | { type: "tool_result"; id: string; name: string; payload: ToolPayload }
  | { type: "session"; session: Record<string, unknown> }
  | { type: "usage"; input_tokens: number; output_tokens: number }
  | {
      type: "validator";
      verdict: "pass" | "retry" | "escalate";
      faithfulness_score: number;
      relevance_score: number;
      unsupported_claims: string[];
      reason: string;
    }
  | {
      type: "escalation";
      reason: string;
      summary: string;
      safety_match: string | null;
    }
  | { type: "done"; stop_reason: string }
  | { type: "error"; message: string };

export type ValidatorEvent = Extract<OrchestratorEvent, { type: "validator" }>;
export type EscalationEvent = Extract<OrchestratorEvent, { type: "escalation" }>;

// --- Local chat-message model used by ChatPanel ---

export type ToolCallRef = {
  id: string;
  name: string;
  arguments: Record<string, unknown>;
};

export type UserMessage = { id: string; role: "user"; content: string };

export type AssistantMessage = {
  id: string;
  role: "assistant";
  content: string;
  toolCalls?: ToolCallRef[];
  validator?: ValidatorEvent | null;
  escalation?: EscalationEvent | null;
};

export type ToolMessage = {
  id: string;
  role: "tool";
  toolCallId: string;
  name: string;
  payload: ToolPayload;
};

export type ChatMessage = UserMessage | AssistantMessage | ToolMessage;
