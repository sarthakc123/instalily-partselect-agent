"use client";

/**
 * Lets in-chat components (FuzzyConfirmCard, CompatBadge follow-ups,
 * future ProductCard "Add to cart") send a follow-up turn without the
 * chat hook being prop-drilled through four layers.
 *
 * Provider is mounted in ChatPanel; consumers read it via useChatActions.
 */

import { createContext, useContext } from "react";

export type ChatActions = {
  send: (text: string) => void;
  isStreaming: boolean;
};

const ChatActionsContext = createContext<ChatActions | null>(null);

export const ChatActionsProvider = ChatActionsContext.Provider;

export function useChatActions(): ChatActions {
  const ctx = useContext(ChatActionsContext);
  if (!ctx) {
    // Render-safe fallback so components don't crash in storybook-style
    // previews. Real usage always wraps in the provider.
    return { send: () => {}, isStreaming: false };
  }
  return ctx;
}
