import os
import asyncio
import logging
import random
import string
import re
import threading
import uuid
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
        pass

def run_http_server():
    try:
        port = int(os.getenv("PORT", 10000))
        server = HTTPServer(('0.0.0.0', port), HealthHandler)
        logger.info(f"✅ HTTP-сервер запущен на порту {port}")
        server.serve_forever()
    except Exception as e:
        logger.error(f"❌ Ошибка HTTP-сервера: {e}")

http_thread = threading.Thread(target=run_http_server, daemon=True)
http_thread.start()

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
        {"id": 4, "type": "action", "text": "Опиши или покажи жестом тот ритм и степень неенности/страсти, которые ты хочешь подарить партнеру сейчас. А затем — те, что хочешь получить."},
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
        {"id": 15, "type": "action", "text": "Кубик чувств (с кубик). Брось кубик. Исследуй выбранное интимное место партнера 1 минуту методом: 1-Губы/дыхание, 2-Пальцы, 3-Щеки/ресницы, 4-Поцелуи, 5-Тепло/холод, 6-Ты выбираешь метод, партнер — зону."}
    ]
}

# ========== ГЛОБАЛЬНЫЕ ХРАНИЛИЩА ==========
active_rooms = {}  # room_code -> GameSession
active_users = {}  # user_id -> room_code or GameState.WAITING_CODE.value
active_timers = {}  # user_id -> timer_task
admin_test_rooms = {}  # user_id -> room_code

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========
def generate_room_code() -> str:
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))

def get_stage_name(stage: GameStage) -> str:
    names = {
        GameStage.WHITE: "🤍 Белая колода (разговоры и флирт)",
        GameStage.YELLOW: "💛 Жёлтая колода (тактильные игры)",
        GameStage.RED: "❤️ Красная колода (интимная глубина)"
    }
    return names.get(stage, "Неизвестная колода")

def get_stage_emoji(stage: GameStage) -> str:
    emojis = {
        GameStage.WHITE: "🤍",
        GameStage.YELLOW: "💛",
        GameStage.RED: "❤️"
    }
    return emojis.get(stage, "🎴")

def parse_timer_from_text(text: str) -> Optional[int]:
    text_lower = text.lower()
    
    minute_match = re.search(r'(\d+)\s*минут', text_lower)
    if minute_match:
        return int(minute_match.group(1)) * 60
    
    second_match = re.search(r'(\d+)\s*секунд', text_lower)
    if second_match:
        return int(second_match.group(1))
    
    return None

def has_photo_in_text(text: str) -> bool:
    photo_words = ['фото', 'галере', 'снимок', 'фотограф']
    return any(word in text.lower() for word in photo_words)

def has_dice_in_text(text: str) -> bool:
    dice_words = ['кубик', 'брось', 'выпавшее число', 'число от 1 до 6']
    return any(word in text.lower() for word in dice_words)

# ========== КЛАСС ИГРОВОЙ СЕССИИ ==========
class GameSession:
    def __init__(self, room_code: str, creator_id: int, is_admin_test: bool = False):
        self.room_code = room_code
        self.creator_id = creator_id
        self.partner_id = None
        self.state = GameState.WAITING_PARTNER
        self.stage = GameStage.WHITE
        self.player_role = {}
        self.used_cards = {"white": set(), "yellow": set(), "red": set()}
        self.player_names = {}
        self.current_card = None
        self.current_card_id = None
        self.current_performer = None
        self.creation_time = datetime.now()
        self.is_admin_test = is_admin_test
        
        logger.info(f"🆕 Создана игровая сессия: {room_code}, админ-тест: {is_admin_test}, создатель: {creator_id}")
        
        # В админ-тесте сразу добавляем создателя
        self.add_player(creator_id, is_creator=True)
        
        if is_admin_test:
            # В админ-тесте у нас один игрок
            self.partner_id = creator_id
            self.state = GameState.PARTNER_FOUND
            logger.info(f"✅ Админ-тест настроен: комната {room_code}")
    
    def add_player(self, user_id: int, is_creator: bool = False):
        if is_creator:
            self.player_role[user_id] = PlayerRole.PERFORMER
            logger.info(f"👤 Добавлен создатель {user_id} как исполняющий")
        elif not self.is_admin_test:
            self.player_role[user_id] = PlayerRole.WAITER
            self.partner_id = user_id
            self.state = GameState.PARTNER_FOUND
            logger.info(f"👤 Добавлен партнер {user_id} как ожидающий")
    
    def get_available_cards(self) -> List[int]:
        all_cards = [card["id"] for card in CARDS_DATA.get(self.stage.value, [])]
        used_cards = self.used_cards.get(self.stage.value, set())
        available = [card_id for card_id in all_cards if card_id not in used_cards]
        logger.debug(f"Доступные карты в колоде {self.stage.value}: {len(available)} из {len(all_cards)}")
        return available
    
    def draw_card(self) -> Optional[Dict]:
        available_cards = self.get_available_cards()
        if not available_cards:
            logger.warning(f"❌ Нет доступных карт в колоде {self.stage.value}")
            return None
        
        card_id = random.choice(available_cards)
        self.used_cards[self.stage.value].add(card_id)
        
        for card in CARDS_DATA.get(self.stage.value, []):
            if card["id"] == card_id:
                self.current_card = card
                self.current_card_id = str(uuid.uuid4())[:8]
                logger.info(f"🎴 Выбрана карта {card_id} из колоде {self.stage.value}")
                return card
        
        logger.error(f"❌ Карта {card_id} не найдена в колоде {self.stage.value}")
        return None
    
    def switch_roles(self):
        # В админ-тесте не меняем роли - у админа всегда обе роли доступны
        if not self.is_admin_test:
            for user_id in self.player_role:
                current_role = self.player_role[user_id]
                self.player_role[user_id] = (
                    PlayerRole.WAITER if current_role == PlayerRole.PERFORMER 
                    else PlayerRole.PERFORMER
                )
            logger.info(f"🔄 Роли изменены")
    
    def get_opponent_id(self, user_id: int) -> Optional[int]:
        if user_id == self.creator_id:
            return self.partner_id
        elif user_id == self.partner_id:
            return self.creator_id
        return None
    
    def can_advance_stage(self) -> bool:
        return len(self.get_available_cards()) == 0
    
    def advance_stage(self) -> Optional[GameStage]:
        if self.stage == GameStage.WHITE:
            self.stage = GameStage.YELLOW
            logger.info(f"🔄 Переход к жёлтой колоде")
            return self.stage
        elif self.stage == GameStage.YELLOW:
            self.stage = GameStage.RED
            logger.info(f"🔄 Переход к красной колоде")
            return self.stage
        return None

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

def performer_keyboard(card: Dict, card_id: str) -> InlineKeyboardMarkup:
    buttons = []
    
    buttons.append([InlineKeyboardButton(text="Пропустить ➡️", callback_data=f"skip_card:{card_id}")])
    
    timer_seconds = parse_timer_from_text(card["text"])
    if timer_seconds is not None:
        buttons.append([InlineKeyboardButton(text="Запустить таймер ⏱️", callback_data=f"start_timer:{card_id}")])
    
    if has_photo_in_text(card["text"]):
        buttons.append([InlineKeyboardButton(text="Отправить фото 📸", callback_data=f"send_photo:{card_id}")])
    
    if has_dice_in_text(card["text"]):
        buttons.append([InlineKeyboardButton(text="Бросить кубик 🎲", callback_data=f"roll_dice:{card_id}")])
    
    buttons.append([InlineKeyboardButton(text="Завершить игру 🏁", callback_data="request_stop_game")])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def waiter_keyboard(card_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Выполнено ✅", callback_data=f"task_done:{card_id}")],
        [InlineKeyboardButton(text="Пропустить ➡️", callback_data=f"skip_card:{card_id}")],
        [InlineKeyboardButton(text="Завершить игру 🏁", callback_data="request_stop_game")]
    ])

def timer_keyboard(card_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏸️ Пауза", callback_data=f"pause_timer:{card_id}")],
        [InlineKeyboardButton(text="⏹️ Остановить", callback_data=f"stop_timer:{card_id}")],
        [InlineKeyboardButton(text="↩️ Назад", callback_data=f"back_to_card:{card_id}")]
    ])

def stop_game_confirmation_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Ну куда уж деваться 😔", callback_data="confirm_stop")],
        [InlineKeyboardButton(text="Да ладно, позже продолжим 😊", callback_data="continue_game")]
    ])

def postpone_response_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Ну ок, снизойду 🙄", callback_data="continue_game")],
        [InlineKeyboardButton(text="Завершить 🚫", callback_data="force_stop")]
    ])

def next_deck_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Перейти дальше ➡️", callback_data="next_deck")],
        [InlineKeyboardButton(text="Завершить игру 🏁", callback_data="request_stop_game")]
    ])

def admin_panel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔧 Начать тест игры", callback_data="admin_start_test")],
        [InlineKeyboardButton(text="📊 Статистика бота", callback_data="admin_stats")],
        [InlineKeyboardButton(text="🔄 Сбросить все игры", callback_data="admin_reset_all")],
        [InlineKeyboardButton(text="🚪 Выйти из админ-панели", callback_data="main_menu")]
    ])

# ========== ОСНОВНЫЕ ОБРАБОТЧИКИ ==========
@router.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        "🦉 Добро пожаловать в Викиторию!\n\n"
        "Игра для двоих, которая поможет стать ближе через:\n"
        "• Разговоры и флирт 🤍\n"
        "• Тактильные игры 💛\n"
        "• Интимная глубина ❤️\n\n"
        "Выберите действие:",
        reply_markup=main_menu_keyboard()
    )

@router.message(Command("myid"))
async def cmd_myid(message: Message):
    user_id = message.from_user.id
    await message.answer(
        f"🆔 Ваш Telegram ID: <code>{user_id}</code>\n\n"
        "Скопируйте этот ID для настройки админ-режима в Render.",
        parse_mode="HTML"
    )

@router.message(Command("admin"))
async def cmd_admin(message: Message):
    if ADMIN_ID and message.from_user.id == ADMIN_ID:
        await message.answer(
            "🛠️ <b>Админ-панель Викитории</b>\n\n"
            "Выберите действие:",
            reply_markup=admin_panel_keyboard()
        )
    else:
        await message.answer("❌ Команда не найдена")

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
    
    if user_id in admin_test_rooms:
        await callback.answer("❌ Завершите текущий тест через /admin", show_alert=True)
        return
    
    room_code = generate_room_code()
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

@router.callback_query(F.data == "cancel_search")
async def cancel_search_handler(callback: CallbackQuery):
    user_id = callback.from_user.id
    
    if user_id in active_users:
        room_code = active_users[user_id]
        
        if isinstance(room_code, str) and room_code in active_rooms:
            game_session = active_rooms[room_code]
            
            if game_session.creator_id == user_id and game_session.partner_id is None:
                cleanup_game(room_code)
    
    await callback.message.edit_text(
        "❌ <b>Поиск отменен</b>",
        reply_markup=main_menu_keyboard()
    )
    await callback.answer()

# ========== АДМИН-ТЕСТ ==========
@router.callback_query(F.data == "admin_start_test")
async def admin_start_test_handler(callback: CallbackQuery):
    if ADMIN_ID and callback.from_user.id == ADMIN_ID:
        admin_id = callback.from_user.id
        
        if admin_id in admin_test_rooms:
            await callback.answer("❌ У вас уже есть активный тест", show_alert=True)
            return
        
        room_code = generate_room_code()
        game_session = GameSession(room_code, admin_id, is_admin_test=True)
        active_rooms[room_code] = game_session
        active_users[admin_id] = room_code
        
        admin_test_rooms[admin_id] = room_code
        
        # Устанавливаем состояние игры сразу
        game_session.state = GameState.IN_GAME
        
        # Отправляем новое сообщение с просьбой ввести имя
        await bot.send_message(
            admin_id,
            f"🎮 <b>Тест игры начат!</b>\n\n"
            f"Код тестовой комнаты: <code>{room_code}</code>\n\n"
            f"<b>Представьтесь:</b>\n"
            f"Напишите ваше имя для начала игры:"
        )
        
        logger.info(f"✅ Админ-тест создан: {room_code}")
        await callback.answer("✅ Тест создан, введите имя")
    else:
        await callback.answer("❌ Доступ запрещён")

async def start_admin_test_game(game_session: GameSession):
    """Начало админ-теста"""
    admin_id = game_session.creator_id
    logger.info(f"🔧 Запускаем админ-тест для {admin_id}")
    
    try:
        # Сохраняем имя тестового партнёра
        game_session.player_names[-1] = "Тестовый партнёр"
        
        # Устанавливаем состояние игры
        game_session.state = GameState.IN_GAME
        
        # В админ-тесте у админа всегда роль исполняющего
        game_session.player_role[admin_id] = PlayerRole.PERFORMER
        
        # 1. Сообщение админу как исполняющему
        await bot.send_message(
            admin_id,
            f"🎮 <b>Тест игры начался!</b>\n\n"
            f"Вы играете с: <b>Тестовый партнёр</b>\n"
            f"Ваша роль в этом раунде: <b>исполняющий</b>\n"
            f"Колода: {get_stage_name(game_session.stage)}\n\n"
            f"<i>Начинаем игру...</i>"
        )
        
        # 2. Сообщение админу как ожидающему
        await bot.send_message(
            admin_id,
            f"👤 <b>Тестовый партнёр (ожидающий):</b>\n\n"
            f"Вы играете с: <b>{game_session.player_names.get(admin_id, 'Админ')}</b>\n"
            f"Ваша роль в этом раунде: <b>ожидающий</b>\n"
            f"Колода: {get_stage_name(game_session.stage)}\n\n"
            f"<i>Ждите задание от партнёра...</i>"
        )
        
        # 3. НЕМЕДЛЕННО отправляем первую карту
        await send_next_card(game_session)
        
        logger.info(f"✅ Админ-тест успешно начат для {admin_id}")
        
    except Exception as e:
        logger.error(f"❌ Ошибка при запуске админ-теста: {e}")
        await bot.send_message(admin_id, f"❌ Ошибка: {str(e)}")

# ========== ОБРАБОТКА ТЕКСТОВЫХ СООБЩЕНИЙ ==========
@router.message(F.text)
async def handle_text_message(message: Message):
    user_id = message.from_user.id
    text = message.text.strip()
    
    logger.info(f"📨 Получено сообщение от {user_id}: '{text}'")
    
    # 1. Если пользователь вводит код комнаты
    if user_id in active_users and active_users[user_id] == GameState.WAITING_CODE.value:
        logger.info(f"👤 Пользователь {user_id} вводит код комнаты")
        room_code = text.upper()
        
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
    
    # 2. Если игрок вводит свое имя (КЛЮЧЕВОЕ ИСПРАВЛЕНИЕ ЗДЕСЬ)
    elif user_id in active_users:
        room_code = active_users[user_id]
        
        if isinstance(room_code, str) and room_code in active_rooms:
            game_session = active_rooms[room_code]
            
            # УПРОЩЕННАЯ ПРОВЕРКА: если пользователь в комнате и еще не представился
            if user_id not in game_session.player_names:
                logger.info(f"👤 Игрок {user_id} представляется как '{text}' в комнате {room_code}")
                
                # Сохраняем имя игрока
                player_name = text[:50]
                game_session.player_names[user_id] = player_name
                
                await message.answer(f"✅ Отлично, {player_name}! Начинаем игру...")
                
                # ОТДЕЛЬНАЯ ЛОГИКА ДЛЯ АДМИН-ТЕСТА
                if game_session.is_admin_test:
                    logger.info(f"🔧 Админ-тест: имя сохранено, запускаем игру")
                    await start_admin_test_game(game_session)
                    return
                
                # ОТДЕЛЬНАЯ ЛОГИКА ДЛЯ ОБЫЧНОЙ ИГРЫ
                elif not game_session.is_admin_test:
                    # Проверяем, представились ли оба
                    all_players = [game_session.creator_id]
                    if game_session.partner_id:
                        all_players.append(game_session.partner_id)
                    
                    all_named = all(player_id in game_session.player_names for player_id in all_players)
                    
                    if all_named:
                        logger.info(f"👥 Оба игрока представились, начинаем игру")
                        await start_regular_game(game_session)
                    else:
                        logger.info(f"⏳ Ждем второго игрока...")
                        await message.answer("⏳ Ждем, когда партнёр представится")

async def start_regular_game(game_session: GameSession):
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
    
    await send_next_card(game_session)

# ========== НАЧАЛО ИГРЫ ОБРАБОТЧИК ==========
@router.callback_query(F.data == "start_game")
async def start_game_handler(callback: CallbackQuery):
    user_id = callback.from_user.id
    
    if user_id not in active_users:
        await callback.answer("❌ Ваша сессия не найдена")
        return
    
    room_code = active_users[user_id]
    
    if room_code not in active_rooms:
        await callback.answer("❌ Комната не найдена")
        return
    
    game_session = active_rooms[room_code]
    
    # ДЛЯ АДМИН-ТЕСТА: не запускаем через эту кнопку
    if game_session.is_admin_test:
        await callback.answer("⚠️ Для админ-теста введите имя в чате")
        return
    
    if game_session.creator_id != user_id:
        await callback.answer("❌ Только создатель может начать игру")
        return
    
    # Начинаем игру
    game_session.state = GameState.IN_GAME
    
    # Просим игроков представиться
    players_to_notify = [game_session.creator_id]
    if not game_session.is_admin_test and game_session.partner_id:
        players_to_notify.append(game_session.partner_id)
    
    for player_id in players_to_notify:
        await bot.send_message(
            player_id,
            "👋 <b>Давайте познакомимся!</b>\n\n"
            "Перед началом игры представьтесь друг другу.\n\n"
            "Напишите ваше имя или как к вам обращаться:"
        )
    
    await callback.message.edit_text("✅ <b>Игра началась!</b>\n\nЖдем, когда оба игрока представятся.")

# ========== ИГРОВАЯ ЛОГИКА ==========
async def send_next_card(game_session: GameSession):
    """Отправить следующую карту в игре"""
    
    # Проверяем, не пуста ли текущая колода
    if len(game_session.get_available_cards()) == 0:
        next_stage = game_session.advance_stage()
        
        if next_stage:
            # Предлагаем перейти к следующей колоде
            players_to_notify = [game_session.creator_id]
            if not game_session.is_admin_test and game_session.partner_id:
                players_to_notify.append(game_session.partner_id)
            
            for player_id in players_to_notify:
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
            players_to_notify = [game_session.creator_id]
            if not game_session.is_admin_test and game_session.partner_id:
                players_to_notify.append(game_session.partner_id)
            
            for player_id in players_to_notify:
                await bot.send_message(
                    player_id,
                    "🏁 <b>Игра завершена!</b>\n\n"
                    "Вы выполнили все задания во всех колодах!\n\n"
                    "Спасибо за игру! 🦉",
                    reply_markup=main_menu_keyboard()
                )
            
            cleanup_game(game_session.room_code)
            return
    
    # Берем новую карту
    card = game_session.draw_card()
    if not card:
        return
    
    card_id = game_session.current_card_id
    
    # Определяем исполняющего
    for player_id, role in game_session.player_role.items():
        if role == PlayerRole.PERFORMER:
            game_session.current_performer = player_id
            
            # Отправляем задание исполняющему
            performer_name = game_session.player_names.get(player_id, "Исполняющий")
            card_text = f"🎴 <b>Задание для {performer_name}:</b>\n\n{card['text']}"
            
            timer_seconds = parse_timer_from_text(card["text"])
            if timer_seconds:
                minutes = timer_seconds // 60
                seconds = timer_seconds % 60
                time_text = f"{minutes} мин" if minutes > 0 else f"{seconds} сек"
                card_text += f"\n\n⏱️ <i>Время на выполнение: {time_text}</i>"
            
            await bot.send_message(
                player_id,
                card_text,
                reply_markup=performer_keyboard(card, card_id)
            )
            
            # Отправляем ожидающему
            if not game_session.is_admin_test and game_session.partner_id:
                opponent_id = game_session.get_opponent_id(player_id)
                await bot.send_message(
                    opponent_id,
                    f"⏳ <b>Ожидание выполнения</b>\n\n"
                    f"{performer_name} выполняет задание.\n\n"
                    f"<i>Задание:</i> {card['text']}\n\n"
                    f"Подтвердите выполнение, когда будет готово.",
                    reply_markup=waiter_keyboard(card_id)
                )
            elif game_session.is_admin_test:
                # В админ-тесте показываем сообщение "ожидающему"
                await bot.send_message(
                    player_id,
                    f"👤 <b>Тестовый партнёр (ожидающий):</b>\n\n"
                    f"{performer_name} выполняет задание.\n\n"
                    f"<i>Задание:</i> {card['text']}\n\n"
                    f"Подтвердите выполнение, когда будет готово.",
                    reply_markup=waiter_keyboard(card_id)
                )
            
            break

# ========== ОБРАБОТЧИКИ ИГРОВЫХ ДЕЙСТВИЙ ==========
@router.callback_query(F.data.startswith("task_done:"))
async def task_done_handler(callback: CallbackQuery):
    user_id = callback.from_user.id
    
    if user_id not in active_users:
        await callback.answer("❌ Вы не в игре")
        return
    
    room_code = active_users[user_id]
    
    if room_code not in active_rooms:
        await callback.answer("❌ Игра не найдена")
        return
    
    game_session = active_rooms[room_code]
    card_id = callback.data.split(":")[1]
    
    # Проверяем актуальность карты
    if game_session.current_card_id != card_id:
        await callback.answer("⚠️ Это задание уже неактивно")
        return
    
    # В админ-тесте админ может подтверждать выполнение как ожидающий
    # В обычной игре - только ожидающий
    if not game_session.is_admin_test and game_session.player_role.get(user_id) != PlayerRole.WAITER:
        await callback.answer("❌ Только ожидающий может подтвердить выполнение")
        return
    
    # Останавливаем таймер, если он был запущен
    if user_id in active_timers:
        active_timers[user_id].cancel()
        del active_timers[user_id]
    
    # Меняем роли (кроме админ-теста)
    if not game_session.is_admin_test:
        game_session.switch_roles()
    
    # Уведомляем игроков
    performer_id = game_session.current_performer
    performer_name = game_session.player_names.get(performer_id, "Исполняющий")
    
    players_to_notify = [game_session.creator_id]
    if not game_session.is_admin_test and game_session.partner_id:
        players_to_notify.append(game_session.partner_id)
    
    for player_id in players_to_notify:
        await bot.send_message(
            player_id,
            f"✅ <b>Задание выполнено!</b>\n\n"
            f"{performer_name} успешно справился(ась) с заданием.\n\n"
            f"<i>Меняем роли...</i>"
        )
    
    # НЕМЕДЛЕННО отправляем следующую карту
    await send_next_card(game_session)
    
    await callback.answer("✅ Задание подтверждено!")

@router.callback_query(F.data.startswith("skip_card:"))
async def skip_card_handler(callback: CallbackQuery):
    user_id = callback.from_user.id
    
    if user_id not in active_users:
        await callback.answer("❌ Вы не в игре")
        return
    
    room_code = active_users[user_id]
    
    if room_code not in active_rooms:
        await callback.answer("❌ Игра не найдена")
        return
    
    game_session = active_rooms[room_code]
    card_id = callback.data.split(":")[1]
    
    # Проверяем актуальность карты
    if game_session.current_card_id != card_id:
        await callback.answer("⚠️ Это задание уже неактивно")
        return
    
    # Останавливаем таймер, если он был запущен
    if user_id in active_timers:
        active_timers[user_id].cancel()
        del active_timers[user_id]
    
    # Меняем роли (кроме админ-теста)
    if not game_session.is_admin_test:
        game_session.switch_roles()
    
    # Уведомляем игроков
    players_to_notify = [game_session.creator_id]
    if not game_session.is_admin_test and game_session.partner_id:
        players_to_notify.append(game_session.partner_id)
    
    for player_id in players_to_notify:
        await bot.send_message(
            player_id,
            "➡️ <b>Карточка пропущена</b>\n\n"
            "Переходим к следующему заданию."
        )
    
    # НЕМЕДЛЕННО отправляем следующую карту
    await send_next_card(game_session)
    
    await callback.answer("Карточка пропущена")

@router.callback_query(F.data.startswith("roll_dice:"))
async def roll_dice_handler(callback: CallbackQuery):
    user_id = callback.from_user.id
    
    if user_id not in active_users:
        await callback.answer("❌ Вы не в игре")
        return
    
    room_code = active_users[user_id]
    
    if room_code not in active_rooms:
        await callback.answer("❌ Игра не найдена")
        return
    
    game_session = active_rooms[room_code]
    card_id = callback.data.split(":")[1]
    
    # Проверяем актуальность карты
    if game_session.current_card_id != card_id:
        await callback.answer("⚠️ Это задание уже неактивно")
        return
    
    # Проверяем, что пользователь - исполняющий
    if game_session.player_role.get(user_id) != PlayerRole.PERFORMER:
        await callback.answer("❌ Только исполняющий может бросить кубик")
        return
    
    # Бросаем кубик
    dice_value = random.randint(1, 6)
    dice_emoji = ["⚀", "⚁", "⚂", "⚃", "⚄", "⚅"][dice_value - 1]
    
    # Отправляем результат
    performer_name = game_session.player_names.get(user_id, "Исполняющий")
    
    players_to_notify = [game_session.creator_id]
    if not game_session.is_admin_test and game_session.partner_id:
        players_to_notify.append(game_session.partner_id)
    
    for player_id in players_to_notify:
        await bot.send_message(
            player_id,
            f"🎲 <b>Бросок кубика от {performer_name}:</b>\n\n"
            f"{dice_emoji} Выпало: <b>{dice_value}</b>"
        )
    
    await callback.answer(f"🎲 Выпало: {dice_value}")

@router.callback_query(F.data.startswith("start_timer:"))
async def start_timer_handler(callback: CallbackQuery):
    user_id = callback.from_user.id
    
    if user_id not in active_users:
        await callback.answer("❌ Вы не в игре")
        return
    
    room_code = active_users[user_id]
    
    if room_code not in active_rooms:
        await callback.answer("❌ Игра не найдена")
        return
    
    game_session = active_rooms[room_code]
    card_id = callback.data.split(":")[1]
    
    # Проверяем актуальность карты
    if game_session.current_card_id != card_id:
        await callback.answer("⚠️ Это задание уже неактивно")
        return
    
    # Проверяем, что пользователь - исполняющий
    if game_session.player_role.get(user_id) != PlayerRole.PERFORMER:
        await callback.answer("❌ Только исполняющий может запустить таймер")
        return
    
    card = game_session.current_card
    if not card:
        await callback.answer("❌ Карточка не найдена")
        return
    
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
    
    players_to_notify = [game_session.creator_id]
    if not game_session.is_admin_test and game_session.partner_id:
        players_to_notify.append(game_session.partner_id)
    
    for player_id in players_to_notify:
        await bot.send_message(
            player_id,
            f"⏱️ <b>Таймер запущен!</b>\n\n"
            f"{performer_name} начал(а) выполнение задания.\n"
            f"Время: {time_text}"
        )
    
    # Запускаем реальный таймер
    await start_timer_with_controls(user_id, card_id, timer_seconds, time_text)
    
    await callback.answer(f"Таймер запущен")

async def start_timer_with_controls(user_id: int, card_id: str, total_seconds: int, time_text: str):
    """Запуск таймера с управлением"""
    
    # Отправляем сообщение с таймером
    msg = await bot.send_message(
        user_id,
        f"⏱️ <b>Таймер:</b> {time_text}\n\n"
        f"⏳ 00:00 / {time_text}",
        reply_markup=timer_keyboard(card_id)
    )
    
    # Создаем задачу таймера
    timer_task = asyncio.create_task(run_timer(user_id, msg.message_id, total_seconds, time_text, card_id))
    active_timers[user_id] = timer_task

async def run_timer(user_id: int, message_id: int, total_seconds: int, time_text: str, card_id: str):
    """Запуск отсчета таймера"""
    try:
        remaining = total_seconds
        while remaining > 0:
            await asyncio.sleep(1)
            remaining -= 1
            
            mins = remaining // 60
            secs = remaining % 60
            
            # Проверяем, не отменен ли таймер
            if user_id not in active_timers:
                break
            
            try:
                await bot.edit_message_text(
                    chat_id=user_id,
                    message_id=message_id,
                    text=f"⏱️ <b>Таймер:</b> {time_text}\n\n"
                         f"⏳ {mins:02d}:{secs:02d} / {time_text}",
                    reply_markup=timer_keyboard(card_id)
                )
            except:
                break
        
        if remaining == 0:
            await bot.edit_message_text(
                chat_id=user_id,
                message_id=message_id,
                text=f"⏰ <b>Время вышло!</b>\n\n"
                     f"Таймер завершён."
            )
            
            # Удаляем таймер
            if user_id in active_timers:
                del active_timers[user_id]
    
    except asyncio.CancelledError:
        # Таймер был отменен
        if user_id in active_timers:
            del active_timers[user_id]

@router.callback_query(F.data.startswith("pause_timer:"))
async def pause_timer_handler(callback: CallbackQuery):
    user_id = callback.from_user.id
    
    if user_id in active_timers:
        active_timers[user_id].cancel()
        del active_timers[user_id]
        
        await callback.answer("⏸️ Таймер остановлен")
    else:
        await callback.answer("❌ Нет активного таймера")

@router.callback_query(F.data.startswith("stop_timer:"))
async def stop_timer_handler(callback: CallbackQuery):
    user_id = callback.from_user.id
    
    if user_id in active_timers:
        active_timers[user_id].cancel()
        del active_timers[user_id]
        
        await bot.send_message(user_id, "⏹️ Таймер остановлен")
        await callback.answer("Таймер остановлен")
    else:
        await callback.answer("❌ Нет активного таймера")

@router.callback_query(F.data.startswith("send_photo:"))
async def send_photo_handler(callback: CallbackQuery):
    user_id = callback.from_user.id
    
    if user_id not in active_users:
        await callback.answer("❌ Вы не в игре")
        return
    
    room_code = active_users[user_id]
    
    if room_code not in active_rooms:
        await callback.answer("❌ Игра не найдена")
        return
    
    game_session = active_rooms[room_code]
    card_id = callback.data.split(":")[1]
    
    # Проверяем актуальность карты
    if game_session.current_card_id != card_id:
        await callback.answer("⚠️ Это задание уже неактивно")
        return
    
    # Проверяем, что пользователь - исполняющий
    if game_session.player_role.get(user_id) != PlayerRole.PERFORMER:
        await callback.answer("❌ Только исполняющий может отправить фото")
        return
    
    performer_name = game_session.player_names.get(user_id, "Исполняющий")
    
    await bot.send_message(
        user_id,
        "📸 <b>Отправка фото</b>\n\n"
        "В реальной игре вы бы отправили фото из галереи.\n\n"
        "<i>Для теста считаем, что фото отправлено.</i>"
    )
    
    if not game_session.is_admin_test and game_session.partner_id:
        opponent_id = game_session.get_opponent_id(user_id)
        await bot.send_message(
            opponent_id,
            f"📸 <b>{performer_name} отправил(а) фото</b>"
        )
    elif game_session.is_admin_test:
        await bot.send_message(
            user_id,
            f"👤 <b>Тестовый партнёр:</b>\n\n"
            f"Получил фото от {performer_name}! 📸"
        )
    
    await callback.answer("Фото отправлено")

@router.callback_query(F.data == "next_deck")
async def next_deck_handler(callback: CallbackQuery):
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
    players_to_notify = [game_session.creator_id]
    if not game_session.is_admin_test and game_session.partner_id:
        players_to_notify.append(game_session.partner_id)
    
    for player_id in players_to_notify:
        await bot.send_message(
            player_id,
            f"🔄 <b>Переход к новой колоде!</b>\n\n"
            f"Теперь играем с {get_stage_name(game_session.stage)}\n\n"
            f"<i>Продолжаем игру...</i>"
        )
    
    # Отправляем первую карту из новой колоды
    await send_next_card(game_session)
    
    await callback.answer("Перешли к следующей колоде")

@router.callback_query(F.data == "request_stop_game")
async def request_stop_game_handler(callback: CallbackQuery):
    user_id = callback.from_user.id
    
    if user_id not in active_users:
        await callback.answer("❌ Вы не в игре")
        return
    
    room_code = active_users[user_id]
    
    if room_code not in active_rooms:
        await callback.answer("❌ Игра не найдена")
        return
    
    game_session = active_rooms[room_code]
    
    # Останавливаем все таймеры
    for player_id in [game_session.creator_id, game_session.partner_id]:
        if player_id and player_id in active_timers:
            active_timers[player_id].cancel()
            del active_timers[player_id]
    
    # В админ-тесте сразу предлагаем завершить
    if game_session.is_admin_test:
        await bot.send_message(
            user_id,
            "🏁 <b>Завершение тестовой игры</b>\n\n"
            "Вы действительно хотите завершить тестовую игру?",
            reply_markup=stop_game_confirmation_keyboard()
        )
    elif game_session.partner_id:
        opponent_id = game_session.get_opponent_id(user_id)
        await bot.send_message(
            opponent_id,
            "🏁 <b>Партнёр хочет завершить игру</b>\n\n"
            "Вы согласны завершить игру?",
            reply_markup=stop_game_confirmation_keyboard()
        )
    
    await callback.message.answer("⏳ <b>Запрос отправлен</b>")
    await callback.answer()

@router.callback_query(F.data.in_(["confirm_stop", "continue_game", "force_stop"]))
async def stop_game_confirmation_handler(callback: CallbackQuery):
    user_id = callback.from_user.id
    
    if user_id not in active_users:
        await callback.answer("❌ Вы не в игре")
        return
    
    room_code = active_users[user_id]
    
    if room_code not in active_rooms:
        await callback.answer("❌ Игра не найдена")
        return
    
    game_session = active_rooms[room_code]
    
    if callback.data in ["confirm_stop", "force_stop"]:
        # Завершаем игру
        players_to_notify = [game_session.creator_id]
        if not game_session.is_admin_test and game_session.partner_id:
            players_to_notify.append(game_session.partner_id)
        
        for player_id in players_to_notify:
            await bot.send_message(
                player_id,
                "🏁 <b>Игра завершена!</b>\n\n"
                "Спасибо за игру! 🦉",
                reply_markup=main_menu_keyboard()
            )
        
        # Останавливаем все таймеры
        for player_id in players_to_notify:
            if player_id in active_timers:
                active_timers[player_id].cancel()
                if player_id in active_timers:
                    del active_timers[player_id]
        
        cleanup_game(room_code)
        
        # Удаляем из админ-тестов если нужно
        if user_id in admin_test_rooms:
            del admin_test_rooms[user_id]
    
    else:  # continue_game
        # Продолжаем игру
        if not game_session.is_admin_test and game_session.partner_id:
            opponent_id = game_session.get_opponent_id(user_id)
            await bot.send_message(
                opponent_id,
                "✅ <b>Партнёр хочет продолжить игру</b>\n\n"
                "Продолжаем выполнение заданий!"
            )
    
    await callback.answer()

def cleanup_game(room_code: str):
    if room_code in active_rooms:
        game_session = active_rooms[room_code]
        
        # Удаляем пользователей
        for player_id in [game_session.creator_id, game_session.partner_id]:
            if player_id and player_id in active_users:
                del active_users[player_id]
        
        # Удаляем комнату
        del active_rooms[room_code]

# ========== АДМИН-ПАНЕЛЬ ==========
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

@router.callback_query(F.data == "admin_stats")
async def admin_stats_handler(callback: CallbackQuery):
    if ADMIN_ID and callback.from_user.id == ADMIN_ID:
        active_users_count = len(active_users)
        active_rooms_count = len(active_rooms)
        
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
            f"• Активных админ-тестов: {len(admin_test_rooms)}\n"
            f"• Активных таймеров: {len(active_timers)}\n\n"
            "<b>Колоды:</b>\n" + "\n".join(deck_stats)
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
        # Останавливаем все таймеры
        for timer in active_timers.values():
            timer.cancel()
        
        # Очищаем все данные
        active_users.clear()
        active_rooms.clear()
        admin_test_rooms.clear()
        active_timers.clear()
        
        try:
            await callback.message.edit_text(
                "🔄 <b>Все данные сброшены!</b>\n\n"
                "• Активные игры очищены\n"
                "• Комнаты удалены\n"
                "• Админ-тесты завершены\n"
                "• Таймеры остановлены\n\n"
                "<i>Бот готов к работе</i>",
                reply_markup=admin_panel_keyboard()
            )
        except Exception as e:
            await callback.message.answer(
                "🔄 <b>Все данные сброшены!</b>\n\n"
                "• Активные игры очищены\n"
                "• Комнаты удалены\n"
                "• Админ-тесты завершены\n"
                "• Таймеры остановлены\n\n"
                "<i>Бот готов к работе</i>",
                reply_markup=admin_panel_keyboard()
            )
    else:
        await callback.answer("❌ Доступ запрещён")

@router.callback_query(F.data == "cancel_game")
async def cancel_game_handler(callback: CallbackQuery):
    user_id = callback.from_user.id
    
    if user_id in active_users:
        room_code = active_users[user_id]
        
        if room_code in active_rooms:
            game_session = active_rooms[room_code]
            
            # Останавливаем таймеры
            if user_id in active_timers:
                active_timers[user_id].cancel()
                del active_timers[user_id]
            
            # Удаляем из админ-тестов
            if game_session.is_admin_test and user_id in admin_test_rooms:
                del admin_test_rooms[user_id]
            
            cleanup_game(room_code)
    
    await callback.message.edit_text(
        "❌ <b>Игра отменена</b>",
        reply_markup=main_menu_keyboard()
    )
    await callback.answer()

# ========== ЗАПУСК БОТА ==========
async def main():
    logger.info("=" * 60)
    logger.info("🚀 ЗАПУСК БОТА 'ВИКИТОРИЯ'")
    logger.info("=" * 60)
    
    total_cards = sum(len(cards) for cards in CARDS_DATA.values())
    logger.info(f"📊 Карты: {total_cards} ({len(CARDS_DATA['white'])}🤍/{len(CARDS_DATA['yellow'])}💛/{len(CARDS_DATA['red'])}❤️)")
    
    if ADMIN_ID:
        logger.info(f"👑 Админ ID: {ADMIN_ID}")
    
    logger.info("✅ Бот запущен")
    logger.info("=" * 60)
    
    try:
        await dp.start_polling(bot)
    except KeyboardInterrupt:
        logger.info("🛑 Бот остановлен")
    except Exception as e:
        logger.error(f"❌ Ошибка запуска: {e}")
        raise

if __name__ == "__main__":
    asyncio.run(main())
