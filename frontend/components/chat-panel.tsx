"use client";

import { useEffect, useRef, useState } from "react";
import { Loader2, RotateCcw, Send } from "lucide-react";
import { motion } from "framer-motion";

import { ChatActionsProvider } from "@/components/chat-actions";
import { useChat } from "@/hooks/use-chat";

import { MessageBubble } from "./messages/message-bubble";

export function ChatPanel() {
  const { messages, status, error, conversationId, send, reset } = useChat();
  const isStreaming = status === "streaming";
  const [input, setInput] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, status]);

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!input.trim() || status === "streaming") return;
    send(input);
    setInput("");
  }

  return (
    <ChatActionsProvider value={{ send, isStreaming }}>
    <section className="flex min-h-[28rem] flex-1 flex-col rounded-2xl border border-border bg-surface shadow-sm">
      {/* Status strip */}
      <div className="flex items-center justify-between border-b border-border px-4 py-2 text-xs text-muted-foreground">
        <span>
          {conversationId
            ? `Conversation #${conversationId.slice(0, 8)}`
            : "New conversation"}
        </span>
        <button
          type="button"
          onClick={reset}
          className="flex items-center gap-1 rounded-md px-2 py-1 hover:bg-surface-muted"
        >
          <RotateCcw size={12} />
          Reset
        </button>
      </div>

      {/* Messages */}
      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto px-4 py-4 space-y-3"
      >
        {messages.length === 0 ? (
          <EmptyState />
        ) : (
          messages.map((m) => <MessageBubble key={m.id} message={m} />)
        )}
        {status === "streaming" ? (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="flex items-center gap-2 text-xs text-muted-foreground"
          >
            <Loader2 size={12} className="animate-spin" />
            <span>Thinking...</span>
          </motion.div>
        ) : null}
        {error ? (
          <div className="rounded-lg border border-rose-300 bg-rose-50 px-3 py-2 text-xs text-rose-900 dark:bg-rose-950/30 dark:text-rose-200">
            {error}
          </div>
        ) : null}
      </div>

      {/* Composer */}
      <form
        onSubmit={handleSubmit}
        className="border-t border-border p-3 flex gap-2"
      >
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask about a part, model, or problem..."
          disabled={status === "streaming"}
          className="flex-1 rounded-lg border border-border bg-surface-muted px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground/70 focus:outline-none focus:ring-2 focus:ring-ps-orange/60"
        />
        <button
          type="submit"
          disabled={status === "streaming" || !input.trim()}
          className="inline-flex items-center gap-1.5 rounded-lg bg-ps-orange px-4 py-2 text-sm font-medium text-white shadow-sm transition-colors hover:bg-ps-orange-dark disabled:cursor-not-allowed disabled:opacity-60"
        >
          {status === "streaming" ? (
            <Loader2 size={14} className="animate-spin" />
          ) : (
            <Send size={14} />
          )}
          Send
        </button>
      </form>
    </section>
    </ChatActionsProvider>
  );
}

function EmptyState() {
  return (
    <div className="flex h-full items-center justify-center text-center">
      <div className="max-w-sm text-sm text-muted-foreground">
        Try one of the prompts above, or ask about a part number, a model
        compatibility check, or a repair you are trying to do.
      </div>
    </div>
  );
}
