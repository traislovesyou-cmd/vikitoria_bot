import os
import asyncio
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Получаем токен из переменной окружения
BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    logger.error("❌ ERROR: BOT_TOKEN environment variable is not set!")
    logger.error("Please set BOT_TOKEN in Render dashboard → Environment")
    exit(1)

# Инициализация бота
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    """Обработчик команды /start"""
    await message.answer(
        "🦉 Привет! Бот 'Виктория' работает!\n\n"
        "Игра для двоих готова к использованию.\n"
        "Создайте комнату или присоединитесь к существующей."
    )

async def main():
    """Основная функция запуска"""
    logger.info("✅ Бот Виктория запущен успешно!")
    logger.info(f"🤖 Бот: @{(await bot.get_me()).username}")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
