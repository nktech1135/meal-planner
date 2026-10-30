from datetime import UTC, datetime

import anthropic
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.advisor.agent import AdvisorError, messages_today, render, run_turn
from app.config import Settings
from app.db import get_db
from app.models import AdvisorConversation, PlanProposal, User
from app.routers.plan import create_item
from app.schemas import ChatIn, ConversationDetail, ConversationOut, PlanItemIn, ProposalAccept, ProposalOut
from app.security import current_user
from app.settings_store import get_runtime

router = APIRouter(prefix="/api/advisor", tags=["advisor"])


def get_anthropic_client(settings: Settings = Depends(get_runtime)) -> anthropic.Anthropic:
    if not settings.anthropic_api_key:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "The advisor isn't set up yet: an admin can add an Anthropic API key in Settings")
    return anthropic.Anthropic(api_key=settings.anthropic_api_key)


def _conversation(db: Session, user: User, conversation_id: int) -> AdvisorConversation:
    conv = db.get(AdvisorConversation, conversation_id)
    if conv is None or conv.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
    return conv


def _detail(db: Session, conv: AdvisorConversation) -> ConversationDetail:
    proposals = db.scalars(select(PlanProposal).where(PlanProposal.conversation_id == conv.id).order_by(PlanProposal.id))
    return ConversationDetail(id=conv.id, title=conv.title, updated_at=conv.updated_at, messages=render(conv),
                              proposals=list(proposals))


@router.get("/conversations", response_model=list[ConversationOut])
def list_conversations(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return list(db.scalars(select(AdvisorConversation).where(AdvisorConversation.user_id == user.id)
                           .order_by(AdvisorConversation.updated_at.desc()).limit(100)))


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
def read_conversation(conversation_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return _detail(db, _conversation(db, user, conversation_id))


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
    settings: Settings = Depends(get_runtime),
):
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
    return _detail(db, conv)


def _proposal(db: Session, user: User, proposal_id: int) -> PlanProposal:
    proposal = db.get(PlanProposal, proposal_id)
    if proposal is None or proposal.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Proposal not found")
    if proposal.status != "pending":
        raise HTTPException(status.HTTP_409_CONFLICT, f"This proposal was already {proposal.status}")
    return proposal


@router.post("/proposals/{proposal_id}/accept", response_model=ProposalOut)
def accept_proposal(proposal_id: int, body: ProposalAccept, user: User = Depends(current_user),
                    db: Session = Depends(get_db)):
    """Add the proposal's items (or the chosen ones) to the user's meal plan."""
    proposal = _proposal(db, user, proposal_id)
    chosen = range(len(proposal.items)) if body.indexes is None else body.indexes
    if any(i < 0 or i >= len(proposal.items) for i in chosen):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Unknown item index")
    for i in chosen:
        item = {k: v for k, v in proposal.items[i].items() if k in PlanItemIn.model_fields}
        create_item(db, user, PlanItemIn(**item), "advisor")
    proposal.status, proposal.resolved_at = "accepted", datetime.now(UTC)
    proposal.accepted_indexes = sorted(set(chosen))
    db.commit()
    return proposal


@router.post("/proposals/{proposal_id}/dismiss", response_model=ProposalOut)
def dismiss_proposal(proposal_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    proposal = _proposal(db, user, proposal_id)
    proposal.status, proposal.resolved_at = "dismissed", datetime.now(UTC)
    db.commit()
    return proposal
