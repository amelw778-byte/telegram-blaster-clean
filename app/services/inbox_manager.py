import asyncio
import logging
import os
from datetime import datetime

from sqlalchemy.exc import IntegrityError
from telethon import TelegramClient, events, types
from telethon.sessions import StringSession

from app.database import SessionLocal
from app.models import InboxMessage, TelegramAccount


logger = logging.getLogger(__name__)


class InboxManager:
    def __init__(self):
        self.tasks: dict[int, asyncio.Task] = {}
        self.clients: dict[int, TelegramClient] = {}

    @staticmethod
    def enabled() -> bool:
        return os.getenv("INBOX_LISTENERS_ENABLED", "true").strip().casefold() in {
            "1",
            "true",
            "yes",
        }

    @staticmethod
    def account_enabled(account_id: int) -> bool:
        selected = os.getenv("INBOX_ACCOUNT_ID", "").strip()
        return not selected or selected == str(account_id)

    def connected(self, account_id: int) -> bool:
        task = self.tasks.get(account_id)
        client = self.clients.get(account_id)
        return bool(task and not task.done() and client and client.is_connected())

    async def start_all(self) -> None:
        if not self.enabled():
            return
        with SessionLocal() as db:
            account_ids = [
                row[0]
                for row in db.query(TelegramAccount.id)
                .filter(TelegramAccount.session_str.isnot(None))
                .all()
                if self.account_enabled(row[0])
            ]
        for index, account_id in enumerate(account_ids, start=1):
            self.start(account_id)
            if index % 10 == 0:
                await asyncio.sleep(1)

    def start(self, account_id: int) -> None:
        if (
            not self.enabled()
            or not self.account_enabled(account_id)
            or (account_id in self.tasks and not self.tasks[account_id].done())
        ):
            return
        task = asyncio.create_task(self._listen(account_id), name=f"inbox-account-{account_id}")
        self.tasks[account_id] = task
        task.add_done_callback(
            lambda done, aid=account_id: self.tasks.pop(aid, None)
            if self.tasks.get(aid) is done
            else None
        )

    async def stop(self, account_id: int) -> None:
        task = self.tasks.pop(account_id, None)
        if task:
            task.cancel()
        client = self.clients.pop(account_id, None)
        if client and client.is_connected():
            await client.disconnect()
        if task:
            await asyncio.gather(task, return_exceptions=True)

    async def shutdown(self) -> None:
        await asyncio.gather(*(self.stop(account_id) for account_id in list(self.tasks)))

    async def _listen(self, account_id: int) -> None:
        while True:
            with SessionLocal() as db:
                account = db.get(TelegramAccount, account_id)
                if not account or not account.session_str:
                    return
                credentials = (account.session_str, account.api_id, account.api_hash)

            client = TelegramClient(StringSession(credentials[0]), credentials[1], credentials[2])

            async def on_message(event):
                await self._store_incoming(account_id, event)

            client.add_event_handler(on_message, events.NewMessage(incoming=True))
            try:
                await client.connect()
                if not await client.is_user_authorized():
                    logger.warning("Inbox listener account %s is no longer authorized", account_id)
                    return
                self.clients[account_id] = client
                await client.run_until_disconnected()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Inbox listener account %s disconnected", account_id)
            finally:
                if self.clients.get(account_id) is client:
                    self.clients.pop(account_id, None)
                if client.is_connected():
                    await client.disconnect()
            await asyncio.sleep(5)

    async def _store_incoming(self, account_id: int, event) -> None:
        if not event.is_private:
            return
        input_peer = await event.get_input_chat()
        if not isinstance(input_peer, types.InputPeerUser):
            return
        peer = await event.get_chat()
        body = (event.raw_text or "").strip()
        if not body:
            if not event.message.media:
                return
            body = "📎 Media"
        peer_name = " ".join(
            part for part in (getattr(peer, "first_name", None), getattr(peer, "last_name", None)) if part
        ) or getattr(peer, "username", None) or str(input_peer.user_id)
        created_at = event.message.date or datetime.utcnow()
        if created_at.tzinfo:
            created_at = created_at.replace(tzinfo=None)

        with SessionLocal() as db:
            account = db.get(TelegramAccount, account_id)
            if not account:
                return
            db.add(InboxMessage(
                user_id=account.user_id,
                account_id=account.id,
                peer_id=input_peer.user_id,
                peer_access_hash=input_peer.access_hash,
                peer_name=peer_name[:255],
                peer_username=(getattr(peer, "username", None) or None),
                telegram_message_id=event.message.id,
                direction="in",
                body=body,
                is_read=False,
                created_at=created_at,
            ))
            try:
                db.commit()
            except IntegrityError:
                db.rollback()

    async def send_reply(
        self,
        account_id: int,
        peer_id: int,
        peer_access_hash: int,
        body: str,
    ) -> tuple[int, datetime]:
        with SessionLocal() as db:
            account = db.get(TelegramAccount, account_id)
            if not account or not account.session_str:
                raise RuntimeError("Akun Telegram tidak tersedia")
            credentials = (account.session_str, account.api_id, account.api_hash)

        client = self.clients.get(account_id)
        temporary = not client or not client.is_connected()
        if temporary:
            client = TelegramClient(StringSession(credentials[0]), credentials[1], credentials[2])
            await client.connect()
        try:
            if not await client.is_user_authorized():
                raise RuntimeError("Session akun Telegram sudah tidak valid")
            sent = await client.send_message(
                types.InputPeerUser(peer_id, peer_access_hash),
                body,
                link_preview=True,
            )
            created_at = sent.date or datetime.utcnow()
            if created_at.tzinfo:
                created_at = created_at.replace(tzinfo=None)
            return sent.id, created_at
        finally:
            if temporary and client.is_connected():
                await client.disconnect()


inbox_manager = InboxManager()
