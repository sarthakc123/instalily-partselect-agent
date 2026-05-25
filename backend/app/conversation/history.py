"""History windowing for chat context.

Rule: trim long conversations to keep prompts small, but never split a
tool-call sequence. The LLM sees a tool_call id without its matching
tool_result and breaks. So we always truncate at a user-message boundary.
"""

from __future__ import annotations

from typing import Any


def truncate_history(
    messages: list[dict[str, Any]],
    *,
    max_messages: int = 24,
) -> list[dict[str, Any]]:
    """Keep at most `max_messages` messages, sliced so the first message in
    the returned list is a `user` message. Drops only from the front; the
    tail (most recent turns) is always preserved.
    """
    if len(messages) <= max_messages:
        return list(messages)

    candidate_start = len(messages) - max_messages
    # Advance forward until we find a user-role message; that becomes the new head.
    for i in range(candidate_start, len(messages)):
        if messages[i].get("role") == "user":
            return list(messages[i:])
    # Shouldn't happen if any user message exists, but if not, return as-is.
    return list(messages)
