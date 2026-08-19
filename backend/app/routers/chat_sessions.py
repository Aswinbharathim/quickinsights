import logging

from fastapi import APIRouter, HTTPException

from app import store
from app.models import (
    ChatMessage,
    ChatMessageCreate,
    ChatMessageUpdate,
    ChatSession,
    ChatSessionCreate,
    ChatSessionUpdate,
)
from app.store import new_id_fn, now_fn

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat-sessions", tags=["chat-sessions"])


@router.get("", response_model=list[ChatSession])
def list_sessions():
    return sorted(store.chat_session_store.values(), key=lambda s: s.created_at, reverse=True)


@router.post("", response_model=ChatSession, status_code=201)
def create_session(payload: ChatSessionCreate):
    new_id = new_id_fn()
    session = ChatSession(
        id=new_id, title="New chat", connection_id=payload.connection_id, created_at=now_fn()
    )
    store.chat_session_store[new_id] = session
    return session


@router.put("/{session_id}", response_model=ChatSession)
def update_session(session_id: str, payload: ChatSessionUpdate):
    existing = store.chat_session_store.get(session_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Chat session not found")
    updated = existing.model_copy(update={k: v for k, v in payload.model_dump().items() if v is not None})
    store.chat_session_store[session_id] = updated
    return updated


@router.delete("/{session_id}", status_code=204)
def delete_session(session_id: str):
    if session_id not in store.chat_session_store:
        raise HTTPException(status_code=404, detail="Chat session not found")
    del store.chat_session_store[session_id]


@router.get("/{session_id}/messages", response_model=list[ChatMessage])
def list_messages(session_id: str):
    if session_id not in store.chat_session_store:
        raise HTTPException(status_code=404, detail="Chat session not found")
    return store.list_chat_messages(session_id)


@router.post("/{session_id}/messages", response_model=ChatMessage, status_code=201)
def create_message(session_id: str, payload: ChatMessageCreate):
    if session_id not in store.chat_session_store:
        raise HTTPException(status_code=404, detail="Chat session not found")
    message = ChatMessage(
        id=payload.id or new_id_fn(),
        role=payload.role,
        question=payload.question,
        created_at=now_fn(),
        ask=payload.ask,
        feedback=payload.feedback,
        error=payload.error,
    )
    return store.add_chat_message(session_id, message)


@router.put("/{session_id}/messages/{message_id}", response_model=ChatMessage)
def update_message(session_id: str, message_id: str, payload: ChatMessageUpdate):
    try:
        return store.update_chat_message(session_id, message_id, payload)
    except KeyError:
        logger.warning("update_message: message %s not found in session %s", message_id, session_id)
        raise HTTPException(status_code=404, detail="Message not found")
