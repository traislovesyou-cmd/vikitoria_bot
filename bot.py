import os
import asyncio
import random
import string
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Конфигурация
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Инициализация
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Хранение данных (в памяти, для демо)
active_rooms = {}
users = {}

# ========== КЛАВИАТУРЫ ==========
def main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Начать игру 🦉", callback_data="create_room")],
        [InlineKeyboardButton(text="Присоединиться к игре", callback_data="join_room")]
    ])

def waiting_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Отменить поиск", callback_data="cancel_search")]
    ])

# ========== ОБРАБОТЧИКИ ==========
@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    """Обработчик команды /start"""
    await message.answer(
        "🦉 Добро пожаловать в Викторию!\n\n"
        "Игра для двоих, которая поможет стать ближе.\n\n"
        "Выберите действие:",
        reply_markup=main_menu()
    )

@dp.callback_query(lambda c: c.data == "create_room")
async def create_room(callback: CallbackQuery):
    """Создание игровой комнаты"""
    user_id = callback.from_user.id
    room_code = ''.join(random.choices(string.ascii_uppercase, k=6))
    
    active_rooms[room_code] = {
        "creator_id": user_id,
        "created_at": asyncio.get_event_loop().time()
    }
    
    users[user_id] = {
        "room_code": room_code,
        "state": "waiting"
    }
    
    await callback.message.edit_text(
        f"🦉 Комната создана!\n\n"
        f"Код для присоединения:\n"
        f"<code>{room_code}</code>\n\n"
        f"Отправьте этот код партнеру.\n"
        f"Ожидание: 5 минут",
        parse_mode="HTML",
        reply_markup=waiting_keyboard()
    )
    
    # Автоудаление через 5 минут
    await asyncio.sleep(300)
    if room_code in active_rooms:
        del active_rooms[room_code]
        if user_id in users:
            del users[user_id]
        try:
            await callback.message.edit_text(
                "Время ожидания истекло.",
                reply_markup=main_menu()
            )
        except:
            pass

@dp.callback_query(lambda c: c.data == "join_room")
async def join_room(callback: CallbackQuery):
    """Присоединение к игре"""
    await callback.message.edit_text(
        "Введите 6-значный код комнаты (только английские буквы):"
    )

@dp.message(lambda message: message.text and len(message.text) == 6 and message.text.isalpha())
async def process_room_code(message: types.Message):
    """Обработка кода комнаты"""
    room_code = message.text.upper()
    
    if room_code not in active_rooms:
        await message.answer(
            "❌ Комната не найдена. Проверьте код или попросите партнера создать новую комнату.",
            reply_markup=main_menu()
        )
        return
    
    creator_id = active_rooms[room_code]["creator_id"]
    
    # Обновляем данные создателя
    if creator_id in users:
        users[creator_id]["state"] = "partner_found"
        users[creator_id]["partner_id"] = message.from_user.id
        
        # Уведомляем создателя
        await bot.send_message(
            creator_id,
            f"🎉 Партнер {message.from_user.first_name} присоединился!\n\n"
            f"Нажмите 'Начать игру' когда будете готовы.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Начать игру 🎮", callback_data="start_game")]
            ])
        )
    
    # Создаем данные для присоединившегося
    users[message.from_user.id] = {
        "room_code": room_code,
        "partner_id": creator_id,
        "state": "partner_found"
    }
    
    # Удаляем комнату из поиска
    del active_rooms[room_code]
    
    await message.answer(
        "✅ Вы успешно присоединились! Ожидайте начала игры от создателя комнаты.",
        reply_markup=main_menu()
    )

@dp.callback_query(lambda c: c.data == "start_game")
async def start_game(callback: CallbackQuery):
    """Начало игры"""
    user_id = callback.from_user.id
    
    if user_id not in users:
        await callback.answer("Ошибка: данные не найдены", show_alert=True)
        return
    
    user_data = users[user_id]
    partner_id = user_data.get("partner_id")
    
    if not partner_id or partner_id not in users:
        await callback.answer("Партнер не найден", show_alert=True)
        return
    
    # Карточки для теста
    cards = [
        "Какая твоя самая бесполезная, но крутая суперспособность в быту?",
        "Выбери любой предмет в этой комнате и продай его партнеру за 30 секунд.",
        "Опиши партнера как вымышленный, но восхищенный им личный ассистент."
    ]
    
    card = random.choice(cards)
    
    # Уведомляем обоих игроков
    await callback.message.edit_text(
        f"🎮 Игра началась!\n\n"
        f"Первое задание:\n\n"
        f"{card}\n\n"
        f"Когда выполните, нажмите 'Далее'",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Далее ➡️", callback_data="next_card")],
            [InlineKeyboardButton(text="Завершить игру 🏁", callback_data="end_game")]
        ])
    )
    
    await bot.send_message(
        partner_id,
        f"🎮 Игра началась!\n\n"
        f"Задание партнера:\n\n"
        f"{card}\n\n"
        f"Следите за выполнением",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Выполнено ✅", callback_data="task_done")],
            [InlineKeyboardButton(text="Завершить игру 🏁", callback_data="end_game")]
        ])
    )

@dp.callback_query(lambda c: c.data == "next_card")
async def next_card(callback: CallbackQuery):
    """Следующая карточка"""
    cards = [
        "Какое случайное воспоминание из детства всплывает у тебя в голове чаще всего?",
        "Поменяйтесь ролями на 5 минут (положение, занятия, действия).",
        "Если бы завтрашний день можно было посвятить только одному из пяти чувств, какое бы ты выбрал(а)?"
    ]
    
    card = random.choice(cards)
    
    await callback.message.edit_text(
        f"🎴 Новое задание:\n\n"
        f"{card}\n\n"
        f"Когда выполните, нажмите 'Далее'",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Далее ➡️", callback_data="next_card")],
            [InlineKeyboardButton(text="Завершить игру 🏁", callback_data="end_game")]
        ])
    )

@dp.callback_query(lambda c: c.data == "end_game")
async def end_game(callback: CallbackQuery):
    """Завершение игры"""
    user_id = callback.from_user.id
    
    if user_id in users:
        user_data = users[user_id]
        partner_id = user_data.get("partner_id")
        
        if partner_id and partner_id in users:
            await bot.send_message(
                partner_id,
                "🦉 Партнер завершил игру. Спасибо за участие!",
                reply_markup=main_menu()
            )
            del users[partner_id]
        
        del users[user_id]
    
    await callback.message.edit_text(
        "🦉 Игра завершена. Спасибо за участие!",
        reply_markup=main_menu()
    )

@dp.callback_query(lambda c: c.data == "cancel_search")
async def cancel_search(callback: CallbackQuery):
    """Отмена поиска"""
    user_id = callback.from_user.id
    
    if user_id in users:
        room_code = users[user_id].get("room_code")
        if room_code and room_code in active_rooms:
            del active_rooms[room_code]
        del users[user_id]
    
    await callback.message.edit_text(
        "Поиск отменен.",
        reply_markup=main_menu()
    )

# ========== ЗАПУСК ==========
async def main():
    """Основная функция запуска"""
    logger.info("Бот Виктория запускается...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
