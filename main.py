import asyncio
import logging

from aiohttp import web
from dotenv import load_dotenv

from support_bot.app import build_bot, build_dispatcher
from support_bot.config import Settings
from support_bot.db import Database
from support_bot.web import create_web_app


async def prepare(settings: Settings):
    settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)

    db = Database(settings.db_path)
    await db.init(settings.moderators)
    settings.moderators.update(await db.get_moderator_ids())

    bot = build_bot(settings)
    dp = build_dispatcher(settings, db)
    return bot, dp, db


async def run_polling(settings: Settings):
    bot, dp, _db = await prepare(settings)
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


async def make_web_app(settings: Settings):
    bot, dp, db = await prepare(settings)
    app = create_web_app(bot, dp, db, settings)
    return app


def main():
    load_dotenv()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    settings = Settings.from_env()
    if settings.run_mode == "webhook":
        web.run_app(make_web_app(settings), host=settings.host, port=settings.port)
    else:
        asyncio.run(run_polling(settings))


if __name__ == "__main__":
    main()
