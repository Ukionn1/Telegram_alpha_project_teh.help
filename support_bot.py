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

# ================= НАСТРОЙКИ =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
MODERATORS_STR = os.getenv("MODERATORS", "")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не задан в переменных окружения!")

MODERATORS = set(int(x.strip()) for x in MODERATORS_STR.split(",") if x.strip().isdigit())

SECRET_PHRASE = "стань_модератором_секрет123"   # ← ИЗМЕНИ НА СВОЮ СЕКРЕТНУЮ ФРАЗУ!

DB_NAME = "support.db"

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode="HTML")
)

dp = Dispatcher()
router = Router()
dp.include_router(router)


# ================= БАЗА ДАННЫХ =================
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
            CREATE TABLE IF NOT EXISTS auto_replies (
                keyword TEXT PRIMARY KEY,
                response TEXT
            );
            CREATE TABLE IF NOT EXISTS moderators (
                user_id INTEGER PRIMARY KEY
            );
        """)
        # Загружаем модераторов из БД
        async with db.execute("SELECT user_id FROM moderators") as cursor:
            for (uid,) in await cursor.fetchall():
                MODERATORS.add(uid)
        
        # Автоответы
        await db.executemany("INSERT OR IGNORE INTO auto_replies (keyword, response) VALUES (?, ?)", [
            ("привет", "Здравствуйте! Чем могу помочь?"),
            ("цена", "Уточните, пожалуйста, какой товар или услуга вас интересует."),
            ("как дела", "Спасибо, хорошо! А у вас как?"),
        ])
        await db.commit()


async def add_moderator(user_id: int) -> bool:
    if user_id in MODERATORS:
        return False
    MODERATORS.add(user_id)
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT OR IGNORE INTO moderators (user_id) VALUES (?)", (user_id,))
        await db.commit()
    return True


# ================= КЛАВИАТУРЫ =================
def category_keyboard():
    kb = InlineKeyboardBuilder()
    categories = ["Техническая проблема", "Оплата", "Возврат", "Другое"]
    for cat in categories:
        kb.button(text=cat, callback_data=f"cat_{cat}")
    kb.adjust(1)
    return kb.as_markup()


def get_ticket_keyboard(ticket_id: int, user_id: int):
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Закрыть тикет", callback_data=f"close_{ticket_id}_{user_id}")
    return kb.as_markup()


# ================= ХЭНДЛЕРЫ =================

@router.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        "👋 Добро пожаловать в поддержку!\n\n"
        "Выберите категорию вашего обращения:",
        reply_markup=category_keyboard()
    )


@router.message(Command("addmod"))
async def cmd_addmod(message: Message):
    if message.from_user.id not in MODERATORS:
        await message.answer("❌ У вас нет прав для этой команды.")
        return

    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Использование:\n/addmod @username\nили\n/addmod 123456789")
        return

    target = args[1].strip()
    try:
        if target.startswith("@"):
            await message.answer("⚠️ Добавление по @username пока не поддерживается стабильно.\nИспользуйте числовой ID пользователя.")
            return
        else:
            target_id = int(target)
    except ValueError:
        await message.answer("❌ Неверный формат.")
        return

    added = await add_moderator(target_id)
    if added:
        await message.answer(f"✅ Пользователь `{target_id}` добавлен в модераторы.")
        try:
            await bot.send_message(target_id, "🎉 Вас назначили модератором поддержки!")
        except:
            await message.answer("⚠️ Пользователь не писал боту, уведомление не отправлено.")
    else:
        await message.answer("Пользователь уже модератор.")


@router.message(F.chat.type == "private")
async def user_message(message: Message):
    user_id = message.from_user.id
    text = (message.text or "").strip()

    # Секретная фраза
    if text == SECRET_PHRASE:
        added = await add_moderator(user_id)
        await message.answer("🎉 Вы успешно добавлены в модераторы!" if added else "Вы уже модератор.")
        return

    # Обычное сообщение пользователя
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT ticket_id, mod_id, status FROM tickets WHERE user_id = ? AND status != 'closed' ORDER BY ticket_id DESC LIMIT 1",
            (user_id,)
        ) as cursor:
            ticket = await cursor.fetchone()

        if ticket:
            _, mod_id, status = ticket
            if status == "active" and mod_id:
                try:
                    await message.forward(mod_id)
                except:
                    pass
                return
            else:
                await message.answer("⏳ Ваша заявка уже в обработке. Ожидайте.")
                return

        # Автоответ
        async with db.execute("SELECT response FROM auto_replies WHERE ? LIKE '%' || keyword || '%'", (text.lower(),)) as cursor:
            reply = await cursor.fetchone()
            if reply:
                await message.answer(reply[0])
                return

    await message.answer("❗️ Сначала выберите категорию через /start")


@router.callback_query(F.data.startswith("accept_"))
async def accept_ticket(callback: CallbackQuery):
    if callback.from_user.id not in MODERATORS:
        await callback.answer("Нет прав!", show_alert=True)
        return

    user_id = int(callback.data.split("_")[1])
    mod_id = callback.from_user.id

    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT ticket_id FROM tickets WHERE user_id = ? AND status = 'pending' ORDER BY ticket_id DESC LIMIT 1",
            (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                await callback.answer("Тикет не найден")
                return
            ticket_id = row[0]

        await db.execute("UPDATE tickets SET mod_id = ?, status = 'active' WHERE ticket_id = ?", (mod_id, ticket_id))
        await db.commit()

    await callback.message.edit_text(
        callback.message.text + f"\n\n✅ Принято модератором {callback.from_user.full_name}"
    )
    await callback.answer("Тикет принят!")

    try:
        await bot.send_message(user_id, "✅ Ваша заявка принята в работу!")
    except:
        pass


@router.message(F.chat.type == "private", lambda m: m.from_user.id in MODERATORS)
async def mod_reply(message: Message):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT user_id FROM tickets WHERE mod_id = ? AND status = 'active' ORDER BY ticket_id DESC LIMIT 1",
            (message.from_user.id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                try:
                    await message.forward(row[0])
                except:
                    pass


@router.callback_query(F.data.startswith("close_"))
async def close_ticket(callback: CallbackQuery):
    if callback.from_user.id not in MODERATORS:
        return
    _, ticket_id, user_id = callback.data.split("_")
    ticket_id = int(ticket_id)

    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE tickets SET status = 'closed' WHERE ticket_id = ?", (ticket_id,))
        await db.commit()

    await callback.message.edit_text(callback.message.text + "\n\n🔒 <b>Тикет закрыт</b>")
    await callback.answer("Тикет закрыт")

    try:
        await bot.send_message(int(user_id), "🔒 Ваша заявка закрыта. Спасибо!")
    except:
        pass


@router.message(Command("queue"))
async def show_queue(message: Message):
    if message.from_user.id not in MODERATORS:
        return
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("""
            SELECT ticket_id, user_id, category, created_at 
            FROM tickets WHERE status = 'pending' ORDER BY ticket_id
        """) as cursor:
            tickets = await cursor.fetchall()

    if not tickets:
        await message.answer("✅ Очередь пуста")
        return

    text = "📋 <b>Очередь тикетов:</b>\n\n"
    for t in tickets:
        text += f"ID: <code>{t[0]}</code> | Категория: {t[2]}\n"
    await message.answer(text)


# ================= ЗАПУСК =================
async def main():
    await init_db()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
