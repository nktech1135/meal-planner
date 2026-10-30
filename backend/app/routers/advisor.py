import anthropic
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.advisor.agent import AdvisorError, messages_today, render, run_turn
from app.config import get_settings
from app.db import get_db
from app.models import AdvisorConversation, User
from app.schemas import ChatIn, ConversationDetail, ConversationOut
from app.security import current_user

router = APIRouter(prefix="/api/advisor", tags=["advisor"])


def get_anthropic_client() -> anthropic.Anthropic:
    key = get_settings().anthropic_api_key  # from ANTHROPIC_API_KEY in the environment or .env
    if not key:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "The advisor isn't configured: set ANTHROPIC_API_KEY on the server")
    return anthropic.Anthropic(api_key=key)


def _conversation(db: Session, user: User, conversation_id: int) -> AdvisorConversation:
    conv = db.get(AdvisorConversation, conversation_id)
    if conv is None or conv.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
    return conv


def _detail(conv: AdvisorConversation) -> ConversationDetail:
    return ConversationDetail(id=conv.id, title=conv.title, updated_at=conv.updated_at, messages=render(conv))


@router.get("/conversations", response_model=list[ConversationOut])
def list_conversations(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return list(db.scalars(select(AdvisorConversation).where(AdvisorConversation.user_id == user.id)
                           .order_by(AdvisorConversation.updated_at.desc()).limit(100)))


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
def read_conversation(conversation_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return _detail(_conversation(db, user, conversation_id))


@router.delete("/conversations/{conversation_id}", status_code=204)
def delete_conversation(conversation_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.delete(_conversation(db, user, conversation_id))
    db.commit()


@router.post("/chat", response_model=ConversationDetail)
def chat(
    body: ChatIn,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
    client: anthropic.Anthropic = Depends(get_anthropic_client),
):
    settings = get_settings()
    if messages_today(db, user) >= settings.advisor_daily_message_limit:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Daily advisor message limit reached")
    if body.conversation_id:
        conv = _conversation(db, user, body.conversation_id)
    else:
        conv = AdvisorConversation(user_id=user.id)
        db.add(conv)
        db.flush()
    try:
        run_turn(db, client, settings, user, conv, body.message)
    except AdvisorError as exc:
        db.rollback()
        raise HTTPException(exc.status_code, str(exc)) from None
    db.refresh(conv)
    return _detail(conv)
