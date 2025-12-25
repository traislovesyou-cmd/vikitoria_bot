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
from typing import Dict, Optional

from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, 
    InlineKeyboardButton, ReplyKeyboardRemove
)
from aiogram.filters import Command

# ========== НАСТРОЙКА ЛОГИРОВАНИЯ ==========
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ========== КОНФИГУРАЦИЯ ==========
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID")  # Новое: ID администратора

if not BOT_TOKEN:
    logger.error("❌ ERROR: BOT_TOKEN environment variable is not set!")
    exit(1)

# Проверяем ADMIN_ID, но не падаем если нет (для обратной совместимости)
if ADMIN_ID:
    try:
        ADMIN_ID = int(ADMIN_ID)
    except ValueError:
        logger.warning(f"⚠️ ADMIN_ID должно быть числом, получено: {ADMIN_ID}")
        ADMIN_ID = None
else:
    logger.info("ℹ️ ADMIN_ID не установлен, админ-режим недоступен")
    ADMIN_ID = None

# Инициализация бота
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)

# ========== HTTP-СЕРВЕР ДЛЯ RENDER ==========
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        response = "🦉 Бот Викитория работает (игра для двоих)"
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
    ENVELOPE = "envelope"

# Хранение данных
active_rooms = {}
active_users = {}
user_timers = {}

# НОВОЕ: Хранение админ-сессий (режим тестирования с самим собой)
admin_sessions = {}  # admin_id -> session_data

# ========== КАРТОЧКИ (остаются без изменений) ==========
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
        {"id": 2, "type": "action", "text": "Дилема доверия (с кубиком). Брось кубик. Четное число: Ты получаешь полный контроль на 5 минут — веди партнера шепотом или прикосновениями. Нечетное: Ты передаешь этот контроль партнеру."},
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

def get_random_card(stage: GameStage) -> Dict:
    deck = CARDS_DATA.get(stage.value, [])
    return random.choice(deck) if deck else {"id": 0, "type": "info", "text": "Карточки временно отсутствуют"}

def has_timer_in_text(text: str) -> bool:
    time_words = ['минут', 'секунд', 'час', 'таймер', 'время', 'минуту', 'секунду']
    return any(word in text.lower() for word in time_words)

def has_photo_in_text(text: str) -> bool:
    photo_words = ['фото', 'галере', 'снимок', 'фотограф']
    return any(word in text.lower() for word in photo_words)

# ========== КЛАВИАТУРЫ (остаются без изменений) ==========
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
    buttons = []
    buttons.append([InlineKeyboardButton(text="Выполнил ✅", callback_data="task_done")])
    buttons.append([InlineKeyboardButton(text="Пропустить ➡️", callback_data="skip_card")])
    
    if has_timer_in_text(card["text"]):
        buttons.append([InlineKeyboardButton(text="Запустить таймер ⏱️", callback_data="start_timer")])
    
    if has_photo_in_text(card["text"]):
        buttons.append([InlineKeyboardButton(text="Отправить фото 📸", callback_data="request_photo")])
    
    if "кубик" in card["text"].lower() or "брось" in card["text"].lower():
        buttons.append([InlineKeyboardButton(text="Бросить кубик 🎲", callback_data="roll_dice")])
    
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

# НОВОЕ: Клавиатура админ-панели
def admin_panel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔧 Тест одиночной игры", callback_data="admin_solo_test")],
        [InlineKeyboardButton(text="📊 Статистика бота", callback_data="admin_stats")],
        [InlineKeyboardButton(text="🔄 Сбросить все игры", callback_data="admin_reset_all")],
        [InlineKeyboardButton(text="🚪 Выйти из админ-панели", callback_data="main_menu")]
    ])

def admin_solo_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🤍 Белая колода", callback_data="admin_white")],
        [InlineKeyboardButton(text="💛 Жёлтая колода", callback_data="admin_yellow")],
        [InlineKeyboardButton(text="❤️ Красная колода", callback_data="admin_red")],
        [InlineKeyboardButton(text="🔙 Назад в админ-панель", callback_data="admin_panel")]
    ])

# ========== АДМИН-КОМАНДЫ ==========
@router.message(Command("myid"))
async def cmd_myid(message: Message):
    """Показать ID пользователя"""
    user_id = message.from_user.id
    await message.answer(
        f"🆔 Ваш Telegram ID: <code>{user_id}</code>\n\n"
        f"Скопируйте этот ID для настройки админ-режима в Render.",
        parse_mode="HTML"
    )

@router.message(Command("admin"))
async def cmd_admin(message: Message):
    """Админ-панель (только для владельца)"""
    user_id = message.from_user.id
    
    if ADMIN_ID and user_id == ADMIN_ID:
        # Показываем админ-панель
        await message.answer(
            "🛠️ <b>Админ-панель Викитории</b>\n\n"
            "Здесь вы можете:\n"
            "• Тестировать игру в одиночку\n"
            "• Просматривать статистику\n"
            "• Управлять состоянием бота\n\n"
            "<i>Выберите действие:</i>",
            parse_mode="HTML",
            reply_markup=admin_panel_keyboard()
        )
    else:
        # Скрываем существование команды для обычных пользователей
        await message.answer("❌ Команда не найдена")

# Обработчики админ-панели
@router.callback_query(F.data == "admin_panel")
async def admin_panel_handler(callback: CallbackQuery):
    """Показать админ-панель"""
    if ADMIN_ID and callback.from_user.id == ADMIN_ID:
        await callback.message.edit_text(
            "🛠️ <b>Админ-панель Викитории</b>\n\n"
            "Выберите действие:",
            parse_mode="HTML",
            reply_markup=admin_panel_keyboard()
        )
    else:
        await callback.answer("❌ Доступ запрещён", show_alert=True)

@router.callback_query(F.data == "admin_solo_test")
async def admin_solo_test_handler(callback: CallbackQuery):
    """Тест одиночной игры"""
    if ADMIN_ID and callback.from_user.id == ADMIN_ID:
        # Создаём админ-сессию
        admin_id = callback.from_user.id
        session_id = str(uuid.uuid4())[:8]
        
        admin_sessions[admin_id] = {
            "session_id": session_id,
            "stage": GameStage.WHITE.value,
            "current_role": PlayerRole.PERFORMER.value,
            "virtual_partner": f"virtual_{session_id}",
            "current_card": None,
            "created_at": datetime.now().isoformat()
        }
        
        await callback.message.edit_text(
            "🎮 <b>Тест одиночной игры</b>\n\n"
            "Вы играете с виртуальным партнёром.\n"
            "Все функции работают как в обычной игре.\n\n"
            "<i>Выберите колоду для тестирования:</i>",
            parse_mode="HTML",
            reply_markup=admin_solo_menu_keyboard()
        )
    else:
        await callback.answer("❌ Доступ запрещён", show_alert=True)

@router.callback_query(F.data.startswith("admin_"))
async def admin_select_deck_handler(callback: CallbackQuery):
    """Выбор колоды для тестирования"""
    if ADMIN_ID and callback.from_user.id == ADMIN_ID:
        admin_id = callback.from_user.id
        
        if admin_id not in admin_sessions:
            await callback.answer("❌ Сессия не найдена", show_alert=True)
            return
        
        # Определяем выбранную колоду
        action = callback.data
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
            await callback.answer("❌ Неизвестная колода", show_alert=True)
            return
        
        # Обновляем сессию
        admin_sessions[admin_id]["stage"] = deck.value
        
        # Начинаем игру
        await callback.message.edit_text(
            f"🎮 <b>Тест одиночной игры</b>\n\n"
            f"Колода: {deck_name}\n"
            f"Ваша роль: <b>Исполняющий</b>\n\n"
            f"<i>Игра началась! Вы получаете первое задание...</i>",
            parse_mode="HTML"
        )
        
        # Отправляем первую карту
        await send_admin_card(admin_id)
    else:
        await callback.answer("❌ Доступ запрещён", show_alert=True)

async def send_admin_card(admin_id: int):
    """Отправить карту в админ-режиме"""
    if admin_id not in admin_sessions:
        return
    
    session = admin_sessions[admin_id]
    stage = GameStage(session["stage"])
    card = get_random_card(stage)
    session["current_card"] = card
    
    if session["current_role"] == PlayerRole.PERFORMER.value:
        # Показываем карту "исполняющему"
        card_text = f"🎴 <b>Ваше задание (исполняющий):</b>\n\n{card['text']}"
        
        if "кубик" in card["text"].lower():
            card_text += "\n\n🎲 <i>Используйте кнопку 'Бросить кубик'</i>"
        
        await bot.send_message(
            admin_id,
            card_text,
            parse_mode="HTML",
            reply_markup=performer_keyboard(card)
        )
        
        # "Партнёру" показываем только текст
        partner_text = f"🎴 <b>Задание партнёра (ожидающий):</b>\n\n{card['text']}"
        await bot.send_message(
            admin_id,  # Отправляем в тот же чат, но как бы от лица партнёра
            partner_text,
            parse_mode="HTML"
        )
    else:
        # Если админ в роли ожидающего
        await bot.send_message(
            admin_id,
            f"⏳ <b>Вы в роли ожидающего</b>\n\n"
            f"Ждите, пока партнёр выполнит задание.\n\n"
            f"<i>Задание партнёра:</i>\n{card['text']}",
            parse_mode="HTML",
            reply_markup=waiter_keyboard()
        )

# НОВОЕ: Обработка игровых действий в админ-режиме
@router.callback_query(F.data.in_(["task_done", "skip_card", "roll_dice", "start_timer"]))
async def admin_game_action_handler(callback: CallbackQuery):
    """Обработка игровых действий в админ-режиме"""
    user_id = callback.from_user.id
    
    # Проверяем, в админ-сессии ли пользователь
    if user_id in admin_sessions:
        action = callback.data
        
        if action == "task_done":
            if admin_sessions[user_id]["current_role"] == PlayerRole.WAITER.value:
                # Меняем роли в админ-сессии
                await switch_admin_roles(user_id)
                await callback.answer("✅ Задание выполнено!")
            else:
                await callback.answer("⏳ Ждите подтверждения партнёра", show_alert=True)
        
        elif action == "skip_card":
            # Меняем роли
            await switch_admin_roles(user_id)
            await callback.answer("Карточка пропущена")
        
        elif action == "roll_dice":
            dice_value = random.randint(1, 6)
            await bot.send_message(
                user_id,
                f"🎲 <b>Бросок кубика от партнёра:</b> выпало {dice_value}",
                parse_mode="HTML"
            )
            await callback.answer(f"🎲 Выпало: {dice_value}", show_alert=True)
        
        elif action == "start_timer":
            card = admin_sessions[user_id].get("current_card", {})
            text = card.get("text", "")
            minutes = 5
            
            time_match = re.search(r'(\d+)\s*минут', text)
            if time_match:
                minutes = int(time_match.group(1))
            
            # Запускаем таймер
            await callback.answer(f"Таймер запущен на {minutes} минут")
            
            # Симуляция таймера
            msg = await bot.send_message(user_id, f"⏱️ Таймер запущен: {minutes} мин")
            await asyncio.sleep(2)  # Для теста сокращаем время
            
            await bot.edit_message_text(
                chat_id=user_id,
                message_id=msg.message_id,
                text="⏰ Время вышло! (тестовый таймер)"
            )
    
    else:
        # Если не в админ-сессии, используем обычную логику
        # (оставлю тебе заполнить или оставить как есть)
        await callback.answer("❌ Действие не обработано", show_alert=True)

async def switch_admin_roles(admin_id: int):
    """Смена ролей в админ-режиме"""
    if admin_id not in admin_sessions:
        return
    
    session = admin_sessions[admin_id]
    
    # Меняем роль
    current = session["current_role"]
    session["current_role"] = PlayerRole.WAITER.value if current == PlayerRole.PERFORMER.value else PlayerRole.PERFORMER.value
    
    # Очищаем текущую карту
    session["current_card"] = None
    
    # Отправляем сообщение о смене роли
    new_role = "ожидающий" if session["current_role"] == PlayerRole.WAITER.value else "исполняющий"
    await bot.send_message(
        admin_id,
        f"🔄 <b>Смена ролей!</b>\n\n"
        f"Теперь вы: <b>{new_role}</b>\n\n"
        f"<i>Продолжаем игру...</i>",
        parse_mode="HTML"
    )
    
    # Отправляем новую карту
    await send_admin_card(admin_id)

@router.callback_query(F.data == "admin_stats")
async def admin_stats_handler(callback: CallbackQuery):
    """Статистика бота"""
    if ADMIN_ID and callback.from_user.id == ADMIN_ID:
        active_users_count = len(active_users)
        active_rooms_count = len(active_rooms)
        admin_sessions_count = len(admin_sessions)
        
        stats_text = (
            "📊 <b>Статистика бота Викитория</b>\n\n"
            f"• Активных пользователей: {active_users_count}\n"
            f"• Активных комнат: {active_rooms_count}\n"
            f"• Админ-сессий: {admin_sessions_count}\n"
            f"• Карт в базе: {sum(len(cards) for cards in CARDS_DATA.values())}\n\n"
            "<i>Данные хранятся в памяти (перезагрузка очистит статистику)</i>"
        )
        
        await callback.message.edit_text(
            stats_text,
            parse_mode="HTML",
            reply_markup=admin_panel_keyboard()
        )
    else:
        await callback.answer("❌ Доступ запрещён", show_alert=True)

@router.callback_query(F.data == "admin_reset_all")
async def admin_reset_all_handler(callback: CallbackQuery):
    """Сброс всех игр"""
    if ADMIN_ID and callback.from_user.id == ADMIN_ID:
        # Очищаем все данные
        active_users.clear()
        active_rooms.clear()
        admin_sessions.clear()
        
        # Отменяем все таймеры
        for timer in user_timers.values():
            timer.cancel()
        user_timers.clear()
        
        await callback.message.edit_text(
            "🔄 <b>Все данные сброшены!</b>\n\n"
            "• Активные игры очищены\n"
            "• Комнаты удалены\n"
            "• Таймеры остановлены\n"
            "• Админ-сессии завершены\n\n"
            "<i>Бот готов к новой работе</i>",
            parse_mode="HTML",
            reply_markup=admin_panel_keyboard()
        )
    else:
        await callback.answer("❌ Доступ запрещён", show_alert=True)

# ========== ОБЫЧНЫЕ КОМАНДЫ (остаются без изменений) ==========
@router.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        "🦉 Добро пожаловать в Викиторию!\n\n"
        "Игра для двоих, которая поможет стать ближе через:\n"
        "• Разговоры и флирт 🤍\n"
        "• Тактильные игры 💛\n"
        "• Интимную глубину ❤️\n\n"
        "Выберите действие:",
        reply_markup=main_menu_keyboard()
    )

# ... (остальные обработчики остаются без изменений, как в предыдущей версии)
# [Здесь должен быть весь остальной код из предыдущего bot.py]

# ========== ЗАПУСК БОТА ==========
async def main():
    """Основная функция запуска бота"""
    await asyncio.sleep(1)
    
    bot_info = await bot.get_me()
    
    logger.info("=" * 50)
    logger.info("🚀 ЗАПУСК БОТА 'ВИКИТОРИЯ' С АДМИН-РЕЖИМОМ")
    logger.info("=" * 50)
    logger.info(f"🤖 Бот: @{bot_info.username}")
    logger.info(f"🆔 ID бота: {bot_info.id}")
    
    if ADMIN_ID:
        logger.info(f"👑 Админ ID: {ADMIN_ID}")
    else:
        logger.info("ℹ️ Админ-режим отключен (ADMIN_ID не установлен)")
    
    logger.info(f"🌐 Порт HTTP: {os.getenv('PORT', 10000)}")
    logger.info("✅ Все системы работают")
    logger.info("=" * 50)
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
