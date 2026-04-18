import os
import asyncio
import logging
import random
import sqlite3
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, Message, ReplyKeyboardRemove

# --- НАСТРОЙКИ ---
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = 1316137517   # ЗАМЕНИ НА СВОЙ ID (узнай в @userinfobot)
DB_PATH = "/app/data/butya.db"

# --- БАЗА ДАННЫХ ---
def init_db():
    if not os.path.exists("/app/data"):
        os.makedirs("/app/data")
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('''CREATE TABLE IF NOT EXISTS users 
                   (id INTEGER PRIMARY KEY, balance INTEGER DEFAULT 10000, last_bonus TEXT)''')
    cur.execute('''CREATE TABLE IF NOT EXISTS history (number INTEGER)''')
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
    cur.execute("UPDATE users SET balance = balance + ? WHERE id = ?", (int(amount), user_id))
    conn.commit()
    conn.close()

# --- СОСТОЯНИЯ ---
class GameStates(StatesGroup):
    guessing = State()

# Временное хранилище ставок: {chat_id: {user_id: [список ставок]}}
pending_bets = {}

# --- КЛАВИАТУРЫ ---
def get_main_kb(chat_type):
    if chat_type == "private":
        return ReplyKeyboardMarkup(keyboard=[
            [KeyboardButton(text="🎮 Играть"), KeyboardButton(text="👤 Профиль")],
            [KeyboardButton(text="🏆 Рейтинг"), KeyboardButton(text="🎁 Бонус")]
        ], resize_keyboard=True)
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🎮 Играть"), KeyboardButton(text="👤 Профиль")]
    ], resize_keyboard=True)

# --- ИНИЦИАЛИЗАЦИЯ ---
bot = Bot(token=TOKEN)
dp = Dispatcher()
logging.basicConfig(level=logging.INFO)

# --- КОМАНДЫ ---

@dp.message(Command("start"))
async def cmd_start(message: Message):
    get_user(message.from_user.id)
    await message.answer("Привет! Я Бутя. Даю 10 000 Угадаек! Играй в рулетку или угадай число.", 
                         reply_markup=get_main_kb(message.chat.type))

@dp.message(F.text == "👤 Профиль")
@dp.message(F.text.lower() == "б")
async def show_profile(message: Message):
    balance, _ = get_user(message.from_user.id)
    await message.answer(f"💰 Ваш баланс: **{balance}** Угадаек.", parse_mode="Markdown")

@dp.message(F.text.lower().startswith("п "), F.reply_to_message)
async def transfer(message: Message):
    try:
        amount = int(message.text.split()[1])
        sender_id = message.from_user.id
        receiver = message.reply_to_message.from_user
        if amount <= 0 or sender_id == receiver.id: return
        
        bal, _ = get_user(sender_id)
        if bal < amount: return await message.answer("❌ Недостаточно Угадаек!")
        
        update_balance(sender_id, -amount)
        update_balance(receiver.id, amount)
        await message.answer(f"✅ Переведено {amount} Угадаек для {receiver.first_name}")
    except: pass

# --- МИНИ-ИГРА: УГАДАЙ ЧИСЛО ---
@dp.message(F.text == "🎮 Играть")
async def start_guess(message: Message, state: FSMContext):
    num = random.randint(1, 10)
    await state.set_state(GameStates.guessing)
    await state.update_data(target=num, attempts=3)
    await message.answer("Я загадал число от 1 до 10. У тебя 3 попытки! Пиши число:")

@dp.message(GameStates.guessing)
async def process_guess(message: Message, state: FSMContext):
    if not message.text.isdigit(): return
    guess = int(message.text)
    data = await state.get_data()
    target = data['target']
    attempts = data['attempts'] - 1

    if guess == target:
        update_balance(message.from_user.id, 50)
        await message.answer("🎉 Угадал! +50 Угадаек.", reply_markup=get_main_kb(message.chat.type))
        await state.clear()
    elif attempts > 0:
        hint = "Больше!" if target > guess else "Меньше!"
        await state.update_data(attempts=attempts)
        await message.answer(f"Неверно. {hint} Осталось попыток: {attempts}")
    else:
        await message.answer(f"Попытки кончились! Это было {target}.", reply_markup=get_main_kb(message.chat.type))
        await state.clear()

# --- РУЛЕТКА ---
@dp.message(lambda m: m.text and m.text[0].isdigit())
async def take_bet(message: Message):
    parts = message.text.split()
    try:
        amount = int(parts[0])
        targets = parts[1:]
        if not targets or amount <= 0: return
        
        bal, _ = get_user(message.from_user.id)
        total_needed = amount * len(targets)
        if bal < total_needed: return await message.answer("❌ Не хватает Угадаек!")
        
        cid = message.chat.id
        if cid not in pending_bets: pending_bets[cid] = []
        
        pending_bets[cid].append({"user_id": message.from_user.id, "name": message.from_user.first_name, "amount": amount, "targets": targets})
        update_balance(message.from_user.id, -total_needed)
        
        report = f"✅ Ставок: {len(targets)}\n💸 Потрачено: {total_needed}\n\n📊 Твои ставки:\n"
        for t in targets: report += f"• {amount} ➔ {t}\n"
        await message.answer(report)
    except: pass

@dp.message(F.text.lower() == "го")
async def spin(message: Message):
    cid = message.chat.id
    if cid not in pending_bets: return
    
    win_num = random.randint(0, 36)
    conn = sqlite3.connect(DB_PATH); cur = conn.cursor()
    cur.execute("INSERT INTO history (number) VALUES (?)", (win_num,))
    conn.commit(); conn.close()
    
    color = "🟢" if win_num == 0 else ("🔴" if win_num % 2 == 0 else "⚫️")
    res_text = f"🎡 Выпало: {color} {win_num}\n\nИТОГИ:\n"
    
    for bet in pending_bets[cid]:
        win_sum = 0
        for t in bet['targets']:
            is_win = False
            mult = 0
            if t == "кр" and win_num != 0 and win_num % 2 == 0: is_win, mult = True, 2
            elif t == "чр" and win_num % 2 != 0: is_win, mult = True, 2
            elif t == "чет" and win_num != 0 and win_num % 2 == 0: is_win, mult = True, 2
            elif t == "нечет" and win_num % 2 != 0: is_win, mult = True, 2
            elif "-" in t:
                low, high = map(int, t.split("-"))
                if low <= win_num <= high:
                    is_win, mult = True, 36 / (high - low + 1)
            elif t.isdigit() and int(t) == win_num: is_win, mult = True, 36
            
            if is_win: win_sum += int(bet['amount'] * mult)
            
        if win_sum > 0:
            update_balance(bet['user_id'], win_sum)
            res_text += f"✅ {bet['name']} выиграл {win_sum}!\n"
        else:
            res_text += f"❌ {bet['name']} проиграл.\n"
            
    pending_bets[cid] = []
    await message.answer(res_text)

@dp.message(F.text.lower() == "лог")
async def show_log(message: Message):
    conn = sqlite3.connect(DB_PATH); cur = conn.cursor()
    cur.execute("SELECT number FROM history ORDER BY rowid DESC LIMIT 10")
    res = cur.fetchall(); conn.close()
    if not res: return await message.answer("История пуста")
    out = "📜 Лог: " + ", ".join([str(r[0]) for r in res])
    await message.answer(out)

# --- АДМИНКА ---
@dp.message(F.reply_to_message, lambda m: m.from_user.id == ADMIN_ID)
async def admin_power(message: Message):
    if message.text.startswith(("+", "-")):
        try:
            val = int(message.text)
            update_balance(message.reply_to_message.from_user.id, val)
            await message.answer(f"👑 Изменено на {val}")
        except: pass

async def main():
    init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
