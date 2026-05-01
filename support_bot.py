import asyncio
import logging
from datetime import datetime
from aiogram import Bot, Dispatcher, F, Router
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.filters import Command
import aiosqlite

logging.basicConfig(level=logging.INFO)

# ================= НАСТРОЙКИ =================
BOT_TOKEN = "ВАШ_ТОКЕН"

MODERATORS = [123456789]  # ← Твои ID

bot = Bot(token=BOT_TOKEN, parse_mode="HTML")
dp = Dispatcher()
router = Router()
dp.include_router(router)

DB_NAME = "support.db"


# ================= БАЗА ДАННЫХ =================
async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS tickets (
                ticket_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                mod_id INTEGER,
                category TEXT,
                status TEXT DEFAULT 'pending',  -- pending, active, closed
                created_at TEXT
            );
            
            CREATE TABLE IF NOT EXISTS auto_replies (
                keyword TEXT PRIMARY KEY,
                response TEXT
            );
        """)
        # Пример автоответов
        await db.executemany("INSERT OR IGNORE INTO auto_replies (keyword, response) VALUES (?, ?)", [
            ("привет", "Здравствуйте! Чем могу помочь?"),
            ("как дела", "Спасибо, хорошо! А у вас как?"),
            ("цена", "Уточните, пожалуйста, какой именно товар/услуга вас интересует."),
        ])
        await db.commit()


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


# Выбор категории
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

    await callback.message.edit_text(f"✅ Категория выбрана: <b>{category}</b>\n\nОпишите вашу проблему:")
    await callback.answer()


# Все сообщения от пользователей
@router.message(F.chat.type == "private")
async def user_message(message: Message):
    user_id = message.from_user.id

    async with aiosqlite.connect(DB_NAME) as db:
        # Проверяем активный тикет
        async with db.execute("SELECT ticket_id, mod_id, status FROM tickets WHERE user_id = ? AND status != 'closed' ORDER BY ticket_id DESC LIMIT 1", (user_id,)) as cursor:
            ticket = await cursor.fetchone()

        if ticket:
            ticket_id, mod_id, status = ticket
            if status == "active" and mod_id:
                try:
                    await message.forward(mod_id)
                except:
                    pass
                return
            else:
                await message.answer("⏳ Ваша заявка уже в обработке. Ожидайте ответа.")
                return

        # Автоответ
        text = (message.text or "").lower()
        async with db.execute("SELECT response FROM auto_replies WHERE ? LIKE '%' || keyword || '%'", (text,)) as cursor:
            reply = await cursor.fetchone()
            if reply:
                await message.answer(reply[0])
                return

    await message.answer("❗️ Сначала выберите категорию через /start")


# Модератор принимает тикет
@router.callback_query(F.data.startswith("accept_"))
async def accept_ticket(callback: CallbackQuery):
    user_id = int(callback.data.split("_")[1])
    mod_id = callback.from_user.id

    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT ticket_id FROM tickets WHERE user_id = ? AND status = 'pending' ORDER BY ticket_id DESC LIMIT 1", (user_id,)) as cursor:
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
        await bot.send_message(user_id, "✅ Ваша заявка принята в работу! Модератор скоро ответит.")
    except:
        pass


# Ответ модератора → пользователю
@router.message(F.chat.type == "private", lambda m: m.from_user.id in [m for m in MODERATORS])
async def mod_reply(message: Message):
    # Ищем последнего активного пользователя модератора
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT user_id FROM tickets WHERE mod_id = ? AND status = 'active' ORDER BY ticket_id DESC LIMIT 1",
            (message.from_user.id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                await message.forward(row[0])


# Закрытие тикета кнопкой
@router.callback_query(F.data.startswith("close_"))
async def close_ticket(callback: CallbackQuery):
    _, ticket_id, user_id = callback.data.split("_")
    ticket_id = int(ticket_id)
    user_id = int(user_id)

    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE tickets SET status = 'closed' WHERE ticket_id = ?", (ticket_id,))
        await db.commit()

    await callback.message.edit_text(callback.message.text + "\n\n🔒 <b>Тикет закрыт</b>")
    await callback.answer("Тикет закрыт")

    try:
        await bot.send_message(user_id, "🔒 Ваша заявка закрыта. Спасибо за обращение!")
    except:
        pass


# Очередь тикетов
@router.message(Command("queue"))
async def show_queue(message: Message):
    if message.from_user.id not in MODERATORS:
        return

    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("""
            SELECT ticket_id, user_id, category, created_at 
            FROM tickets 
            WHERE status = 'pending' 
            ORDER BY ticket_id
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
