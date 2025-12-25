import os
import asyncio
import logging
import random
import string
import re
import threading
import uuid
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime
from enum import Enum
from typing import Dict, Optional, List, Set

from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, 
    InlineKeyboardButton
)
from aiogram.filters import Command
from aiogram.exceptions import TelegramRetryAfter, TelegramNetworkError, TelegramAPIError
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage

# ========== НАСТРОЙКА ЛОГИРОВАНИЯ ==========
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('bot.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

# ========== КОНФИГУРАЦИЯ ==========
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID")

if not BOT_TOKEN:
    logger.error("❌ ERROR: BOT_TOKEN environment variable is not set!")
    exit(1)

if ADMIN_ID:
    try:
        ADMIN_ID = int(ADMIN_ID)
    except ValueError:
        logger.warning(f"⚠️ ADMIN_ID должно быть числом, получено: {ADMIN_ID}")
        ADMIN_ID = None
else:
    logger.info("ℹ️ ADMIN_ID не установлен, админ-режим недоступен")
    ADMIN_ID = None

# Инициализация с хранилищем состояний
storage = MemoryStorage()
bot = Bot(token=BOT_TOKEN, parse_mode="HTML")
dp = Dispatcher(storage=storage)
router = Router()
dp.include_router(router)

# ========== HTTP-СЕРВЕР ДЛЯ RENDER ==========
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        response = "🦉 Бот Викитория работает"
        self.wfile.write(response.encode('utf-8'))
    
    def log_message(self, format, *args):
        logger.info(f"HTTP: {format % args}")

def run_http_server():
    """Запуск HTTP сервера в отдельном потоке"""
    try:
        port = int(os.getenv("PORT", 10000))
        server = HTTPServer(('0.0.0.0', port), HealthHandler)
        logger.info(f"✅ HTTP-сервер запущен на порту {port}")
        server.serve_forever()
    except Exception as e:
        logger.error(f"❌ Ошибка HTTP-сервера: {e}")

# Запускаем HTTP-сервер в отдельном потоке
http_thread = threading.Thread(target=run_http_server, daemon=True)
http_thread.start()

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

# Карточки
CARDS_DATA = {
    "white": [
        {"id": 1, "type": "question", "text": "Какая твоя самая бесполезная, но крутая суперспособность в быту?"},
        {"id": 2, "type": "action", "text": "Выбери любой предмет в этой комнате и продай его партнеру за 30 секунд, как самый дорогой телешоу-продавец."},
        {"id": 3, "type": "question", "text": "Если бы сегодняшний вечер был песней, то какой жанр? А если фильмом?"},
        {"id": 4, "type": "action", "text": "С завязанными глазами определи на вкус, чем тебя кормит партнер (2,3 продукта)."},
        {"id": 5, "type": "action", "text": "Стань зеркалом партнера на 1 минуту. Повторяй ВСЕ его/ее движения."},
        {"id": 6, "type": "question", "text": "В какой момент за последний месяц ты чувствовал(а) себя самым настоящим взрослым? А самым настоящим ребенком?"},
        {"id": 7, "type": "action", "text": "Фото в галерее. Назови партнеру: сверху или снизу и цифру от 1 до 3. Партнер открывает галерею в своем телефоне, находит фото по указанным координатам. Прокомментируй его."},
        {"id": 8, "type": "question", "text": "Опиши партнера так, как мог бы описать его вымышленный, но восхищенный им личный ассистент."},
        {"id": 9, "type": "question", "text": "Какая привычка партнера (жест, слово) тебя неожиданно умиляет или забавляет?"},
        {"id": 10, "type": "question", "text": "Как бы ты описал(а) идеальный «фирменный поцелуй» для пары на таком этапе отношений, как у вас?"},
        {"id": 11, "type": "action", "text": "Игра в контрасты. Расскажи партнеру два факта о себе: один правдивый, один ложный. Задача партнера — угадать, где правда."},
        {"id": 12, "type": "question", "text": "Какое случайное воспоминание из детства о незначительном, но очень приятном моменте (запах, звук, тактильное ощущение) всплывает у тебя в голове чаще всего и почему?"},
        {"id": 13, "type": "question", "text": "Если бы завтрашний день можно было посвятить только одному из пяти чувств (вкус, осязание, обоняние, слух, зрение), какое бы ты выбрал(а) и почему?"},
        {"id": 14, "type": "action", "text": "Поменяйтесь ролями на 5 минут (положение, занятия, действия)."}
    ],
    "yellow": [
        {"id": 1, "type": "action", "text": "Массаж с кубиком. Брось кубик (число от 1 до 6). 1 – Шея и плечи партнера, 2 – Стопы, 3 – Кисти рук, 4 – Голова, 5 – Спина (через одежду), 6 – Ты выбираешь зону. Массаж — 3 минуты."},
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
        {"id": 2, "type": "action", "text": "Дилема доверия (с кубиком). Брось кубик. Четное число: Ты получаещь полный контроль на 5 минут — веди партнера шепотом или прикосновениями. Нечетное: Ты передаешь этот контроль партнеру."},
        {"id": 3, "type": "action", "text": "Поцелуй-зеркало. Целуй партнера так, как будто пытаешься точно скопировать его ритм, силу и манеру. Затем поменяйтесь ролями — теперь партнер зеркалит тебя."},
        {"id": 4, "type": "action", "text": "Опиши или покажи жестом тот ритм и степень нежности/страсти, которые ты хочешь подарить партнеру сейчас. А затем — те, что хочешь получить."},
        {"id": 5, "type": "question", "text": "Слово-разрешение и слово-интрига. Назови коротко, что ты точно хочешь сейчас. И что тебе интересно попробовать. Партнер сделает то же самое."},
        {"id": 6, "type": "question", "text": "Какой внутренний барьер (мысль, сомнение, привычка) тебе сейчас сложнее всего отпустить, чтобы быть со мной здесь полностью? Или его нет?"},
        {"id": 7, "type": "question", "text": "Что из того, что я делаю (или не делаю) прямо сейчас, заставляет тебя чувствовать себя максимально видимым/ой и желанным/ой?"},
        {"id": 8, "type": "question", "text": "Если бы прямо сейчас у тебя была возможность одним лишь шепотом заставить мое тело сделать одно непроизвольное движение (вздрогнуть, выгнуться, замереть), что бы ты прошептал(а) и куда?"},
        {"id": 9, "type": "question", "text": "Есть ли что-то, что ты хочешь сообщить/рассказать/поделиться с партнером, но не находишь для этого подходящего времени?"},
        {"id": 10, "type": "action", "text": "5 минут на флирт незнакомцев. Разыграйте сцену знакомства и мгновенного влечения. Инициатива у того, кто вытянул карту."},
        {"id": 11, "type": "action", "text": "Температура (с кубиком). Брось кубик. Выпавшее число — количество поцелуев, которые нужно поставить на теле партнера, чередуя горячие (с дыханием) и холодные (едва касаясь губами) на свое усмотрение."},
        {"id": 12, "type": "action", "text": "Выбор в твоих руках. 5 минут. Молча протяни партнеру повязку для глаз. Этот жест передает ему/ей право решить: надеть на себя, надеть на тебя или отложить. Любое решение — начало следующего действия."},
        {"id": 13, "type": "action", "text": "Поза и время (с кубиком). Вытянувший карту загадывает позу для партнера. Партнер бросает кубик. Время в позе = (число на кубике / 2) с округлением вверх. Пример: 5 -> 3 минуты."},
        {"id": 14, "type": "action", "text": "Безусловное желание. 3 минуты. Вытянувший карту формулирует: «Я хочу, чтобы следующие 3 минуты ты...». Это становится правилом."},
        {"id": 15, "type": "action", "text": "Кубик чувств (с кубиком). Брось кубик. Исследуй выбранное интимное место партнера 1 минуту методом: 1-Губы/дыхание, 2-Пальцы, 3-Щеки/ресницы, 4-Поцелуи, 5-Тепло/холод, 6-Ты выбираешь метод, партнер — зону."}
    ]
}

# Хранение данных
active_rooms = {}
active_users = {}
admin_sessions = {}

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========
def generate_room_code() -> str:
    """Генерация кода комнаты"""
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))

def get_stage_name(stage: GameStage) -> str:
    """Получить название колоды"""
    return {
        GameStage.WHITE: "🤍 Белая колода (разговоры и флирт)",
        GameStage.YELLOW: "💛 Жёлтая колода (тактильные игры)",
        GameStage.RED: "❤️ Красная колода (интимная глубина)"
    }.get(stage, "Неизвестная колода")

def get_stage_emoji(stage: GameStage) -> str:
    """Получить эмодзи колоды"""
    return {
        GameStage.WHITE: "🤍",
        GameStage.YELLOW: "💛",
        GameStage.RED: "❤️"
    }.get(stage, "🎴")

def parse_timer_from_text(text: str) -> Optional[int]:
    """Извлечь время в секундах из текста задания"""
    text_lower = text.lower()
    
    # Ищем минуты
    minute_match = re.search(r'(\d+)\s*минут', text_lower)
    if minute_match:
        return int(minute_match.group(1)) * 60
    
    # Ищем секунды
    second_match = re.search(r'(\d+)\s*секунд', text_lower)
    if second_match:
        return int(second_match.group(1))
    
    return None

def has_photo_in_text(text: str) -> bool:
    """Проверить, требует ли задание фото"""
    photo_words = ['фото', 'галере', 'снимок', 'фотограф']
    return any(word in text.lower() for word in photo_words)

def has_dice_in_text(text: str) -> bool:
    """Проверить, требует ли задание кубик"""
    dice_words = ['кубик', 'брось', 'выпавшее число', 'число от 1 до 6']
    return any(word in text.lower() for word in dice_words)

# ========== КЛАСС ИГРОВОЙ СЕССИИ ==========
class GameSession:
    def __init__(self, room_code: str, creator_id: int):
        self.room_code = room_code
        self.creator_id = creator_id
        self.partner_id = None
        self.state = GameState.WAITING_PARTNER
        self.stage = GameStage.WHITE
        self.player_role = {}
        self.used_cards = {"white": set(), "yellow": set(), "red": set()}
        self.player_names = {}
        self.current_card = None
        self.current_performer = None
        self.creation_time = datetime.now()
        
        # Добавляем создателя
        self.add_player(creator_id, is_creator=True)
    
    def add_player(self, user_id: int, is_creator: bool = False):
        """Добавить игрока в комнату"""
        if is_creator:
            self.player_role[user_id] = PlayerRole.PERFORMER
        else:
            self.player_role[user_id] = PlayerRole.WAITER
            self.partner_id = user_id
            self.state = GameState.PARTNER_FOUND
    
    def get_available_cards(self) -> List[int]:
        """Получить список доступных карт в текущей колоде"""
        all_cards = [card["id"] for card in CARDS_DATA.get(self.stage.value, [])]
        used_cards = self.used_cards.get(self.stage.value, set())
        return [card_id for card_id in all_cards if card_id not in used_cards]
    
    def draw_card(self) -> Optional[Dict]:
        """Взять случайную карту из текущей колоды"""
        available_cards = self.get_available_cards()
        if not available_cards:
            return None
        
        card_id = random.choice(available_cards)
        self.used_cards[self.stage.value].add(card_id)
        
        # Находим карту по ID
        for card in CARDS_DATA.get(self.stage.value, []):
            if card["id"] == card_id:
                self.current_card = card
                return card
        
        return None
    
    def switch_roles(self):
        """Поменять роли игроков"""
        for user_id in self.player_role:
            current_role = self.player_role[user_id]
            self.player_role[user_id] = (
                PlayerRole.WAITER if current_role == PlayerRole.PERFORMER 
                else PlayerRole.PERFORMER
            )
    
    def get_opponent_id(self, user_id: int) -> Optional[int]:
        """Получить ID оппонента"""
        if user_id == self.creator_id:
            return self.partner_id
        elif user_id == self.partner_id:
            return self.creator_id
        return None
    
    def can_advance_stage(self) -> bool:
        """Можно ли перейти к следующей колоде"""
        return len(self.get_available_cards()) == 0
    
    def advance_stage(self) -> Optional[GameStage]:
        """Перейти к следующей колоде"""
        if self.stage == GameStage.WHITE:
            self.stage = GameStage.YELLOW
            return self.stage
        elif self.stage == GameStage.YELLOW:
            self.stage = GameStage.RED
            return self.stage
        return None
    
    def is_deck_empty(self) -> bool:
        """Пуста ли текущая колода"""
        return len(self.get_available_cards()) == 0

# ========== КЛАВИАТУРЫ ==========
def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Начать игру 🦉", callback_data="create_room")],
        [InlineKeyboardButton(text="Присоединиться к игре", callback_data="join_room")],
        [InlineKeyboardButton(text="Правила игры", callback_data="show_rules")]
    ])

def back_to_main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="В главное меню", callback_data="main_menu")]
    ])

def waiting_partner_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Отменить поиск", callback_data="cancel_search")],
        [InlineKeyboardButton(text="В главное меню", callback_data="main_menu")]
    ])

def partner_found_keyboard(is_creator: bool) -> InlineKeyboardMarkup:
    if is_creator:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Начать игру! 🎮", callback_data="start_game")],
            [InlineKeyboardButton(text="Отмена", callback_data="cancel_game")]
        ])
    else:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Ожидаю начала... ⏳", callback_data="wait")],
            [InlineKeyboardButton(text="Выйти", callback_data="cancel_game")]
        ])

def performer_keyboard(card: Dict) -> InlineKeyboardMarkup:
    """Клавиатура для исполняющего (БЕЗ кнопки 'Выполнил')"""
    buttons = []
    
    # Кнопка пропуска
    buttons.append([InlineKeyboardButton(text="Пропустить ➡️", callback_data="skip_card")])
    
    # Специальные кнопки в зависимости от задания
    if parse_timer_from_text(card["text"]) is not None:
        buttons.append([InlineKeyboardButton(text="Запустить таймер ⏱️", callback_data="start_timer")])
    
    if has_photo_in_text(card["text"]):
        buttons.append([InlineKeyboardButton(text="Отправить фото 📸", callback_data="send_photo")])
    
    if has_dice_in_text(card["text"]):
        buttons.append([InlineKeyboardButton(text="Бросить кубик 🎲", callback_data="roll_dice")])
    
    # Кнопка завершения игры
    buttons.append([InlineKeyboardButton(text="Завершить игру 🏁", callback_data="request_stop_game")])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def waiter_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура для ожидающего (только подтверждение выполнения)"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Выполнено ✅", callback_data="task_done")],
        [InlineKeyboardButton(text="Пропустить ➡️", callback_data="skip_card")],
        [InlineKeyboardButton(text="Завершить игру 🏁", callback_data="request_stop_game")]
    ])

def stop_game_confirmation_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Да, завершить 🏁", callback_data="confirm_stop")],
        [InlineKeyboardButton(text="Нет, продолжить ➡️", callback_data="continue_game")]
    ])

def next_deck_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Перейти дальше ➡️", callback_data="next_deck")],
        [InlineKeyboardButton(text="Завершить игру 🏁", callback_data="request_stop_game")]
    ])

# Админ-клавиатуры
def admin_panel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔧 Тест одиночной игры", callback_data="admin_solo_test")],
        [InlineKeyboardButton(text="📊 Статистика бота", callback_data="admin_stats")],
        [InlineKeyboardButton(text="🔄 Сбросить все игры", callback_data="admin_reset_all")],
        [InlineKeyboardButton(text="🚪 Выйти из админ-панели", callback_data="main_menu")]
    ])

def admin_deck_selection_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🤍 Белая колода", callback_data="admin_deck_white")],
        [InlineKeyboardButton(text="💛 Жёлтая колода", callback_data="admin_deck_yellow")],
        [InlineKeyboardButton(text="❤️ Красная колода", callback_data="admin_deck_red")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel")]
    ])

# ========== ОБРАБОТЧИКИ КОМАНД ==========
@router.message(Command("start"))
async def cmd_start(message: Message):
    """Команда /start"""
    await message.answer(
        "🦉 Добро пожаловать в Викиторию!\n\n"
        "Игра для двоих, которая поможет стать ближе через:\n"
        "• Разговоры и флирт 🤍\n"
        "• Тактильные игры 💛\n"
        "• Интимную глубина ❤️\n\n"
        "Выберите действие:",
        reply_markup=main_menu_keyboard()
    )

@router.message(Command("myid"))
async def cmd_myid(message: Message):
    """Показать ID пользователя"""
    user_id = message.from_user.id
    await message.answer(
        f"🆔 Ваш Telegram ID: <code>{user_id}</code>\n\n"
        "Скопируйте этот ID для настройки админ-режима в Render.",
        parse_mode="HTML"
    )

@router.message(Command("admin"))
async def cmd_admin(message: Message):
    """Админ-панель"""
    if ADMIN_ID and message.from_user.id == ADMIN_ID:
        await message.answer(
            "🛠️ <b>Админ-панель Викитории</b>\n\n"
            "Выберите действие:",
            reply_markup=admin_panel_keyboard()
        )
    else:
        await message.answer("❌ Команда не найдена")

# ========== ГЛАВНОЕ МЕНЮ ==========
@router.callback_query(F.data == "main_menu")
async def main_menu_handler(callback: CallbackQuery):
    await callback.message.edit_text(
        "🦉 Добро пожаловать в Викиторию!\n\n"
        "Выберите действие:",
        reply_markup=main_menu_keyboard()
    )

@router.callback_query(F.data == "show_rules")
async def show_rules_handler(callback: CallbackQuery):
    rules_text = (
        "📖 <b>Правила игры Викитория</b>\n\n"
        "🎴 <b>Как играть:</b>\n"
        "1. Создайте комнату или присоединитесь к существующей\n"
        "2. Представьтесь друг другу\n"
        "3. Начните игру с белой колоды 🤍\n"
        "4. По очереди выполняйте задания\n\n"
        "🎭 <b>Роли в каждом раунде:</b>\n"
        "• <b>Исполняющий</b> - получает задание\n"
        "• <b>Ожидающий</b> - подтверждает выполнение\n\n"
        "<i>Роли меняются после каждого задания</i>\n\n"
        "🤍💛❤️ <b>Колоды:</b>\n"
        "• Белая - разговоры и флирт\n"
        "• Жёлтая - тактильные игры\n"
        "• Красная - интимная глубина\n\n"
        "<i>Играйте в своём темпе, уважайте границы друг друга.</i>"
    )
    
    await callback.message.edit_text(
        rules_text,
        reply_markup=back_to_main_keyboard()
    )

# ========== СОЗДАНИЕ И ПОДКЛЮЧЕНИЕ К КОМНАТАМ ==========
@router.callback_query(F.data == "create_room")
async def create_room_handler(callback: CallbackQuery):
    user_id = callback.from_user.id
    
    # Генерируем уникальный код
    room_code = generate_room_code()
    
    # Создаем сессию
    game_session = GameSession(room_code, user_id)
    active_rooms[room_code] = game_session
    active_users[user_id] = room_code
    
    await callback.message.edit_text(
        f"🎮 <b>Комната создана!</b>\n\n"
        f"Код комнаты: <code>{room_code}</code>\n\n"
        f"Отправьте этот код партнеру.\n"
        f"Ждем присоединения...",
        reply_markup=waiting_partner_keyboard()
    )

@router.callback_query(F.data == "join_room")
async def join_room_handler(callback: CallbackQuery):
    user_id = callback.from_user.id
    active_users[user_id] = GameState.WAITING_CODE.value
    
    await callback.message.edit_text(
        "🔢 <b>Присоединиться к игре</b>\n\n"
        "Введите код комнаты (6 символов):",
        reply_markup=back_to_main_keyboard()
    )

@router.message(F.text)
async def handle_text_message(message: Message):
    user_id = message.from_user.id
    
    # Если пользователь вводит код комнаты
    if user_id in active_users and active_users[user_id] == GameState.WAITING_CODE.value:
        room_code = message.text.strip().upper()
        
        if len(room_code) != 6 or not room_code.isalnum():
            await message.answer(
                "❌ Неверный формат кода. Код должен содержать 6 букв или цифр.",
                reply_markup=back_to_main_keyboard()
            )
            return
        
        if room_code not in active_rooms:
            await message.answer(
                f"❌ Комната с кодом <code>{room_code}</code> не найдена.",
                reply_markup=back_to_main_keyboard()
            )
            return
        
        game_session = active_rooms[room_code]
        
        if game_session.partner_id is not None:
            await message.answer(
                "❌ В этой комнате уже есть два игрока.",
                reply_markup=back_to_main_keyboard()
            )
            return
        
        # Присоединяем игрока
        game_session.add_player(user_id)
        active_users[user_id] = room_code
        
        # Уведомляем создателя
        creator_id = game_session.creator_id
        await bot.send_message(
            creator_id,
            f"🎉 <b>Партнёр присоединился!</b>\n\n"
            f"Игрок @{message.from_user.username or 'без username'} в игре.\n\n"
            f"Можете начинать игру!",
            reply_markup=partner_found_keyboard(is_creator=True)
        )
        
        # Уведомляем присоединившегося
        await message.answer(
            f"✅ <b>Вы присоединились к комнате!</b>\n\n"
            f"Код комнаты: <code>{room_code}</code>\n\n"
            f"Ожидайте начала игры.",
            reply_markup=partner_found_keyboard(is_creator=False)
        )
    
    # Если игрок вводит свое имя
    elif user_id in active_users:
        room_code = active_users.get(user_id)
        if isinstance(room_code, str) and room_code in active_rooms:
            game_session = active_rooms[room_code]
            
            # Проверяем, что игра началась и игрок еще не представился
            if (game_session.state == GameState.IN_GAME and 
                user_id not in game_session.player_names):
                
                player_name = message.text.strip()[:50]
                game_session.player_names[user_id] = player_name
                
                await message.answer(f"✅ Отлично, {player_name}! Теперь дождитесь, когда партнёр представится.")
                
                # Проверяем, представились ли оба
                if len(game_session.player_names) == 2:
                    # Начинаем игру
                    for player_id in [game_session.creator_id, game_session.partner_id]:
                        opponent_id = game_session.get_opponent_id(player_id)
                        opponent_name = game_session.player_names.get(opponent_id, "партнёр")
                        player_role = game_session.player_role[player_id]
                        role_text = "исполняющий" if player_role == PlayerRole.PERFORMER else "ожидающий"
                        
                        await bot.send_message(
                            player_id,
                            f"🎮 <b>Игра начинается!</b>\n\n"
                            f"Вы играете с: <b>{opponent_name}</b>\n"
                            f"Ваша роль в этом раунде: <b>{role_text}</b>\n"
                            f"Колода: {get_stage_name(game_session.stage)}\n\n"
                            f"<i>Готовы?</i>"
                        )
                    
                    # Отправляем первую карту
                    await send_next_card(game_session)

# ========== ИГРОВАЯ ЛОГИКА ==========
async def send_next_card(game_session: GameSession):
    """Отправить следующую карту в игре"""
    
    # Проверяем, не пуста ли текущая колода
    if game_session.is_deck_empty():
        next_stage = game_session.advance_stage()
        if next_stage:
            # Предлагаем перейти к следующей колоде
            for player_id in [game_session.creator_id, game_session.partner_id]:
                await bot.send_message(
                    player_id,
                    f"🎴 <b>Колода закончилась!</b>\n\n"
                    f"Вы выполнили все задания в {get_stage_emoji(game_session.stage)} колоде.\n\n"
                    f"Переходим к {get_stage_name(game_session.stage)}?",
                    reply_markup=next_deck_keyboard()
                )
            return
        else:
            # Все колоды закончились
            for player_id in [game_session.creator_id, game_session.partner_id]:
                await bot.send_message(
                    player_id,
                    "🏁 <b>Игра завершена!</b>\n\n"
                    "Вы выполнили все задания во всех колодах!\n\n"
                    "Спасибо за игру! 🦉",
                    reply_markup=main_menu_keyboard()
                )
            
            # Очищаем данные
            cleanup_game(game_session.room_code)
            return
    
    # Берем новую карту
    card = game_session.draw_card()
    if not card:
        return
    
    # Определяем исполняющего
    for player_id, role in game_session.player_role.items():
        if role == PlayerRole.PERFORMER:
            game_session.current_performer = player_id
            opponent_id = game_session.get_opponent_id(player_id)
            
            # Отправляем задание исполняющему
            performer_name = game_session.player_names.get(player_id, "Исполняющий")
            card_text = f"🎴 <b>Задание для {performer_name}:</b>\n\n{card['text']}"
            
            # Добавляем таймер, если есть
            timer_seconds = parse_timer_from_text(card["text"])
            if timer_seconds:
                minutes = timer_seconds // 60
                seconds = timer_seconds % 60
                time_text = f"{minutes} мин" if minutes > 0 else f"{seconds} сек"
                card_text += f"\n\n⏱️ <i>Время на выполнение: {time_text}</i>"
            
            await bot.send_message(
                player_id,
                card_text,
                reply_markup=performer_keyboard(card)
            )
            
            # Отправляем ожидающему
            await bot.send_message(
                opponent_id,
                f"⏳ <b>Ожидание выполнения</b>\n\n"
                f"{performer_name} выполняет задание.\n\n"
                f"<i>Задание:</i> {card['text']}\n\n"
                f"Подтвердите выполнение, когда будет готово.",
                reply_markup=waiter_keyboard()
            )
            break

@router.callback_query(F.data == "start_game")
async def start_game_handler(callback: CallbackQuery):
    """Начало игры после создания комнаты"""
    user_id = callback.from_user.id
    
    if user_id not in active_users:
        await callback.answer("❌ Ваша сессия не найдена")
        return
    
    room_code = active_users[user_id]
    
    if room_code not in active_rooms:
        await callback.answer("❌ Комната не найдена")
        return
    
    game_session = active_rooms[room_code]
    
    if game_session.creator_id != user_id:
        await callback.answer("❌ Только создатель может начать игру")
        return
    
    if game_session.partner_id is None:
        await callback.answer("❌ Нужно дождаться партнера")
        return
    
    # Начинаем игру
    game_session.state = GameState.IN_GAME
    
    # Просим игроков представиться
    for player_id in [game_session.creator_id, game_session.partner_id]:
        await bot.send_message(
            player_id,
            "👋 <b>Давайте познакомимся!</b>\n\n"
            "Перед началом игры представьтесь друг другу.\n\n"
            "Напишите ваше имя или как к вам обращаться:"
        )
    
    await callback.message.edit_text(
        "✅ <b>Игра началась!</b>\n\n"
        "Попросите партнера представиться, затем начните выполнять задания."
    )

# ========== ОБРАБОТЧИКИ ИГРОВЫХ ДЕЙСТВИЙ ==========
@router.callback_query(F.data == "task_done")
async def task_done_handler(callback: CallbackQuery):
    """Ожидающий подтверждает выполнение"""
    user_id = callback.from_user.id
    
    if user_id not in active_users:
        await callback.answer("❌ Вы не в игре")
        return
    
    room_code = active_users[user_id]
    
    if room_code not in active_rooms:
        await callback.answer("❌ Игра не найдена")
        return
    
    game_session = active_rooms[room_code]
    
    # Проверяем, что пользователь - ожидающий
    if game_session.player_role.get(user_id) != PlayerRole.WAITER:
        await callback.answer("❌ Только ожидающий может подтвердить выполнение")
        return
    
    # Меняем роли
    game_session.switch_roles()
    
    # Уведомляем игроков
    performer_id = game_session.current_performer
    performer_name = game_session.player_names.get(performer_id, "Исполняющий")
    
    for player_id in [game_session.creator_id, game_session.partner_id]:
        await bot.send_message(
            player_id,
            f"✅ <b>Задание выполнено!</b>\n\n"
            f"{performer_name} успешно справился(ась) с заданием.\n\n"
            f"<i>Меняем роли...</i>"
        )
    
    # Отправляем следующую карту
    await asyncio.sleep(1)
    await send_next_card(game_session)
    
    await callback.answer("✅ Задание подтверждено!")

@router.callback_query(F.data == "skip_card")
async def skip_card_handler(callback: CallbackQuery):
    """Пропуск карты"""
    user_id = callback.from_user.id
    
    if user_id not in active_users:
        await callback.answer("❌ Вы не в игре")
        return
    
    room_code = active_users[user_id]
    
    if room_code not in active_rooms:
        await callback.answer("❌ Игра не найдена")
        return
    
    game_session = active_rooms[room_code]
    
    # Меняем роли
    game_session.switch_roles()
    
    # Уведомляем игроков
    for player_id in [game_session.creator_id, game_session.partner_id]:
        await bot.send_message(
            player_id,
            "➡️ <b>Карточка пропущена</b>\n\n"
            "Переходим к следующему заданию."
        )
    
    # Отправляем следующую карту
    await asyncio.sleep(1)
    await send_next_card(game_session)
    
    await callback.answer("Карточка пропущена")

@router.callback_query(F.data == "roll_dice")
async def roll_dice_handler(callback: CallbackQuery):
    """Бросок кубика"""
    user_id = callback.from_user.id
    
    if user_id not in active_users:
        await callback.answer("❌ Вы не в игре")
        return
    
    room_code = active_users[user_id]
    
    if room_code not in active_rooms:
        await callback.answer("❌ Игра не найдена")
        return
    
    game_session = active_rooms[room_code]
    
    # Проверяем, что пользователь - исполняющий
    if game_session.player_role.get(user_id) != PlayerRole.PERFORMER:
        await callback.answer("❌ Только исполняющий может бросить кубик")
        return
    
    # Бросаем кубик
    dice_value = random.randint(1, 6)
    dice_emoji = ["⚀", "⚁", "⚂", "⚃", "⚄", "⚅"][dice_value - 1]
    
    # Отправляем результат
    performer_name = game_session.player_names.get(user_id, "Исполняющий")
    
    for player_id in [game_session.creator_id, game_session.partner_id]:
        await bot.send_message(
            player_id,
            f"🎲 <b>Бросок кубика от {performer_name}:</b>\n\n"
            f"{dice_emoji} Выпало: <b>{dice_value}</b>"
        )
    
    await callback.answer(f"🎲 Выпало: {dice_value}")

@router.callback_query(F.data == "start_timer")
async def start_timer_handler(callback: CallbackQuery):
    """Запуск таймера"""
    user_id = callback.from_user.id
    
    if user_id not in active_users:
        await callback.answer("❌ Вы не в игре")
        return
    
    room_code = active_users[user_id]
    
    if room_code not in active_rooms:
        await callback.answer("❌ Игра не найдена")
        return
    
    game_session = active_rooms[room_code]
    
    # Проверяем, что пользователь - исполняющий
    if game_session.player_role.get(user_id) != PlayerRole.PERFORMER:
        await callback.answer("❌ Только исполняющий может запустить таймер")
        return
    
    # Получаем текущую карту
    card = game_session.current_card
    if not card:
        await callback.answer("❌ Карточка не найдена")
        return
    
    # Извлекаем время из текста
    timer_seconds = parse_timer_from_text(card["text"])
    if not timer_seconds:
        await callback.answer("❌ В этом задании нет таймера")
        return
    
    # Запускаем таймер
    minutes = timer_seconds // 60
    seconds = timer_seconds % 60
    time_text = f"{minutes} мин" if minutes > 0 else f"{seconds} сек"
    
    # Уведомляем об запуске
    performer_name = game_session.player_names.get(user_id, "Исполняющий")
    
    for player_id in [game_session.creator_id, game_session.partner_id]:
        await bot.send_message(
            player_id,
            f"⏱️ <b>Таймер запущен!</b>\n\n"
            f"{performer_name} начал(а) выполнение задания.\n"
            f"Время: {time_text}"
        )
    
    # Демо-таймер (5 секунд для теста)
    msg = await bot.send_message(
        user_id,
        f"⏱️ Отсчёт: 5 сек"
    )
    
    for i in range(5, 0, -1):
        await asyncio.sleep(1)
        try:
            await bot.edit_message_text(
                chat_id=user_id,
                message_id=msg.message_id,
                text=f"⏱️ Отсчёт: {i} сек"
            )
        except:
            break
    
    await bot.send_message(
        user_id,
        f"⏰ <b>Время вышло!</b>\n\n"
        f"Время на выполнение задания истекло."
    )
    
    await callback.answer(f"Таймер завершён")

@router.callback_query(F.data == "send_photo")
async def send_photo_handler(callback: CallbackQuery):
    """Отправка фото (симуляция)"""
    user_id = callback.from_user.id
    
    if user_id not in active_users:
        await callback.answer("❌ Вы не в игре")
        return
    
    room_code = active_users[user_id]
    
    if room_code not in active_rooms:
        await callback.answer("❌ Игра не найдена")
        return
    
    game_session = active_rooms[room_code]
    
    # Проверяем, что пользователь - исполняющий
    if game_session.player_role.get(user_id) != PlayerRole.PERFORMER:
        await callback.answer("❌ Только исполняющий может отправить фото")
        return
    
    # Симуляция отправки фото
    performer_name = game_session.player_names.get(user_id, "Исполняющий")
    opponent_id = game_session.get_opponent_id(user_id)
    
    await bot.send_message(
        user_id,
        "📸 <b>Симуляция отправки фото</b>\n\n"
        "В реальной игре вы бы отправили фото из галереи.\n\n"
        "<i>Тест пройден успешно! ✅</i>"
    )
    
    if opponent_id:
        await bot.send_message(
            opponent_id,
            f"📸 <b>{performer_name} отправил(а) фото</b>\n\n"
            f"В реальной игре вы бы увидели фото."
        )
    
    await callback.answer("Фото отправлено (симуляция)")

@router.callback_query(F.data == "next_deck")
async def next_deck_handler(callback: CallbackQuery):
    """Переход к следующей колоде"""
    user_id = callback.from_user.id
    
    if user_id not in active_users:
        await callback.answer("❌ Вы не в игре")
        return
    
    room_code = active_users[user_id]
    
    if room_code not in active_rooms:
        await callback.answer("❌ Игра не найдена")
        return
    
    game_session = active_rooms[room_code]
    
    # Переходим к следующей колоде
    next_stage = game_session.advance_stage()
    if not next_stage:
        await callback.answer("❌ Нет следующей колоды")
        return
    
    # Уведомляем игроков
    for player_id in [game_session.creator_id, game_session.partner_id]:
        await bot.send_message(
            player_id,
            f"🔄 <b>Переход к новой колоде!</b>\n\n"
            f"Теперь играем с {get_stage_name(game_session.stage)}\n\n"
            f"<i>Продолжаем игру...</i>"
        )
    
    # Отправляем первую карту из новой колоды
    await asyncio.sleep(1)
    await send_next_card(game_session)
    
    await callback.answer("Перешли к следующей колоде")

@router.callback_query(F.data == "request_stop_game")
async def request_stop_game_handler(callback: CallbackQuery):
    """Запрос на завершение игры"""
    user_id = callback.from_user.id
    
    if user_id not in active_users:
        await callback.answer("❌ Вы не в игре")
        return
    
    room_code = active_users[user_id]
    
    if room_code not in active_rooms:
        await callback.answer("❌ Игра не найдена")
        return
    
    game_session = active_rooms[room_code]
    opponent_id = game_session.get_opponent_id(user_id)
    
    if opponent_id:
        await bot.send_message(
            opponent_id,
            "🏁 <b>Партнёр хочет завершить игру</b>\n\n"
            "Вы согласны завершить игру?",
            reply_markup=stop_game_confirmation_keyboard()
        )
    
    await callback.message.answer(
        "⏳ <b>Запрос отправлен партнёру</b>\n\n"
        "Ждём подтверждения..."
    )
    
    await callback.answer()

@router.callback_query(F.data.in_(["confirm_stop", "continue_game"]))
async def stop_game_confirmation_handler(callback: CallbackQuery):
    """Подтверждение завершения игры"""
    user_id = callback.from_user.id
    
    if user_id not in active_users:
        await callback.answer("❌ Вы не в игре")
        return
    
    room_code = active_users[user_id]
    
    if room_code not in active_rooms:
        await callback.answer("❌ Игра не найдена")
        return
    
    game_session = active_rooms[room_code]
    opponent_id = game_session.get_opponent_id(user_id)
    
    if callback.data == "confirm_stop":
        # Завершаем игру
        for player_id in [game_session.creator_id, game_session.partner_id]:
            await bot.send_message(
                player_id,
                "🏁 <b>Игра завершена!</b>\n\n"
                "Спасибо за игру! 🦉",
                reply_markup=main_menu_keyboard()
            )
        
        # Очищаем данные
        cleanup_game(room_code)
    
    else:  # continue_game
        # Продолжаем игру
        await bot.send_message(
            opponent_id,
            "✅ <b>Партнёр хочет продолжить игру</b>\n\n"
            "Продолжаем выполнение заданий!"
        )
    
    await callback.answer()

def cleanup_game(room_code: str):
    """Очистка данных игры"""
    if room_code in active_rooms:
        game_session = active_rooms[room_code]
        
        # Удаляем пользователей
        for player_id in [game_session.creator_id, game_session.partner_id]:
            if player_id and player_id in active_users:
                del active_users[player_id]
        
        # Удаляем комнату
        del active_rooms[room_code]

# ========== АДМИН-РЕЖИМ ==========
@router.callback_query(F.data == "admin_panel")
async def admin_panel_handler(callback: CallbackQuery):
    if ADMIN_ID and callback.from_user.id == ADMIN_ID:
        await callback.message.edit_text(
            "🛠️ <b>Админ-панель Викитории</b>\n\n"
            "Выберите действие:",
            reply_markup=admin_panel_keyboard()
        )
    else:
        await callback.answer("❌ Доступ запрещён")

@router.callback_query(F.data == "admin_solo_test")
async def admin_solo_test_handler(callback: CallbackQuery):
    if ADMIN_ID and callback.from_user.id == ADMIN_ID:
        await callback.message.edit_text(
            "🎮 <b>Тест одиночной игры</b>\n\n"
            "Выберите колоду для тестирования:",
            reply_markup=admin_deck_selection_keyboard()
        )
    else:
        await callback.answer("❌ Доступ запрещён")

@router.callback_query(F.data.startswith("admin_deck_"))
async def admin_select_deck_handler(callback: CallbackQuery):
    if ADMIN_ID and callback.from_user.id == ADMIN_ID:
        admin_id = callback.from_user.id
        action = callback.data
        
        # Определяем выбранную колоду
        if "white" in action:
            deck = GameStage.WHITE
            deck_name = "Белая колода 🤍"
        elif "yellow" in action:
            deck = GameStage.YELLOW
            deck_name = "Жёлтая колода 💛"
        elif "red" in action:
            deck = GameStage.RED
            deck_name = "Красная колода ❤️"
        else:
            await callback.answer("❌ Неизвестная колода")
            return
        
        # Создаем админ-сессию
        session_id = str(uuid.uuid4())[:8]
        
        admin_sessions[admin_id] = {
            "session_id": session_id,
            "stage": deck.value,
            "stage_name": deck_name,
            "current_role": PlayerRole.PERFORMER.value,
            "used_cards": set(),
            "current_card": None,
            "test_mode": True,
            "created_at": datetime.now().isoformat()
        }
        
        await callback.message.edit_text(
            f"🎮 <b>Тест начат!</b>\n\n"
            f"Колода: {deck_name}\n"
            f"Вы в роли: <b>Исполняющий</b>\n\n"
            f"<i>Тестируйте все функции игры:</i>\n"
            f"• Таймеры ⏱️\n"
            f"• Кубик 🎲\n"
            f"• Фото 📸 (симуляция)\n\n"
            f"<b>Поехали!</b>"
        )
        
        # Отправляем первую карту
        await send_admin_card_test(admin_id)
    else:
        await callback.answer("❌ Доступ запрещён")

async def send_admin_card_test(admin_id: int):
    """Отправить карту в админ-режиме тестирования"""
    if admin_id not in admin_sessions:
        return
    
    session = admin_sessions[admin_id]
    stage = GameStage(session["stage"])
    
    # Выбираем случайную карту
    available_cards = CARDS_DATA.get(stage.value, [])
    if not available_cards:
        await bot.send_message(admin_id, "❌ В этой колоде нет карт")
        return
    
    card = random.choice(available_cards)
    session["current_card"] = card
    
    # Отправляем карту
    card_text = f"🎴 <b>Задание (исполняющий):</b>\n\n{card['text']}"
    
    # Добавляем информацию о времени
    timer_seconds = parse_timer_from_text(card["text"])
    if timer_seconds:
        minutes = timer_seconds // 60
        seconds = timer_seconds % 60
        time_text = f"{minutes} мин" if minutes > 0 else f"{seconds} сек"
        card_text += f"\n\n⏱️ <i>Время на выполнение: {time_text}</i>"
    
    await bot.send_message(
        admin_id,
        card_text,
        reply_markup=performer_keyboard(card)
    )
    
    # Отправляем уведомление "ожидающему"
    await bot.send_message(
        admin_id,
        f"👤 <b>Виртуальный партнёр (ожидающий):</b>\n\n"
        f"Вижу ваше задание.\n"
        f"Жду выполнения..."
    )

@router.callback_query(F.data.in_(["task_done", "skip_card", "roll_dice", "start_timer", "send_photo", "request_stop_game"]))
async def admin_game_action_handler(callback: CallbackQuery):
    """Обработчик игровых действий в админ-режиме"""
    user_id = callback.from_user.id
    
    if user_id in admin_sessions:
        session = admin_sessions[user_id]
        action = callback.data
        
        try:
            if action == "task_done":
                # В админ-режиме task_done доступен всегда
                await callback.answer("✅ Задание подтверждено!")
                
                # Меняем роль
                current_role = session["current_role"]
                new_role = (
                    PlayerRole.WAITER.value 
                    if current_role == PlayerRole.PERFORMER.value 
                    else PlayerRole.PERFORMER.value
                )
                session["current_role"] = new_role
                
                role_name = "ожидающий" if new_role == PlayerRole.WAITER.value else "исполняющий"
                
                await bot.send_message(
                    user_id,
                    f"🔄 <b>Смена ролей!</b>\n\n"
                    f"Теперь вы: <b>{role_name}</b>\n\n"
                    f"<i>Продолжаем тест...</i>"
                )
                
                # Отправляем новую карту
                await asyncio.sleep(1)
                await send_admin_card_test(user_id)
            
            elif action == "skip_card":
                await callback.answer("Карточка пропущена")
                
                # Меняем роль
                current_role = session["current_role"]
                new_role = (
                    PlayerRole.WAITER.value 
                    if current_role == PlayerRole.PERFORMER.value 
                    else PlayerRole.PERFORMER.value
                )
                session["current_role"] = new_role
                
                await bot.send_message(
                    user_id,
                    "➡️ <b>Карточка пропущена</b>\n\n"
                    "Переходим к следующему заданию."
                )
                
                await asyncio.sleep(1)
                await send_admin_card_test(user_id)
            
            elif action == "roll_dice":
                dice_value = random.randint(1, 6)
                dice_emoji = ["⚀", "⚁", "⚂", "⚃", "⚄", "⚅"][dice_value - 1]
                
                await bot.send_message(
                    user_id,
                    f"🎲 <b>Результат броска:</b>\n\n"
                    f"{dice_emoji} Выпало: <b>{dice_value}</b>"
                )
                
                await callback.answer(f"🎲 Выпало: {dice_value}")
            
            elif action == "start_timer":
                card = session.get("current_card")
                if not card:
                    await callback.answer("❌ Карточка не найдена")
                    return
                
                timer_seconds = parse_timer_from_text(card["text"])
                if not timer_seconds:
                    await callback.answer("❌ В этом задании нет таймера")
                    return
                
                minutes = timer_seconds // 60
                seconds = timer_seconds % 60
                time_text = f"{minutes} мин" if minutes > 0 else f"{seconds} сек"
                
                await bot.send_message(
                    user_id,
                    f"⏱️ <b>Таймер запущен!</b>\n\n"
                    f"Время: {time_text}"
                )
                
                # Демо-таймер (5 секунд)
                msg = await bot.send_message(user_id, f"⏱️ Отсчёт: 5 сек")
                
                for i in range(5, 0, -1):
                    await asyncio.sleep(1)
                    try:
                        await bot.edit_message_text(
                            chat_id=user_id,
                            message_id=msg.message_id,
                            text=f"⏱️ Отсчёт: {i} сек"
                        )
                    except:
                        break
                
                await bot.send_message(
                    user_id,
                    f"⏰ <b>Время вышло!</b>\n\n"
                    f"Время на выполнение задания истекло."
                )
                
                await callback.answer(f"Таймер завершён")
            
            elif action == "send_photo":
                await bot.send_message(
                    user_id,
                    "📸 <b>Симуляция отправки фото</b>\n\n"
                    "В реальной игре вы бы отправили фото из галереи.\n\n"
                    "<i>Тест пройден успешно! ✅</i>"
                )
                
                await bot.send_message(
                    user_id,
                    "👤 <b>Виртуальный партнёр:</b>\n\n"
                    "Получил ваше фото! 📸"
                )
                
                await callback.answer("Фото отправлено (симуляция)")
            
            elif action == "request_stop_game":
                # В админ-режиме сразу завершаем
                del admin_sessions[user_id]
                
                await callback.message.edit_text(
                    "🏁 <b>Тест завершён!</b>\n\n"
                    "Возвращаемся в админ-панель..."
                )
                
                await callback.message.answer(
                    "🛠️ <b>Админ-панель Викитории</b>\n\n"
                    "Выберите действие:",
                    reply_markup=admin_panel_keyboard()
                )
                
                await callback.answer()
        
        except Exception as e:
            logger.error(f"Ошибка в админ-режиме: {e}")
            await callback.answer("❌ Ошибка при обработке")
    else:
        await callback.answer("❌ Не в админ-режиме")

@router.callback_query(F.data == "admin_stats")
async def admin_stats_handler(callback: CallbackQuery):
    if ADMIN_ID and callback.from_user.id == ADMIN_ID:
        active_users_count = len(active_users)
        active_rooms_count = len(active_rooms)
        admin_sessions_count = len(admin_sessions)
        
        # Статистика по колодам
        deck_stats = []
        for stage_name, cards in CARDS_DATA.items():
            stage_display = {
                "white": "🤍 Белая",
                "yellow": "💛 Жёлтая", 
                "red": "❤️ Красная"
            }.get(stage_name, stage_name)
            deck_stats.append(f"• {stage_display}: {len(cards)} карт")
        
        stats_text = (
            "📊 <b>Статистика бота Викитория</b>\n\n"
            f"• Активных пользователей: {active_users_count}\n"
            f"• Активных комнат: {active_rooms_count}\n"
            f"• Админ-сессий: {admin_sessions_count}\n\n"
            "<b>Колоды:</b>\n" + "\n".join(deck_stats) + "\n\n"
            "<i>Данные хранятся в памяти</i>"
        )
        
        await callback.message.edit_text(
            stats_text,
            reply_markup=admin_panel_keyboard()
        )
    else:
        await callback.answer("❌ Доступ запрещён")

@router.callback_query(F.data == "admin_reset_all")
async def admin_reset_all_handler(callback: CallbackQuery):
    if ADMIN_ID and callback.from_user.id == ADMIN_ID:
        # Очищаем все данные
        active_users.clear()
        active_rooms.clear()
        admin_sessions.clear()
        
        await callback.message.edit_text(
            "🔄 <b>Все данные сброшены!</b>\n\n"
            "• Активные игры очищены\n"
            "• Комнаты удалены\n"
            "• Админ-сессии завершены\n\n"
            "<i>Бот готов к работе</i>",
            reply_markup=admin_panel_keyboard()
        )
    else:
        await callback.answer("❌ Доступ запрещён")

# ========== ОБРАБОТКА ОШИБОК ==========
@router.errors()
async def error_handler(event, **kwargs):
    """Обработчик ошибок"""
    logger.error(f"Ошибка в боте: {event.exception}")
    
    try:
        # Пытаемся уведомить администратора об ошибке
        if ADMIN_ID:
            await bot.send_message(
                ADMIN_ID,
                f"⚠️ <b>Ошибка в боте:</b>\n\n"
                f"{type(event.exception).__name__}: {str(event.exception)[:200]}",
                parse_mode="HTML"
            )
    except:
        pass

# ========== ЗАПУСК БОТА С ПЕРЕЗАПУСКОМ ==========
async def run_bot():
    """Запуск бота с обработкой перезапусков"""
    max_retries = 10
    retry_delay = 5
    
    for retry in range(max_retries):
        try:
            logger.info(f"🚀 Попытка запуска бота #{retry + 1}")
            
            bot_info = await bot.get_me()
            logger.info(f"🤖 Бот: @{bot_info.username} (ID: {bot_info.id})")
            
            if ADMIN_ID:
                logger.info(f"👑 Админ ID: {ADMIN_ID}")
            
            # Запускаем polling
            await dp.start_polling(bot)
            
        except TelegramRetryAfter as e:
            logger.warning(f"⚠️ Лимит запросов. Ждем {e.retry_after} секунд...")
            await asyncio.sleep(e.retry_after)
            
        except (TelegramNetworkError, ConnectionError) as e:
            logger.error(f"❌ Сетевая ошибка: {e}")
            if retry < max_retries - 1:
                logger.info(f"⏳ Перезапуск через {retry_delay} секунд...")
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, 60)  # Экспоненциальная задержка
            else:
                logger.error("❌ Достигнуто максимальное количество попыток")
                raise
            
        except TelegramAPIError as e:
            logger.error(f"❌ Ошибка API Telegram: {e}")
            raise
            
        except Exception as e:
            logger.error(f"❌ Неожиданная ошибка: {e}")
            if retry < max_retries - 1:
                logger.info(f"⏳ Перезапуск через {retry_delay} секунд...")
                await asyncio.sleep(retry_delay)
            else:
                logger.error("❌ Достигнуто максимальное количество попыток")
                raise

async def main():
    """Основная функция запуска"""
    logger.info("=" * 60)
    logger.info("🚀 ЗАПУСК БОТА 'ВИКИТОРИЯ'")
    logger.info("=" * 60)
    
    # Статистика карт
    total_cards = sum(len(cards) for cards in CARDS_DATA.values())
    logger.info(f"📊 Карты: {total_cards} ({len(CARDS_DATA['white'])}🤍/{len(CARDS_DATA['yellow'])}💛/{len(CARDS_DATA['red'])}❤️)")
    
    try:
        await run_bot()
    except KeyboardInterrupt:
        logger.info("🛑 Бот остановлен пользователем")
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}")
        raise
    finally:
        logger.info("👋 Завершение работы бота")

if __name__ == "__main__":
    # Запускаем бота с обработкой ошибок
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("🛑 Бот остановлен")
    except Exception as e:
        logger.error(f"❌ Фатальная ошибка: {e}")
