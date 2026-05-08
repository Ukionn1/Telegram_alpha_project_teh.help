from __future__ import annotations

import re
from pathlib import Path

from aiogram import Bot
from aiogram.types import Message


SAFE_NAME_RE = re.compile(r"[^a-zA-Zа-яА-ЯёЁ0-9._ -]+")


def safe_filename(name: str | None, fallback: str) -> str:
    raw = (name or fallback).strip() or fallback
    raw = SAFE_NAME_RE.sub("_", raw)
    return raw[:120]


def extract_attachment(message: Message) -> dict | None:
    if message.photo:
        item = max(message.photo, key=lambda photo: photo.file_size or 0)
        return {
            "content_type": "photo",
            "file_id": item.file_id,
            "file_unique_id": item.file_unique_id,
            "file_name": f"photo_{item.file_unique_id}.jpg",
            "mime_type": "image/jpeg",
            "file_size": item.file_size,
        }
    if message.document:
        item = message.document
        return {
            "content_type": "document",
            "file_id": item.file_id,
            "file_unique_id": item.file_unique_id,
            "file_name": item.file_name,
            "mime_type": item.mime_type,
            "file_size": item.file_size,
        }
    if message.video:
        item = message.video
        return {
            "content_type": "video",
            "file_id": item.file_id,
            "file_unique_id": item.file_unique_id,
            "file_name": item.file_name or f"video_{item.file_unique_id}.mp4",
            "mime_type": item.mime_type,
            "file_size": item.file_size,
        }
    if message.audio:
        item = message.audio
        return {
            "content_type": "audio",
            "file_id": item.file_id,
            "file_unique_id": item.file_unique_id,
            "file_name": item.file_name or f"audio_{item.file_unique_id}.mp3",
            "mime_type": item.mime_type,
            "file_size": item.file_size,
        }
    if message.voice:
        item = message.voice
        return {
            "content_type": "voice",
            "file_id": item.file_id,
            "file_unique_id": item.file_unique_id,
            "file_name": f"voice_{item.file_unique_id}.ogg",
            "mime_type": item.mime_type,
            "file_size": item.file_size,
        }
    if message.animation:
        item = message.animation
        return {
            "content_type": "animation",
            "file_id": item.file_id,
            "file_unique_id": item.file_unique_id,
            "file_name": item.file_name or f"animation_{item.file_unique_id}.mp4",
            "mime_type": item.mime_type,
            "file_size": item.file_size,
        }
    if message.video_note:
        item = message.video_note
        return {
            "content_type": "video_note",
            "file_id": item.file_id,
            "file_unique_id": item.file_unique_id,
            "file_name": f"video_note_{item.file_unique_id}.mp4",
            "mime_type": "video/mp4",
            "file_size": item.file_size,
        }
    if message.sticker:
        item = message.sticker
        ext = "webm" if item.is_video else "tgs" if item.is_animated else "webp"
        return {
            "content_type": "sticker",
            "file_id": item.file_id,
            "file_unique_id": item.file_unique_id,
            "file_name": f"sticker_{item.file_unique_id}.{ext}",
            "mime_type": None,
            "file_size": item.file_size,
        }
    return None


def message_text(message: Message) -> str | None:
    text = message.text or message.caption
    if text:
        text = text.strip()
    return text or None


async def save_attachment(
    bot: Bot,
    message: Message,
    ticket_id: int,
    uploads_dir: Path,
    max_download_mb: int,
) -> dict | None:
    attachment = extract_attachment(message)
    if not attachment:
        return None

    file_size = attachment.get("file_size") or 0
    if file_size and file_size > max_download_mb * 1024 * 1024:
        return attachment

    ticket_dir = uploads_dir / str(ticket_id)
    ticket_dir.mkdir(parents=True, exist_ok=True)
    file_name = safe_filename(
        attachment.get("file_name"),
        f"{attachment['content_type']}_{attachment.get('file_unique_id') or message.message_id}",
    )
    local_path = ticket_dir / file_name

    try:
        tg_file = await bot.get_file(attachment["file_id"])
        await bot.download_file(tg_file.file_path, destination=local_path)
        attachment["local_path"] = str(local_path)
    except Exception:
        attachment["local_path"] = None

    return attachment
