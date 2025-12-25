import os
import asyncio
import logging
import random
import string
import uuid
from datetime import datetime
from enum import Enum
from typing import Dict, Optional, List

from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command

# ========== НАСТРОЙКА ЛОГИРОВАНИЯ ==========
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ========== КОНФИГУРАЦИЯ ==========
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = 204845203  # Твой ID из логов

storage = None
bot = Bot(token=BOT_TOKEN, parse_mode="HTML")
dp = Dispatcher()
router = Router()
dp.include_router(router)

# ========== ПРОСТЫЕ ДАННЫЕ ==========
class GameState(Enum):
    IN_GAME = "in_game"

class GameSession:
    def __init__(self, room_code: str, creator_id: int):
        self.room_code = room_code
        self.creator_id = creator_id
        self.state = GameState.IN_GAME
        self.player_names = {}
        self.is_admin_test = True
        
        logger.info(f"🆕 Создана тестовая сессия: {room_code}, создатель: {creator_id}")

# ========== ГЛОБАЛЬНЫЕ ХРАНИЛИЩА ==========
active_users = {}  # user_id -> room_code
active_rooms = {}  # room_code -> GameSession
admin_test_rooms = {}  # user_id -> room_code

def generate_room_code() -> str:
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))

# ========== КОМАНДЫ ==========
@router.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        "🦉 Тестовый бот для проверки админ-режима\n\n"
        "Команды:\n"
        "/test - начать тест игры\n"
        "/myid - узнать свой ID\n"
        "/status - статус теста"
    )

@router.message(Command("myid"))
async def cmd_myid(message: Message):
    await message.answer(f"🆔 Ваш ID: <code>{message.from_user.id}</code>")

@router.message(Command("status"))
async def cmd_status(message: Message):
    user_id = message.from_user.id
    if user_id in active_users:
        room_code = active_users[user_id]
        await message.answer(f"📊 Статус: есть активный тест в комнате {room_code}")
    else:
        await message.answer("📊 Статус: нет активных тестов")

@router.message(Command("test"))
async def cmd_test(message: Message):
    """Прямой запуск теста через команду"""
    user_id = message.from_user.id
    
    if user_id in admin_test_rooms:
        await message.answer("❌ У тебя уже есть активный тест!")
        return
    
    room_code = generate_room_code()
    game_session = GameSession(room_code, user_id)
    
    active_rooms[room_code] = game_session
    active_users[user_id] = room_code
    admin_test_rooms[user_id] = room_code
    
    await message.answer(
        f"🎮 <b>Тест игры начат!</b>\n\n"
        f"Код тестовой комнаты: <code>{room_code}</code>\n\n"
        f"<b>Представьтесь:</b>\n"
        f"Напишите ваше имя для начала игры:"
    )
    
    logger.info(f"✅ Тест создан через команду: {room_code}")

# ========== ОБРАБОТКА ИМЕНИ ==========
@router.message(F.text)
async def handle_text_message(message: Message):
    user_id = message.from_user.id
    text = message.text.strip()
    
    logger.info(f"📨 Получено сообщение от {user_id}: '{text}'")
    
    # Если пользователь в активном тесте и еще не представился
    if user_id in active_users:
        room_code = active_users[user_id]
        
        if room_code in active_rooms:
            game_session = active_rooms[room_code]
            
            # Проверяем, что игра началась и игрок еще не представился
            if user_id not in game_session.player_names:
                logger.info(f"👤 Игрок {user_id} представляется как '{text}'")
                
                # Сохраняем имя
                game_session.player_names[user_id] = text[:50]
                
                await message.answer(f"✅ Отлично, {text}! Начинаем тест...")
                
                # НЕМЕДЛЕННО запускаем тест
                await start_admin_test_game(game_session)
            else:
                await message.answer(f"👋 Привет снова, {game_session.player_names[user_id]}!")

async def start_admin_test_game(game_session: GameSession):
    """Начало админ-теста"""
    admin_id = game_session.creator_id
    logger.info(f"🔧 Запускаем тест для {admin_id}")
    
    try:
        # 1. Сообщение как исполняющему
        await bot.send_message(
            admin_id,
            f"🎮 <b>Тест игры начался!</b>\n\n"
            f"Вы играете с: <b>Тестовый партнёр</b>\n"
            f"Ваша роль: <b>исполняющий</b>\n\n"
            f"Первое задание будет скоро..."
        )
        
        # 2. Сообщение как ожидающему
        await bot.send_message(
            admin_id,
            f"👤 <b>Тестовый партнёр (ожидающий):</b>\n\n"
            f"Вы играете с: <b>Админ</b>\n"
            f"Ваша роль: <b>ожидающий</b>\n\n"
            f"Ждите задание..."
        )
        
        # 3. Тестовое задание
        await bot.send_message(
            admin_id,
            f"🎴 <b>Тестовое задание:</b>\n\n"
            f"Какая твоя самая бесполезная, но крутая суперспособность в быту?\n\n"
            f"<i>Это тестовая карта</i>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Выполнено", callback_data="test_done")],
                [InlineKeyboardButton(text="➡️ Пропустить", callback_data="test_skip")]
            ])
        )
        
        logger.info(f"✅ Тест успешно запущен для {admin_id}")
        
    except Exception as e:
        logger.error(f"❌ Ошибка при запуске теста: {e}")
        await bot.send_message(admin_id, f"❌ Ошибка: {str(e)}")

# ========== ОБРАБОТЧИКИ КНОПОК ==========
@router.callback_query(F.data == "test_done")
async def test_done_handler(callback):
    await callback.answer("✅ Тест выполнен!")
    await callback.message.answer("🎉 Отлично! Тест работает корректно!")

@router.callback_query(F.data == "test_skip")
async def test_skip_handler(callback):
    await callback.answer("➡️ Тест пропущен")
    await callback.message.answer("📤 Следующее задание...")

# ========== ЗАПУСК БОТА ==========
async def main():
    logger.info("=" * 60)
    logger.info("🚀 ТЕСТОВЫЙ БОТ ДЛЯ АДМИН-РЕЖИМА")
    logger.info("=" * 60)
    
    logger.info(f"👑 Админ ID: {ADMIN_ID}")
    logger.info("✅ Бот запущен")
    
    try:
        await dp.start_polling(bot)
    except KeyboardInterrupt:
        logger.info("🛑 Бот остановлен")
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        raise

if __name__ == "__main__":
    asyncio.run(main())
