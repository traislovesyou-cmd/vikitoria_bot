import os
import asyncio
import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command

# ========== НАСТРОЙКА ЛОГИРОВАНИЯ ==========
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ========== КОНФИГУРАЦИЯ ==========
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    logger.error("❌ ERROR: BOT_TOKEN environment variable is not set!")
    exit(1)

# Инициализация бота
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ========== HTTP-СЕРВЕР ДЛЯ RENDER ==========
class HealthHandler(BaseHTTPRequestHandler):
    """Обработчик HTTP-запросов для проверки здоровья"""
    
    def do_GET(self):
        # Отвечаем на любой GET-запрос
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        response = "🦉 Bot Vikitoria is alive and polling Telegram"
        self.wfile.write(response.encode('utf-8'))
    
    def log_message(self, format, *args):
        # Отключаем стандартное логирование HTTP-сервера
        pass

def run_http_server():
    """Запуск HTTP-сервера в отдельном потоке"""
    try:
        # Получаем порт из переменной окружения (Render сам устанавливает)
        port = int(os.getenv("PORT", 10000))
        server = HTTPServer(('0.0.0.0', port), HealthHandler)
        
        logger.info(f"✅ HTTP-сервер запущен на порту {port}")
        logger.info(f"🌐 Health check доступен по адресу: http://0.0.0.0:{port}/")
        
        # Запускаем сервер (блокирующий вызов)
        server.serve_forever()
    except Exception as e:
        logger.error(f"❌ Ошибка HTTP-сервера: {e}")

# Запускаем HTTP-сервер в отдельном потоке ДО запуска бота
http_thread = threading.Thread(target=run_http_server, daemon=True)
http_thread.start()

# ========== ОБРАБОТЧИКИ TELEGRAM ==========
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    """Команда /start"""
    await message.answer(
        "🦉 Привет! Я бот 'Виктория' - игра для двоих.\n\n"
        "✅ Бот работает на Render с Docker\n"
        "✅ HTTP-сервер запущен для проверки здоровья\n"
        "✅ Готов создавать комнаты и начинать игру\n\n"
        "Тестовая версия - полный функционал скоро!"
    )

@dp.message(Command("test"))
async def cmd_test(message: types.Message):
    """Тестовая команда"""
    await message.answer(
        f"👤 ID: {message.from_user.id}\n"
        f"📛 Имя: {message.from_user.first_name}\n"
        f"✅ Бот жив и отвечает!"
    )

@dp.message(Command("ping"))
async def cmd_ping(message: types.Message):
    """Проверка работы"""
    await message.answer("🏓 Понг! Бот работает корректно.")

# ========== ЗАПУСК БОТА ==========
async def main():
    """Основная функция запуска бота"""
    # Даем время HTTP-серверу запуститься
    await asyncio.sleep(1)
    
    # Получаем информацию о боте
    bot_info = await bot.get_me()
    
    logger.info("=" * 50)
    logger.info("🚀 ЗАПУСК БОТА 'ВИКТОРИЯ'")
    logger.info("=" * 50)
    logger.info(f"🤖 Бот: @{bot_info.username}")
    logger.info(f"🆔 ID бота: {bot_info.id}")
    logger.info(f"📛 Имя бота: {bot_info.first_name}")
    logger.info(f"🌐 Порт HTTP: {os.getenv('PORT', 10000)}")
    logger.info("✅ Все системы работают")
    logger.info("=" * 50)
    
    # Запускаем polling
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
