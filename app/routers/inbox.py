import logging
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.auth import get_current_user, verify_csrf
from app.database import get_db
from app.models import InboxMessage, TelegramAccount, User
from app.services.inbox_manager import inbox_manager


router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parents[1] / "templates"))
logger = logging.getLogger(__name__)


@router.get("/inbox")
def inbox_page(
    request: Request,
    account_id: int | None = None,
    peer_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # ponytail: recent-window grouping stays simple; move to a SQL window query past 1,000 messages/user.
    recent = (
        db.query(InboxMessage)
        .options(joinedload(InboxMessage.account))
        .filter(InboxMessage.user_id == current_user.id)
        .order_by(InboxMessage.created_at.desc(), InboxMessage.id.desc())
        .limit(1000)
        .all()
    )
    conversations = {}
    for message in recent:
        key = (message.account_id, message.peer_id)
        if key not in conversations:
            conversations[key] = {
                "account_id": message.account_id,
                "account_label": message.account.label or message.account.phone,
                "peer_id": message.peer_id,
                "peer_name": message.peer_name,
                "peer_username": message.peer_username,
                "latest": message,
                "unread": 0,
            }
        if message.direction == "in" and not message.is_read:
            conversations[key]["unread"] += 1

    selected = None
    messages = []
    if account_id is not None and peer_id is not None:
        latest = (
            db.query(InboxMessage)
            .options(joinedload(InboxMessage.account))
            .filter(
                InboxMessage.user_id == current_user.id,
                InboxMessage.account_id == account_id,
                InboxMessage.peer_id == peer_id,
            )
            .order_by(InboxMessage.created_at.desc(), InboxMessage.id.desc())
            .first()
        )
        if not latest:
            raise HTTPException(status_code=404, detail="Percakapan tidak ditemukan")
        messages = list(reversed(
            db.query(InboxMessage)
            .filter(
                InboxMessage.user_id == current_user.id,
                InboxMessage.account_id == account_id,
                InboxMessage.peer_id == peer_id,
            )
            .order_by(InboxMessage.created_at.desc(), InboxMessage.id.desc())
            .limit(200)
            .all()
        ))
        db.query(InboxMessage).filter(
            InboxMessage.user_id == current_user.id,
            InboxMessage.account_id == account_id,
            InboxMessage.peer_id == peer_id,
            InboxMessage.direction == "in",
            InboxMessage.is_read.is_(False),
        ).update({InboxMessage.is_read: True}, synchronize_session=False)
        db.commit()
        selected = {
            "account_id": account_id,
            "account_label": latest.account.label or latest.account.phone,
            "peer_id": peer_id,
            "peer_name": latest.peer_name,
            "peer_username": latest.peer_username,
        }
        if (account_id, peer_id) in conversations:
            conversations[(account_id, peer_id)]["unread"] = 0

    return templates.TemplateResponse(request, "inbox.html", {
        "request": request,
        "conversations": list(conversations.values()),
        "selected": selected,
        "messages": messages,
        "error": request.query_params.get("error"),
    })


@router.post("/inbox/reply")
async def reply(
    account_id: int = Form(...),
    peer_id: int = Form(...),
    body: str = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _csrf: None = Depends(verify_csrf),
):
    body = body.strip()
    destination = f"/inbox?account_id={account_id}&peer_id={peer_id}"
    if not body or len(body) > 4096:
        return RedirectResponse(f"{destination}&error=invalid_message", status_code=303)

    account = db.query(TelegramAccount).filter(
        TelegramAccount.id == account_id,
        TelegramAccount.user_id == current_user.id,
    ).first()
    latest = (
        db.query(InboxMessage)
        .filter(
            InboxMessage.user_id == current_user.id,
            InboxMessage.account_id == account_id,
            InboxMessage.peer_id == peer_id,
        )
        .order_by(InboxMessage.created_at.desc(), InboxMessage.id.desc())
        .first()
    )
    if not account or not latest:
        raise HTTPException(status_code=404, detail="Percakapan tidak ditemukan")

    try:
        telegram_message_id, created_at = await inbox_manager.send_reply(
            account.id,
            peer_id,
            latest.peer_access_hash,
            body,
        )
    except Exception:
        logger.exception("Telegram inbox reply failed for account %s", account.id)
        return RedirectResponse(f"{destination}&error=send_failed", status_code=303)

    db.add(InboxMessage(
        user_id=current_user.id,
        account_id=account.id,
        peer_id=peer_id,
        peer_access_hash=latest.peer_access_hash,
        peer_name=latest.peer_name,
        peer_username=latest.peer_username,
        telegram_message_id=telegram_message_id,
        direction="out",
        body=body,
        is_read=True,
        created_at=created_at,
    ))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
    return RedirectResponse(destination, status_code=303)


@router.get("/api/inbox/unread")
def unread(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    account_ids = {
        row[0]
        for row in db.query(TelegramAccount.id).filter(
            TelegramAccount.user_id == current_user.id,
        )
    }
    query = db.query(InboxMessage).filter(
        InboxMessage.user_id == current_user.id,
        InboxMessage.direction == "in",
        InboxMessage.is_read.is_(False),
    )
    count = query.count()
    latest = query.options(joinedload(InboxMessage.account)).order_by(
        InboxMessage.created_at.desc(), InboxMessage.id.desc()
    ).first()
    return JSONResponse({
        "unread_count": count,
        "latest_id": latest.id if latest else None,
        "latest_preview": latest.body[:120] if latest else None,
        "peer_name": latest.peer_name if latest else None,
        "account_label": (latest.account.label or latest.account.phone) if latest else None,
        "url": f"/inbox?account_id={latest.account_id}&peer_id={latest.peer_id}" if latest else "/inbox",
        "connected_account_ids": [
            account_id for account_id in account_ids if inbox_manager.connected(account_id)
        ],
    })
