from __future__ import annotations

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

from .config import Settings
from .db import Database
from .formatting import h
from .security import WebAppAuthError, validate_webapp_init_data
from .texts import OPEN_STATUSES


MINI_APP_HTML = r"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Кабинет поддержки</title>
  <script src="https://telegram.org/js/telegram-web-app.js"></script>
  <style>
    :root {
      color-scheme: light dark;
      --bg: var(--tg-theme-bg-color, #f5f7fb);
      --text: var(--tg-theme-text-color, #172033);
      --hint: var(--tg-theme-hint-color, #667085);
      --button: var(--tg-theme-button-color, #2775d1);
      --button-text: var(--tg-theme-button-text-color, #ffffff);
      --surface: var(--tg-theme-secondary-bg-color, #ffffff);
      --line: rgba(100, 116, 139, 0.22);
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      min-height: 100vh;
    }
    button, input, textarea, select {
      font: inherit;
    }
    .layout {
      display: grid;
      grid-template-columns: 360px 1fr;
      min-height: 100vh;
    }
    aside {
      border-right: 1px solid var(--line);
      background: var(--surface);
      min-width: 0;
    }
    header {
      display: flex;
      gap: 10px;
      align-items: center;
      justify-content: space-between;
      padding: 14px;
      border-bottom: 1px solid var(--line);
      position: sticky;
      top: 0;
      background: var(--surface);
      z-index: 2;
    }
    h1, h2 {
      margin: 0;
      font-size: 18px;
      letter-spacing: 0;
    }
    h2 {
      font-size: 16px;
    }
    .filters {
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 8px;
      padding: 12px;
      border-bottom: 1px solid var(--line);
    }
    select, input, textarea {
      width: 100%;
      border: 1px solid var(--line);
      background: var(--bg);
      color: var(--text);
      border-radius: 8px;
      padding: 10px 11px;
      outline: none;
    }
    button {
      border: 0;
      border-radius: 8px;
      padding: 10px 12px;
      background: var(--button);
      color: var(--button-text);
      cursor: pointer;
      white-space: nowrap;
    }
    button.secondary {
      color: var(--text);
      background: transparent;
      border: 1px solid var(--line);
    }
    button.danger {
      background: #d92d20;
      color: white;
    }
    .tickets {
      display: grid;
    }
    .ticket {
      width: 100%;
      display: grid;
      gap: 5px;
      text-align: left;
      background: transparent;
      color: var(--text);
      border-radius: 0;
      border-bottom: 1px solid var(--line);
      padding: 13px 14px;
    }
    .ticket.active {
      background: rgba(39, 117, 209, 0.12);
    }
    .ticket-title {
      font-weight: 700;
      overflow-wrap: anywhere;
    }
    .meta {
      color: var(--hint);
      font-size: 13px;
      line-height: 1.35;
    }
    main {
      display: grid;
      grid-template-rows: auto 1fr auto;
      min-width: 0;
    }
    .details {
      padding: 16px;
      border-bottom: 1px solid var(--line);
      display: grid;
      gap: 10px;
      background: var(--surface);
    }
    .actions {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }
    .messages {
      overflow: auto;
      padding: 12px 16px 18px;
      display: grid;
      align-content: start;
      gap: 10px;
    }
    .msg {
      max-width: 780px;
      padding: 10px 12px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--surface);
      overflow-wrap: anywhere;
    }
    .msg.mod {
      margin-left: auto;
      background: rgba(39, 117, 209, 0.12);
    }
    .composer {
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 8px;
      padding: 12px;
      border-top: 1px solid var(--line);
      background: var(--surface);
    }
    textarea {
      min-height: 44px;
      max-height: 140px;
      resize: vertical;
    }
    .empty {
      color: var(--hint);
      padding: 22px 16px;
    }
    @media (max-width: 760px) {
      .layout {
        grid-template-columns: 1fr;
      }
      aside {
        max-height: 42vh;
        overflow: auto;
        border-right: 0;
        border-bottom: 1px solid var(--line);
      }
      main {
        min-height: 58vh;
      }
      .composer {
        grid-template-columns: 1fr;
      }
    }
  </style>
</head>
<body>
  <div class="layout">
    <aside>
      <header>
        <h1>Заявки</h1>
        <button id="refresh" class="secondary">Обновить</button>
      </header>
      <div class="filters">
        <select id="status">
          <option value="open">Открытые</option>
          <option value="pending">Новые</option>
          <option value="mine">Мои</option>
          <option value="closed">Закрытые</option>
        </select>
        <button id="takeNext">Взять</button>
      </div>
      <div id="tickets" class="tickets"></div>
    </aside>
    <main>
      <section id="details" class="details">
        <h2>Выберите заявку</h2>
        <div class="meta">Лог и ответы появятся здесь.</div>
      </section>
      <section id="messages" class="messages"></section>
      <form id="composer" class="composer">
        <textarea id="reply" placeholder="Ответ клиенту"></textarea>
        <button type="submit">Отправить</button>
      </form>
    </main>
  </div>
  <script>
    const tg = window.Telegram?.WebApp;
    tg?.ready();
    tg?.expand();

    const initData = tg?.initData || new URLSearchParams(location.search).get("initData") || "";
    let tickets = [];
    let selectedId = null;

    function headers() {
      return { "Content-Type": "application/json", "X-Telegram-Init-Data": initData };
    }

    async function api(path, options = {}) {
      const response = await fetch(path, { ...options, headers: { ...headers(), ...(options.headers || {}) } });
      if (!response.ok) {
        const text = await response.text();
        throw new Error(text || response.statusText);
      }
      return response.json();
    }

    function statusText(status) {
      return { pending: "Новая", active: "В работе", waiting_user: "Ждем клиента", closed: "Закрыта" }[status] || status;
    }

    function escapeHtml(value) {
      return String(value ?? "").replace(/[&<>"']/g, char => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
      }[char]));
    }

    function renderTickets() {
      const box = document.querySelector("#tickets");
      if (!tickets.length) {
        box.innerHTML = '<div class="empty">Заявок нет</div>';
        return;
      }
      box.innerHTML = tickets.map(ticket => `
        <button class="ticket ${ticket.ticket_id === selectedId ? "active" : ""}" data-id="${ticket.ticket_id}">
          <span class="ticket-title">#${ticket.ticket_id} ${escapeHtml(ticket.subject)}</span>
          <span class="meta">${statusText(ticket.status)} · ${escapeHtml(ticket.category_title)} · сообщений: ${ticket.messages_count}</span>
          <span class="meta">Клиент: ${escapeHtml(ticket.full_name || ticket.username || ticket.user_id)}</span>
        </button>
      `).join("");
      box.querySelectorAll(".ticket").forEach(btn => btn.addEventListener("click", () => selectTicket(Number(btn.dataset.id))));
    }

    function renderDetails(data) {
      const ticket = data.ticket;
      selectedId = ticket.ticket_id;
      document.querySelector("#details").innerHTML = `
        <h2>#${ticket.ticket_id} ${escapeHtml(ticket.subject)}</h2>
        <div class="meta">${statusText(ticket.status)} · ${escapeHtml(ticket.category_title)} · клиент ${escapeHtml(ticket.full_name || ticket.username || ticket.user_id)}</div>
        <div class="actions">
          <button data-action="assign">Назначить на себя</button>
          <button data-action="current" class="secondary">Сделать текущей</button>
          <button data-action="close" class="danger">Закрыть</button>
        </div>
      `;
      document.querySelector("[data-action='assign']").onclick = () => ticketAction("assign");
      document.querySelector("[data-action='current']").onclick = () => ticketAction("current");
      document.querySelector("[data-action='close']").onclick = () => ticketAction("close");

      const messages = document.querySelector("#messages");
      messages.innerHTML = data.messages.map(message => `
        <article class="msg ${message.sender_role === "mod" ? "mod" : ""}">
          <div class="meta">${escapeHtml(message.created_at.slice(5, 16).replace("T", " "))} · ${escapeHtml(message.sender_role)}</div>
          <div>${message.content_type !== "text" ? `<b>${escapeHtml(message.content_type)}:</b> ${escapeHtml(message.file_name || "")}<br>` : ""}${escapeHtml(message.text || "")}</div>
        </article>
      `).join("") || '<div class="empty">Сообщений пока нет</div>';
      messages.scrollTop = messages.scrollHeight;
      renderTickets();
    }

    async function loadTickets() {
      const status = document.querySelector("#status").value;
      const data = await api(`/api/tickets?status=${encodeURIComponent(status)}`);
      tickets = data.tickets;
      renderTickets();
      if (selectedId && tickets.some(ticket => ticket.ticket_id === selectedId)) {
        await selectTicket(selectedId);
      }
    }

    async function selectTicket(id) {
      const data = await api(`/api/tickets/${id}`);
      renderDetails(data);
    }

    async function ticketAction(action) {
      if (!selectedId) return;
      await api(`/api/tickets/${selectedId}/${action}`, { method: "POST", body: "{}" });
      await loadTickets();
      await selectTicket(selectedId);
    }

    document.querySelector("#refresh").onclick = loadTickets;
    document.querySelector("#status").onchange = loadTickets;
    document.querySelector("#takeNext").onclick = async () => {
      const data = await api("/api/tickets/take-next", { method: "POST", body: "{}" });
      selectedId = data.ticket_id;
      await loadTickets();
      await selectTicket(selectedId);
    };
    document.querySelector("#composer").onsubmit = async event => {
      event.preventDefault();
      if (!selectedId) return;
      const textarea = document.querySelector("#reply");
      const text = textarea.value.trim();
      if (!text) return;
      await api(`/api/tickets/${selectedId}/reply`, { method: "POST", body: JSON.stringify({ text }) });
      textarea.value = "";
      await selectTicket(selectedId);
    };

    loadTickets().catch(error => {
      document.body.innerHTML = `<div class="empty">Ошибка доступа: ${escapeHtml(error.message)}</div>`;
    });
  </script>
</body>
</html>"""


def json_ticket(ticket: dict) -> dict:
    category_titles = {
        "tech": "Техническая проблема",
        "payment": "Оплата",
        "refund": "Возврат",
        "account": "Аккаунт",
        "other": "Другое",
    }
    return {
        **ticket,
        "category_title": category_titles.get(ticket["category"], ticket["category"]),
    }


async def require_moderator(request: web.Request) -> int:
    settings: Settings = request.app["settings"]
    db: Database = request.app["db"]

    init_data = request.headers.get("X-Telegram-Init-Data", "")
    user_id = settings.webapp_dev_user_id
    if init_data:
        try:
            data = validate_webapp_init_data(init_data, settings.bot_token)
            user = data.get("user_obj") or {}
            user_id = int(user["id"])
        except (KeyError, TypeError, ValueError, WebAppAuthError) as exc:
            raise web.HTTPUnauthorized(text=f"Bad Telegram WebApp auth: {exc}") from exc

    if not user_id:
        raise web.HTTPUnauthorized(text="Open the cabinet from Telegram Mini App.")
    if not await db.is_moderator(user_id):
        raise web.HTTPForbidden(text="Moderator access required.")
    return user_id


async def index(_request: web.Request) -> web.Response:
    raise web.HTTPFound("/app")


async def mini_app(_request: web.Request) -> web.Response:
    return web.Response(text=MINI_APP_HTML, content_type="text/html")


async def api_tickets(request: web.Request) -> web.Response:
    mod_id = await require_moderator(request)
    db: Database = request.app["db"]
    status = request.query.get("status", "open")
    if status == "mine":
        tickets = await db.list_tickets(statuses=("active", "waiting_user"), mod_id=mod_id, limit=50)
    elif status == "pending":
        tickets = await db.list_tickets(statuses=("pending",), limit=50)
    elif status == "closed":
        tickets = await db.list_tickets(statuses=("closed",), limit=50)
    else:
        tickets = await db.list_tickets(statuses=OPEN_STATUSES, limit=50)
    return web.json_response({"tickets": [json_ticket(ticket) for ticket in tickets]})


async def api_ticket(request: web.Request) -> web.Response:
    await require_moderator(request)
    db: Database = request.app["db"]
    ticket_id = int(request.match_info["ticket_id"])
    ticket = await db.get_ticket(ticket_id)
    if not ticket:
        raise web.HTTPNotFound(text="Ticket not found")
    messages = await db.get_ticket_messages(ticket_id, limit=200)
    events = await db.get_ticket_events(ticket_id, limit=50)
    return web.json_response(
        {
            "ticket": json_ticket(ticket),
            "messages": messages,
            "events": events,
        }
    )


async def api_assign(request: web.Request) -> web.Response:
    mod_id = await require_moderator(request)
    db: Database = request.app["db"]
    ticket_id = int(request.match_info["ticket_id"])
    ok = await db.assign_ticket(ticket_id, mod_id)
    if not ok:
        raise web.HTTPBadRequest(text="Ticket cannot be assigned")
    await db.set_current_ticket(mod_id, ticket_id)
    return web.json_response({"ok": True})


async def api_current(request: web.Request) -> web.Response:
    mod_id = await require_moderator(request)
    db: Database = request.app["db"]
    ticket_id = int(request.match_info["ticket_id"])
    ticket = await db.get_ticket(ticket_id)
    if not ticket:
        raise web.HTTPNotFound(text="Ticket not found")
    await db.set_current_ticket(mod_id, ticket_id)
    return web.json_response({"ok": True})


async def api_close(request: web.Request) -> web.Response:
    mod_id = await require_moderator(request)
    db: Database = request.app["db"]
    bot: Bot = request.app["bot"]
    ticket_id = int(request.match_info["ticket_id"])
    ticket = await db.get_ticket(ticket_id)
    if not ticket:
        raise web.HTTPNotFound(text="Ticket not found")
    ok = await db.close_ticket(ticket_id, mod_id)
    if not ok:
        raise web.HTTPBadRequest(text="Ticket is already closed")
    try:
        await bot.send_message(ticket["user_id"], f"🔒 Заявка #{ticket_id} закрыта. Спасибо за обращение.")
    except (TelegramBadRequest, TelegramForbiddenError):
        pass
    return web.json_response({"ok": True})


async def api_reply(request: web.Request) -> web.Response:
    mod_id = await require_moderator(request)
    db: Database = request.app["db"]
    bot: Bot = request.app["bot"]
    ticket_id = int(request.match_info["ticket_id"])
    payload = await request.json()
    text = (payload.get("text") or "").strip()
    if not text:
        raise web.HTTPBadRequest(text="Text is required")

    ticket = await db.get_ticket(ticket_id)
    if not ticket or ticket["status"] == "closed":
        raise web.HTTPBadRequest(text="Ticket is closed or missing")

    await bot.send_message(ticket["user_id"], f"<b>Ответ поддержки:</b>\n\n{h(text)}")
    await db.add_message(
        ticket_id=ticket_id,
        sender_role="mod",
        sender_id=mod_id,
        tg_chat_id=None,
        tg_message_id=None,
        text=text,
    )
    await db.mark_waiting_user(ticket_id, mod_id)
    return web.json_response({"ok": True})


async def api_take_next(request: web.Request) -> web.Response:
    mod_id = await require_moderator(request)
    db: Database = request.app["db"]
    bot: Bot = request.app["bot"]
    ticket_id = await db.take_next_ticket(mod_id)
    if not ticket_id:
        raise web.HTTPNotFound(text="Queue is empty")
    ticket = await db.get_ticket(ticket_id)
    try:
        await bot.send_message(ticket["user_id"], f"✅ Заявка #{ticket_id} принята в работу.")
    except (TelegramBadRequest, TelegramForbiddenError):
        pass
    return web.json_response({"ok": True, "ticket_id": ticket_id})


async def on_startup(app: web.Application) -> None:
    bot: Bot = app["bot"]
    dp: Dispatcher = app["dp"]
    settings: Settings = app["settings"]
    await bot.set_webhook(
        settings.webhook_url,
        secret_token=settings.webhook_secret,
        drop_pending_updates=True,
        allowed_updates=dp.resolve_used_update_types(),
    )


async def on_shutdown(app: web.Application) -> None:
    bot: Bot = app["bot"]
    await bot.session.close()


def create_web_app(bot: Bot, dp: Dispatcher, db: Database, settings: Settings) -> web.Application:
    app = web.Application()
    app["bot"] = bot
    app["dp"] = dp
    app["db"] = db
    app["settings"] = settings

    app.router.add_get("/", index)
    app.router.add_get("/app", mini_app)
    app.router.add_get("/api/tickets", api_tickets)
    app.router.add_post("/api/tickets/take-next", api_take_next)
    app.router.add_get("/api/tickets/{ticket_id:\\d+}", api_ticket)
    app.router.add_post("/api/tickets/{ticket_id:\\d+}/assign", api_assign)
    app.router.add_post("/api/tickets/{ticket_id:\\d+}/current", api_current)
    app.router.add_post("/api/tickets/{ticket_id:\\d+}/close", api_close)
    app.router.add_post("/api/tickets/{ticket_id:\\d+}/reply", api_reply)

    SimpleRequestHandler(dispatcher=dp, bot=bot, secret_token=settings.webhook_secret).register(
        app,
        path=settings.webhook_path,
    )
    setup_application(app, dp, bot=bot)
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)
    return app
