"""Load prompt files from disk and substitute session variables."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

_PROMPT_DIR = Path(__file__).parent


@lru_cache(maxsize=8)
def _read(name: str) -> str:
    return (_PROMPT_DIR / f"{name}.md").read_text(encoding="utf-8")


def render(name: str, **vars: Any) -> str:
    """Minimal {{var}} substitution. Unsupplied vars render as '(not set)'."""
    text = _read(name)
    for key, value in vars.items():
        text = text.replace("{{" + key + "}}", str(value) if value is not None else "(not set)")
    # Any remaining placeholders become "(not set)".
    import re
    return re.sub(r"\{\{[a-zA-Z_]+\}\}", "(not set)", text)
