import asyncio
import logging
import random
import sqlite3
import os  # Добавь это в самый верх к импортам

from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, Message

# --- НАСТРОЙКИ ---
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = 123456789 # Твой ID (узнай его в @userinfobot)
DB_PATH = "/app/data/telegram-bot1" # Путь для Railway Volume

# --- БАЗА ДАННЫХ ---
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('''CREATE TABLE IF NOT EXISTS users 
                   (id INTEGER PRIMARY KEY, balance INTEGER DEFAULT 10000, last_bonus TEXT)''')
    cur.execute('''CREATE TABLE IF NOT EXISTS history (number INTEGER, color TEXT)''')
    conn.commit()
    conn.close()

def get_user(user_id):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT balance, last_bonus FROM users WHERE id = ?", (user_id,))
    res = cur.fetchone()
    if not res:
        cur.execute("INSERT INTO users (id) VALUES (?)", (user_id,))
        conn.commit()
        res = (10000, None)
    conn.close()
    return res

def update_balance(user_id, amount):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("UPDATE users SET balance = balance + ? WHERE id = ?", (amount, user_id))
    conn.commit()
    conn.close()

# --- БОТ И ЛОГИКА ---
bot = Bot(token=TOKEN)
dp = Dispatcher()
logging.basicConfig(level=logging.INFO)

class GameStates(StatesGroup):
    guessing = State()

# Групповые ставки
pending_bets = {} # {chat_id: [{user_id, amount, targets}]}

# Клавиатуры
def get_kb(chat_type):
    buttons = [
        [KeyboardButton(text="🎮 Играть"), KeyboardButton(text="👤 Профиль")]
    ]
    if chat_type == "private":
        buttons.append([KeyboardButton(text="🏆 Рейтинг"), KeyboardButton(text="🎁 Бонус")])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

@dp.message(Command("start"))
async def start(message: Message):
    get_user(message.from_user.id)
    kb = get_kb(message.chat.type)
    await message.answer(f"Привет! Я Бутя. Даю 10 000 Угадаек на старт!", reply_markup=kb)

# --- КОМАНДА Б (Баланс) ---
@dp.message(F.text.lower() == "б")
async def balance(message: Message):
    data = get_user(message.from_user.id)
    await message.answer(f"💰 Твой баланс: {data[0]} Угадаек")

# --- КОМАНДА П (Перевод) ---
@dp.message(F.text.lower().startswith("п "), F.reply_to_message)
async def transfer(message: Message):
    try:
        amount = int(message.text.split()[1])
        sender_id = message.from_user.id
        receiver_id = message.reply_to_message.from_user.id
        
        if amount <= 0: return
        
        balance, _ = get_user(sender_id)
        if balance < amount:
            return await message.answer("❌ Недостаточно Угадаек!")
            
        update_balance(sender_id, -amount)
        update_balance(receiver_id, amount)
        await message.answer(f"✅ Переведено {amount} Угадаек пользователю {message.reply_to_message.from_user.first_name}")
    except:
        pass

# --- РУЛЕТКА ---
@dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower() == "го")
async def spin_roulette(message: Message):
    chat_id = message.chat.id
    if chat_id not in pending_bets or not pending_bets[chat_id]:
        return await message.answer("🎰 Ставок пока нет!")

    win_num = random.randint(0, 36)
    colors = {0: "🟢"}
    for i in range(1, 37): colors[i] = "🔴" if i % 2 == 0 else "⚫️" # Упростим
    
    res_text = f"🎡 Выпало: {colors[win_num]} {win_num}\n\n"
    
    # Тут будет логика расчета победителей на основе твоих формул...
    # (Для краткости примера опустим детальный парсинг, но структура такая)
    
    pending_bets[chat_id] = []
    await message.answer(res_text)

# --- АДМИН ПАНЕЛЬ ---
@dp.message(F.reply_to_message, lambda m: m.from_user.id == ADMIN_ID)
async def admin_mod(message: Message):
    if message.text.startswith(("+", "-")):
        try:
            val = int(message.text)
            update_balance(message.reply_to_message.from_user.id, val)
            await message.answer(f"⚙️ Баланс изменен на {val}")
        except: pass

async def main():
    init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

