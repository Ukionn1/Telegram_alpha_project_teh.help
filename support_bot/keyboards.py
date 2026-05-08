from aiogram.types import KeyboardButton, ReplyKeyboardMarkup, WebAppInfo
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .texts import CATEGORIES, STATUS_EMOJI, STATUS_TITLES


def user_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🆘 Создать заявку"), KeyboardButton(text="❓ Частые вопросы")],
            [KeyboardButton(text="📋 Мои заявки")],
        ],
        resize_keyboard=True,
        persistent=True,
    )


def moderator_menu(web_app_url: str | None = None) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📌 Текущая"), KeyboardButton(text="🕘 Новые заявки"), KeyboardButton(text="🖥 Кабинет")],
            [KeyboardButton(text="🟢 Мои активные"), KeyboardButton(text="📝 Все открытые")],
            [KeyboardButton(text="⏭ Взять следующую"), KeyboardButton(text="🧾 Лог текущей")],
            [KeyboardButton(text="💬 Шаблоны"), KeyboardButton(text="🔒 Закрыть текущую")],
        ],
        resize_keyboard=True,
        persistent=True,
    )


def moderator_webapp_keyboard(web_app_url: str):
    kb = InlineKeyboardBuilder()
    kb.button(text="🖥 Открыть кабинет", web_app=WebAppInfo(url=web_app_url))
    return kb.as_markup()


def cancel_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Отмена")]],
        resize_keyboard=True,
        one_time_keyboard=False,
    )


def attachment_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="✅ Отправить заявку")],
            [KeyboardButton(text="Отмена")],
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
    )


def category_keyboard():
    kb = InlineKeyboardBuilder()
    for key, title in CATEGORIES:
        kb.button(text=title, callback_data=f"ticket_cat:{key}")
    kb.adjust(1)
    return kb.as_markup()


def after_faq_keyboard():
    kb = InlineKeyboardBuilder()
    kb.button(text="🆘 Создать заявку", callback_data="ticket_create")
    kb.button(text="❓ Еще вопросы", callback_data="faq_list")
    kb.adjust(1)
    return kb.as_markup()


def faq_keyboard(items: list[dict]):
    kb = InlineKeyboardBuilder()
    for item in items:
        kb.button(text=item["question"], callback_data=f"faq:{item['id']}")
    kb.button(text="🆘 Создать заявку", callback_data="ticket_create")
    kb.adjust(1)
    return kb.as_markup()


def ticket_actions(ticket_id: int, status: str | None = None):
    kb = InlineKeyboardBuilder()
    if status == "pending" or status is None:
        kb.button(text="✅ Взять", callback_data=f"take:{ticket_id}")
    kb.button(text="📌 Текущая", callback_data=f"select:{ticket_id}")
    kb.button(text="🧾 Лог", callback_data=f"log:{ticket_id}")
    kb.button(text="🔒 Закрыть", callback_data=f"close:{ticket_id}")
    kb.adjust(2)
    return kb.as_markup()


def ticket_list_keyboard(tickets: list[dict], action: str = "select"):
    kb = InlineKeyboardBuilder()
    for ticket in tickets:
        status = ticket.get("status", "")
        label = f"{STATUS_EMOJI.get(status, '')} #{ticket['ticket_id']} · {ticket['subject'][:28]}"
        kb.button(text=label, callback_data=f"{action}:{ticket['ticket_id']}")
    kb.adjust(1)
    return kb.as_markup()


def canned_keyboard(replies: list[dict]):
    kb = InlineKeyboardBuilder()
    for item in replies:
        kb.button(text=item["title"], callback_data=f"replytpl:{item['id']}")
    kb.adjust(1)
    return kb.as_markup()


def status_label(status: str) -> str:
    return f"{STATUS_EMOJI.get(status, '')} {STATUS_TITLES.get(status, status)}".strip()
