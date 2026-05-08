from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

import aiosqlite

from .texts import DEFAULT_CANNED_REPLIES, DEFAULT_FAQ


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def row_to_dict(row: aiosqlite.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {key: row[key] for key in row.keys()}


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)

    @asynccontextmanager
    async def connect(self):
        db = await aiosqlite.connect(self.path)
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA foreign_keys = ON")
        try:
            yield db
        finally:
            await db.close()

    async def init(self, env_moderators: set[int]) -> None:
        async with self.connect() as db:
            await db.executescript(
                """
                PRAGMA journal_mode = WAL;

                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    full_name TEXT,
                    first_seen TEXT NOT NULL,
                    last_seen TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS moderators (
                    user_id INTEGER PRIMARY KEY,
                    name TEXT,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    added_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS tickets (
                    ticket_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    mod_id INTEGER,
                    category TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'draft',
                    priority TEXT NOT NULL DEFAULT 'normal',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_message_at TEXT,
                    closed_at TEXT
                );

                CREATE TABLE IF NOT EXISTS ticket_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticket_id INTEGER NOT NULL,
                    sender_role TEXT NOT NULL,
                    sender_id INTEGER,
                    tg_chat_id INTEGER,
                    tg_message_id INTEGER,
                    text TEXT,
                    content_type TEXT NOT NULL DEFAULT 'text',
                    file_id TEXT,
                    file_unique_id TEXT,
                    file_name TEXT,
                    mime_type TEXT,
                    file_size INTEGER,
                    local_path TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(ticket_id) REFERENCES tickets(ticket_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS ticket_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticket_id INTEGER NOT NULL,
                    actor_id INTEGER,
                    event TEXT NOT NULL,
                    details TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(ticket_id) REFERENCES tickets(ticket_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS mod_current_ticket (
                    mod_id INTEGER PRIMARY KEY,
                    ticket_id INTEGER NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS faq (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    question TEXT NOT NULL,
                    answer TEXT NOT NULL,
                    keywords TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS canned_replies (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    body TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status, ticket_id);
                CREATE INDEX IF NOT EXISTS idx_tickets_user_status ON tickets(user_id, status, ticket_id);
                CREATE INDEX IF NOT EXISTS idx_messages_ticket ON ticket_messages(ticket_id, id);
                """
            )

            for mod_id in env_moderators:
                await db.execute(
                    """
                    INSERT INTO moderators(user_id, name, is_active, added_at)
                    VALUES (?, ?, 1, ?)
                    ON CONFLICT(user_id) DO UPDATE SET is_active = 1
                    """,
                    (mod_id, "env", now_iso()),
                )

            async with db.execute("SELECT COUNT(*) AS count FROM faq") as cursor:
                faq_count = (await cursor.fetchone())["count"]
            if faq_count == 0:
                await db.executemany(
                    "INSERT INTO faq(question, answer, keywords) VALUES (?, ?, ?)",
                    [(item["question"], item["answer"], item["keywords"]) for item in DEFAULT_FAQ],
                )

            async with db.execute("SELECT COUNT(*) AS count FROM canned_replies") as cursor:
                canned_count = (await cursor.fetchone())["count"]
            if canned_count == 0:
                await db.executemany(
                    "INSERT INTO canned_replies(title, body) VALUES (?, ?)",
                    DEFAULT_CANNED_REPLIES,
                )

            await db.commit()

    async def upsert_user(self, user_id: int, username: str | None, full_name: str | None) -> None:
        stamp = now_iso()
        async with self.connect() as db:
            await db.execute(
                """
                INSERT INTO users(user_id, username, full_name, first_seen, last_seen)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    username = excluded.username,
                    full_name = excluded.full_name,
                    last_seen = excluded.last_seen
                """,
                (user_id, username, full_name, stamp, stamp),
            )
            await db.commit()

    async def get_moderator_ids(self) -> set[int]:
        async with self.connect() as db:
            async with db.execute("SELECT user_id FROM moderators WHERE is_active = 1") as cursor:
                return {row["user_id"] for row in await cursor.fetchall()}

    async def is_moderator(self, user_id: int) -> bool:
        async with self.connect() as db:
            async with db.execute(
                "SELECT 1 FROM moderators WHERE user_id = ? AND is_active = 1",
                (user_id,),
            ) as cursor:
                return await cursor.fetchone() is not None

    async def add_moderator(self, user_id: int, name: str | None = None) -> None:
        async with self.connect() as db:
            await db.execute(
                """
                INSERT INTO moderators(user_id, name, is_active, added_at)
                VALUES (?, ?, 1, ?)
                ON CONFLICT(user_id) DO UPDATE SET is_active = 1, name = excluded.name
                """,
                (user_id, name, now_iso()),
            )
            await db.commit()

    async def create_ticket(self, user_id: int, category: str, subject: str) -> int:
        stamp = now_iso()
        async with self.connect() as db:
            cursor = await db.execute(
                """
                INSERT INTO tickets(user_id, category, subject, status, created_at, updated_at)
                VALUES (?, ?, ?, 'draft', ?, ?)
                """,
                (user_id, category, subject, stamp, stamp),
            )
            ticket_id = int(cursor.lastrowid)
            await self._add_event(db, ticket_id, user_id, "created", {"category": category, "subject": subject})
            await db.commit()
            return ticket_id

    async def submit_ticket(self, ticket_id: int) -> None:
        stamp = now_iso()
        async with self.connect() as db:
            await db.execute(
                """
                UPDATE tickets
                SET status = 'pending', updated_at = ?, last_message_at = COALESCE(last_message_at, ?)
                WHERE ticket_id = ? AND status = 'draft'
                """,
                (stamp, stamp, ticket_id),
            )
            await self._add_event(db, ticket_id, None, "submitted", None)
            await db.commit()

    async def add_message(
        self,
        *,
        ticket_id: int,
        sender_role: str,
        sender_id: int | None,
        tg_chat_id: int | None,
        tg_message_id: int | None,
        text: str | None,
        content_type: str = "text",
        file_id: str | None = None,
        file_unique_id: str | None = None,
        file_name: str | None = None,
        mime_type: str | None = None,
        file_size: int | None = None,
        local_path: str | None = None,
    ) -> int:
        stamp = now_iso()
        async with self.connect() as db:
            cursor = await db.execute(
                """
                INSERT INTO ticket_messages(
                    ticket_id, sender_role, sender_id, tg_chat_id, tg_message_id, text,
                    content_type, file_id, file_unique_id, file_name, mime_type, file_size,
                    local_path, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ticket_id,
                    sender_role,
                    sender_id,
                    tg_chat_id,
                    tg_message_id,
                    text,
                    content_type,
                    file_id,
                    file_unique_id,
                    file_name,
                    mime_type,
                    file_size,
                    local_path,
                    stamp,
                ),
            )
            await db.execute(
                "UPDATE tickets SET updated_at = ?, last_message_at = ? WHERE ticket_id = ?",
                (stamp, stamp, ticket_id),
            )
            await db.commit()
            return int(cursor.lastrowid)

    async def add_event(self, ticket_id: int, actor_id: int | None, event: str, details: dict[str, Any] | None = None) -> None:
        async with self.connect() as db:
            await self._add_event(db, ticket_id, actor_id, event, details)
            await db.commit()

    async def _add_event(
        self,
        db: aiosqlite.Connection,
        ticket_id: int,
        actor_id: int | None,
        event: str,
        details: dict[str, Any] | None,
    ) -> None:
        await db.execute(
            "INSERT INTO ticket_events(ticket_id, actor_id, event, details, created_at) VALUES (?, ?, ?, ?, ?)",
            (ticket_id, actor_id, event, json.dumps(details, ensure_ascii=False) if details else None, now_iso()),
        )

    async def list_tickets(
        self,
        *,
        statuses: tuple[str, ...] | None = None,
        mod_id: int | None = None,
        user_id: int | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        query = [
            """
            SELECT t.*, u.username, u.full_name,
                   (SELECT COUNT(*) FROM ticket_messages m WHERE m.ticket_id = t.ticket_id) AS messages_count,
                   (SELECT COUNT(*) FROM ticket_messages m WHERE m.ticket_id = t.ticket_id AND m.content_type != 'text') AS files_count
            FROM tickets t
            LEFT JOIN users u ON u.user_id = t.user_id
            WHERE 1 = 1
            """
        ]
        params: list[Any] = []
        if statuses:
            query.append(f"AND t.status IN ({','.join('?' for _ in statuses)})")
            params.extend(statuses)
        if mod_id is not None:
            query.append("AND t.mod_id = ?")
            params.append(mod_id)
        if user_id is not None:
            query.append("AND t.user_id = ?")
            params.append(user_id)
        query.append("ORDER BY t.ticket_id DESC LIMIT ?")
        params.append(limit)

        async with self.connect() as db:
            async with db.execute("\n".join(query), params) as cursor:
                return [row_to_dict(row) for row in await cursor.fetchall() if row is not None]

    async def get_ticket(self, ticket_id: int) -> dict[str, Any] | None:
        async with self.connect() as db:
            async with db.execute(
                """
                SELECT t.*, u.username, u.full_name
                FROM tickets t
                LEFT JOIN users u ON u.user_id = t.user_id
                WHERE t.ticket_id = ?
                """,
                (ticket_id,),
            ) as cursor:
                return row_to_dict(await cursor.fetchone())

    async def get_ticket_messages(self, ticket_id: int, limit: int = 100) -> list[dict[str, Any]]:
        async with self.connect() as db:
            async with db.execute(
                """
                SELECT *
                FROM ticket_messages
                WHERE ticket_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (ticket_id, limit),
            ) as cursor:
                rows = [row_to_dict(row) for row in await cursor.fetchall() if row is not None]
        return list(reversed(rows))

    async def get_ticket_events(self, ticket_id: int, limit: int = 50) -> list[dict[str, Any]]:
        async with self.connect() as db:
            async with db.execute(
                """
                SELECT *
                FROM ticket_events
                WHERE ticket_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (ticket_id, limit),
            ) as cursor:
                rows = [row_to_dict(row) for row in await cursor.fetchall() if row is not None]
        return list(reversed(rows))

    async def find_user_open_ticket(self, user_id: int) -> dict[str, Any] | None:
        async with self.connect() as db:
            async with db.execute(
                """
                SELECT *
                FROM tickets
                WHERE user_id = ? AND status IN ('pending', 'active', 'waiting_user')
                ORDER BY ticket_id DESC
                LIMIT 1
                """,
                (user_id,),
            ) as cursor:
                return row_to_dict(await cursor.fetchone())

    async def set_current_ticket(self, mod_id: int, ticket_id: int) -> None:
        async with self.connect() as db:
            await db.execute(
                """
                INSERT INTO mod_current_ticket(mod_id, ticket_id, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(mod_id) DO UPDATE SET
                    ticket_id = excluded.ticket_id,
                    updated_at = excluded.updated_at
                """,
                (mod_id, ticket_id, now_iso()),
            )
            await db.commit()

    async def get_current_ticket_id(self, mod_id: int) -> int | None:
        async with self.connect() as db:
            async with db.execute(
                "SELECT ticket_id FROM mod_current_ticket WHERE mod_id = ?",
                (mod_id,),
            ) as cursor:
                row = await cursor.fetchone()
                return int(row["ticket_id"]) if row else None

    async def take_ticket(self, ticket_id: int, mod_id: int) -> bool:
        stamp = now_iso()
        async with self.connect() as db:
            cursor = await db.execute(
                """
                UPDATE tickets
                SET mod_id = ?, status = 'active', updated_at = ?
                WHERE ticket_id = ? AND status = 'pending'
                """,
                (mod_id, stamp, ticket_id),
            )
            if cursor.rowcount != 1:
                await db.rollback()
                return False
            await self._add_event(db, ticket_id, mod_id, "taken", None)
            await db.execute(
                """
                INSERT INTO mod_current_ticket(mod_id, ticket_id, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(mod_id) DO UPDATE SET ticket_id = excluded.ticket_id, updated_at = excluded.updated_at
                """,
                (mod_id, ticket_id, stamp),
            )
            await db.commit()
            return True

    async def assign_ticket(self, ticket_id: int, mod_id: int) -> bool:
        stamp = now_iso()
        async with self.connect() as db:
            cursor = await db.execute(
                """
                UPDATE tickets
                SET mod_id = ?, status = CASE WHEN status = 'closed' THEN status ELSE 'active' END, updated_at = ?
                WHERE ticket_id = ? AND status != 'closed'
                """,
                (mod_id, stamp, ticket_id),
            )
            if cursor.rowcount != 1:
                await db.rollback()
                return False
            await self._add_event(db, ticket_id, mod_id, "assigned", None)
            await db.commit()
            return True

    async def take_next_ticket(self, mod_id: int) -> int | None:
        async with self.connect() as db:
            async with db.execute(
                "SELECT ticket_id FROM tickets WHERE status = 'pending' ORDER BY ticket_id LIMIT 1"
            ) as cursor:
                row = await cursor.fetchone()
            if not row:
                return None
            ticket_id = int(row["ticket_id"])
        return ticket_id if await self.take_ticket(ticket_id, mod_id) else None

    async def close_ticket(self, ticket_id: int, actor_id: int | None) -> bool:
        stamp = now_iso()
        async with self.connect() as db:
            cursor = await db.execute(
                """
                UPDATE tickets
                SET status = 'closed', closed_at = ?, updated_at = ?
                WHERE ticket_id = ? AND status != 'closed'
                """,
                (stamp, stamp, ticket_id),
            )
            if cursor.rowcount != 1:
                await db.rollback()
                return False
            await self._add_event(db, ticket_id, actor_id, "closed", None)
            await db.commit()
            return True

    async def mark_waiting_user(self, ticket_id: int, actor_id: int | None) -> None:
        stamp = now_iso()
        async with self.connect() as db:
            await db.execute(
                "UPDATE tickets SET status = 'waiting_user', updated_at = ? WHERE ticket_id = ? AND status != 'closed'",
                (stamp, ticket_id),
            )
            await self._add_event(db, ticket_id, actor_id, "waiting_user", None)
            await db.commit()

    async def mark_active_from_user(self, ticket_id: int, actor_id: int | None) -> None:
        stamp = now_iso()
        async with self.connect() as db:
            await db.execute(
                "UPDATE tickets SET status = 'active', updated_at = ? WHERE ticket_id = ? AND status = 'waiting_user'",
                (stamp, ticket_id),
            )
            await self._add_event(db, ticket_id, actor_id, "user_replied", None)
            await db.commit()

    async def list_faq(self) -> list[dict[str, Any]]:
        async with self.connect() as db:
            async with db.execute("SELECT * FROM faq ORDER BY id") as cursor:
                return [row_to_dict(row) for row in await cursor.fetchall() if row is not None]

    async def get_faq(self, faq_id: int) -> dict[str, Any] | None:
        async with self.connect() as db:
            async with db.execute("SELECT * FROM faq WHERE id = ?", (faq_id,)) as cursor:
                return row_to_dict(await cursor.fetchone())

    async def list_canned_replies(self) -> list[dict[str, Any]]:
        async with self.connect() as db:
            async with db.execute("SELECT * FROM canned_replies ORDER BY id") as cursor:
                return [row_to_dict(row) for row in await cursor.fetchall() if row is not None]

    async def get_canned_reply(self, reply_id: int) -> dict[str, Any] | None:
        async with self.connect() as db:
            async with db.execute("SELECT * FROM canned_replies WHERE id = ?", (reply_id,)) as cursor:
                return row_to_dict(await cursor.fetchone())
