/**
 * Custom chat transport. Posts to the FastAPI /chat endpoint, parses the
 * SSE stream into our typed event union, attaches the live provider header,
 * and exposes a cancel handle.
 */

import { getProvider } from "./conversation";
import { parseSSE } from "./sse";
import type { OrchestratorEvent } from "./types";

const DEFAULT_BACKEND_URL = "http://localhost:8000";

function backendUrl(): string {
  // NEXT_PUBLIC_ makes it available in the browser bundle.
  return process.env.NEXT_PUBLIC_BACKEND_URL || DEFAULT_BACKEND_URL;
}

export type SendChatArgs = {
  message: string;
  conversationId?: string | null;
  signal?: AbortSignal;
};

/** Open the /chat SSE stream and yield typed events as they arrive. */
export async function* sendChat({
  message,
  conversationId,
  signal,
}: SendChatArgs): AsyncGenerator<OrchestratorEvent> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    Accept: "text/event-stream",
  };
  const provider = getProvider();
  if (provider && provider !== "default") {
    headers["X-LLM-Provider"] = provider;
  }

  const body = JSON.stringify({
    message,
    conversation_id: conversationId ?? undefined,
  });

  const response = await fetch(`${backendUrl()}/chat`, {
    method: "POST",
    headers,
    body,
    signal,
  });

  if (!response.ok) {
    const text = await response.text().catch(() => "");
    throw new Error(`Backend ${response.status}: ${text || response.statusText}`);
  }

  yield* parseSSE(response, signal);
}

/** Server-side conversation purge (used by the Reset button). */
export async function deleteConversation(conversationId: string): Promise<void> {
  await fetch(`${backendUrl()}/conversations/${conversationId}`, {
    method: "DELETE",
  });
}

/** One-shot fetch of a stored conversation. Used to rehydrate on page load. */
export async function fetchConversation(conversationId: string): Promise<{
  id: string;
  session: Record<string, unknown>;
  messages: Array<{
    role: string;
    content: string;
    tool_calls?: unknown;
    tool_call_id?: string;
    tool_name?: string;
  }>;
}> {
  const res = await fetch(
    `${backendUrl()}/conversations/${conversationId}`,
  );
  if (!res.ok) {
    throw new Error(`Backend ${res.status}: ${res.statusText}`);
  }
  return res.json();
}
