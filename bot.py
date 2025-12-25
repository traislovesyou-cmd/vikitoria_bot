import os
import asyncio
import json
import random
import string
import logging
import re
from datetime import datetime
from enum import Enum
from typing import Dict, Optional, List, Any

from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, 
    InlineKeyboardButton, ReplyKeyboardRemove
)
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# ========== НАСТРОЙКА ЛОГИРОВАНИЯ ==========
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ========== КОНФИГУРАЦИЯ ==========
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    logger.error("❌ ERROR: BOT_TOKEN environment variable is not set!")
    exit(1)

# Инициализация
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()
dp.include_router(router)

# ========== МОДЕЛИ ДАННЫХ ==========
class GameState(Enum):
    WAITING_CODE = "waiting_code"
    WAITING_PARTNER = "waiting_partner"
    PARTNER_FOUND = "partner_found"
    IN_GAME = "in_game"

class PlayerRole(Enum):
    PERFORMER = "performer"
    WAITER = "waiter"

class GameStage(Enum):
    WHITE = "white"
    YELLOW = "yellow"
    RED = "red"

# Хранение в памяти (для демо)
active_rooms = {}  # код комнаты -> creator_id
active_users = {}  # user_id -> user_data
user_timers = {}   # user_id -> timer_task

# ========== КАРТОЧКИ (полный набор) ==========
CARDS_DATA = {
    "white": [
        {"id": 1, "type": "question", "text": "Какая твоя самая бесполезная, но крутая суперспособность в быту?"},
        {"id": 2, "type": "action", "text": "Выбери любой предмет в этой комнате и продай его партнеру за 30 секунд, как самый дорогой телешоу-продавец."},
        {"id": 3, "type": "question", "text": "Если бы сегодняшний вечер был песней, то какой жанр? А если фильмом?"},
        {"id": 4, "type": "action", "text": "С завязанными глазами определи на вкус, чем тебя кормит партнер (2,3 продукта)."},
        {"id": 5, "type": "action", "text": "Стань зеркалом партнера на 1 минуту. Повторяй ВСЕ его/ее движения."},
        {"id": 6, "type": "question", "text": "В какой момент за последний месяц ты чувствовал(а) себя самым настоящим взрослым? А самым настоящим ребенком?"},
        {"id": 7, "type": "action_with_dice", "text": "Фото в галерее. Назови партнеру: сверху или снизу и цифру от 1 до 3. Партнер открывает галерею в своем телефоне, находит фото по указанным координатам. Прокомментируй его."},
        {"id": 8, "type": "question", "text": "Опиши партнера так, как мог бы описать его вымышленный, но восхищенный им личный ассистент."},
        {"id": 9, "type": "question", "text": "Какая привычка партнера (жест, слово) тебя неожиданно умиляет или забавляет?"},
        {"id": 10, "type": "question", "text": "Как бы ты описал(а) идеальный «фирменный поцелуй» для пары на таком этапе отношений, как у вас?"},
        {"id": 11, "type": "action", "text": "Игра в контрасты. Расскажи партнеру два факта о себе: один правдивый, один ложный. Задача партнера — угадать, где правда."},
        {"id": 12, "type": "question", "text": "Какое случайное воспоминание из детства о незначительном, но очень приятном моменте (запах, звук, тактильное ощущение) всплывает у тебя в голове чаще всего и почему?"},
        {"id": 13, "type": "question", "text": "Если бы завтрашний день можно было посвятить только одному из пяти чувств (вкус, осязание, обоняние, слух, зрение), какое бы ты выбрал(а) и почему?"},
        {"id": 14, "type": "action", "text": "Поменяйтесь ролями на 5 минут (положение, занятия, действия)."}
    ],
    "yellow": [
        {"id": 1, "type": "action_with_dice", "text": "Массаж с кубиком. Брось кубик (число от 1 до 6). 1 – Шея и плечи партнера, 2 – Стопы, 3 – Кисти рук, 4 – Голова, 5 – Спина (через одежду), 6 – Ты выбираешь зону. Массаж — 3 минуты."},
        {"id": 2, "type": "action", "text": "Лайк заботы. Одним касанием «отметь» ту часть тела партнера, которая, по-твоему, сегодня больше всего нуждается во внимании. Молча. Партнер потом повторяет."},
        {"id": 3, "type": "action", "text": "Сними с партнера один предмет одежды, но не руками. (Потом можно надеть обратно)."},
        {"id": 4, "type": "action", "text": "На ближайшие 5 минут вводится «табу на слова». Общайся с партнером только прикосновениями."},
        {"id": 5, "type": "action", "text": "В течение следующих 2 минут общайся с партнером, глядя только в глаза, не отводя взгляд."},
        {"id": 6, "type": "action", "text": "Завяжи партнеру глаза. Используй 3 разных предмета для тактильных прикосновений. Партнер должен угадать предметы."},
        {"id": 7, "type": "action", "text": "Шепот и отзвук. Завяжи партнеру глаза. Проведи пальцем по его/ее коже, задав ритмичный рисунок. Задача партнера — повторить этот ритм прикосновением на твоем теле."},
        {"id": 8, "type": "action", "text": "Фокус на звуке. На 60 секунд закрой глаза. Партнер будет медленно прикасаться к тебе. Опиши каждое прикосновение только как звук."}
    ],
    "red": [
        {"id": 1, "type": "action", "text": "Слушай кожу. Нанеси немного масла или крема на свои ладони, разогрей. Води ладонями по коже партнера с разной силой и скоростью. По тактильному отклику угадай, где приятнее всего."},
        {"id": 2, "type": "action_with_dice", "text": "Дилема доверия (с кубиком). Брось кубик. Четное число: Ты получаешь полный контроль на 5 минут — веди партнера шепотом или прикосновениями. Нечетное: Ты передаешь этот контроль партнеру."},
        {"id": 3, "type": "action", "text": "Поцелуй-зеркало. Целуй партнера так, как будто пытаешься точно скопировать его ритм, силу и манеру. Затем поменяйтесь ролями — теперь партнер зеркалит тебя."},
        {"id": 4, "type": "action", "text": "Опиши или покажи жестом тот ритм и степень нежности/страсти, которые ты хочешь подарить партнеру сейчас. А затем — те, что хочешь получить."},
        {"id": 5, "type": "question", "text": "Слово-разрешение и слово-интрига. Назови коротко, что ты точно хочешь сейчас. И что тебе интересно попробовать. Партнер сделает то же самое."},
        {"id": 6, "type": "question", "text": "Какой внутренний барьер (мысль, сомнение, привычка) тебе сейчас сложнее всего отпустить, чтобы быть со мной здесь полностью? Или его нет?"},
        {"id": 7, "type": "question", "text": "Что из того, что я делаю (или не делаю) прямо сейчас, заставляет тебя чувствовать себя максимально видимым/ой и желанным/ой?"},
        {"id": 8, "type": "question", "text": "Если бы прямо сейчас у тебя была возможность одним лишь шепотом заставить мое тело сделать одно непроизвольное движение (вздрогнуть, выгнуться, замереть), что бы ты прошептал(а) и куда?"},
        {"id": 9, "type": "question", "text": "Есть ли что-то, что ты хочешь сообщить/рассказать/поделиться с партнером, но не находишь для этого подходящего времени?"},
        {"id": 10, "type": "action", "text": "5 минут на флирт незнакомцев. Разыграйте сцену знакомства и мгновенного влечения. Инициатива у того, кто вытянул карту."},
        {"id": 11, "type": "action_with_dice", "text": "Температура (с кубиком). Брось кубик. Выпавшее число — количество поцелуев, которые нужно поставить на теле партнера, чередуя горячие (с дыханием) и холодные (едва касаясь губами) на свое усмотрение."},
        {"id": 12, "type": "action", "text": "Выбор в твоих руках. 5 минут. Молча протяни партнеру повязку для глаз. Этот жест передает ему/ей право решить: надеть на себя, надеть на тебя или отложить. Любое решение — начало следующего действия."},
        {"id": 13, "type": "action_with_dice", "text": "Поза и время (с кубиком). Вытянувший карту загадывает позу для партнера. Партнер бросает кубик. Время в позе = (число на кубике / 2) с округлением вверх. Пример: 5 -> 3 минуты."},
        {"id": 14, "type": "action", "text": "Безусловное желание. 3 минуты. Вытянувший карту формулирует: «Я хочу, чтобы следующие 3 минуты ты...». Это становится правилом."},
        {"id": 15, "type": "action_with_dice", "text": "Кубик чувств (с кубиком). Брось кубик. Исследуй выбранное интимное место партнера 1 минуту методом: 1-Губы/дыхание, 2-Пальцы, 3-Щеки/ресницы, 4-Поцелуи, 5-Тепло/холод, 6-Ты выбираешь метод, партнер — зону."}
    ]
}

def get_random_card(stage: GameStage) -> Dict:
    """Получить случайную карту из колоды"""
    deck = CARDS_DATA.get(stage.value, [])
    return random.choice(deck) if deck else {"id": 0, "type": "info", "text": "Карточки временно отсутствуют"}

def has_timer_in_text(text: str) -> bool:
    """Проверить, есть ли в тексте упоминание времени"""
    time_indicators = ['минут', 'секунд', 'час', 'таймер', 'время', 'минуту', 'секунду']
    return any(indicator in text.lower() for indicator in time_indicators)

def has_photo_in_text(text: str) -> bool:
    """Проверить, нужно ли фото"""
    return 'фото' in text.lower() or 'галере' in text.lower() or 'снимок' in text.lower()

def has_dice_in_card(card: Dict) -> bool:
    """Проверить, нужен ли кубик"""
    return card.get("type") == "action_with_dice"

# ========== КЛАВИАТУРЫ ==========
def main_menu_keyboard() -> InlineKeyboardMarkup:
    """Главное меню"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Начать игру 🦉", callback_data="create_room")],
        [InlineKeyboardButton(text="Присоединиться к игре", callback_data="join_room")],
        [InlineKeyboardButton(text="Правила игры", callback_data="show_rules")]
    ])

def back_to_main_keyboard() -> InlineKeyboardMarkup:
    """Кнопка назад"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="В главное меню", callback_data="main_menu")]
    ])

def waiting_partner_keyboard() -> InlineKeyboardMarkup:
    """Ожидание партнера"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Отменить поиск", callback_data="cancel_search")],
        [InlineKeyboardButton(text="В главное меню", callback_data="main_menu")]
    ])

def partner_found_keyboard(is_creator: bool) -> InlineKeyboardMarkup:
    """Партнер найден"""
    if is_creator:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Начать игру! 🎮", callback_data="start_game")],
            [InlineKeyboardButton(text="Отмена", callback_data="cancel_game")]
        ])
    else:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Ожидаю начала...", callback_data="wait")],
            [InlineKeyboardButton(text="Выйти", callback_data="cancel_game")]
        ])

def performer_keyboard(card: Dict) -> InlineKeyboardMarkup:
    """Клавиатура исполняющего"""
    buttons = []
    
    # Основные кнопки
    buttons.append([InlineKeyboardButton(text="Выполнил ✅", callback_data="task_done")])
    buttons.append([InlineKeyboardButton(text="Пропустить ➡️", callback_data="skip_card")])
    
    # Специальные кнопки
    if has_timer_in_text(card["text"]):
        buttons.append([InlineKeyboardButton(text="Запустить таймер ⏱️", callback_data="start_timer")])
    
    if has_photo_in_text(card["text"]):
        buttons.append([InlineKeyboardButton(text="Отправить фото 📸", callback_data="request_photo")])
    
    if has_dice_in_card(card):
        buttons.append([InlineKeyboardButton(text="Бросить кубик 🎲", callback_data="roll_dice")])
    
    # Кнопка завершения
    buttons.append([InlineKeyboardButton(text="Завершить игру 🏁", callback_data="end_game")])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def waiter_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура ожидающего"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Выполнено ✅", callback_data="task_done")],
        [InlineKeyboardButton(text="Пропустить ➡️", callback_data="skip_card")],
        [InlineKeyboardButton(text="Завершить игру 🏁", callback_data="end_game")]
    ])

# ========== ТАЙМЕРЫ ==========
async def smart_timer(chat_id: int, seconds: int):
    """Умный таймер с уведомлениями"""
    try:
        msg = await bot.send_message(chat_id, f"⏱️ Таймер запущен: {seconds} сек.")
        
        intervals = []
        if seconds > 900:  # > 15 минут
            intervals = list(range(seconds, 0, -300))
        elif seconds > 120:  # > 2 минут
            intervals = list(range(seconds, 0, -60))
        elif seconds > 60:
            intervals = list(range(seconds, 0, -10))
        elif seconds > 20:
            intervals = list(range(seconds, 0, -5))
        else:
            intervals = list(range(seconds, 0, -1))
        
        for remaining in intervals[1:]:
            await asyncio.sleep(intervals[0] - remaining)
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=msg.message_id,
                text=f"⏱️ Осталось: {remaining} сек."
            )
        
        await asyncio.sleep(intervals[0])
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=msg.message_id,
            text="⏰ Время вышло!"
        )
        
    except asyncio.CancelledError:
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=msg.message_id,
            text="⏹️ Таймер остановлен"
        )
    except Exception as e:
        logger.error(f"Timer error: {e}")

# ========== ОСНОВНЫЕ ОБРАБОТЧИКИ ==========
@router.message(Command("start"))
async def cmd_start(message: Message):
    """Команда /start"""
    await message.answer(
        "🦉 Добро пожаловать в Викторию!\n\n"
        "Игра для двоих, которая поможет стать ближе через разговоры, "
        "тактильные игры и откровенность.\n\n"
        "Основные правила:\n"
        "• Всегда можно сказать 'Пропустить'\n"
        "• Уважайте границы друг друга\n"
        "• Говорите 'Ворчун!' если стало неловко\n"
        "• Описывайте ощущения через метафоры\n\n"
        "Выберите действие:",
        reply_markup=main_menu_keyboard()
    )

@router.callback_query(F.data == "main_menu")
async def main_menu_handler(callback: CallbackQuery):
    """Возврат в главное меню"""
    user_id = callback.from_user.id
    
    # Отменяем таймеры
    if user_id in user_timers:
        user_timers[user_id].cancel()
        del user_timers[user_id]
    
    # Уведомляем партнера
    if user_id in active_users:
        user_data = active_users[user_id]
        partner_id = user_data.get("partner_id")
        
        if partner_id and partner_id in active_users:
            await bot.send_message(
                partner_id,
                "Партнер вышел в главное меню. Игра завершена.",
                reply_markup=main_menu_keyboard()
            )
            # Очищаем партнера
            if partner_id in user_timers:
                user_timers[partner_id].cancel()
                del user_timers[partner_id]
            del active_users[partner_id]
        
        # Очищаем комнату
        room_code = user_data.get("room_code")
        if room_code and room_code in active_rooms:
            del active_rooms[room_code]
        
        # Очищаем себя
        del active_users[user_id]
    
    await callback.message.edit_text(
        "Выберите действие:",
        reply_markup=main_menu_keyboard()
    )

@router.callback_query(F.data == "create_room")
async def create_room_handler(callback: CallbackQuery):
    """Создание комнаты"""
    user_id = callback.from_user.id
    room_code = ''.join(random.choices(string.ascii_uppercase, k=6))
    
    # Сохраняем данные
    active_users[user_id] = {
        "state": GameState.WAITING_PARTNER.value,
        "room_code": room_code,
        "stage": GameStage.WHITE.value,
        "room_created": datetime.now().timestamp()
    }
    
    active_rooms[room_code] = {
        "creator_id": user_id,
        "created_at": datetime.now().timestamp()
    }
    
    await callback.message.edit_text(
        f"🦉 Комната создана!\n\n"
        f"Код для присоединения:\n"
        f"<code>{room_code}</code>\n\n"
        f"Отправьте этот код партнеру.\n"
        f"Ожидание: 5 минут",
        parse_mode="HTML",
        reply_markup=waiting_partner_keyboard()
    )
    
    # Автоудаление через 5 минут
    await asyncio.sleep(300)
    if room_code in active_rooms:
        del active_rooms[room_code]
    if user_id in active_users and active_users[user_id].get("room_code") == room_code:
        del active_users[user_id]
        try:
            await callback.message.edit_text(
                "Время ожидания истекло. Комната удалена.",
                reply_markup=main_menu_keyboard()
            )
        except:
            pass

@router.callback_query(F.data == "join_room")
async def join_room_handler(callback: CallbackQuery):
    """Присоединение к комнате"""
    await callback.message.edit_text(
        "✏️ Введите 6-значный код комнаты (только английские буквы, например: ABCDEF):",
        reply_markup=back_to_main_keyboard()
    )

@router.message(F.text.regexp(r'^[A-Z]{6}$'))
async def process_room_code(message: Message):
    """Обработка кода комнаты"""
    room_code = message.text.upper()
    user_id = message.from_user.id
    
    if room_code not in active_rooms:
        await message.answer(
            "❌ Комната не найдена. Проверьте код или попросите партнера создать новую комнату.",
            reply_markup=main_menu_keyboard()
        )
        return
    
    if user_id in active_users:
        await message.answer(
            "❌ Вы уже в игре. Сначала завершите текущую.",
            reply_markup=main_menu_keyboard()
        )
        return
    
    creator_id = active_rooms[room_code]["creator_id"]
    
    # Обновляем данные создателя
    if creator_id in active_users:
        active_users[creator_id]["state"] = GameState.PARTNER_FOUND.value
        active_users[creator_id]["partner_id"] = user_id
        
        # Удаляем комнату из поиска
        del active_rooms[room_code]
        
        # Уведомляем создателя
        await bot.send_message(
            creator_id,
            f"🎉 Партнер {message.from_user.first_name} присоединился!\n\n"
            f"Теперь вы можете начать игру.",
            reply_markup=partner_found_keyboard(is_creator=True)
        )
    
    # Создаем данные для присоединившегося
    active_users[user_id] = {
        "state": GameState.PARTNER_FOUND.value,
        "room_code": room_code,
        "partner_id": creator_id,
        "stage": GameStage.WHITE.value
    }
    
    await message.answer(
        f"✅ Вы присоединились! Ожидайте начала игры.",
        reply_markup=partner_found_keyboard(is_creator=False)
    )

@router.callback_query(F.data == "start_game")
async def start_game_handler(callback: CallbackQuery):
    """Начало игры"""
    user_id = callback.from_user.id
    
    if user_id not in active_users:
        await callback.answer("❌ Ошибка: данные не найдены", show_alert=True)
        return
    
    user_data = active_users[user_id]
    partner_id = user_data.get("partner_id")
    
    if not partner_id or partner_id not in active_users:
        await callback.answer("❌ Партнер не найден", show_alert=True)
        return
    
    # Определяем роли случайно
    user_data["state"] = GameState.IN_GAME.value
    user_data["role"] = PlayerRole.PERFORMER.value if random.random() > 0.5 else PlayerRole.WAITER.value
    
    # Обновляем партнера
    partner_data = active_users[partner_id]
    partner_data["state"] = GameState.IN_GAME.value
    partner_data["role"] = PlayerRole.WAITER.value if user_data["role"] == PlayerRole.PERFORMER.value else PlayerRole.PERFORMER.value
    
    # Отправляем сообщения
    await callback.message.edit_text(
        "🎮 Игра началась!\n\n"
        f"Ваша роль: <b>{'Исполняющий' if user_data['role'] == PlayerRole.PERFORMER.value else 'Ожидающий'}</b>\n"
        f"Этап: Белая колода (Разговор и флирт)",
        parse_mode="HTML"
    )
    
    await bot.send_message(
        partner_id,
        "🎮 Игра началась!\n\n"
        f"Ваша роль: <b>{'Исполняющий' if partner_data['role'] == PlayerRole.PERFORMER.value else 'Ожидающий'}</b>\n"
        f"Этап: Белая колода (Разговор и флирт)",
        parse_mode="HTML"
    )
    
    # Раздаем первую карту
    await send_next_card(user_id)

async def send_next_card(user_id: int):
    """Отправка следующей карточки"""
    if user_id not in active_users:
        return
    
    user_data = active_users[user_id]
    
    if user_data["state"] != GameState.IN_GAME.value:
        return
    
    # Получаем карту
    stage = GameStage(user_data["stage"])
    card = get_random_card(stage)
    user_data["current_card"] = card
    
    # Отправляем карту
    if user_data["role"] == PlayerRole.PERFORMER.value:
        text = f"🎴 Ваше задание:\n\n{card['text']}"
        await bot.send_message(user_id, text, reply_markup=performer_keyboard(card))
        
        # Партнеру только текст
        partner_id = user_data.get("partner_id")
        if partner_id and partner_id in active_users:
            await bot.send_message(
                partner_id,
                f"🎴 Задание партнера:\n\n{card['text']}",
                reply_markup=waiter_keyboard()
            )
    else:
        # Если ожидающий, ничего не делаем
        pass

# ========== ОБРАБОТКА КАРТОЧЕК ==========
@router.callback_query(F.data == "task_done")
async def task_done_handler(callback: CallbackQuery):
    """Задание выполнено"""
    user_id = callback.from_user.id
    
    if user_id not in active_users:
        await callback.answer("❌ Ошибка", show_alert=True)
        return
    
    user_data = active_users[user_id]
    
    if user_data["role"] == PlayerRole.WAITER.value:
        # Меняем роли
        await switch_roles(user_id)
        await callback.answer("✅ Задание выполнено!")
    else:
        await callback.answer("⏳ Дождитесь подтверждения партнера", show_alert=True)

@router.callback_query(F.data == "skip_card")
async def skip_card_handler(callback: CallbackQuery):
    """Пропуск карточки"""
    user_id = callback.from_user.id
    
    if user_id not in active_users:
        await callback.answer("❌ Ошибка", show_alert=True)
        return
    
    user_data = active_users[user_id]
    card = user_data.get("current_card", {})
    
    # Уведомляем партнера
    partner_id = user_data.get("partner_id")
    if partner_id and partner_id in active_users:
        await bot.send_message(
            partner_id,
            f"⏩ Партнер пропустил карточку:\n\n{card.get('text', '')}\n\nВаш ход!"
        )
    
    # Меняем роли
    await switch_roles(user_id)
    await callback.answer("Карточка пропущена")

async def switch_roles(user_id: int):
    """Смена ролей"""
    if user_id not in active_users:
        return
    
    user_data = active_users[user_id]
    partner_id = user_data.get("partner_id")
    
    if not partner_id or partner_id not in active_users:
        return
    
    # Меняем роли
    user_data["role"] = PlayerRole.WAITER.value if user_data["role"] == PlayerRole.PERFORMER.value else PlayerRole.PERFORMER.value
    active_users[partner_id]["role"] = PlayerRole.PERFORMER.value if user_data["role"] == PlayerRole.WAITER.value else PlayerRole.WAITER.value
    
    # Очищаем текущие карты
    user_data["current_card"] = None
    active_users[partner_id]["current_card"] = None
    
    # Отправляем новую карту новому исполнителю
    new_performer = user_id if user_data["role"] == PlayerRole.PERFORMER.value else partner_id
    await send_next_card(new_performer)

@router.callback_query(F.data == "start_timer")
async def start_timer_handler(callback: CallbackQuery):
    """Запуск таймера"""
    user_id = callback.from_user.id
    
    if user_id not in active_users:
        await callback.answer("❌ Ошибка", show_alert=True)
        return
    
    user_data = active_users[user_id]
    card = user_data.get("current_card", {})
    
    # Парсим время из текста
    text = card.get("text", "")
    minutes = 5  # по умолчанию
    
    time_match = re.search(r'(\d+)\s*минут', text)
    if time_match:
        minutes = int(time_match.group(1))
    
    # Запускаем таймер
    if user_id in user_timers:
        user_timers[user_id].cancel()
    
    user_timers[user_id] = asyncio.create_task(smart_timer(user_id, minutes * 60))
    
    await callback.answer(f"Таймер запущен на {minutes} минут")

@router.callback_query(F.data == "roll_dice")
async def roll_dice_handler(callback: CallbackQuery):
    """Бросок кубика"""
    dice_value = random.randint(1, 6)
    
    user_id = callback.from_user.id
    if user_id in active_users:
        user_data = active_users[user_id]
        partner_id = user_data.get("partner_id")
        
        if partner_id:
            await bot.send_message(
                partner_id,
                f"🎲 Партнер бросил кубик: выпало {dice_value}"
            )
    
    await callback.answer(f"🎲 Выпало: {dice_value}", show_alert=True)

@router.callback_query(F.data == "end_game")
async def end_game_handler(callback: CallbackQuery):
    """Завершение игры"""
    user_id = callback.from_user.id
    
    if user_id in active_users:
        user_data = active_users[user_id]
        partner_id = user_data.get("partner_id")
        
        # Уведомляем партнера
        if partner_id and partner_id in active_users:
            await bot.send_message(
                partner_id,
                "🦉 Партнер завершил игру. Спасибо за участие!",
                reply_markup=main_menu_keyboard()
            )
            
            # Очищаем партнера
            if partner_id in user_timers:
                user_timers[partner_id].cancel()
                del user_timers[partner_id]
            del active_users[partner_id]
        
        # Очищаем себя
        if user_id in user_timers:
            user_timers[user_id].cancel()
            del user_timers[user_id]
        del active_users[user_id]
    
    await callback.message.edit_text(
        "🦉 Игра завершена. Спасибо за участие!",
        reply_markup=main_menu_keyboard()
    )

@router.callback_query(F.data == "show_rules")
async def show_rules_handler(callback: CallbackQuery):
    """Показать правила"""
    rules = (
        "📜 Правила игры 'Виктория':\n\n"
        "🎯 Цель: Создать атмосферу для постепенного сближения\n\n"
        "📋 Основные правила:\n"
        "1. Всегда можно сказать 'Пропустить'\n"
        "2. Уважайте границы друг друга\n"
        "3. Говорите 'Ворчун!' если стало неловко\n"
        "4. Описывайте ощущения через метафоры\n\n"
        "🎴 Этапы игры:\n"
        "• Белый - Разговор и флирт\n"
        "• Жёлтый - Тактильные игры\n"
        "• Красный - Интимная глубина\n\n"
        "🔄 Как играть:\n"
        "1. Один создаёт комнату, второй присоединяется\n"
        "2. Исполняющий получает задание\n"
        "3. Ожидающий следит за выполнением\n"
        "4. После выполнения меняемся ролями"
    )
    
    await callback.message.edit_text(rules, reply_markup=back_to_main_keyboard())

# ========== ЗАПУСК ==========
async def main():
    """Основная функция запуска"""
    logger.info("✅ Бот 'Виктория' запускается...")
    bot_info = await bot.get_me()
    logger.info(f"🤖 Бот: @{bot_info.username}")
    logger.info(f"🆔 ID: {bot_info.id}")
    logger.info("🚀 Бот готов к работе!")
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
