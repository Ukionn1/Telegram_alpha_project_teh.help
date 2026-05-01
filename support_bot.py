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

SECRET_PHRASE = "стань_модератором_секрет123"

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


async def add_moderator(user_id: int) -> bool:
    if user_id in MODERATORS: return False
    MODERATORS.add(user_id)
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT OR IGNORE INTO moderators VALUES (?)", (user_id,))
        await db.commit()
    return True


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

    await callback.message.edit_text(f"✅ Категория: <b>{category}</b>\n\nОпишите вашу проблему:")
    await callback.answer("Категория выбрана")


@router.message(Command("addmod"))
async def cmd_addmod(message: Message):
    if message.from_user.id not in MODERATORS:
        return await message.answer("Нет прав.")
    # ваш код /addmod...


@router.message(Command("queue"))
async def show_queue(message: Message):
    if message.from_user.id not in MODERATORS: return
    # код /queue...


@router.message(Command("close"))
async def cmd_close(message: Message):
    if message.from_user.id not in MODERATORS: return
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT ticket_id, user_id FROM tickets WHERE mod_id = ? AND status = 'active' ORDER BY ticket_id DESC LIMIT 1",
            (message.from_user.id,)
        ) as c:
            row = await c.fetchone()
            if not row:
                return await message.answer("Нет активного тикета.")
            ticket_id, user_id = row
            await db.execute("UPDATE tickets SET status = 'closed' WHERE ticket_id = ?", (ticket_id,))
            await db.commit()
    await message.answer("✅ Тикет закрыт.")
    try:
        await bot.send_message(user_id, "🔒 Ваша заявка закрыта.\nЕсли нужно — нажмите /start и выберите категорию.")
    except:
        pass


@router.message(F.chat.type == "private")
async def user_message(message: Message):
    user_id = message.from_user.id
    text = (message.text or "").strip()

    if text == SECRET_PHRASE:
        await add_moderator(user_id)
        return await message.answer("🎉 Вы теперь модератор!")

    async with aiosqlite.connect(DB_NAME) as db:
        # Проверяем, есть ли открытый тикет
        async with db.execute(
            "SELECT status FROM tickets WHERE user_id = ? AND status != 'closed' ORDER BY ticket_id DESC LIMIT 1",
            (user_id,)
        ) as c:
            active = await c.fetchone()

        if not active:
            # Нет активного тикета — предлагаем начать заново
            return await message.answer("Пожалуйста, нажмите /start и выберите категорию для нового обращения.")

        if active[0] == "active":
            # Пересылаем модератору
            async with db.execute("SELECT mod_id FROM tickets WHERE user_id = ? AND status = 'active' ORDER BY ticket_id DESC LIMIT 1", (user_id,)) as c:
                mod_row = await c.fetchone()
                if mod_row and mod_row[0]:
                    await message.forward(mod_row[0])
            return

    # Если дошли сюда — создаём новый тикет (но лучше через /start)
    await message.answer("Нажмите /start для нового обращения.")


# accept_ticket, mod_reply и т.д. — оставил как раньше (можно добавить из предыдущих версий)


async def main():
    await init_db()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
