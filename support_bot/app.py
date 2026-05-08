from __future__ import annotations

import logging
from typing import Awaitable, Callable

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, Message

from .config import Settings
from .db import Database
from .files import message_text, save_attachment
from .formatting import (
    clip,
    format_public_ticket,
    format_ticket_header,
    format_ticket_list,
    format_ticket_log,
    format_ticket_notification,
    h,
)
from .keyboards import (
    after_faq_keyboard,
    attachment_menu,
    cancel_menu,
    canned_keyboard,
    category_keyboard,
    faq_keyboard,
    moderator_menu,
    moderator_webapp_keyboard,
    ticket_actions,
    ticket_list_keyboard,
    user_menu,
)
from .knowledge import find_faq_answer
from .texts import CATEGORY_TITLES, OPEN_STATUSES

logger = logging.getLogger(__name__)

SECRET_PHRASE = "стань_модератором_секрет123"


class TicketFlow(StatesGroup):
    category = State()
    subject = State()
    details = State()
    attachments = State()


def build_bot(settings: Settings) -> Bot:
    return Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


def build_dispatcher(settings: Settings, db: Database) -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage(), settings=settings, db=db)
    router = Router()
    register_handlers(router, settings, db)
    dp.include_router(router)
    return dp


def is_moderator(settings: Settings, user_id: int | None) -> bool:
    return bool(user_id and user_id in settings.moderators)


def is_cancel(text: str | None) -> bool:
    return (text or "").strip().lower() in {"отмена", "/cancel", "cancel"}


async def remember_user(db: Database, message: Message) -> None:
    user = message.from_user
    if user:
        await db.upsert_user(user.id, user.username, user.full_name)


async def safe_edit_text(callback: CallbackQuery, text: str, **kwargs) -> None:
    if not callback.message:
        return
    try:
        await callback.message.edit_text(text, **kwargs)
    except TelegramBadRequest:
        await callback.message.answer(text, **kwargs)


async def add_message_from_telegram(
    *,
    db: Database,
    bot: Bot,
    settings: Settings,
    ticket_id: int,
    message: Message,
    sender_role: str,
) -> int:
    attachment = await save_attachment(
        bot=bot,
        message=message,
        ticket_id=ticket_id,
        uploads_dir=settings.uploads_dir,
        max_download_mb=settings.max_download_mb,
    )
    text = message_text(message)
    content_type = attachment["content_type"] if attachment else "text"

    return await db.add_message(
        ticket_id=ticket_id,
        sender_role=sender_role,
        sender_id=message.from_user.id if message.from_user else None,
        tg_chat_id=message.chat.id,
        tg_message_id=message.message_id,
        text=text,
        content_type=content_type,
        file_id=attachment.get("file_id") if attachment else None,
        file_unique_id=attachment.get("file_unique_id") if attachment else None,
        file_name=attachment.get("file_name") if attachment else None,
        mime_type=attachment.get("mime_type") if attachment else None,
        file_size=attachment.get("file_size") if attachment else None,
        local_path=attachment.get("local_path") if attachment else None,
    )


async def notify_moderators(bot: Bot, db: Database, settings: Settings, ticket_id: int) -> None:
    ticket = await db.get_ticket(ticket_id)
    if not ticket:
        return
    messages = await db.get_ticket_messages(ticket_id, limit=100)
    text = format_ticket_notification(ticket, messages)
    mod_ids = await db.get_moderator_ids()
    settings.moderators.update(mod_ids)

    if not mod_ids:
        logger.warning("No moderators configured for ticket #%s", ticket_id)
        return

    attachments = [
        message
        for message in messages
        if message["sender_role"] == "user" and message["content_type"] != "text" and message.get("tg_message_id")
    ]
    for mod_id in mod_ids:
        try:
            await bot.send_message(mod_id, text, reply_markup=ticket_actions(ticket_id, ticket["status"]))
            if attachments:
                await bot.send_message(mod_id, f"📎 Вложения по заявке #{ticket_id}:")
            for attachment in attachments:
                await bot.copy_message(mod_id, attachment["tg_chat_id"], attachment["tg_message_id"])
        except (TelegramBadRequest, TelegramForbiddenError) as exc:
            logger.info("Cannot notify moderator %s: %s", mod_id, exc)


async def notify_about_ticket_update(
    bot: Bot,
    db: Database,
    settings: Settings,
    ticket: dict,
    message: Message,
) -> None:
    snippet = message_text(message) or "[вложение]"
    text = f"💬 Новое сообщение в заявке <b>#{ticket['ticket_id']}</b>\n\n{h(clip(snippet, 800))}"
    target_ids = [ticket["mod_id"]] if ticket.get("mod_id") else list(await db.get_moderator_ids())
    for target_id in target_ids:
        if not target_id:
            continue
        try:
            await bot.send_message(target_id, text, reply_markup=ticket_actions(ticket["ticket_id"], ticket["status"]))
            if message.content_type != "text":
                await bot.copy_message(target_id, message.chat.id, message.message_id)
        except (TelegramBadRequest, TelegramForbiddenError) as exc:
            logger.info("Cannot send ticket update to moderator %s: %s", target_id, exc)


async def show_faq(message: Message, db: Database) -> None:
    items = await db.list_faq()
    await message.answer("Выберите вопрос или напишите его обычным сообщением:", reply_markup=faq_keyboard(items))


async def show_user_tickets(message: Message, db: Database) -> None:
    tickets = await db.list_tickets(user_id=message.from_user.id, limit=10)
    if not tickets:
        await message.answer("У вас пока нет заявок. Нажмите «Создать заявку», если нужна помощь.", reply_markup=user_menu())
        return
    text = "\n\n".join(format_public_ticket(ticket) for ticket in tickets)
    await message.answer(text, reply_markup=user_menu())


async def start_ticket_flow_message(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(TicketFlow.category)
    await message.answer("Оформляем заявку. Для отмены нажмите «Отмена».", reply_markup=cancel_menu())
    await message.answer("Выберите категорию обращения:", reply_markup=category_keyboard())


async def start_ticket_flow_callback(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(TicketFlow.category)
    if callback.message:
        await callback.message.answer("Оформляем заявку. Для отмены нажмите «Отмена».", reply_markup=cancel_menu())
    await safe_edit_text(callback, "Выберите категорию обращения:", reply_markup=category_keyboard())
    await callback.answer()


async def show_ticket_log_to_message(message: Message, db: Database, ticket_id: int, reply_markup=None) -> None:
    ticket = await db.get_ticket(ticket_id)
    if not ticket:
        await message.answer("Заявка не найдена.")
        return
    messages = await db.get_ticket_messages(ticket_id, limit=100)
    events = await db.get_ticket_events(ticket_id, limit=50)
    await message.answer(format_ticket_log(ticket, messages, events), reply_markup=reply_markup or ticket_actions(ticket_id, ticket["status"]))


def register_handlers(router: Router, settings: Settings, db: Database) -> None:
    web_app_url = f"{settings.public_base_url}/app" if settings.public_base_url else None

    @router.message(Command("id"))
    async def cmd_id(message: Message):
        await message.answer(f"Ваш Telegram ID: <code>{message.from_user.id}</code>")

    @router.message(Command("start"))
    async def cmd_start(message: Message, state: FSMContext):
        await remember_user(db, message)
        await state.clear()
        if is_moderator(settings, message.from_user.id):
            await message.answer("Добро пожаловать в панель поддержки.", reply_markup=moderator_menu(web_app_url))
        else:
            await message.answer(
                "Здравствуйте. Я помогу найти ответ или оформить заявку для поддержки.",
                reply_markup=user_menu(),
            )

    @router.message(Command("help"))
    async def cmd_help(message: Message):
        if is_moderator(settings, message.from_user.id):
            await message.answer(
                "Меню модератора: выберите текущую заявку, посмотрите лог или отправьте сообщение клиенту. "
                "Обычное сообщение модератора уходит только в выбранную заявку.",
                reply_markup=moderator_menu(web_app_url),
            )
        else:
            await message.answer(
                "Опишите вопрос обычным сообщением. Если ответа в базе знаний нет, я предложу создать заявку.",
                reply_markup=user_menu(),
            )

    @router.message(Command("cancel"))
    async def cmd_cancel(message: Message, state: FSMContext):
        await state.clear()
        markup = moderator_menu(web_app_url) if is_moderator(settings, message.from_user.id) else user_menu()
        await message.answer("Действие отменено.", reply_markup=markup)

    @router.message(Command("queue"), lambda m: is_moderator(settings, m.from_user.id))
    async def cmd_queue(message: Message):
        await send_pending_tickets(message)

    @router.message(Command("active"), lambda m: is_moderator(settings, m.from_user.id))
    async def cmd_active(message: Message):
        await send_my_active_tickets(message)

    @router.message(Command("close"), lambda m: is_moderator(settings, m.from_user.id))
    async def cmd_close(message: Message, bot: Bot):
        await close_current_ticket(message, bot)

    @router.callback_query(F.data == "ticket_create")
    async def cb_ticket_create(callback: CallbackQuery, state: FSMContext):
        if is_moderator(settings, callback.from_user.id):
            await callback.answer("Для модератора создание заявки отключено.")
            return
        await start_ticket_flow_callback(callback, state)

    @router.callback_query(F.data == "faq_list")
    async def cb_faq_list(callback: CallbackQuery):
        items = await db.list_faq()
        await safe_edit_text(callback, "Выберите вопрос:", reply_markup=faq_keyboard(items))
        await callback.answer()

    @router.callback_query(F.data.startswith("faq:"))
    async def cb_faq(callback: CallbackQuery):
        faq_id = int(callback.data.split(":", 1)[1])
        item = await db.get_faq(faq_id)
        if not item:
            await callback.answer("Вопрос не найден.")
            return
        await safe_edit_text(
            callback,
            f"<b>{h(item['question'])}</b>\n\n{h(item['answer'])}",
            reply_markup=after_faq_keyboard(),
        )
        await callback.answer()

    @router.callback_query(StateFilter(TicketFlow.category), F.data.startswith("ticket_cat:"))
    async def cb_ticket_category(callback: CallbackQuery, state: FSMContext):
        category = callback.data.split(":", 1)[1]
        await state.update_data(category=category)
        await state.set_state(TicketFlow.subject)
        await safe_edit_text(
            callback,
            f"Категория: <b>{h(CATEGORY_TITLES.get(category, category))}</b>\n\n"
            "Напишите короткую тему заявки. Например: «Не проходит оплата» или «Ошибка при входе».",
        )
        await callback.answer()

    @router.message(StateFilter(TicketFlow.category))
    async def ticket_wait_category(message: Message, state: FSMContext):
        if is_cancel(message.text):
            await state.clear()
            await message.answer("Создание заявки отменено.", reply_markup=user_menu())
            return
        await message.answer("Пожалуйста, выберите категорию кнопкой выше.", reply_markup=category_keyboard())

    @router.message(StateFilter(TicketFlow.subject))
    async def ticket_subject(message: Message, state: FSMContext):
        if is_cancel(message.text):
            await state.clear()
            await message.answer("Создание заявки отменено.", reply_markup=user_menu())
            return
        subject = (message.text or "").strip()
        if len(subject) < 4:
            await message.answer("Тема слишком короткая. Напишите 4-80 символов.")
            return
        await state.update_data(subject=subject[:80])
        await state.set_state(TicketFlow.details)
        await message.answer(
            "Теперь опишите проблему одним сообщением: что произошло, когда началось, что уже пробовали. "
            "Если есть номер заказа или ошибка, добавьте их сюда.",
        )

    @router.message(StateFilter(TicketFlow.details))
    async def ticket_details(message: Message, state: FSMContext, bot: Bot):
        if is_cancel(message.text):
            await state.clear()
            await message.answer("Создание заявки отменено.", reply_markup=user_menu())
            return

        text = message_text(message)
        if not text:
            await message.answer("Нужно описание проблемы. Файлы можно будет добавить следующим шагом.")
            return

        data = await state.get_data()
        ticket_id = await db.create_ticket(message.from_user.id, data["category"], data["subject"])
        await add_message_from_telegram(
            db=db,
            bot=bot,
            settings=settings,
            ticket_id=ticket_id,
            message=message,
            sender_role="user",
        )
        await state.update_data(ticket_id=ticket_id)
        await state.set_state(TicketFlow.attachments)
        await message.answer(
            "Описание сохранил. Теперь отправьте файлы, фото, видео или голосовые сообщения, если они нужны.\n\n"
            "Когда всё готово, нажмите «✅ Отправить заявку».",
            reply_markup=attachment_menu(),
        )

    @router.message(StateFilter(TicketFlow.attachments))
    async def ticket_attachments(message: Message, state: FSMContext, bot: Bot):
        if is_cancel(message.text):
            await state.clear()
            await message.answer("Создание заявки отменено.", reply_markup=user_menu())
            return

        data = await state.get_data()
        ticket_id = data.get("ticket_id")
        if not ticket_id:
            await state.clear()
            await message.answer("Черновик не найден. Начните заново.", reply_markup=user_menu())
            return

        if (message.text or "").strip() == "✅ Отправить заявку":
            await db.submit_ticket(ticket_id)
            await notify_moderators(bot, db, settings, ticket_id)
            await state.clear()
            await message.answer(
                f"✅ Заявка #{ticket_id} отправлена. Все сообщения по ней можно дописывать прямо сюда.",
                reply_markup=user_menu(),
            )
            return

        if not message_text(message) and message.content_type == "text":
            await message.answer("Отправьте файл или нажмите «✅ Отправить заявку».", reply_markup=attachment_menu())
            return

        await add_message_from_telegram(
            db=db,
            bot=bot,
            settings=settings,
            ticket_id=ticket_id,
            message=message,
            sender_role="user",
        )
        await message.answer("Добавил в заявку.", reply_markup=attachment_menu())

    @router.message(lambda m: is_moderator(settings, m.from_user.id))
    async def moderator_messages(message: Message, bot: Bot):
        await remember_user(db, message)
        text = (message.text or "").strip()

        menu_actions: dict[str, Callable[[Message], Awaitable[None]]] = {
            "🕘 Новые заявки": send_pending_tickets,
            "🟢 Мои активные": send_my_active_tickets,
            "📝 Все открытые": send_open_tickets,
            "⏭ Взять следующую": take_next_ticket,
            "🧾 Лог текущей": show_current_log,
            "💬 Шаблоны": show_canned_replies,
        }
        if text in menu_actions:
            await menu_actions[text](message)
            return
        if text == "📌 Текущая":
            await show_current_ticket(message)
            return
        if text == "🔒 Закрыть текущую":
            await close_current_ticket(message, bot)
            return
        if text == "🖥 Кабинет":
            if web_app_url:
                await message.answer("Откройте кабинет модератора:", reply_markup=moderator_webapp_keyboard(web_app_url))
            else:
                await message.answer(
                    "Кабинет включится после настройки PUBLIC_BASE_URL и webhook-режима.",
                    reply_markup=moderator_menu(web_app_url),
                )
            return

        await send_moderator_reply(message, bot)

    @router.message(lambda m: not is_moderator(settings, m.from_user.id))
    async def user_messages(message: Message, bot: Bot, state: FSMContext):
        await remember_user(db, message)
        text = (message.text or "").strip()

        if text == SECRET_PHRASE:
            await db.add_moderator(message.from_user.id, message.from_user.full_name)
            settings.moderators.add(message.from_user.id)
            await message.answer("Готово, вы теперь модератор.", reply_markup=moderator_menu(web_app_url))
            return

        if text == "🆘 Создать заявку":
            await start_ticket_flow_message(message, state)
            return
        if text == "❓ Частые вопросы":
            await show_faq(message, db)
            return
        if text == "📋 Мои заявки":
            await show_user_tickets(message, db)
            return

        open_ticket = await db.find_user_open_ticket(message.from_user.id)
        if open_ticket:
            await add_message_from_telegram(
                db=db,
                bot=bot,
                settings=settings,
                ticket_id=open_ticket["ticket_id"],
                message=message,
                sender_role="user",
            )
            if open_ticket["status"] == "waiting_user":
                await db.mark_active_from_user(open_ticket["ticket_id"], message.from_user.id)
            await notify_about_ticket_update(bot, db, settings, open_ticket, message)
            await message.answer(f"✅ Добавил сообщение в заявку #{open_ticket['ticket_id']}.", reply_markup=user_menu())
            return

        answer = await find_faq_answer(db, text)
        if answer:
            await message.answer(
                f"<b>{h(answer['question'])}</b>\n\n{h(answer['answer'])}",
                reply_markup=after_faq_keyboard(),
            )
            return

        await message.answer(
            "Я не нашел точный ответ в базе знаний. Лучше оформить заявку, чтобы модератор увидел детали и вложения.",
            reply_markup=after_faq_keyboard(),
        )

    @router.callback_query(F.data.startswith("take:"))
    async def cb_take(callback: CallbackQuery, bot: Bot):
        if not is_moderator(settings, callback.from_user.id):
            await callback.answer("Нет прав.", show_alert=True)
            return
        ticket_id = int(callback.data.split(":", 1)[1])
        ok = await db.take_ticket(ticket_id, callback.from_user.id)
        if not ok:
            await callback.answer("Заявку уже взяли или она закрыта.", show_alert=True)
            return
        ticket = await db.get_ticket(ticket_id)
        await callback.answer("Заявка взята и выбрана текущей.")
        await safe_edit_text(callback, format_ticket_header(ticket), reply_markup=ticket_actions(ticket_id, ticket["status"]))
        try:
            await bot.send_message(ticket["user_id"], f"✅ Заявка #{ticket_id} принята в работу.")
        except (TelegramBadRequest, TelegramForbiddenError):
            pass

    @router.callback_query(F.data.startswith("select:"))
    async def cb_select(callback: CallbackQuery):
        if not is_moderator(settings, callback.from_user.id):
            await callback.answer("Нет прав.", show_alert=True)
            return
        ticket_id = int(callback.data.split(":", 1)[1])
        ticket = await db.get_ticket(ticket_id)
        if not ticket:
            await callback.answer("Заявка не найдена.", show_alert=True)
            return
        await db.set_current_ticket(callback.from_user.id, ticket_id)
        await callback.answer(f"Текущая заявка #{ticket_id}")
        await safe_edit_text(callback, format_ticket_header(ticket), reply_markup=ticket_actions(ticket_id, ticket["status"]))

    @router.callback_query(F.data.startswith("log:"))
    async def cb_log(callback: CallbackQuery):
        if not is_moderator(settings, callback.from_user.id):
            await callback.answer("Нет прав.", show_alert=True)
            return
        ticket_id = int(callback.data.split(":", 1)[1])
        ticket = await db.get_ticket(ticket_id)
        if not ticket:
            await callback.answer("Заявка не найдена.", show_alert=True)
            return
        messages = await db.get_ticket_messages(ticket_id, limit=100)
        events = await db.get_ticket_events(ticket_id, limit=50)
        await safe_edit_text(callback, format_ticket_log(ticket, messages, events), reply_markup=ticket_actions(ticket_id, ticket["status"]))
        await callback.answer()

    @router.callback_query(F.data.startswith("close:"))
    async def cb_close(callback: CallbackQuery, bot: Bot):
        if not is_moderator(settings, callback.from_user.id):
            await callback.answer("Нет прав.", show_alert=True)
            return
        ticket_id = int(callback.data.split(":", 1)[1])
        ticket = await db.get_ticket(ticket_id)
        if not ticket:
            await callback.answer("Заявка не найдена.", show_alert=True)
            return
        ok = await db.close_ticket(ticket_id, callback.from_user.id)
        if not ok:
            await callback.answer("Заявка уже закрыта.", show_alert=True)
            return
        await callback.answer("Заявка закрыта.")
        await safe_edit_text(callback, f"🔒 Заявка #{ticket_id} закрыта.")
        try:
            await bot.send_message(ticket["user_id"], f"🔒 Заявка #{ticket_id} закрыта. Спасибо за обращение.")
        except (TelegramBadRequest, TelegramForbiddenError):
            pass

    @router.callback_query(F.data.startswith("replytpl:"))
    async def cb_reply_template(callback: CallbackQuery, bot: Bot):
        if not is_moderator(settings, callback.from_user.id):
            await callback.answer("Нет прав.", show_alert=True)
            return
        reply_id = int(callback.data.split(":", 1)[1])
        canned = await db.get_canned_reply(reply_id)
        current_id = await db.get_current_ticket_id(callback.from_user.id)
        if not canned or not current_id:
            await callback.answer("Нет шаблона или текущей заявки.", show_alert=True)
            return
        ticket = await db.get_ticket(current_id)
        if not ticket or ticket["status"] == "closed":
            await callback.answer("Текущая заявка закрыта или не найдена.", show_alert=True)
            return
        await bot.send_message(ticket["user_id"], f"<b>Ответ поддержки:</b>\n\n{h(canned['body'])}")
        await db.add_message(
            ticket_id=current_id,
            sender_role="mod",
            sender_id=callback.from_user.id,
            tg_chat_id=callback.message.chat.id if callback.message else None,
            tg_message_id=callback.message.message_id if callback.message else None,
            text=canned["body"],
        )
        await db.mark_waiting_user(current_id, callback.from_user.id)
        await callback.answer("Шаблон отправлен.")

    async def send_pending_tickets(message: Message) -> None:
        tickets = await db.list_tickets(statuses=("pending",), limit=20)
        await message.answer(
            format_ticket_list("Новые заявки", tickets),
            reply_markup=ticket_list_keyboard(tickets, action="take") if tickets else moderator_menu(web_app_url),
        )

    async def send_my_active_tickets(message: Message) -> None:
        tickets = await db.list_tickets(statuses=("active", "waiting_user"), mod_id=message.from_user.id, limit=20)
        await message.answer(
            format_ticket_list("Мои активные заявки", tickets),
            reply_markup=ticket_list_keyboard(tickets) if tickets else moderator_menu(web_app_url),
        )

    async def send_open_tickets(message: Message) -> None:
        tickets = await db.list_tickets(statuses=OPEN_STATUSES, limit=30)
        await message.answer(
            format_ticket_list("Все открытые заявки", tickets),
            reply_markup=ticket_list_keyboard(tickets) if tickets else moderator_menu(web_app_url),
        )

    async def show_current_ticket(message: Message) -> None:
        ticket_id = await db.get_current_ticket_id(message.from_user.id)
        if not ticket_id:
            await message.answer("Текущая заявка не выбрана.", reply_markup=moderator_menu(web_app_url))
            return
        ticket = await db.get_ticket(ticket_id)
        if not ticket:
            await message.answer("Текущая заявка не найдена.", reply_markup=moderator_menu(web_app_url))
            return
        await message.answer(format_ticket_header(ticket), reply_markup=ticket_actions(ticket_id, ticket["status"]))

    async def take_next_ticket(message: Message) -> None:
        ticket_id = await db.take_next_ticket(message.from_user.id)
        if not ticket_id:
            await message.answer("Очередь пуста.", reply_markup=moderator_menu(web_app_url))
            return
        ticket = await db.get_ticket(ticket_id)
        await message.answer(
            f"✅ Вы взяли заявку #{ticket_id}.\n\n{format_ticket_header(ticket)}",
            reply_markup=ticket_actions(ticket_id, ticket["status"]),
        )

    async def show_current_log(message: Message) -> None:
        ticket_id = await db.get_current_ticket_id(message.from_user.id)
        if not ticket_id:
            await message.answer("Текущая заявка не выбрана.", reply_markup=moderator_menu(web_app_url))
            return
        await show_ticket_log_to_message(message, db, ticket_id)

    async def show_canned_replies(message: Message) -> None:
        replies = await db.list_canned_replies()
        await message.answer("Выберите шаблон. Он отправится в текущую заявку.", reply_markup=canned_keyboard(replies))

    async def close_current_ticket(message: Message, bot: Bot) -> None:
        ticket_id = await db.get_current_ticket_id(message.from_user.id)
        if not ticket_id:
            await message.answer("Текущая заявка не выбрана.", reply_markup=moderator_menu(web_app_url))
            return
        ticket = await db.get_ticket(ticket_id)
        if not ticket:
            await message.answer("Заявка не найдена.", reply_markup=moderator_menu(web_app_url))
            return
        ok = await db.close_ticket(ticket_id, message.from_user.id)
        if not ok:
            await message.answer("Заявка уже закрыта.", reply_markup=moderator_menu(web_app_url))
            return
        await message.answer(f"🔒 Заявка #{ticket_id} закрыта.", reply_markup=moderator_menu(web_app_url))
        try:
            await bot.send_message(ticket["user_id"], f"🔒 Заявка #{ticket_id} закрыта. Спасибо за обращение.")
        except (TelegramBadRequest, TelegramForbiddenError):
            pass

    async def send_moderator_reply(message: Message, bot: Bot) -> None:
        ticket_id = await db.get_current_ticket_id(message.from_user.id)
        if not ticket_id:
            await message.answer("Сначала выберите заявку: «Новые заявки», «Мои активные» или «Взять следующую».", reply_markup=moderator_menu(web_app_url))
            return
        ticket = await db.get_ticket(ticket_id)
        if not ticket or ticket["status"] == "closed":
            await message.answer("Текущая заявка закрыта или не найдена.", reply_markup=moderator_menu(web_app_url))
            return

        text = message_text(message)
        if message.content_type == "text":
            await bot.send_message(ticket["user_id"], f"<b>Ответ поддержки:</b>\n\n{h(text)}")
        else:
            await bot.copy_message(ticket["user_id"], message.chat.id, message.message_id)

        await add_message_from_telegram(
            db=db,
            bot=bot,
            settings=settings,
            ticket_id=ticket_id,
            message=message,
            sender_role="mod",
        )
        await db.mark_waiting_user(ticket_id, message.from_user.id)
        await message.answer(f"✅ Отправлено в заявку #{ticket_id}.", reply_markup=moderator_menu(web_app_url))
