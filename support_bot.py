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
    await message.answer("👋 Выберите категорию вашего обращения:", reply_markup=category_keyboard())


@router.message(Command("addmod"))
async def cmd_addmod(message: Message):
    if message.from_user.id not in MODERATORS:
        return await message.answer("❌ У вас нет прав.")

    try:
        arg = message.text.split(maxsplit=1)[1].strip()
    except IndexError:
        return await message.answer("Использование:\n/addmod 123456789\nили\n/addmod @username")

    target_id = None

    if arg.startswith("@"):
        username = arg[1:]
        try:
            chat = await bot.get_chat(username)
            target_id = chat.id
            await message.answer(f"✅ Найден пользователь @{username} (ID: <code>{target_id}</code>)")
        except Exception:
            return await message.answer("❌ Не удалось найти пользователя по этому @username.\nПопробуйте использовать числовой ID.")
    else:
        try:
            target_id = int(arg)
        except ValueError:
            return await message.answer("❌ Неверный формат. Используйте число или @username.")

    if target_id in MODERATORS:
        return await message.answer("Пользователь уже модератор.")

    MODERATORS.add(target_id)
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT OR IGNORE INTO moderators (user_id) VALUES (?)", (target_id,))
        await db.commit()

    await message.answer(f"✅ Пользователь <code>{target_id}</code> успешно добавлен в модераторы.")
    try:
        await bot.send_message(target_id, "🎉 Вас назначили модератором поддержки!")
    except:
        pass


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
        text += f"ID: <code>{t[0]}</code> | Пользователь: <code>{t[1]}</code> | {t[2]}\n"
    await message.answer(text)


@router.message(Command("close"))
async def cmd_close(message: Message):
    if message.from_user.id not in MODERATORS:
        return
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT ticket_id, user_id FROM tickets WHERE mod_id = ? AND status = 'active' ORDER BY ticket_id DESC LIMIT 1",
            (message.from_user.id,)
        ) as c:
            row = await c.fetchone()
            if not row:
                return await message.answer("❌ Нет активного тикета.")
            ticket_id, user_id = row
            await db.execute("UPDATE tickets SET status = 'closed' WHERE ticket_id = ?", (ticket_id,))
            await db.commit()
    await message.answer("✅ Тикет закрыт.")
    try:
        await bot.send_message(user_id, "🔒 Ваша заявка закрыта.")
    except:
        pass


# ================= СООБЩЕНИЯ ОТ ПОЛЬЗОВАТЕЛЕЙ =================
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

        for mod_id in MODERATORS:
            try:
                await bot.send_message(
                    mod_id,
                    f"🔔 <b>Новая заявка</b>\nКатегория: <b>{category}</b>\nПользователь: <code>{user_id}</code>\n\n{text[:400]}...",
                    reply_markup=get_accept_keyboard(user_id)
                )
            except:
                continue

        await message.answer("✅ Сообщение отправлено модераторам. Можете писать дальше.")


@router.message(F.chat.type == "private", lambda m: m.from_user.id in MODERATORS)
async def mod_reply(message: Message):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT user_id FROM tickets WHERE mod_id = ? AND status = 'active' ORDER BY ticket_id DESC LIMIT 1",
            (message.from_user.id,)
        ) as c:
            row = await c.fetchone()
            if row:
                await bot.send_message(row[0], f"<b>Ответ поддержки:</b>\n\n{message.text}")


@router.callback_query(F.data.startswith("accept_"))
async def accept_ticket(callback: CallbackQuery):
    if callback.from_user.id not in MODERATORS:
        return await callback.answer("Нет прав!", show_alert=True)

    user_id = int(callback.data.split("_")[1])
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT ticket_id FROM tickets WHERE user_id = ? AND status = 'pending' ORDER BY ticket_id DESC LIMIT 1",
            (user_id,)
        ) as c:
            row = await c.fetchone()
            if row:
                await db.execute("UPDATE tickets SET mod_id = ?, status = 'active' WHERE ticket_id = ?",
                                 (callback.from_user.id, row[0]))
                await db.commit()

    await callback.message.edit_text(callback.message.text + f"\n\n✅ Принято {callback.from_user.full_name}")
    await callback.answer("Тикет принят!")
    try:
        await bot.send_message(user_id, "✅ Заявка принята в работу!")
    except:
        pass


async def main():
    await init_db()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
