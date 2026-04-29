import asyncio
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from .config import BOT_TOKEN
from .handlers import (
    common, accounts, vars_subjects, templates, 
    mailing, rotation, parser_poshmark, api_parsers
)

async def main():
    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())

    # Регистрация роутеров
    dp.include_router(common.router)
    dp.include_router(accounts.router)
    dp.include_router(vars_subjects.router)
    dp.include_router(templates.router)
    dp.include_router(mailing.router)
    dp.include_router(rotation.router)
    dp.include_router(parser_poshmark.router)
    dp.include_router(api_parsers.router)

    print("Бот запущен. Ctrl+C для остановки.")
    await dp.start_polling(bot, drop_pending_updates=True)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("Бот остановлен.")
