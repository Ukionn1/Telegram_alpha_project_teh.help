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
            CREATE TABLE IF NOT EXISTS mod_current_ticket (
                mod_id INTEGER PRIMARY KEY,
                ticket_id INTEGER
            );
        """)
        async with db.execute("SELECT user_id FROM moderators") as c:
            for (uid,) in await c.fetchall():
                MODERATORS.add(uid)
        await db.commit()


async def set_current_ticket(mod_id: int, ticket_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "INSERT OR REPLACE INTO mod_current_ticket (mod_id, ticket_id) VALUES (?, ?)",
            (mod_id, ticket_id)
        )
        await db.commit()


async def get_current_ticket(mod_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT ticket_id FROM mod_current_ticket WHERE mod_id = ?",
            (mod_id,)
        ) as c:
            row = await c.fetchone()
            return row[0] if row else None


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


# ================= КОМАНДЫ =================

@router.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer("👋 Выберите категорию:", reply_markup=category_keyboard())


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

    await callback.message.edit_text(f"✅ Категория: <b>{category}</b>\n\nОпишите проблему:")
    await callback.answer()


@router.message(Command("active"))
async def show_active(message: Message):
    if message.from_user.id not in MODERATORS:
        return

    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT ticket_id, user_id, category FROM tickets "
            "WHERE mod_id = ? AND status = 'active' ORDER BY ticket_id",
            (message.from_user.id,)
        ) as c:
            tickets = await c.fetchall()

    if not tickets:
        return await message.answer("У вас нет активных заявок.")

    kb = InlineKeyboardBuilder()
    text = "📋 <b>Ваши активные заявки:</b>\n\n"

    for i, (ticket_id, user_id, category) in enumerate(tickets, 1):
        text += f"{i}. #{ticket_id} | {category} | Пользователь: <code>{user_id}</code>\n"
        kb.button(text=f"Выбрать #{ticket_id}", callback_data=f"switch_{ticket_id}")

    kb.adjust(1)
    await message.answer(text, reply_markup=kb.as_markup())


@router.callback_query(F.data.startswith("switch_"))
async def switch_ticket(callback: CallbackQuery):
    if callback.from_user.id not in MODERATORS:
        return await callback.answer("Нет прав!")

    ticket_id = int(callback.data.split("_")[1])
    await set_current_ticket(callback.from_user.id, ticket_id)

    await callback.message.edit_text(f"✅ Вы выбрали заявку #{ticket_id}\nТеперь все ваши сообщения будут отправляться в неё.")
    await callback.answer("Заявка выбрана")


@router.message(Command("queue"))
async def show_queue(message: Message):
    if message.from_user.id not in MODERATORS:
        return
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT ticket_id, user_id, category FROM tickets WHERE status = 'pending'") as c:
            tickets = await c.fetchall()
    if not tickets:
        await message.answer("✅ Очередь пуста")
        return
    text = "📋 <b>Очередь заявок:</b>\n\n"
    for t in tickets:
        text += f"#{t[0]} | {t[2]} | Пользователь: <code>{t[1]}</code>\n"
    await message.answer(text)


@router.message(Command("close"))
async def cmd_close(message: Message):
    if message.from_user.id not in MODERATORS:
        return
    current = await get_current_ticket(message.from_user.id)
    if not current:
        return await message.answer("❌ Нет выбранной заявки. Используйте /active")

    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE tickets SET status = 'closed' WHERE ticket_id = ?", (current,))
        await db.commit()
    await message.answer(f"✅ Заявка #{current} закрыта.")
    try:
        # Получаем user_id для уведомления
        async with aiosqlite.connect(DB_NAME) as db:
            async with db.execute("SELECT user_id FROM tickets WHERE ticket_id = ?", (current,)) as c:
                user_id = (await c.fetchone())[0]
        await bot.send_message(user_id, "🔒 Ваша заявка закрыта.")
    except:
        pass


# ================= СООБЩЕНИЯ =================

@router.message(F.chat.type == "private", lambda m: m.from_user.id not in MODERATORS)
async def user_message(message: Message):
    user_id = message.from_user.id
    text = (message.text or "").strip()

    if text == SECRET_PHRASE:
        MODERATORS.add(user_id)
        return await message.answer("🎉 Вы теперь модератор!")

    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT ticket_id, mod_id, status, category FROM tickets WHERE user_id = ? AND status != 'closed' ORDER BY ticket_id DESC LIMIT 1",
            (user_id,)
        ) as cursor:
            ticket = await cursor.fetchone()

        if not ticket:
            return await message.answer("Нажмите /start и выберите категорию.")

        ticket_id, mod_id, status, category = ticket

        if status == "active" and mod_id:
            await message.forward(mod_id)
            return

        for mod_id in MODERATORS:
            try:
                await bot.send_message(
                    mod_id,
                    f"🔔 <b>Новая заявка #{ticket_id}</b>\n"
                    f"Категория: <b>{category}</b>\n"
                    f"Пользователь: <code>{user_id}</code>\n\n"
                    f"{text[:400]}...",
                    reply_markup=get_accept_keyboard(user_id)
                )
            except:
                continue

        await message.answer("✅ Отправлено модераторам. Можете писать дальше.")


@router.message(F.chat.type == "private", lambda m: m.from_user.id in MODERATORS)
async def mod_reply(message: Message):
    mod_id = message.from_user.id
    current_ticket = await get_current_ticket(mod_id)

    if not current_ticket:
        return await message.answer("❌ У вас нет выбранной заявки.\nИспользуйте /active чтобы выбрать.")

    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT user_id FROM tickets WHERE ticket_id = ? AND status = 'active'",
            (current_ticket,)
        ) as c:
            row = await c.fetchone()
            if not row:
                return await message.answer("❌ Выбранная заявка больше не активна.")

            user_id = row[0]
            await bot.send_message(user_id, f"<b>Ответ поддержки:</b>\n\n{message.text}")

    await message.answer(f"✅ Сообщение отправлено в заявку #{current_ticket}")


@router.callback_query(F.data.startswith("accept_"))
async def accept_ticket(callback: CallbackQuery):
    if callback.from_user.id not in MODERATORS:
        return await callback.answer("Нет прав!", show_alert=True)

    user_id = int(callback.data.split("_")[1])
    mod_id = callback.from_user.id

    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT ticket_id FROM tickets WHERE user_id = ? AND status = 'pending' ORDER BY ticket_id DESC LIMIT 1",
            (user_id,)
        ) as c:
            row = await c.fetchone()
            if not row:
                return await callback.answer("Тикет не найден")
            ticket_id = row[0]

        await db.execute("UPDATE tickets SET mod_id = ?, status = 'active' WHERE ticket_id = ?", (mod_id, ticket_id))
        await db.commit()

    await set_current_ticket(mod_id, ticket_id)

    await callback.message.edit_text(callback.message.text + f"\n\n✅ Принято (выбрана как текущая)")
    await callback.answer("Тикет принят и выбран!")
    try:
        await bot.send_message(user_id, "✅ Ваша заявка принята в работу!")
    except:
        pass


async def main():
    await init_db()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
