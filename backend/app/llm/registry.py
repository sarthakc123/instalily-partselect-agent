"""Role-based provider selection + per-request override.

Roles:
  - orchestrator: tool-using LLM that drives the conversation (Claude Sonnet 4.6 default)
  - validator:    different family from orchestrator (GPT-4o default)
  - utility:      cheap/fast (Groq Llama 3.1 8B default)

Per-request override: the frontend sends `X-LLM-Provider: anthropic|openai|groq`.
The orchestrator graph threads that into `get_provider("orchestrator",
override_provider=...)`. We then pick a model appropriate for that role on
that provider via the `_ROLE_PROVIDER_MODELS` table (e.g. orchestrator-on-Groq
should NOT fall back to the tiny utility model; scope leaks under prompt
injection on a small model).
"""

from __future__ import annotations

from typing import Literal

from app.config import settings
from app.llm.base import LLMProvider

Role = Literal["orchestrator", "validator", "utility"]
ProviderName = Literal["anthropic", "openai", "groq"]


# Default provider per role (from env).
_ROLE_DEFAULTS: dict[Role, ProviderName] = {
    "orchestrator": settings.llm_orchestrator_provider,  # type: ignore[dict-item]
    "validator": settings.llm_validator_provider,        # type: ignore[dict-item]
    "utility": settings.llm_utility_provider,            # type: ignore[dict-item]
}


# Model per (role, provider). The diagonal (role's native provider) uses the
# env-configured model; off-diagonal entries pick a model appropriate to the
# role on the other provider. Critical: orchestrator-on-Groq picks the 70B
# model, not the 8B utility model, or scope adherence collapses under
# prompt injection.
_ROLE_PROVIDER_MODELS: dict[tuple[Role, ProviderName], str] = {
    ("orchestrator", "anthropic"): settings.llm_orchestrator_model,
    ("orchestrator", "openai"): "gpt-4o",
    ("orchestrator", "groq"): "llama-3.3-70b-versatile",

    ("validator", "anthropic"): "claude-haiku-4-5-20251001",
    ("validator", "openai"): settings.llm_validator_model,
    # OpenAI's open-weight gpt-oss-20b hosted on Groq: different LLM family
    # from the Llama orchestrator, satisfying the spec's cross-family
    # diversity requirement without needing a second provider key. 20B is
    # plenty for JSON grading and the output is clean (no reasoning tags).
    ("validator", "groq"): "openai/gpt-oss-20b",

    ("utility", "anthropic"): "claude-haiku-4-5-20251001",
    ("utility", "openai"): "gpt-4o-mini",
    ("utility", "groq"): settings.llm_utility_model,
}


def _build(provider: ProviderName, model: str) -> LLMProvider:
    if provider == "anthropic":
        from app.llm.anthropic_provider import AnthropicProvider
        return AnthropicProvider(model=model)
    if provider == "openai":
        from app.llm.openai_provider import OpenAIProvider
        return OpenAIProvider(model=model)
    if provider == "groq":
        from app.llm.groq_provider import GroqProvider
        return GroqProvider(model=model)
    raise ValueError(f"Unknown provider: {provider}")


def get_provider(
    role: Role,
    *,
    override_provider: ProviderName | None = None,
    override_model: str | None = None,
) -> LLMProvider:
    """Return a configured provider for the given role.

    Resolution:
      1. provider = override_provider or role default
      2. model    = override_model or _ROLE_PROVIDER_MODELS[(role, provider)]
    """
    provider: ProviderName = override_provider or _ROLE_DEFAULTS[role]
    model = override_model or _ROLE_PROVIDER_MODELS[(role, provider)]
    return _build(provider, model)
