"use client";

/**
 * Live LLM provider flip. Reads/writes a value in localStorage that the
 * chat panel (Layer I) attaches as the X-LLM-Provider header on every
 * /chat request. The demo angle: switch from Claude (orchestrator default)
 * to Groq mid-conversation and watch latency drop.
 *
 * Phase 1: cosmetic only (no chat wired yet). Phase I implements the read.
 */

import { useEffect, useState } from "react";

type Provider = "anthropic" | "openai" | "groq" | "default";

const STORAGE_KEY = "ps.llm_provider";

export function ProviderSwitcher() {
  const [provider, setProvider] = useState<Provider>("default");

  useEffect(() => {
    const stored = window.localStorage.getItem(STORAGE_KEY) as Provider | null;
    if (stored) setProvider(stored);
  }, []);

  function update(next: Provider) {
    setProvider(next);
    if (next === "default") {
      window.localStorage.removeItem(STORAGE_KEY);
    } else {
      window.localStorage.setItem(STORAGE_KEY, next);
    }
  }

  return (
    <label className="flex items-center gap-2 text-sm">
      <span className="text-white/80">Model</span>
      <select
        value={provider}
        onChange={(e) => update(e.target.value as Provider)}
        className="rounded-md border border-white/20 bg-ps-blue-dark px-2 py-1 text-sm text-white focus:outline-none focus:ring-2 focus:ring-ps-orange"
        aria-label="Pick the LLM provider"
      >
        <option value="default">Default (Claude)</option>
        <option value="anthropic">Anthropic</option>
        <option value="openai">OpenAI</option>
        <option value="groq">Groq</option>
      </select>
    </label>
  );
}
