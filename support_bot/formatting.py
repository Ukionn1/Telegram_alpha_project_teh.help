from __future__ import annotations

import html
from typing import Any

from .keyboards import status_label
from .texts import CATEGORY_TITLES


def h(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=False)


def clip(value: str, limit: int = 3500) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


def user_title(ticket: dict) -> str:
    name = ticket.get("full_name") or ""
    username = ticket.get("username") or ""
    user_id = ticket.get("user_id")
    if username:
        return f"{h(name)} @{h(username)} (<code>{user_id}</code>)"
    if name:
        return f"{h(name)} (<code>{user_id}</code>)"
    return f"<code>{user_id}</code>"


def format_ticket_header(ticket: dict) -> str:
    category = CATEGORY_TITLES.get(ticket["category"], ticket["category"])
    files = ticket.get("files_count")
    files_line = f"\nВложений: <b>{files}</b>" if files is not None else ""
    return (
        f"<b>Заявка #{ticket['ticket_id']}: {h(ticket['subject'])}</b>\n"
        f"Статус: <b>{status_label(ticket['status'])}</b>\n"
        f"Категория: <b>{h(category)}</b>\n"
        f"Клиент: {user_title(ticket)}\n"
        f"Создана: <code>{h(ticket['created_at'][:16])}</code>{files_line}"
    )


def format_ticket_notification(ticket: dict, messages: list[dict]) -> str:
    user_messages = [m for m in messages if m["sender_role"] == "user"]
    body_parts = []
    for message in user_messages:
        if message.get("text"):
            body_parts.append(h(message["text"]))
        elif message.get("content_type") != "text":
            name = message.get("file_name") or message.get("content_type")
            body_parts.append(f"[{h(name)}]")
    body = "\n\n".join(body_parts).strip() or "Пользователь не добавил текст."
    text = f"🔔 <b>Новая заявка</b>\n\n{format_ticket_header(ticket)}\n\n<b>Текст заявки:</b>\n{body}"
    return clip(text, 3900)


def format_ticket_list(title: str, tickets: list[dict]) -> str:
    if not tickets:
        return "Заявок нет."
    lines = [f"<b>{h(title)}</b>", ""]
    for ticket in tickets:
        category = CATEGORY_TITLES.get(ticket["category"], ticket["category"])
        lines.append(
            f"{status_label(ticket['status'])} <b>#{ticket['ticket_id']}</b> · {h(ticket['subject'])}\n"
            f"{h(category)} · клиент <code>{ticket['user_id']}</code> · сообщений: {ticket.get('messages_count', 0)}"
        )
    return clip("\n\n".join(lines), 3900)


def format_message_line(message: dict) -> str:
    role = {
        "user": "Клиент",
        "mod": "Модератор",
        "system": "Система",
        "bot": "Бот",
    }.get(message["sender_role"], message["sender_role"])
    stamp = h(message["created_at"][5:16].replace("T", " "))
    body = message.get("text") or ""
    if message.get("content_type") != "text":
        file_name = message.get("file_name") or message.get("content_type")
        file_note = f"[{h(message['content_type'])}: {h(file_name)}]"
        body = f"{file_note}\n{h(body)}" if body else file_note
    else:
        body = h(body)
    return f"<code>{stamp}</code> <b>{role}:</b>\n{body}".strip()


def format_ticket_log(ticket: dict, messages: list[dict], events: list[dict]) -> str:
    lines = [format_ticket_header(ticket), "", "<b>История сообщений:</b>"]
    if messages:
        lines.extend(format_message_line(message) for message in messages[-25:])
    else:
        lines.append("Сообщений пока нет.")

    if events:
        lines.append("")
        lines.append("<b>События:</b>")
        for event in events[-10:]:
            actor = f" · <code>{event['actor_id']}</code>" if event.get("actor_id") else ""
            lines.append(f"<code>{h(event['created_at'][5:16].replace('T', ' '))}</code> {h(event['event'])}{actor}")

    return clip("\n\n".join(lines), 3900)


def format_public_ticket(ticket: dict) -> str:
    category = CATEGORY_TITLES.get(ticket["category"], ticket["category"])
    return (
        f"<b>#{ticket['ticket_id']} · {h(ticket['subject'])}</b>\n"
        f"Статус: <b>{status_label(ticket['status'])}</b>\n"
        f"Категория: {h(category)}\n"
        f"Создана: <code>{h(ticket['created_at'][:16])}</code>"
    )
