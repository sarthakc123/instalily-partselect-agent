"use client";

import { motion } from "framer-motion";

import type { ChatMessage } from "@/lib/types";

import { ToolStep } from "./tool-step";
import { ToolResultRenderer } from "./tool-result";
import { EscalationBanner, ValidatorBadge } from "./validator-badge";

export function MessageBubble({ message }: { message: ChatMessage }) {
  if (message.role === "user") {
    return (
      <motion.div
        initial={{ opacity: 0, y: 6 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.18 }}
        className="flex justify-end"
      >
        <div className="max-w-[80%] rounded-2xl bg-ps-blue px-4 py-2.5 text-ps-blue-fg shadow-sm">
          <p className="whitespace-pre-wrap text-sm leading-relaxed">
            {message.content}
          </p>
        </div>
      </motion.div>
    );
  }

  if (message.role === "tool") {
    return (
      <motion.div
        initial={{ opacity: 0, y: 6 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.18 }}
        className="flex justify-start"
      >
        <div className="w-full max-w-[92%]">
          <ToolResultRenderer name={message.name} payload={message.payload} />
        </div>
      </motion.div>
    );
  }

  // assistant
  const hasContent = message.content.length > 0;
  const hasToolCalls = (message.toolCalls?.length ?? 0) > 0;
  const hasValidator = !!message.validator;
  const hasEscalation = !!message.escalation;
  if (!hasContent && !hasToolCalls && !hasValidator && !hasEscalation) {
    return null;
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.18 }}
      className="flex justify-start"
    >
      <div className="max-w-[88%] space-y-2">
        {message.toolCalls?.map((tc) => (
          <ToolStep
            key={tc.id}
            name={tc.name}
            args={tc.arguments}
          />
        ))}
        {hasContent ? (
          <div className="rounded-2xl bg-surface-muted px-4 py-2.5 text-foreground shadow-sm border border-border">
            <p className="whitespace-pre-wrap text-sm leading-relaxed">
              {message.content}
            </p>
          </div>
        ) : null}
        {hasValidator ? <ValidatorBadge event={message.validator!} /> : null}
        {hasEscalation ? (
          <EscalationBanner
            reason={message.escalation!.reason}
            safety_match={message.escalation!.safety_match}
          />
        ) : null}
      </div>
    </motion.div>
  );
}
