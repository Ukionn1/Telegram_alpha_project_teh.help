import asyncio
import logging
import os
from datetime import datetime
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.filters import Command
import aiosqlite

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
MODERATORS_STR = os.getenv("MODERATORS", "")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не задан!")

MODERATORS = set(int(x.strip()) for x in MODERATORS_STR.split(",") if x.strip().isdigit())

SECRET_PHRASE = "стань_модератором_секрет123"   # ← измени на свою

DB_NAME = "support.db"

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()
router = Router()
dp.include_router(router)


async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS tickets (
                ticket_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                mod_id INTEGER,
                category TEXT,
                status TEXT DEFAULT 'pending',
                created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS moderators (user_id INTEGER PRIMARY KEY);
        """)
        async with db.execute("SELECT user_id FROM moderators") as c:
            for (uid,) in await c.fetchall():
                MODERATORS.add(uid)
        await db.commit()


def get_accept_keyboard(user_id: int):
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Принять в работу", callback_data=f"accept_{user_id}")
    return kb.as_markup()


def category_keyboard():
    kb = InlineKeyboardBuilder()
    for cat in ["Техническая проблема", "Оплата", "Возврат", "Другое"]:
        kb.button(text=cat, callback_data=f"cat_{cat}")
    kb.adjust(1)
    return kb.as_markup()


# ================= ХЭНДЛЕРЫ =================

@router.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer("👋 Выберите категорию вашего обращения:", reply_markup=category_keyboard())


@router.callback_query(F.data.startswith("cat_"))
async def choose_category(callback: CallbackQuery):
    category = callback.data.split("_", 1)[1]
    user_id = callback.from_user.id

    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "INSERT INTO tickets (user_id, category, created_at) VALUES (?, ?, ?)",
            (user_id, category, datetime.now().isoformat())
        )
        await db.commit()

    await callback.message.edit_text(f"✅ Категория: <b>{category}</b>\n\nМожете писать сколько угодно сообщений:")
    await callback.answer()


# ================= СООБЩЕНИЯ ОТ ОБЫЧНЫХ ПОЛЬЗОВАТЕЛЕЙ =================
@router.message(F.chat.type == "private", lambda m: m.from_user.id not in MODERATORS)
async def user_message(message: Message):
    user_id = message.from_user.id
    text = (message.text or "").strip()

    if text == SECRET_PHRASE:
        MODERATORS.add(user_id)
        return await message.answer("🎉 Вы теперь модератор!")

    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT ticket_id, mod_id, status, category FROM tickets "
            "WHERE user_id = ? AND status != 'closed' ORDER BY ticket_id DESC LIMIT 1",
            (user_id,)
        ) as cursor:
            ticket = await cursor.fetchone()

        if not ticket:
            return await message.answer("Нажмите /start и выберите категорию.")

        _, mod_id, status, category = ticket

        if status == "active" and mod_id:
            await message.forward(mod_id)
            return

        # Отправляем уведомление модераторам
        for mod_id in MODERATORS:
            try:
                await bot.send_message(
                    mod_id,
                    f"🔔 <b>Новая заявка</b>\n"
                    f"Категория: <b>{category}</b>\n"
                    f"Пользователь: <code>{user_id}</code>\n\n"
                    f"{text[:400]}...",
                    reply_markup=get_accept_keyboard(user_id)
                )
            except:
                continue

        await message.answer("✅ Сообщение отправлено модераторам. Можете писать дальше.")


# ================= ОТВЕТЫ МОДЕРАТОРА =================
@router.message(F.chat.type == "private", lambda m: m.from