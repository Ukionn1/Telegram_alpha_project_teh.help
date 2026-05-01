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

SECRET_PHRASE = "стань_модератором_секрет123"   # ← Измени!

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
            CREATE TABLE IF NOT EXISTS tickets (...);  -- (оставил сокращённо)
            CREATE TABLE IF NOT EXISTS auto_replies (...);
            CREATE TABLE IF NOT EXISTS moderators (user_id INTEGER PRIMARY KEY);
        """)
        # Загрузка модераторов
        async with db.execute("SELECT user_id FROM moderators") as cursor:
            for (uid,) in await cursor.fetchall():
                MODERATORS.add(uid)
        
        await db.executemany("INSERT OR IGNORE INTO auto_replies (keyword, response) VALUES (?, ?)", [
            ("привет", "Здравствуйте! Чем могу помочь?"),
            ("цена", "Уточните, пожалуйста..."),
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


# ================= КОМАНДА /addmod =================
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
            # Пытаемся получить ID по username
            username = target[1:]
            # Для этого пользователь должен писать боту или быть в чате
            # aiogram не может напрямую получить ID по username без дополнительной логики.
            # Поэтому рекомендуем использовать ID.
            await message.answer("⚠️ Добавление по @username работает нестабильно.\nЛучше используйте числовой ID пользователя.")
            return
        else:
            # По ID
            target_id = int(target)
    except ValueError:
        await message.answer("❌ Неверный формат. Используйте @username или числовой ID.")
        return

    added = await add_moderator(target_id)
    if added:
        await message.answer(f"✅ Пользователь `{target_id}` добавлен в модераторы.")
        try:
            await bot.send_message(target_id, "🎉 Вас назначили модератором поддержки!")
        except:
            await message.answer("⚠️ Не удалось отправить уведомление пользователю (возможно, он не писал боту).")
    else:
        await message.answer("Пользователь уже является модератором.")


# ================= Остальной код (user_message, accept, close и т.д.) =================
@router.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        "👋 Добро пожаловать в поддержку!\n\nВыберите категорию:",
        reply_markup=InlineKeyboardBuilder().button(text=cat, callback_data=f"cat_{cat}").adjust(1).as_markup()
        for cat in ["Техническая проблема", "Оплата", "Возврат", "Другое"]  # упрощённо
    )  # Примечание: полную клавиатуру оставь как в предыдущей версии


# ... (весь остальной код из предыдущей версии: user_message, secret phrase, accept_ticket, mod_reply, close_ticket, /queue и main())

# Для экономии места я не дублирую весь код здесь. 
# Просто возьми предыдущую полную версию и замени блок /addmod на новый выше.
