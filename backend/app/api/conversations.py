"""Conversation CRUD: list, get, delete. The /chat endpoint creates them."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.conversation import store

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.get("")
async def list_conversations(limit: int = 20) -> dict:
    rows = store.list_conversations(limit=limit)
    return {"conversations": rows}


@router.get("/{conversation_id}")
async def get_conversation(conversation_id: str) -> dict:
    conv = store.get_or_create_conversation(conversation_id)
    # If we just CREATED this one (no prior messages), tell the caller it was empty.
    return {
        "id": conv["id"],
        "session": conv["session"],
        "messages": conv["messages"],
    }


@router.delete("/{conversation_id}", status_code=204)
async def delete_conversation(conversation_id: str) -> None:
    ok = store.delete_conversation(conversation_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Conversation not found")
