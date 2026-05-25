/**
 * localStorage helpers for the resumable chat. The frontend remembers two
 * things across reloads:
 *   - the current conversation_id (so the next /chat call hits the same row)
 *   - the chosen LLM provider override (read by the chat transport on every send)
 */

export const CONVERSATION_KEY = "ps.conversation_id";
export const PROVIDER_KEY = "ps.llm_provider";

export function getConversationId(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(CONVERSATION_KEY);
}

export function setConversationId(id: string): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(CONVERSATION_KEY, id);
}

export function clearConversationId(): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(CONVERSATION_KEY);
}

export function getProvider(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(PROVIDER_KEY);
}
