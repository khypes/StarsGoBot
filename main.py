import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

import coindrop
import emojis
import fulfillment
from config import BOT_TOKEN, DROP_PENDING_UPDATES, DB_PATH
from database.db import init_db, close_db
from fallback import EmojiFallbackMiddleware
from handlers import admin, coindrop_admin, emoji_admin, style_admin, user
from middlewares import AccessMiddleware

log = logging.getLogger("starsgo")


async def main():
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN topilmadi! .env faylini yarating (.env.example dan nusxa oling) "
            "yoki Railway Variables bo'limiga BOT_TOKEN qo'shing."
        )

    await init_db()
    await emojis.load()
    log.info("Baza: %s | Premium emoji: %d ta o'rnatilgan", DB_PATH, emojis.count_set())

    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    # custom emoji rad etilsa — oddiy emojiga avtomatik qaytadi
    bot.session.middleware(EmojiFallbackMiddleware())

    dp = Dispatcher(storage=MemoryStorage())
    access = AccessMiddleware()
    dp.message.outer_middleware(access)
    dp.callback_query.outer_middleware(access)

    # Tartib muhim: admin routerlari avval (ular faqat adminlar uchun filtrlanadi)
    dp.include_router(admin.router)
    dp.include_router(emoji_admin.router)
    dp.include_router(coindrop_admin.router)
    dp.include_router(style_admin.router)
    dp.include_router(user.router)

    worker = asyncio.create_task(fulfillment.worker(bot))  # Coindrop: holatni kuzatish va qayta urinish
    try:
        await bot.delete_webhook(drop_pending_updates=DROP_PENDING_UPDATES)
        me = await bot.get_me()
        log.info("Bot ishga tushdi: @%s", me.username)
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)
        await coindrop.close_session()
        await bot.session.close()
        await close_db()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot to'xtatildi.")
