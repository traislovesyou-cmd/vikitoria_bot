import os
import asyncio
import json
import random
import string
import logging
from datetime import datetime
from enum import Enum
from typing import Dict, Optional, List, Any

from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, 
    InlineKeyboardButton, ReplyKeyboardRemove, PhotoSize
)
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

# ========== НАСТРОЙКА ЛОГГИРОВАНИЯ ==========
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ========== КОНФИГУРАЦИЯ ==========
BOT_TOKEN = os.getenv("BOT_TOKEN")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # Render сам подставит
WEBHOOK_PATH = "/webhook"
WEB_SERVER_HOST = "0.0.0.0"
WEB_SERVER_PORT = int(os.getenv("PORT", 10000))

# Инициализация бота
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()  # Для Render проще использовать MemoryStorage
dp = Dispatcher(storage=storage)
router = Router()
dp.include_router(router)

# ========== МОДЕЛИ ДАННЫХ ==========
class GameState(Enum):
    WAITING_CODE = "waiting_code"
    WAITING_PARTNER = "waiting_partner"
    PARTNER_FOUND = "partner_found"
    IN_GAME = "in_game"
    AWAITING_CONFIRMATION = "awaiting_confirmation"

class PlayerRole(Enum):
    PERFORMER = "performer"
    WAITER = "waiter"

class GameStage(Enum):
    WHITE = "white"
    YELLOW = "yellow"
    RED = "red"
    ENVELOPE = "envelope"

# Вместо Redis будем хранить в памяти (для простоты)
# В продакшене лучше Redis, но для Render Free сойдёт
active_users = {}
active_rooms = {}
user_timers = {}

# ========== ЗАГРУЗКА ДАННЫХ КАРТОЧЕК ==========
CARDS_DATA = {
    "white": [
        {
            "id": 1,
            "type": "question",
            "text": "Какая твоя самая бесполезная, но крутая суперспособность в быту?"
        },
        {
            "id": 2,
            "type": "action",
            "text": "Выбери любой предмет в этой комнате и продай его партнеру за 30 секунд, как самый дорогой телешоу-продавец."
        },
        {
            "id": 3,
            "type": "question",
            "text": "Если бы сегодняшний вечер был песней, то какой жанр? А если фильмом?"
        },
        {
            "id": 4,
            "type": "action",
            "text": "С завязанными глазами определи на вкус, чем тебя кормит партнер (2,3 продукта)."
        },
        {
            "id": 5,
            "type": "action",
            "text": "Стань зеркалом партнера на 1 минуту. Повторяй ВСЕ его/ее движения."
        },
        {
            "id": 6,
            "type": "question",
            "text": "В какой момент за последний месяц ты чувствовал(а) себя самым настоящим взрослым? А самым настоящим ребенком?"
        },
        {
            "id": 7,
            "type": "action_with_dice_photo",
            "text": "Фото в галерее. Назови партнеру: сверху или снизу и цифру от 1 до 3. Партнер открывает галерею в своем телефоне, находит фото по указанным координатам. Прокомментируй его."
        },
        {
            "id": 8,
            "type": "question",
            "text": "Опиши партнера так, как мог бы описать его вымышленный, но восхищенный им личный ассистент."
        },
        {
            "id": 9,
            "type": "question",
            "text": "Какая привычка партнера (жест, слово) тебя неожиданно умиляет или забавляет?"
        },
        {
            "id": 10,
            "type": "question",
            "text": "Как бы ты описал(а) идеальный «фирменный поцелуй» для пары на таком этапе отношений, как у вас?"
        },
        {
            "id": 11,
            "type": "action",
            "text": "Игра в контрасты. Расскажи партнеру два факта о себе: один правдивый, один ложный. Задача партнера — угадать, где правда."
        },
        {
            "id": 12,
            "type": "question",
            "text": "Какое случайное воспоминание из детства о незначительном, но очень приятном моменте (запах, звук, тактильное ощущение) всплывает у тебя в голове чаще всего и почему?"
        },
        {
            "id": 13,
            "type": "question",
            "text": "Если бы завтрашний день можно было посвятить только одному из пяти чувств (вкус, осязание, обоняние, слух, зрение), какое бы ты выбрал(а) и почему?"
        },
        {
            "id": 14,
            "type": "action",
            "text": "Поменяйтесь ролями на 5 минут (положение, занятия, действия)."
        }
    ],
    "yellow": [
        {
            "id": 1,
            "type": "action_with_dice",
            "text": "Массаж с кубиком. Брось кубик (число от 1 до 6). 1 – Шея и плечи партнера, 2 – Стопы, 3 – Кисти рук, 4 – Голова, 5 – Спина (через одежду), 6 – Ты выбираешь зону. Массаж — 3 минуты.",
            "dice_meaning": "1: Шея и плечи, 2: Стопы, 3: Кисти рук, 4: Голова, 5: Спина, 6: Твой выбор"
        },
        {
            "id": 2,
            "type": "action",
            "text": "Лайк заботы. Одним касанием «отметь» ту часть тела партнера, которая, по-твоему, сегодня больше всего нуждается во внимании. Молча. Партнер потом повторяет."
        },
        {
            "id": 3,
            "type": "action",
            "text": "Сними с партнера один предмет одежды, но не руками. (Потом можно надеть обратно)."
        },
        {
            "id": 4,
            "type": "action",
            "text": "На ближайшие 5 минут вводится «табу на слова». Общайся с партнером только прикосновениями."
        },
        {
            "id": 5,
            "type": "action",
            "text": "В течение следующих 2 минут общайся с партнером, глядя только в глаза, не отводя взгляд."
        },
        {
            "id": 6,
            "type": "action",
            "text": "Завяжи партнеру глаза. Используй 3 разных предмета для тактильных прикосновений. Партнер должен угадать предметы."
        },
        {
            "id": 7,
            "type": "action",
            "text": "Шепот и отзвук. Завяжи партнеру глаза. Проведи пальцем по его/ее коже, задав ритмичный рисунок. Задача партнера — повторить этот ритм прикосновением на твоем теле."
        },
        {
            "id": 8,
            "type": "action",
            "text": "Фокус на звуке. На 60 секунд закрой глаза. Партнер будет медленно прикасаться к тебе. Опиши каждое прикосновение только как звук."
        }
    ],
    "red": [
        {
            "id": 1,
            "type": "action",
            "text": "Слушай кожу. Нанеси немного масла или крема на свои ладони, разогрей. Води ладонями по коже партнера с разной силой и скоростью. По тактильному отклику угадай, где приятнее всего."
        },
        {
            "id": 2,
            "type": "action_with_dice",
            "text": "Дилема доверия (с кубиком). Брось кубик. Четное число: Ты получаешь полный контроль на 5 минут — веди партнера шепотом или прикосновениями. Нечетное: Ты передаешь этот контроль партнеру.",
            "dice_meaning": "Четное: Контроль у тебя, Нечетное: Контроль у партнера"
        },
        {
            "id": 3,
            "type": "action",
            "text": "Поцелуй-зеркало. Целуй партнера так, как будто пытаешься точно скопировать его ритм, силу и манеру. Затем поменяйтесь ролями — теперь партнер зеркалит тебя."
        },
        {
            "id": 4,
            "type": "action",
            "text": "Опиши или покажи жестом тот ритм и степень нежности/страсти, которые ты хочешь подарить партнеру сейчас. А затем — те, что хочешь получить."
        },
        {
            "id": 5,
            "type": "question",
            "text": "Слово-разрешение и слово-интрига. Назови коротко, что ты точно хочешь сейчас. И что тебе интересно попробовать. Партнер сделает то же самое."
        },
        {
            "id": 6,
            "type": "question",
            "text": "Какой внутренний барьер (мысль, сомнение, привычка) тебе сейчас сложнее всего отпустить, чтобы быть со мной здесь полностью? Или его нет?"
        },
        {
            "id": 7,
            "type": "question",
            "text": "Что из того, что я делаю (или не делаю) прямо сейчас, заставляет тебя чувствовать себя максимально видимым/ой и желанным/ой?"
        },
        {
            "id": 8,
            "type": "question",
            "text": "Если бы прямо сейчас у тебя была возможность одним лишь шепотом заставить мое тело сделать одно непроизвольное движение (вздрогнуть, выгнуться, замереть), что бы ты прошептал(а) и куда?"
        },
        {
            "id": 9,
            "type": "question",
            "text": "Есть ли что-то, что ты хочешь сообщить/рассказать/поделиться с партнером, но не находишь для этого подходящего времени?"
        },
        {
            "id": 10,
            "type": "action",
            "text": "5 минут на флирт незнакомцев. Разыграйте сцену знакомства и мгновенного влечения. Инициатива у того, кто вытянул карту."
        },
        {
            "id": 11,
            "type": "action_with_dice",
            "text": "Температура (с кубиком). Брось кубик. Выпавшее число — количество поцелуев, которые нужно поставить на теле партнера, чередуя горячие (с дыханием) и холодные (едва касаясь губами) на свое усмотрение.",
            "dice_meaning": "Число: Количество поцелуев"
        },
        {
            "id": 12,
            "type": "action",
            "text": "Выбор в твоих руках. 5 минут. Молча протяни партнеру повязку для глаз. Этот жест передает ему/ей право решить: надеть на себя, надеть на тебя или отложить. Любое решение — начало следующего действия."
        },
        {
            "id": 13,
            "type": "action_with_dice",
            "text": "Поза и время (с кубиком). Вытянувший карту загадывает позу для партнера. Партнер бросает кубик. Время в позе = (число на кубике / 2) с округлением вверх. Пример: 5 -> 3 минуты.",
            "dice_meaning": "Число: Расчёт времени в позе"
        },
        {
            "id": 14,
            "type": "action",
            "text": "Безусловное желание. 3 минуты. Вытянувший карту формулирует: «Я хочу, чтобы следующие 3 минуты ты...». Это становится правилом."
        },
        {
            "id": 15,
            "type": "action_with_dice",
            "text": "Кубик чувств (с кубиком). Брось кубик. Исследуй выбранное интимное место партнера 1 минуту методом: 1-Губы/дыхание, 2-Пальцы, 3-Щеки/ресницы, 4-Поцелуи, 5-Тепло/холод, 6-Ты выбираешь метод, партнер — зону.",
            "dice_meaning": "1: Губы/дыхание, 2: Пальцы, 3: Щеки/ресницы, 4: Поцелуи, 5: Тепло/холод, 6: Выбор метода и зоны"
        }
    ]
}

def get_random_card(stage: GameStage) -> Dict:
    deck = CARDS_DATA.get(stage.value, [])
    return random.choice(deck) if deck else {"id": 0, "type": "info", "text": "Карточки временно отсутствуют"}

def has_timer_in_text(text: str) -> bool:
    time_indicators = ['минут', 'секунд', 'час', 'таймер', 'время', 'минуту', 'секунду']
    return any(indicator in text.lower() for indicator in time_indicators)

def has_photo_in_text(text: str) -> bool:
    return 'фото' in text.lower() or 'галере' in text.lower() or 'снимок' in text.lower()

def has_dice_in_card(card: Dict) -> bool:
    return card.get("type") in ["action_with_dice", "action_with_dice_photo"]

# ========== КЛАВИАТУРЫ ==========
def main_menu_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="Начать игру 🦉", callback_data="create_room")],
        [InlineKeyboardButton(text="Присоединиться к игре", callback_data="join_room")],
        [InlineKeyboardButton(text="Правила игры", callback_data="show_rules")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def back_to_main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="В главное меню", callback_data="main_menu")]
    ])

def waiting_partner_keyboard(room_code: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Отменить поиск", callback_data="cancel_search")],
        [InlineKeyboardButton(text="В главное меню", callback_data="main_menu")]
    ])

def partner_found_keyboard(is_creator: bool) -> InlineKeyboardMarkup:
    if is_creator:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Начать игру!", callback_data="start_game_session")],
            [InlineKeyboardButton(text="Отмена", callback_data="cancel_game")]
        ])
    else:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Жду начала игры...", callback_data="wait")],
            [InlineKeyboardButton(text="Выйти", callback_data="cancel_game")]
        ])

def performer_keyboard(card: Dict) -> InlineKeyboardMarkup:
    buttons = []
    
    # Основные кнопки
    buttons.append([InlineKeyboardButton(text="Пропустить ➡️", callback_data="skip_card")])
    
    # Специальные кнопки в зависимости от карты
    if has_timer_in_text(card["text"]):
        buttons.append([InlineKeyboardButton(text="Запустить таймер ⏱️", callback_data="start_timer")])
    
    if has_photo_in_text(card["text"]):
        buttons.append([InlineKeyboardButton(text="Отправить фото 📸", callback_data="request_photo")])
    
    if has_dice_in_card(card):
        buttons.append([InlineKeyboardButton(text="Бросить кубик 🎲", callback_data="roll_dice")])
    
    # Кнопка завершения игры (везде, кроме начального экрана)
    buttons.append([InlineKeyboardButton(text="Завершить игру 🏁", callback_data="request_stop_game")])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def waiter_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Выполнено ✅", callback_data="task_done")],
        [InlineKeyboardButton(text="Пропустить ➡️", callback_data="skip_card")],
        [InlineKeyboardButton(text="Завершить игру 🏁", callback_data="request_stop_game")]
    ])

def stop_game_confirmation_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Ну куда уж деваться 😔", callback_data="confirm_stop")],
        [InlineKeyboardButton(text="Да ладно, позже продолжим 😊", callback_data="postpone_stop")]
    ])

def postpone_response_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Ну ок, снизойду 🙄", callback_data="continue_game")],
        [InlineKeyboardButton(text="Завершить 🚫", callback_data="force_stop")]
    ])

def envelope_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Для неё 💝", callback_data="envelope_her")],
        [InlineKeyboardButton(text="Для него 💙", callback_data="envelope_him")]
    ])

def envelope_done_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Выполнено ✅", callback_data="envelope_done")]
    ])

# ========== УПРАВЛЕНИЕ ДАННЫМИ ==========
class UserData:
    def __init__(self, user_id: int):
        self.user_id = user_id
        self.partner_id: Optional[int] = None
        self.game_state: GameState = GameState.WAITING_CODE
        self.room_code: Optional[str] = None
        self.role: Optional[PlayerRole] = None
        self.current_card: Optional[Dict] = None
        self.current_stage: GameStage = GameStage.WHITE
        self.envelope_choice: Optional[str] = None
        self.waiting_for_photo: bool = False

# ========== ОСНОВНЫЕ ОБРАБОТЧИКИ ==========
@router.message(Command("start"))
async def cmd_start(message: Message):
    """Начало работы с ботом"""
    user_id = message.from_user.id
    
    if user_id not in active_users:
        active_users[user_id] = UserData(user_id)
    
    welcome_text = (
        "🦉 Добро пожаловать в Викторию!\n\n"
        "Это игра для двоих, которая поможет вам стать ближе через разговоры, "
        "тактильные игры и откровенность.\n\n"
        "Основные правила:\n"
        "• Всегда можно сказать 'Пропустить'\n"
        "• Уважайте границы друг друга\n"
        "• Говорите 'Ворчун!' если стало неловко\n"
        "• Описывайте ощущения через метафоры\n\n"
        "Выберите действие:"
    )
    
    await message.answer(welcome_text, reply_markup=main_menu_keyboard())

@router.callback_query(F.data == "main_menu")
async def return_to_main(callback: CallbackQuery):
    """Возврат в главное меню"""
    user_id = callback.from_user.id
    
    # Отменяем таймер если есть
    if user_id in user_timers:
        user_timers[user_id].cancel()
        del user_timers[user_id]
    
    # Уведомляем партнера если есть игра
    if user_id in active_users:
        user = active_users[user_id]
        if user.partner_id and user.partner_id in active_users:
            partner = active_users[user.partner_id]
            if partner.game_state == GameState.IN_GAME:
                await bot.send_message(
                    user.partner_id,
                    "Партнер вышел в главное меню. Игра завершена.",
                    reply_markup=main_menu_keyboard()
                )
                # Очищаем данные партнера
                if user.partner_id in active_users:
                    del active_users[user.partner_id]
        
        # Очищаем свою комнату если есть
        if user.room_code and user.room_code in active_rooms:
            del active_rooms[user.room_code]
        
        # Очищаем свои данные
        del active_users[user_id]
    
    await callback.message.edit_text(
        "Выберите действие:",
        reply_markup=main_menu_keyboard()
    )

@router.callback_query(F.data == "create_room")
async def create_game_room(callback: CallbackQuery):
    """Создание игровой комнаты"""
    user_id = callback.from_user.id
    room_code = ''.join(random.choices(string.ascii_uppercase, k=6))
    
    user = UserData(user_id)
    user.game_state = GameState.WAITING_PARTNER
    user.room_code = room_code
    active_users[user_id] = user
    active_rooms[room_code] = {"creator_id": user_id, "created_at": datetime.now()}
    
    await callback.message.edit_text(
        f"🦉 Комната создана!\n\n"
        f"Код для присоединения:\n"
        f"<code>{room_code}</code>\n\n"
        f"Отправьте этот код партнеру или пусть он введет его вручную.\n"
        f"Ожидание: 5 минут\n\n"
        f"Для присоединения партнер должен:\n"
        f"1. Нажать 'Присоединиться к игре'\n"
        f"2. Ввести этот код: {room_code}",
        parse_mode="HTML",
        reply_markup=waiting_partner_keyboard(room_code)
    )
    
    # Автоматическая отмена через 5 минут
    await asyncio.sleep(300)
    if room_code in active_rooms:
        del active_rooms[room_code]
    if user_id in active_users:
        if active_users[user_id].room_code == room_code:
            del active_users[user_id]
            try:
                await callback.message.edit_text(
                    "Время ожидания истекло. Комната удалена.",
                    reply_markup=main_menu_keyboard()
                )
            except:
                pass

@router.callback_query(F.data == "join_room")
async def ask_room_code(callback: CallbackQuery):
    """Запрос кода комнаты"""
    await callback.message.edit_text(
        "✏️ Введите 6-значный код комнаты (только английские буквы, например: ABCDEF):",
        reply_markup=back_to_main_keyboard()
    )

@router.message(F.text.regexp(r'^[A-Z]{6}$'))
async def join_room_by_code(message: Message):
    """Присоединение по коду комнаты"""
    room_code = message.text.upper()
    user_id = message.from_user.id
    
    if room_code not in active_rooms:
        await message.answer(
            "❌ Комната не найдена или время истекло. Попросите партнера создать новую комнату.",
            reply_markup=main_menu_keyboard()
        )
        return
    
    if user_id in active_users:
        await message.answer("❌ Вы уже в игре. Сначала завершите текущую.", reply_markup=main_menu_keyboard())
        return
    
    creator_id = active_rooms[room_code]["creator_id"]
    
    # Создаем данные пользователя
    user = UserData(user_id)
    user.game_state = GameState.PARTNER_FOUND
    user.room_code = room_code
    user.partner_id = creator_id
    active_users[user_id] = user
    
    # Обновляем данные создателя
    if creator_id in active_users:
        creator = active_users[creator_id]
        creator.game_state = GameState.PARTNER_FOUND
        creator.partner_id = user_id
        # Удаляем комнату из поиска
        if room_code in active_rooms:
            del active_rooms[room_code]
        
        # Уведомляем создателя
        await bot.send_message(
            creator_id,
            f"🎉 Партнер найден! {message.from_user.first_name} присоединился.\n\n"
            f"Теперь вы можете начать игру.",
            reply_markup=partner_found_keyboard(is_creator=True)
        )
    
    await message.answer(
        f"✅ Вы присоединились к комнате! Ожидайте начала игры от создателя.",
        reply_markup=partner_found_keyboard(is_creator=False)
    )

@router.callback_query(F.data == "start_game_session")
async def start_game(callback: CallbackQuery):
    """Начало игровой сессии (только для создателя комнаты)"""
    user_id = callback.from_user.id
    
    if user_id not in active_users:
        await callback.answer("❌ Ошибка: данные не найдены", show_alert=True)
        return
    
    user = active_users[user_id]
    
    if not user.partner_id:
        await callback.answer("❌ Ошибка: партнер не найден", show_alert=True)
        return
    
    # Определяем роли случайно
    user.role = PlayerRole.PERFORMER if random.random() > 0.5 else PlayerRole.WAITER
    user.game_state = GameState.IN_GAME
    
    # Обновляем партнера
    if user.partner_id in active_users:
        partner = active_users[user.partner_id]
        partner.role = PlayerRole.WAITER if user.role == PlayerRole.PERFORMER else PlayerRole.PERFORMER
        partner.game_state = GameState.IN_GAME
    
    # Удаляем комнату если ещё существует
    if user.room_code and user.room_code in active_rooms:
        del active_rooms[user.room_code]
    
    # Уведомляем обоих
    await callback.message.edit_text(
        "🎮 Игра началась!\n\n"
        f"Ваша роль: <b>{'Исполняющий' if user.role == PlayerRole.PERFORMER else 'Ожидающий'}</b>\n"
        f"Этап: Белая колода (Разговор и флирт)\n\n"
        f"<i>Правила ролей:</i>\n"
        f"• <b>Исполняющий</b> - выполняет задание\n"
        f"• <b>Ожидающий</b> - следит за выполнением",
        parse_mode="HTML"
    )
    
    await bot.send_message(
        user.partner_id,
        "🎮 Игра началась!\n\n"
        f"Ваша роль: <b>{'Исполняющий' if partner.role == PlayerRole.PERFORMER else 'Ожидающий'}</b>\n"
        f"Этап: Белая колода (Разговор и флирт)\n\n"
        f"<i>Правила ролей:</i>\n"
        f"• <b>Исполняющий</b> - выполняет задание\n"
        f"• <b>Ожидающий</b> - следит за выполнением",
        parse_mode="HTML"
    )
    
    # Раздаем первую карту
    await send_next_card(user_id)

async def send_next_card(user_id: int):
    """Отправка следующей карточки"""
    if user_id not in active_users:
        return
    
    user = active_users[user_id]
    
    if user.game_state != GameState.IN_GAME:
        return
    
    # Получаем карту
    card = get_random_card(user.current_stage)
    user.current_card = card
    
    # Отправляем карту в зависимости от роли
    if user.role == PlayerRole.PERFORMER:
        text = f"🎴 Ваше задание:\n\n{card['text']}"
        if card.get('dice_meaning'):
            text += f"\n\n🎲 Значение кубика: {card['dice_meaning']}"
        await bot.send_message(user_id, text, reply_markup=performer_keyboard(card))
        
        # Ожидающему отправляем только текст
        if user.partner_id and user.partner_id in active_users:
            partner = active_users[user.partner_id]
            await bot.send_message(
                user.partner_id,
                f"🎴 Задание партнера:\n\n{card['text']}",
                reply_markup=waiter_keyboard()
            )
    else:
        # Если ожидающий, ждем когда исполнитель получит карту
        pass

# ========== ОБРАБОТКА КАРТОЧЕК ==========
@router.callback_query(F.data == "skip_card")
async def skip_current_card(callback: CallbackQuery):
    """Пропуск карточки"""
    user_id = callback.from_user.id
    
    if user_id not in active_users:
        await callback.answer("❌ Ошибка: данные не найдены", show_alert=True)
        return
    
    user = active_users[user_id]
    
    if not user.current_card:
        await callback.answer("❌ Нет активной карточки", show_alert=True)
        return
    
    # Уведомляем партнера
    if user.partner_id and user.partner_id in active_users:
        await bot.send_message(
            user.partner_id,
            f"⏩ Партнер пропустил карточку:\n\n{user.current_card['text']}\n\nВаш ход!"
        )
    
    # Меняем роли
    await switch_roles(user_id)
    await callback.answer("Карточка пропущена ✅")

@router.callback_query(F.data == "task_done")
async def mark_task_done(callback: CallbackQuery):
    """Отметка выполнения задания (от ожидающего)"""
    user_id = callback.from_user.id
    
    if user_id not in active_users:
        await callback.answer("❌ Ошибка: данные не найдены", show_alert=True)
        return
    
    user = active_users[user_id]
    
    if user.role != PlayerRole.WAITER:
        await callback.answer("❌ Сейчас не ваш ход", show_alert=True)
        return
    
    # Меняем роли
    await switch_roles(user_id)
    await callback.answer("Задание выполнено ✅")

@router.callback_query(F.data == "start_timer")
async def start_card_timer(callback: CallbackQuery):
    """Запуск таймера для карточки"""
    user_id = callback.from_user.id
    
    if user_id not in active_users:
        await callback.answer("❌ Ошибка: данные не найдены", show_alert=True)
        return
    
    user = active_users[user_id]
    
    if not user.current_card:
        await callback.answer("❌ Нет активной карточки", show_alert=True)
        return
    
    # Парсим время из текста
    import re
    text = user.current_card['text']
    minutes = 5  # значение по умолчанию
    
    time_match = re.search(r'(\d+)\s*минут', text)
    if time_match:
        minutes = int(time_match.group(1))
    else:
        # Пробуем найти секунды
        sec_match = re.search(r'(\d+)\s*секунд', text)
        if sec_match:
            minutes = int(sec_match.group(1)) / 60
    
    total_seconds = int(minutes * 60)
    
    # Запускаем таймер
    if user_id in user_timers:
        user_timers[user_id].cancel()
    
    async def timer_task():
        try:
            msg = await bot.send_message(user_id, f"⏱️ Таймер запущен: {minutes} мин.")
            
            # Интервалы уведомлений
            intervals = []
            if total_seconds > 900:  # > 15 минут
                intervals = list(range(total_seconds, 0, -300))
            elif total_seconds > 120:  # > 2 минут
                intervals = list(range(total_seconds, 0, -60))
            elif total_seconds > 60:
                intervals = list(range(total_seconds, 0, -10))
            elif total_seconds > 20:
                intervals = list(range(total_seconds, 0, -5))
            else:
                intervals = list(range(total_seconds, 0, -1))
            
            for remaining in intervals[1:]:
                await asyncio.sleep(intervals[0] - remaining)
                if remaining > 60:
                    await bot.edit_message_text(
                        chat_id=user_id,
                        message_id=msg.message_id,
                        text=f"⏱️ Осталось: {remaining // 60} мин {remaining % 60} сек."
                    )
                else:
                    await bot.edit_message_text(
                        chat_id=user_id,
                        message_id=msg.message_id,
                        text=f"⏱️ Осталось: {remaining} сек."
                    )
            
            await asyncio.sleep(intervals[0])
            await bot.edit_message_text(
                chat_id=user_id,
                message_id=msg.message_id,
                text="⏰ Время вышло!"
            )
            
        except asyncio.CancelledError:
            await bot.edit_message_text(
                chat_id=user_id,
                message_id=msg.message_id,
                text="⏹️ Таймер остановлен"
            )
        except Exception as e:
            logger.error(f"Timer error: {e}")
    
    user_timers[user_id] = asyncio.create_task(timer_task())
    
    # Обновляем клавиатуру для добавления кнопки остановки
    kb = performer_keyboard(user.current_card)
    kb.inline_keyboard.append([InlineKeyboardButton(text="Остановить таймер ⏹️", callback_data="stop_timer")])
    
    await callback.message.edit_reply_markup(reply_markup=kb)
    await callback.answer(f"Таймер запущен на {minutes} минут")

@router.callback_query(F.data == "stop_timer")
async def stop_card_timer(callback: CallbackQuery):
    """Остановка таймера"""
    user_id = callback.from_user.id
    
    if user_id in user_timers:
        user_timers[user_id].cancel()
        del user_timers[user_id]
    
    if user_id in active_users and active_users[user_id].current_card:
        await callback.message.edit_reply_markup(
            reply_markup=performer_keyboard(active_users[user_id].current_card)
        )
    
    await callback.answer("Таймер остановлен")

@router.callback_query(F.data == "roll_dice")
async def roll_dice_handler(callback: CallbackQuery):
    """Бросок кубика"""
    dice_value = random.randint(1, 6)
    
    user_id = callback.from_user.id
    if user_id in active_users:
        user = active_users[user_id]
        if user.current_card and user.partner_id:
            # Отправляем результат партнеру
            await bot.send_message(
                user.partner_id,
                f"🎲 Партнер бросил кубик: выпало {dice_value}"
            )
    
    await callback.answer(f"🎲 Выпало: {dice_value}", show_alert=True)

@router.callback_query(F.data == "request_photo")
async def request_photo_handler(callback: CallbackQuery):
    """Запрос на отправку фото"""
    user_id = callback.from_user.id
    
    if user_id in active_users:
        active_users[user_id].waiting_for_photo = True
    
    await callback.message.answer(
        "📸 Отправьте фото в ответ на это сообщение. "
        "Оно будет переслано вашему партнеру."
    )
    await callback.answer()

@router.message(F.photo)
async def handle_photo_message(message: Message):
    """Обработка полученного фото"""
    user_id = message.from_user.id
    
    if user_id not in active_users:
        return
    
    user = active_users[user_id]
    
    if not user.waiting_for_photo or not user.partner_id:
        return
    
    user.waiting_for_photo = False
    
    # Пересылаем фото партнеру
    await bot.send_photo(
        user.partner_id,
        photo=message.photo[-1].file_id,
        caption="📸 Партнер отправил фото"
    )
    
    await message.answer("✅ Фото отправлено партнеру!")

# ========== УПРАВЛЕНИЕ ИГРОЙ ==========
@router.callback_query(F.data == "request_stop_game")
async def request_stop_game(callback: CallbackQuery):
    """Запрос на завершение игры"""
    user_id = callback.from_user.id
    
    if user_id not in active_users:
        await callback.answer("❌ Ошибка: данные не найдены", show_alert=True)
        return
    
    user = active_users[user_id]
    
    if not user.partner_id:
        await callback.answer("❌ Нет активного партнера", show_alert=True)
        return
    
    user.game_state = GameState.AWAITING_CONFIRMATION
    
    await callback.message.edit_text(
        "Вы уверены, что хотите завершить игру?",
        reply_markup=stop_game_confirmation_keyboard()
    )

@router.callback_query(F.data == "confirm_stop")
async def confirm_stop_game(callback: CallbackQuery):
    """Подтверждение завершения игры"""
    user_id = callback.from_user.id
    
    if user_id not in active_users:
        await callback.answer("❌ Ошибка: данные не найдены", show_alert=True)
        return
    
    user = active_users[user_id]
    
    # Уведомляем партнера если есть
    if user.partner_id:
        await bot.send_message(
            user.partner_id,
            "Партнер завершил игру. Возврат в главное меню.",
            reply_markup=main_menu_keyboard()
        )
        
        # Очищаем данные партнера
        if user.partner_id in active_users:
            if user.partner_id in user_timers:
                user_timers[user.partner_id].cancel()
                del user_timers[user.partner_id]
            del active_users[user.partner_id]
    
    # Очищаем свои данные
    if user_id in user_timers:
        user_timers[user_id].cancel()
        del user_timers[user_id]
    
    if user_id in active_users:
        del active_users[user_id]
    
    await callback.message.edit_text(
        "Игра завершена. Возврат в главное меню.",
        reply_markup=main_menu_keyboard()
    )

@router.callback_query(F.data == "postpone_stop")
async def postpone_stop_game(callback: CallbackQuery):
    """Предложение отложить завершение"""
    user_id = callback.from_user.id
    
    if user_id not in active_users:
        await callback.answer("❌ Ошибка: данные не найдены", show_alert=True)
        return
    
    user = active_users[user_id]
    
    if not user.partner_id:
        await callback.answer("❌ Нет активного партнера", show_alert=True)
        return
    
    await bot.send_message(
        user.partner_id,
        "🦉 Партнер предлагает продолжить позже с этого же места.\n\n"
        "Ваш ответ?",
        reply_markup=postpone_response_keyboard()
    )
    
    await callback.message.edit_text(
        "Запрос отправлен партнеру. Ожидайте ответа.",
        reply_markup=back_to_main_keyboard()
    )

@router.callback_query(F.data == "continue_game")
async def continue_after_postpone(callback: CallbackQuery):
    """Согласие продолжить игру"""
    user_id = callback.from_user.id
    
    if user_id not in active_users:
        await callback.answer("❌ Ошибка: данные не найдены", show_alert=True)
        return
    
    user = active_users[user_id]
    
    if not user.partner_id or user.partner_id not in active_users:
        await callback.answer("❌ Партнер не найден", show_alert=True)
        return
    
    partner = active_users[user.partner_id]
    user.game_state = GameState.IN_GAME
    partner.game_state = GameState.IN_GAME
    
    await bot.send_message(
        user.partner_id,
        "✅ Партнер согласился продолжить! Игра возобновляется."
    )
    
    await callback.message.edit_text(
        "✅ Игра продолжается!",
        reply_markup=waiter_keyboard() if user.role == PlayerRole.WAITER else performer_keyboard(user.current_card)
    )

@router.callback_query(F.data == "force_stop")
async def force_stop_game(callback: CallbackQuery):
    """Принудительное завершение после отложенного запроса"""
    user_id = callback.from_user.id
    
    if user_id not in active_users:
        await callback.answer("❌ Ошибка: данные не найдены", show_alert=True)
        return
    
    user = active_users[user_id]
    
    # Уведомляем партнера
    if user.partner_id:
        await bot.send_message(
            user.partner_id,
            "🦉 Игра завершена. Но когда-нибудь можно попробовать заново.",
            reply_markup=main_menu_keyboard()
        )
        
        # Очищаем данные партнера
        if user.partner_id in active_users:
            if user.partner_id in user_timers:
                user_timers[user.partner_id].cancel()
                del user_timers[user.partner_id]
            del active_users[user.partner_id]
    
    # Очищаем свои данные
    if user_id in user_timers:
        user_timers[user_id].cancel()
        del user_timers[user_id]
    
    if user_id in active_users:
        del active_users[user_id]
    
    await callback.message.edit_text(
        "🦉 Игра завершена. Возврат в главное меню.",
        reply_markup=main_menu_keyboard()
    )

async def switch_roles(user_id: int):
    """Смена ролей между игроками"""
    if user_id not in active_users:
        return
    
    user = active_users[user_id]
    
    if not user.partner_id or user.partner_id not in active_users:
        return
    
    partner = active_users[user.partner_id]
    
    # Меняем роли
    user.role, partner.role = partner.role, user.role
    user.current_card = None
    partner.current_card = None
    
    # Отправляем новую карту новому исполнителю
    new_performer_id = user_id if user.role == PlayerRole.PERFORMER else user.partner_id
    await send_next_card(new_performer_id)

# ========== ДОПОЛНИТЕЛЬНЫЕ ЭТАПЫ ==========
@router.message(Command("envelope"))
async def admin_start_envelope(message: Message):
    """Запуск благодарственной карты (команда для теста)"""
    user_id = message.from_user.id
    
    if user_id not in active_users:
        await message.answer("❌ Сначала начните игру", reply_markup=main_menu_keyboard())
        return
    
    user = active_users[user_id]
    
    if user.game_state != GameState.IN_GAME:
        await message.answer("❌ Сейчас не время для этого этапа")
        return
    
    await message.answer(
        "🦉 Благодарственная карта!\n\n"
        "Выберите конверт:",
        reply_markup=envelope_keyboard()
    )

@router.callback_query(F.data.startswith("envelope_"))
async def handle_envelope_choice(callback: CallbackQuery):
    """Обработка выбора конверта"""
    user_id = callback.from_user.id
    
    if user_id not in active_users:
        await callback.answer("❌ Ошибка: данные не найдены", show_alert=True)
        return
    
    user = active_users[user_id]
    choice = callback.data.split("_")[1]  # her или him
    
    user.envelope_choice = choice
    user.current_stage = GameStage.ENVELOPE
    
    await callback.message.edit_text(
        f"Вы выбрали конверт: {'Для неё 💝' if choice == 'her' else 'Для него 💙'}\n\n"
        f"Задание: Напишите благодарность партнеру за сегодняшний вечер.\n\n"
        f"Когда будете готовы, нажмите 'Выполнено'",
        reply_markup=envelope_done_keyboard()
    )

@router.callback_query(F.data == "envelope_done")
async def envelope_task_done(callback: CallbackQuery):
    """Завершение этапа с конвертами"""
    user_id = callback.from_user.id
    
    if user_id not in active_users:
        await callback.answer("❌ Ошибка: данные не найдены", show_alert=True)
        return
    
    user = active_users[user_id]
    
    if not user.partner_id or user.partner_id not in active_users:
        await callback.answer("❌ Партнер не найден", show_alert=True)
        return
    
    partner = active_users[user.partner_id]
    
    # Проверяем, оба ли завершили
    if partner.envelope_choice:
        # Оба завершили
        await bot.send_message(
            user_id, 
            "🎉 Игра завершена! Спасибо за игру! 🦉", 
            reply_markup=main_menu_keyboard()
        )
        await bot.send_message(
            user.partner_id, 
            "🎉 Игра завершена! Спасибо за игру! 🦉", 
            reply_markup=main_menu_keyboard()
        )
        
        # Очищаем данные
        for uid in [user_id, user.partner_id]:
            if uid in user_timers:
                user_timers[uid].cancel()
                del user_timers[uid]
            if uid in active_users:
                del active_users[uid]
    else:
        await callback.answer("⏳ Ждем завершения партнера", show_alert=True)

# ========== WEBHOOK НАСТРОЙКИ ==========
async def on_startup(bot: Bot):
    """Действия при запуске бота"""
    if WEBHOOK_URL:
        await bot.set_webhook(
            url=WEBHOOK_URL + WEBHOOK_PATH,
            drop_pending_updates=True
        )
        logger.info(f"Webhook установлен: {WEBHOOK_URL + WEBHOOK_PATH}")
    else:
        logger.info("Запуск в режиме polling")

async def on_shutdown(bot: Bot):
    """Действия при остановке бота"""
    logger.info("Остановка бота...")
    
    # Отменяем все таймеры
    for timer in user_timers.values():
        timer.cancel()
    
    if WEBHOOK_URL:
        await bot.delete_webhook()
    
    await bot.session.close()

# ========== ЗАПУСК ПРИЛОЖЕНИЯ ==========
def main():
    """Основная функция запуска"""
    # Регистрируем обработчики startup/shutdown
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)
    
    if WEBHOOK_URL:
        # Режим webhook для Render
        app = web.Application()
        webhook_requests_handler = SimpleRequestHandler(
            dispatcher=dp,
            bot=bot,
        )
        webhook_requests_handler.register(app, path=WEBHOOK_PATH)
        setup_application(app, dp, bot=bot)
        
        logger.info(f"Запуск webhook на порту {WEB_SERVER_PORT}")
        web.run_app(app, host=WEB_SERVER_HOST, port=WEB_SERVER_PORT)
    else:
        # Режим polling для локальной разработки
        logger.info("Запуск polling")
        dp.run_polling(bot)

if __name__ == "__main__":
    main()
