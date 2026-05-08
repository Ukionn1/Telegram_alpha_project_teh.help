# Telegram Support Bot

Бот поддержки на `aiogram 3` с нормальными заявками, логированием переписки, вложениями, FAQ-ботом и мини-кабинетом модератора.

## Что умеет

- Пользователь видит простое меню: FAQ, мои заявки, создать заявку.
- Заявка создается через мастер: категория, тема, подробное описание, вложения, отправка.
- Бот сохраняет историю каждой заявки в SQLite: сообщения, файлы, события, текущий статус.
- Модераторы видят полный текст новой заявки и приложенные пользователем файлы.
- Обычные сообщения модератора отправляются только в выбранную текущую заявку.
- Модератор может взять заявку, переключиться на другую, посмотреть лог, закрыть заявку, отправить шаблонный ответ.
- FAQ отвечает на простые вопросы без участия человека, а если ответа нет, предлагает оформить заявку.
- Mini App `/app` дает веб-кабинет: список заявок, лог, назначение на себя, закрытие, ответ клиенту.

## Быстрый запуск локально

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Заполните `.env`:

```env
BOT_TOKEN=токен_от_BotFather
MODERATORS=ваш_telegram_id
RUN_MODE=polling
```

Запуск:

```powershell
.\.venv\Scripts\python.exe main.py
```

Узнать свой Telegram ID можно командой `/id`.

## Продакшен на Beget

Для этого проекта лучше использовать Beget VPS/VDS, а не обычный виртуальный хостинг: боту нужен постоянно работающий Python-процесс, webhook endpoint и HTTPS для Telegram Mini App. В документации Beget VPS/VDS описан как виртуальный сервер, а в облаке также есть DBaaS и S3, которые пригодятся при росте проекта: [Beget VPS/VDS](https://beget.com/ru/kb/manual/vps).

Минимальный `.env` для VPS:

```env
BOT_TOKEN=токен_от_BotFather
MODERATORS=111111111,222222222
RUN_MODE=webhook
PUBLIC_BASE_URL=https://support.example.com
WEBHOOK_PATH=/telegram/webhook
WEBHOOK_SECRET=длинная_случайная_строка
HOST=127.0.0.1
PORT=8080
```

Схема запуска:

1. Развернуть код на VPS, создать `.venv`, установить `requirements.txt`.
2. Поднять процесс через `systemd`, пример есть в [deploy/support-bot.service](/C:/Users/Ukio/Documents/ALPHA.TG.DS/deploy/support-bot.service).
3. Настроить Nginx reverse proxy на `127.0.0.1:8080`, пример в [deploy/nginx.conf](/C:/Users/Ukio/Documents/ALPHA.TG.DS/deploy/nginx.conf).
4. Выпустить HTTPS-сертификат, например через Certbot.
5. В BotFather можно дополнительно включить Mini App/Menu Button на URL `https://support.example.com/app`. В самом боте модераторская кнопка «Кабинет» отправляет inline-кнопку Web App, чтобы Telegram передал данные для проверки доступа.

## Почему так

- Для webhook использован штатный `aiohttp`-интегратор `SimpleRequestHandler` из aiogram; документация aiogram отдельно отмечает, что webhook и long polling нельзя использовать одновременно: [aiogram webhook docs](https://docs.aiogram.dev/en/dev-3.x/dispatcher/webhook.html).
- Telegram Mini Apps запускаются из кнопок и получают данные пользователя через WebApp API; поэтому кабинет проверяет подпись `initData`: [Telegram Mini Apps](https://core.telegram.org/bots/webapps).
- Bot API позволяет скачивать файлы через `getFile`, но обычный лимит скачивания для бота составляет 20 MB; поэтому путь файла логируется всегда, а локальное скачивание ограничено `MAX_DOWNLOAD_MB`: [Telegram Bot API getFile](https://core.telegram.org/bots/api#getfile).

## Структура

- [main.py](/C:/Users/Ukio/Documents/ALPHA.TG.DS/main.py) - точка входа, polling/webhook режимы.
- [support_bot/app.py](/C:/Users/Ukio/Documents/ALPHA.TG.DS/support_bot/app.py) - сценарии пользователя и модератора.
- [support_bot/db.py](/C:/Users/Ukio/Documents/ALPHA.TG.DS/support_bot/db.py) - SQLite, заявки, сообщения, события, FAQ, шаблоны.
- [support_bot/web.py](/C:/Users/Ukio/Documents/ALPHA.TG.DS/support_bot/web.py) - Mini App и API кабинета.
- [support_bot/security.py](/C:/Users/Ukio/Documents/ALPHA.TG.DS/support_bot/security.py) - проверка Telegram WebApp `initData`.
- [support_bot/files.py](/C:/Users/Ukio/Documents/ALPHA.TG.DS/support_bot/files.py) - сохранение вложений.

## Что стоит добавить следующим этапом

- PostgreSQL вместо SQLite, если заявок станет много или модераторов будет несколько десятков.
- SLA и приоритеты: авто-пометки `urgent`, таймеры просрочки, уведомления старшему модератору.
- Поиск по логам и клиентам в Mini App.
- Роли: оператор, старший модератор, администратор.
- Экспорт заявки в CSV/PDF и выгрузка вложений в S3.
