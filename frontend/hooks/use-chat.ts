"use client";

/**
 * The chat hook. Holds the message list + streaming state, drives the
 * /chat SSE transport, and persists conversation_id to localStorage so
 * a page reload resumes where the user left off.
 *
 * Message-array invariant: assistant messages and tool messages are
 * interleaved in chronological order. When a tool_result event arrives,
 * we close the current assistant message (any subsequent text_deltas go
 * into a fresh assistant message). This mirrors the backend persistence
 * shape and keeps the round-trip clean.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { v4 as uuid } from "uuid";

import {
  clearConversationId,
  getConversationId,
  setConversationId,
} from "@/lib/conversation";
import {
  deleteConversation,
  fetchConversation,
  sendChat,
} from "@/lib/transport";
import type {
  AssistantMessage,
  ChatMessage,
  EscalationEvent,
  ToolPayload,
  ValidatorEvent,
} from "@/lib/types";

export type ChatStatus = "idle" | "streaming" | "error";

export type UseChat = {
  messages: ChatMessage[];
  status: ChatStatus;
  error: string | null;
  conversationId: string | null;
  send: (text: string) => void;
  reset: () => void;
};

export function useChat(): UseChat {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [status, setStatus] = useState<ChatStatus>("idle");
  const [error, setError] = useState<string | null>(null);
  const [conversationId, setConvId] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const cursorIdRef = useRef<string | null>(null);

  // Restore prior conversation on mount.
  useEffect(() => {
    const stored = getConversationId();
    if (!stored) return;
    setConvId(stored);
    let cancelled = false;
    (async () => {
      try {
        const conv = await fetchConversation(stored);
        if (cancelled) return;
        setMessages(rehydrate(conv.messages));
      } catch {
        // Stored id may be stale (server wiped); start fresh.
        clearConversationId();
        setConvId(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const reset = useCallback(async () => {
    abortRef.current?.abort();
    const id = conversationId;
    setMessages([]);
    setStatus("idle");
    setError(null);
    setConvId(null);
    clearConversationId();
    if (id) {
      try {
        await deleteConversation(id);
      } catch {
        // best-effort; ignore network error here
      }
    }
  }, [conversationId]);

  const send = useCallback(
    (text: string) => {
      const trimmed = text.trim();
      if (!trimmed || status === "streaming") return;

      const controller = new AbortController();
      abortRef.current?.abort();
      abortRef.current = controller;

      // Append user message and an empty assistant cursor immediately so the
      // UI updates before the first byte arrives.
      const cursorId = uuid();
      cursorIdRef.current = cursorId;
      setMessages((prev) => [
        ...prev,
        { id: uuid(), role: "user", content: trimmed },
        { id: cursorId, role: "assistant", content: "" } satisfies AssistantMessage,
      ]);
      setStatus("streaming");
      setError(null);

      (async () => {
        try {
          for await (const ev of sendChat({
            message: trimmed,
            conversationId,
            signal: controller.signal,
          })) {
            switch (ev.type) {
              case "conversation": {
                if (!conversationId) {
                  setConvId(ev.id);
                  setConversationId(ev.id);
                }
                break;
              }
              case "text_delta": {
                appendToCursor(setMessages, cursorIdRef, ev.content);
                break;
              }
              case "tool_call": {
                attachToolCall(setMessages, cursorIdRef, {
                  id: ev.id,
                  name: ev.name,
                  arguments: ev.arguments,
                });
                break;
              }
              case "tool_result": {
                // Close current assistant cursor, push the tool message,
                // then open a fresh cursor for the continuation text.
                const nextCursor = uuid();
                cursorIdRef.current = nextCursor;
                setMessages((prev) => [
                  ...prev,
                  {
                    id: uuid(),
                    role: "tool",
                    toolCallId: ev.id,
                    name: ev.name,
                    payload: ev.payload as ToolPayload,
                  },
                  { id: nextCursor, role: "assistant", content: "" },
                ]);
                break;
              }
              case "session":
              case "usage": {
                // not surfaced in the message list for v1
                break;
              }
              case "validator": {
                attachValidator(setMessages, cursorIdRef, ev);
                break;
              }
              case "escalation": {
                attachEscalation(setMessages, cursorIdRef, ev);
                break;
              }
              case "done": {
                setStatus("idle");
                // Drop trailing empty assistant message if any.
                setMessages((prev) => {
                  if (prev.length === 0) return prev;
                  const last = prev[prev.length - 1];
                  if (
                    last.role === "assistant" &&
                    !last.content &&
                    !last.toolCalls?.length
                  ) {
                    return prev.slice(0, -1);
                  }
                  return prev;
                });
                break;
              }
              case "error": {
                setStatus("error");
                setError(ev.message);
                break;
              }
            }
          }
          // Stream ended without an explicit done (treat as idle).
          setStatus((s) => (s === "streaming" ? "idle" : s));
        } catch (err) {
          if (controller.signal.aborted) return;
          setStatus("error");
          setError(String(err));
        }
      })();
    },
    [conversationId, status],
  );

  return { messages, status, error, conversationId, send, reset };
}

// --- helpers ---

function appendToCursor(
  setMessages: React.Dispatch<React.SetStateAction<ChatMessage[]>>,
  cursorRef: React.MutableRefObject<string | null>,
  text: string,
) {
  setMessages((prev) => {
    const cursorId = cursorRef.current;
    if (!cursorId) return prev;
    return prev.map((m) =>
      m.id === cursorId && m.role === "assistant"
        ? { ...m, content: m.content + text }
        : m,
    );
  });
}

function attachToolCall(
  setMessages: React.Dispatch<React.SetStateAction<ChatMessage[]>>,
  cursorRef: React.MutableRefObject<string | null>,
  call: { id: string; name: string; arguments: Record<string, unknown> },
) {
  setMessages((prev) => {
    const cursorId = cursorRef.current;
    if (!cursorId) return prev;
    return prev.map((m) =>
      m.id === cursorId && m.role === "assistant"
        ? { ...m, toolCalls: [...(m.toolCalls ?? []), call] }
        : m,
    );
  });
}

function attachValidator(
  setMessages: React.Dispatch<React.SetStateAction<ChatMessage[]>>,
  cursorRef: React.MutableRefObject<string | null>,
  event: ValidatorEvent,
) {
  setMessages((prev) => {
    const cursorId = cursorRef.current;
    if (!cursorId) return prev;
    return prev.map((m) =>
      m.id === cursorId && m.role === "assistant"
        ? { ...m, validator: event }
        : m,
    );
  });
}

function attachEscalation(
  setMessages: React.Dispatch<React.SetStateAction<ChatMessage[]>>,
  cursorRef: React.MutableRefObject<string | null>,
  event: EscalationEvent,
) {
  setMessages((prev) => {
    const cursorId = cursorRef.current;
    if (!cursorId) return prev;
    return prev.map((m) =>
      m.id === cursorId && m.role === "assistant"
        ? { ...m, escalation: event }
        : m,
    );
  });
}

/**
 * Convert server-loaded message rows into our local ChatMessage shape.
 * Tool messages on the server stash {tool_call_id, tool_name} in the
 * tool_calls JSONB column and put the JSON-stringified payload in content.
 */
function rehydrate(
  rows: Array<{
    role: string;
    content: string;
    tool_calls?: unknown;
    tool_call_id?: string;
    tool_name?: string;
  }>,
): ChatMessage[] {
  const out: ChatMessage[] = [];
  for (const r of rows) {
    if (r.role === "user") {
      out.push({ id: uuid(), role: "user", content: r.content });
    } else if (r.role === "assistant") {
      const calls = Array.isArray(r.tool_calls)
        ? (r.tool_calls as Array<{
            id: string;
            name: string;
            arguments: Record<string, unknown>;
          }>)
        : undefined;
      out.push({
        id: uuid(),
        role: "assistant",
        content: r.content,
        toolCalls: calls,
      });
    } else if (r.role === "tool") {
      let payload: ToolPayload;
      try {
        payload = JSON.parse(r.content) as ToolPayload;
      } catch {
        payload = { tool: r.tool_name ?? "unknown" };
      }
      out.push({
        id: uuid(),
        role: "tool",
        toolCallId: r.tool_call_id ?? "",
        name: r.tool_name ?? payload.tool ?? "unknown",
        payload,
      });
    }
  }
  return out;
}
