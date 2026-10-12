import asyncio
from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from backend.config import settings

async def main():
    if not settings.bot_token:
        raise RuntimeError("BOT_TOKEN is required")
    bot = Bot(settings.bot_token)
    dp = Dispatcher()

    @dp.message(CommandStart())
    async def start(message: Message):
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="Открыть магазин", web_app=WebAppInfo(url=settings.app_url))
        ]])
        await message.answer(
            "SellStars\n\nКаталог, оформление заказов и история покупок доступны в Mini App.",
            reply_markup=keyboard
        )

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
