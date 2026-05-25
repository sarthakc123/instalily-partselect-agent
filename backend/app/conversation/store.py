"""Conversation + message persistence in Postgres.

Tables: `conversations` (id, llm_provider, state JSONB) and `messages`
(conversation_id, role, content, tool_calls JSONB). The `state` JSONB
column stores our small session dict (`last_part`, `model_number`, etc.).

This is the API-facing context layer. The orchestrator itself is stateless
between calls; persistence lives here.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from psycopg.types.json import Jsonb

from app.db.pool import connection


def new_conversation_id() -> str:
    return str(uuid.uuid4())


def get_or_create_conversation(
    conversation_id: str | None,
    *,
    llm_provider: str = "anthropic",
) -> dict[str, Any]:
    """Return `{id, session, messages}`. Creates a row if needed.

    `messages` is the full ordered history in state-message dict shape
    (`{role, content, tool_calls?, tool_call_id?, tool_name?}`), ready
    to feed back into the orchestrator.
    """
    cid = conversation_id or new_conversation_id()
    with connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT id, state FROM conversations WHERE id = %s", (cid,))
        row = cur.fetchone()
        if row is None:
            cur.execute(
                "INSERT INTO conversations (id, llm_provider, state) VALUES (%s, %s, %s)",
                (cid, llm_provider, Jsonb({})),
            )
            conn.commit()
            return {"id": cid, "session": {}, "messages": []}

        session = row["state"] or {}

        cur.execute(
            "SELECT role, content, tool_calls FROM messages "
            "WHERE conversation_id = %s ORDER BY id ASC",
            (cid,),
        )
        rows = cur.fetchall()

    messages: list[dict[str, Any]] = []
    for r in rows:
        msg: dict[str, Any] = {"role": r["role"], "content": r["content"]}
        if r["tool_calls"]:
            tc = r["tool_calls"]
            # Tool result messages stash tool_call_id + tool_name inside tool_calls JSONB.
            if r["role"] == "tool":
                msg["tool_call_id"] = tc.get("tool_call_id")
                msg["tool_name"] = tc.get("tool_name")
            else:
                msg["tool_calls"] = tc.get("calls", tc) if isinstance(tc, dict) else tc
        messages.append(msg)

    return {"id": cid, "session": session, "messages": messages}


def save_user_message(conversation_id: str, content: str) -> None:
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO messages (conversation_id, role, content) VALUES (%s, %s, %s)",
            (conversation_id, "user", content),
        )
        conn.commit()


def save_assistant_message(
    conversation_id: str, content: str, tool_calls: list[dict[str, Any]] | None
) -> None:
    tc_json = Jsonb({"calls": tool_calls}) if tool_calls else None
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO messages (conversation_id, role, content, tool_calls) "
            "VALUES (%s, %s, %s, %s)",
            (conversation_id, "assistant", content, tc_json),
        )
        conn.commit()


def save_tool_message(
    conversation_id: str,
    *,
    tool_call_id: str,
    tool_name: str,
    content: str,
) -> None:
    """Tool-result messages get their call id + name stashed in the tool_calls
    JSONB column so we can reconstruct the exact provider-message shape on load."""
    blob = Jsonb({"tool_call_id": tool_call_id, "tool_name": tool_name})
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO messages (conversation_id, role, content, tool_calls) "
            "VALUES (%s, %s, %s, %s)",
            (conversation_id, "tool", content, blob),
        )
        conn.commit()


def update_session(conversation_id: str, session: dict[str, Any]) -> None:
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE conversations SET state = %s WHERE id = %s",
            (Jsonb(session), conversation_id),
        )
        conn.commit()


def list_conversations(limit: int = 20) -> list[dict[str, Any]]:
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT c.id, c.created_at, c.llm_provider,
                   (SELECT COUNT(*) FROM messages m WHERE m.conversation_id = c.id) AS n_messages,
                   (SELECT m.content FROM messages m WHERE m.conversation_id = c.id
                    AND m.role = 'user' ORDER BY m.id ASC LIMIT 1)                   AS first_user_message
            FROM conversations c
            ORDER BY c.created_at DESC
            LIMIT %s
            """,
            (limit,),
        )
        return list(cur.fetchall())


def delete_conversation(conversation_id: str) -> bool:
    with connection() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM conversations WHERE id = %s", (conversation_id,))
        deleted = cur.rowcount > 0
        conn.commit()
    return deleted
