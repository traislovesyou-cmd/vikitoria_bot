import os
import asyncio
import logging
import random
import string
import re
import threading
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
if not BOT_TOKEN:
    logger.error("❌ ERROR: BOT_TOKEN environment variable is not set!")
    exit(1)

# Инициализация бота
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)

# ========== HTTP-СЕРВЕР ДЛЯ RENDER ==========
class HealthHandler(BaseHTTPRequestHandler):
    """Обработчик HTTP-запросов для проверки здоровья"""
    
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        response = "🦉 Бот Викитория работает (игра для двоих)"
        self.wfile.write(response.encode('utf-8'))
    
    def log_message(self, format, *args):
        pass  # Отключаем логи HTTP

def run_http_server():
    """Запуск HTTP-сервера в отдельном потоке"""
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
    PERFORMER = "performer"  # Исполняющий
    WAITER = "waiter"        # Ожидающий

class GameStage(Enum):
    WHITE = "white"   # Этап 1: Разговор и флирт
    YELLOW = "yellow" # Этап 2: Тактильные игры
    RED = "red"       # Этап 3: Интимная глубина
    ENVELOPE = "envelope"  # Благодарственные карты

# Хранение данных в памяти
active_rooms = {}    # код комнаты -> данные комнаты
active_users = {}    # user_id -> данные пользователя
user_timers = {}     # user_id -> задача таймера

# ========== КАРТОЧКИ ДЛЯ ИГРЫ ==========
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
    """Получить случайную карту из колоды"""
    deck = CARDS_DATA.get(stage.value, [])
    return random.choice(deck) if deck else {"id": 0, "type": "info", "text": "Карточки временно отсутствуют"}

def has_timer_in_text(text: str) -> bool:
    """Проверить, есть ли в тексте упоминание времени"""
    time_words = ['минут', 'секунд', 'час', 'таймер', 'время', 'минуту', 'секунду']
    return any(word in text.lower() for word in time_words)

def has_photo_in_text(text: str) -> bool:
    """Проверить, нужно ли фото"""
    photo_words = ['фото', 'галере', 'снимок', 'фотограф']
    return any(word in text.lower() for word in photo_words)

# ========== КЛАВИАТУРЫ ==========
def main_menu_keyboard() -> InlineKeyboardMarkup:
    """Главное меню"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Начать игру 🦉", callback_data="create_room")],
        [InlineKeyboardButton(text="Присоединиться к игре", callback_data="join_room")],
        [InlineKeyboardButton(text="Правила игры", callback_data="show_rules")]
    ])

def back_to_main_keyboard() -> InlineKeyboardMarkup:
    """Кнопка назад в главное меню"""
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
            [InlineKeyboardButton(text="Ожидаю начала... ⏳", callback_data="wait")],
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
    
    # Кнопка кубика (для карт с кубиком)
    if "кубик" in card["text"].lower() or "брось" in card["text"].lower():
        buttons.append([InlineKeyboardButton(text="Бросить кубик 🎲", callback_data="roll_dice")])
    
    # Кнопка завершения игры
    buttons.append([InlineKeyboardButton(text="Завершить игру 🏁", callback_data="request_stop_game")])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def waiter_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура ожидающего"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Выполнено ✅", callback_data="task_done")],
        [InlineKeyboardButton(text="Пропустить ➡️", callback_data="skip_card")],
        [InlineKeyboardButton(text="Завершить игру 🏁", callback_data="request_stop_game")]
    ])

def stop_game_confirmation_keyboard() -> InlineKeyboardMarkup:
    """Подтверждение завершения игры"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Ну куда уж деваться 😔", callback_data="confirm_stop")],
        [InlineKeyboardButton(text="Да ладно, позже продолжим 😊", callback_data="postpone_stop")]
    ])

def postpone_response_keyboard() -> InlineKeyboardMarkup:
    """Ответ на предложение продолжить позже"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Ну ок, снизойду 🙄", callback_data="continue_game")],
        [InlineKeyboardButton(text="Завершить 🚫", callback_data="force_stop")]
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
        "• Интимную глубину ❤️\n\n"
        "Основные правила:\n"
        "✓ Всегда можно сказать 'Пропустить'\n"
        "✓ Уважайте границы друг друга\n"
        "✓ Говорите 'Ворчун!' если стало неловко\n"
        "✓ Описывайте ощущения через метафоры\n\n"
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
    
    # Уведомляем партнера, если есть активная игра
    if user_id in active_users:
        user_data = active_users[user_id]
        partner_id = user_data.get("partner_id")
        
        if partner_id and partner_id in active_users:
            await bot.send_message(
                partner_id,
                "🦉 Партнер вышел в главное меню. Игра завершена.",
                reply_markup=main_menu_keyboard()
            )
            # Очищаем данные партнера
            if partner_id in user_timers:
                user_timers[partner_id].cancel()
                del user_timers[partner_id]
            del active_users[partner_id]
        
        # Очищаем комнату
        room_code = user_data.get("room_code")
        if room_code and room_code in active_rooms:
            del active_rooms[room_code]
        
        # Очищаем свои данные
        del active_users[user_id]
    
    await callback.message.edit_text(
        "🦉 Выберите действие:",
        reply_markup=main_menu_keyboard()
    )

@router.callback_query(F.data == "create_room")
async def create_room_handler(callback: CallbackQuery):
    """Создание игровой комнаты"""
    user_id = callback.from_user.id
    room_code = ''.join(random.choices(string.ascii_uppercase, k=6))
    
    # Сохраняем данные пользователя
    active_users[user_id] = {
        "state": GameState.WAITING_PARTNER.value,
        "room_code": room_code,
        "stage": GameStage.WHITE.value,
        "created_at": datetime.now().isoformat()
    }
    
    # Сохраняем комнату
    active_rooms[room_code] = {
        "creator_id": user_id,
        "created_at": datetime.now().isoformat()
    }
    
    await callback.message.edit_text(
        f"🦉 Игровая комната создана!\n\n"
        f"Код для присоединения:\n"
        f"<code>{room_code}</code>\n\n"
        f"Отправьте этот код партнеру.\n"
        f"Ожидание: 5 минут\n\n"
        f"Партнер должен:\n"
        f"1. Нажать 'Присоединиться к игре'\n"
        f"2. Ввести код: {room_code}",
        parse_mode="HTML",
        reply_markup=waiting_partner_keyboard()
    )
    
    # Автоматическое удаление комнаты через 5 минут
    await asyncio.sleep(300)  # 5 минут
    if room_code in active_rooms:
        del active_rooms[room_code]
        if user_id in active_users and active_users[user_id].get("room_code") == room_code:
            del active_users[user_id]
            try:
                await callback.message.edit_text(
                    "⏰ Время ожидания истекло. Комната удалена.",
                    reply_markup=main_menu_keyboard()
                )
            except:
                pass

@router.callback_query(F.data == "join_room")
async def join_room_handler(callback: CallbackQuery):
    """Присоединение к игре"""
    await callback.message.edit_text(
        "✏️ Введите 6-значный код комнаты (только английские буквы, например: ABCDEF):",
        reply_markup=back_to_main_keyboard()
    )

@router.message(F.text.regexp(r'^[A-Z]{6}$'))
async def process_room_code(message: Message):
    """Обработка введенного кода комнаты"""
    room_code = message.text.upper()
    user_id = message.from_user.id
    
    if room_code not in active_rooms:
        await message.answer(
            "❌ Комната не найдена. Возможно:\n"
            "• Код введен неправильно\n"
            "• Время ожидания истекло (5 минут)\n"
            "• Комната уже началась\n\n"
            "Попросите партнера создать новую комнату.",
            reply_markup=main_menu_keyboard()
        )
        return
    
    if user_id in active_users:
        await message.answer(
            "❌ Вы уже участвуете в игре. Сначала завершите текущую.",
            reply_markup=main_menu_keyboard()
        )
        return
    
    creator_id = active_rooms[room_code]["creator_id"]
    
    if creator_id not in active_users:
        await message.answer(
            "❌ Создатель комнаты больше не в сети.",
            reply_markup=main_menu_keyboard()
        )
        del active_rooms[room_code]
        return
    
    # Обновляем данные создателя комнаты
    active_users[creator_id]["state"] = GameState.PARTNER_FOUND.value
    active_users[creator_id]["partner_id"] = user_id
    
    # Создаем данные для присоединившегося
    active_users[user_id] = {
        "state": GameState.PARTNER_FOUND.value,
        "room_code": room_code,
        "partner_id": creator_id,
        "stage": GameStage.WHITE.value
    }
    
    # Удаляем комнату из поиска
    del active_rooms[room_code]
    
    # Уведомляем создателя комнаты
    creator_name = message.from_user.first_name
    await bot.send_message(
        creator_id,
        f"🎉 Партнер {creator_name} присоединился!\n\n"
        f"Теперь вы можете начать игру.",
        reply_markup=partner_found_keyboard(is_creator=True)
    )
    
    # Уведомляем присоединившегося
    await message.answer(
        f"✅ Вы присоединились к комнате!\n"
        f"Ожидайте начала игры от создателя комнаты.",
        reply_markup=partner_found_keyboard(is_creator=False)
    )

@router.callback_query(F.data == "start_game")
async def start_game_handler(callback: CallbackQuery):
    """Начало игровой сессии"""
    user_id = callback.from_user.id
    
    if user_id not in active_users:
        await callback.answer("❌ Ошибка: данные не найдены", show_alert=True)
        return
    
    user_data = active_users[user_id]
    partner_id = user_data.get("partner_id")
    
    if not partner_id or partner_id not in active_users:
        await callback.answer("❌ Партнер не найден", show_alert=True)
        return
    
    partner_data = active_users[partner_id]
    
    # Случайно определяем роли
    is_user_performer = random.random() > 0.5
    user_data["role"] = PlayerRole.PERFORMER.value if is_user_performer else PlayerRole.WAITER.value
    partner_data["role"] = PlayerRole.WAITER.value if is_user_performer else PlayerRole.PERFORMER.value
    
    # Обновляем состояния
    user_data["state"] = GameState.IN_GAME.value
    partner_data["state"] = GameState.IN_GAME.value
    
    user_role_name = "Исполняющий" if user_data["role"] == PlayerRole.PERFORMER.value else "Ожидающий"
    partner_role_name = "Исполняющий" if partner_data["role"] == PlayerRole.PERFORMER.value else "Ожидающий"
    
    # Уведомляем обоих игроков
    await callback.message.edit_text(
        f"🎮 Игра началась!\n\n"
        f"Ваша роль: <b>{user_role_name}</b>\n"
        f"Этап: Белая колода 🤍\n\n"
        f"<i>Правила ролей:</i>\n"
        f"• <b>Исполняющий</b> - выполняет задание\n"
        f"• <b>Ожидающий</b> - следит за выполнением",
        parse_mode="HTML"
    )
    
    await bot.send_message(
        partner_id,
        f"🎮 Игра началась!\n\n"
        f"Ваша роль: <b>{partner_role_name}</b>\n"
        f"Этап: Белая колода 🤍\n\n"
        f"<i>Правила ролей:</i>\n"
        f"• <b>Исполняющий</b> - выполняет задание\n"
        f"• <b>Ожидающий</b> - следит за выполнением",
        parse_mode="HTML"
    )
    
    # Раздаем первую карту исполнителю
    performer_id = user_id if user_data["role"] == PlayerRole.PERFORMER.value else partner_id
    await send_next_card(performer_id)

async def send_next_card(user_id: int):
    """Отправка следующей карточки исполнителю"""
    if user_id not in active_users:
        return
    
    user_data = active_users[user_id]
    
    if user_data["state"] != GameState.IN_GAME.value:
        return
    
    # Получаем карту для текущего этапа
    stage = GameStage(user_data["stage"])
    card = get_random_card(stage)
    user_data["current_card"] = card
    
    # Отправляем карту исполнителю
    if user_data["role"] == PlayerRole.PERFORMER.value:
        card_text = f"🎴 Ваше задание:\n\n{card['text']}"
        
        # Добавляем подсказку для карт с кубиком
        if "кубик" in card["text"].lower():
            card_text += "\n\n🎲 Используйте кнопку 'Бросить кубик'"
        
        await bot.send_message(user_id, card_text, reply_markup=performer_keyboard(card))
        
        # Отправляем ожидающему информацию о задании
        partner_id = user_data.get("partner_id")
        if partner_id and partner_id in active_users:
            await bot.send_message(
                partner_id,
                f"🎴 Задание партнера:\n\n{card['text']}",
                reply_markup=waiter_keyboard()
            )

# ========== ОБРАБОТКА ИГРОВЫХ ДЕЙСТВИЙ ==========
@router.callback_query(F.data == "task_done")
async def task_done_handler(callback: CallbackQuery):
    """Задание выполнено"""
    user_id = callback.from_user.id
    
    if user_id not in active_users:
        await callback.answer("❌ Ошибка: данные не найдены", show_alert=True)
        return
    
    user_data = active_users[user_id]
    
    if user_data["role"] == PlayerRole.WAITER.value:
        # Ожидающий подтверждает выполнение
        await switch_roles(user_id)
        await callback.answer("✅ Задание выполнено!")
    else:
        # Исполняющий пытается нажать "Выполнил" - нужно ждать подтверждения партнера
        await callback.answer("⏳ Дождитесь подтверждения от партнера", show_alert=True)

@router.callback_query(F.data == "skip_card")
async def skip_card_handler(callback: CallbackQuery):
    """Пропуск текущей карточки"""
    user_id = callback.from_user.id
    
    if user_id not in active_users:
        await callback.answer("❌ Ошибка: данные не найдены", show_alert=True)
        return
    
    user_data = active_users[user_id]
    card = user_data.get("current_card", {})
    
    # Уведомляем партнера о пропуске
    partner_id = user_data.get("partner_id")
    if partner_id and partner_id in active_users:
        await bot.send_message(
            partner_id,
            f"⏩ Партнер пропустил карточку:\n\n{card.get('text', '')}\n\n"
            f"Теперь ваш ход!",
            reply_markup=waiter_keyboard()
        )
    
    # Меняем роли
    await switch_roles(user_id)
    await callback.answer("Карточка пропущена")

async def switch_roles(user_id: int):
    """Смена ролей между игроками"""
    if user_id not in active_users:
        return
    
    user_data = active_users[user_id]
    partner_id = user_data.get("partner_id")
    
    if not partner_id or partner_id not in active_users:
        return
    
    partner_data = active_users[partner_id]
    
    # Меняем роли
    user_data["role"] = PlayerRole.WAITER.value if user_data["role"] == PlayerRole.PERFORMER.value else PlayerRole.PERFORMER.value
    partner_data["role"] = PlayerRole.PERFORMER.value if user_data["role"] == PlayerRole.WAITER.value else PlayerRole.WAITER.value
    
    # Очищаем текущие карты
    user_data["current_card"] = None
    partner_data["current_card"] = None
    
    # Отправляем новую карту новому исполнителю
    new_performer_id = user_id if user_data["role"] == PlayerRole.PERFORMER.value else partner_id
    await send_next_card(new_performer_id)

@router.callback_query(F.data == "start_timer")
async def start_timer_handler(callback: CallbackQuery):
    """Запуск таймера для задания"""
    user_id = callback.from_user.id
    
    if user_id not in active_users:
        await callback.answer("❌ Ошибка", show_alert=True)
        return
    
    user_data = active_users[user_id]
    card = user_data.get("current_card", {})
    text = card.get("text", "")
    
    # Парсим время из текста задания
    minutes = 5  # значение по умолчанию
    time_match = re.search(r'(\d+)\s*минут', text)
    if time_match:
        minutes = int(time_match.group(1))
    
    seconds = minutes * 60
    
    # Запускаем таймер
    if user_id in user_timers:
        user_timers[user_id].cancel()
    
    async def timer_task():
        try:
            msg = await bot.send_message(user_id, f"⏱️ Таймер запущен: {minutes} мин")
            
            # Настройка интервалов уведомлений
            intervals = []
            if seconds > 900:  # > 15 минут
                intervals = list(range(seconds, 0, -300))  # каждые 5 минут
            elif seconds > 120:  # > 2 минут
                intervals = list(range(seconds, 0, -60))   # каждую минуту
            elif seconds > 60:
                intervals = list(range(seconds, 0, -10))   # каждые 10 секунд
            elif seconds > 20:
                intervals = list(range(seconds, 0, -5))    # каждые 5 секунд
            else:
                intervals = list(range(seconds, 0, -1))    # каждую секунду
            
            for remaining in intervals[1:]:
                await asyncio.sleep(intervals[0] - remaining)
                if remaining > 60:
                    await bot.edit_message_text(
                        chat_id=user_id,
                        message_id=msg.message_id,
                        text=f"⏱️ Осталось: {remaining // 60} мин {remaining % 60} сек"
                    )
                else:
                    await bot.edit_message_text(
                        chat_id=user_id,
                        message_id=msg.message_id,
                        text=f"⏱️ Осталось: {remaining} сек"
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
            logger.error(f"Ошибка таймера: {e}")
    
    user_timers[user_id] = asyncio.create_task(timer_task())
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

@router.callback_query(F.data == "request_stop_game")
async def request_stop_game_handler(callback: CallbackQuery):
    """Запрос на завершение игры"""
    user_id = callback.from_user.id
    
    if user_id not in active_users:
        await callback.answer("❌ Ошибка: данные не найдены", show_alert=True)
        return
    
    user_data = active_users[user_id]
    
    if not user_data.get("partner_id"):
        await callback.answer("❌ Нет активного партнера", show_alert=True)
        return
    
    user_data["state"] = GameState.AWAITING_CONFIRMATION.value
    
    await callback.message.edit_text(
        "Вы уверены, что хотите завершить игру?\n\n"
        "Партнер получит запрос на подтверждение.",
        reply_markup=stop_game_confirmation_keyboard()
    )

@router.callback_query(F.data == "confirm_stop")
async def confirm_stop_handler(callback: CallbackQuery):
    """Подтверждение завершения игры"""
    user_id = callback.from_user.id
    
    if user_id not in active_users:
        await callback.answer("❌ Ошибка", show_alert=True)
        return
    
    user_data = active_users[user_id]
    partner_id = user_data.get("partner_id")
    
    # Уведомляем партнера
    if partner_id:
        await bot.send_message(
            partner_id,
            "🦉 Партнер завершил игру. Возврат в главное меню.",
            reply_markup=main_menu_keyboard()
        )
        
        # Очищаем данные партнера
        if partner_id in active_users:
            if partner_id in user_timers:
                user_timers[partner_id].cancel()
                del user_timers[partner_id]
            del active_users[partner_id]
    
    # Очищаем свои данные
    if user_id in user_timers:
        user_timers[user_id].cancel()
        del user_timers[user_id]
    
    if user_id in active_users:
        del active_users[user_id]
    
    await callback.message.edit_text(
        "🦉 Игра завершена. Спасибо за участие!",
        reply_markup=main_menu_keyboard()
    )

@router.callback_query(F.data == "show_rules")
async def show_rules_handler(callback: CallbackQuery):
    """Показать правила игры"""
    rules = (
        "📜 Правила игры 'Викитория':\n\n"
        "🎯 Цель: Создать атмосферу для постепенного сближения\n\n"
        "📋 Основные правила:\n"
        "1. Всегда можно сказать 'Пропустить'\n"
        "2. Уважайте границы друг друга\n"
        "3. Говорите 'Ворчун!' если стало неловко\n"
        "4. Описывайте ощущения через метафоры\n\n"
        "🎴 Этапы игры:\n"
        "• 🤍 Белый - Разговор и флирт\n"
        "• 💛 Жёлтый - Тактильные игры\n"
        "• ❤️ Красный - Интимная глубина\n\n"
        "👥 Роли в игре:\n"
        "• Исполняющий - выполняет задание\n"
        "• Ожидающий - следит за выполнением\n\n"
        "🔄 Как играть:\n"
        "1. Один создаёт комнату, второй присоединяется\n"
        "2. Исполняющий получает задание\n"
        "3. Ожидающий следит за выполнением\n"
        "4. После выполнения меняемся ролями"
    )
    
    await callback.message.edit_text(rules, reply_markup=back_to_main_keyboard())

# ========== ЗАПУСК БОТА ==========
async def main():
    """Основная функция запуска бота"""
    # Даем время HTTP-серверу запуститься
    await asyncio.sleep(1)
    
    # Получаем информацию о боте
    bot_info = await bot.get_me()
    
    logger.info("=" * 50)
    logger.info("🚀 ЗАПУСК БОТА 'ВИКИТОРИЯ'")
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
