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
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, Message

# --- НАСТРОЙКИ ---
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = 1316137517  # ЗАМЕНИ НА СВОЙ ID
DB_PATH = "/app/data/butya.db
"

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

# --- СОСТОЯНИЯ И ПАМЯТЬ ---
class GameStates(StatesGroup):
    guessing = State()

pending_bets = {}

# --- КЛАВИАТУРЫ ---
def get_main_kb(chat_type):
    if chat_type == "private":
        return ReplyKeyboardMarkup(keyboard=[
            [KeyboardButton(text="🎮 Играть"), KeyboardButton(text="👤 Профиль")],
            [KeyboardButton(text="🏆 Рейтинг"), KeyboardButton(text="🎁 Бонус")]
        ], resize_keyboard=True)
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🎮 Играть"), KeyboardButton(text="👤 Профиль")],
        [KeyboardButton(text="📊 Ставки"), KeyboardButton(text="🚫 Отмена")]
    ], resize_keyboard=True)

# --- ИНИЦИАЛИЗАЦИЯ ---
bot = Bot(token=TOKEN)
dp = Dispatcher()
logging.basicConfig(level=logging.INFO)

# --- БАЗОВЫЕ КОМАНДЫ ---
@dp.message(Command("start"))
async def cmd_start(message: Message):
    get_user(message.from_user.id)
    await message.answer(f"Привет! Я Бутя. Даю 10000 Угадаек! Играй в рулетку или угадай число.", 
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
        await message.answer(f"🎉 Угадал! +50 Угадаек.", reply_markup=get_main_kb(message.chat.type))
        await state.clear()
    elif attempts > 0:
        hint = "Больше!" if target > guess else "Меньше!"
        await state.update_data(attempts=attempts)
        await message.answer(f"Неверно. {hint} Осталось попыток: {attempts}")
    else:
        await message.answer(f"Попытки кончились! Это было {target}.", reply_markup=get_main_kb(message.chat.type))
        await state.clear()

# --- УПРАВЛЕНИЕ СТАВКАМИ ---
@dp.message(F.text == "📊 Ставки")
async def show_my_bets(message: Message):
    cid = message.chat.id
    uid = message.from_user.id
    if cid not in pending_bets or not any(b['user_id'] == uid for b in pending_bets[cid]):
        return await message.answer("У тебя пока нет активных ставок в этом раунде.")
    
    my_bets = [b for b in pending_bets[cid] if b['user_id'] == uid]
    text = "📝 Твои текущие ставки:\n"
    for b in my_bets:
        for t in b['targets']:
            text += f"• {b['amount']} ➔ {t}\n"
    await message.answer(text)

@dp.message(F.text == "🚫 Отмена")
async def cancel_my_bets(message: Message):
    cid = message.chat.id
    uid = message.from_user.id
    if cid in pending_bets:
        refund = sum(b['amount'] * len(b['targets']) for b in pending_bets[cid] if b['user_id'] == uid)
        if refund > 0:
            pending_bets[cid] = [b for b in pending_bets[cid] if b['user_id'] != uid]
            update_balance(uid, refund)
            await message.answer(f"✅ Твои ставки отменены. {refund} Угадаек возвращены на баланс.")
        else:
            await message.answer("У тебя нет активных ставок.")

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
    if cid not in pending_bets or not pending_bets[cid]:
        return await message.answer("🎰 Ставок пока нет!")
    
    win_num = random.randint(0, 36)
    
    conn = sqlite3.connect(DB_PATH); cur = conn.cursor()
    cur.execute("INSERT INTO history (number) VALUES (?)", (win_num,))
    conn.commit(); conn.close()
    
    if win_num == 0: color_emoji, color_text = "🟢", "ЗЕРО"
    elif win_num % 2 == 0: color_emoji, color_text = "🔴", "КРАСНОЕ"
    else: color_emoji, color_text = "⚫", "ЧЁРНОЕ"
        
    res_text = f"🎰 {color_emoji} {color_text} {win_num}\n\n"
    users_results = {} 

    for bet in pending_bets[cid]:
        uid = bet['user_id']
        if uid not in users_results:
            users_results[uid] = {"name": bet['name'], "results": [], "total_win": 0, "total_spent": 0}
        
        current_spent = bet['amount'] * len(bet['targets'])
        users_results[uid]["total_spent"] += current_spent
        
        for t in bet['targets']:
            is_win = False
            mult = 0
            if t in ["к", "кр", "красное"] and win_num != 0 and win_num % 2 == 0: is_win, mult = True, 2
            elif t in ["ч", "чр", "черное"] and win_num % 2 != 0: is_win, mult = True, 2
            elif t == "чет" and win_num != 0 and win_num % 2 == 0: is_win, mult = True, 2
            elif t == "нечет" and win_num % 2 != 0: is_win, mult = True, 2
            elif "-" in t:
                try:
                    low, high = map(int, t.split("-"))
                    if low <= win_num <= high: is_win, mult = True, 36 / (high - low + 1)
                except: pass
            elif t.isdigit() and int(t) == win_num: is_win, mult = True, 36
            
            if is_win:
                win_val = int(bet['amount'] * mult)
                users_results[uid]["total_win"] += win_val
                users_results[uid]["results"].append(f"✅ {bet['amount']} ➔ {t} (+{win_val})")
            else:
                users_results[uid]["results"].append(f"❌ {bet['amount']} ➔ {t}")

    for uid, data in users_results.items():
        res_text += f"👤 {data['name']}:\n"
        res_text += "\n".join(data['results']) + "\n"
        
        final_profit = data['total_win'] - data['total_spent']
        profit_sign = "+" if final_profit >= 0 else ""
        res_text += f"💰 Итог: {profit_sign}{abs(final_profit)}\n\n"
        
        if data['total_win'] > 0:
            update_balance(uid, data['total_win'])
            
    pending_bets[cid] = [] 
    await message.answer(res_text)

# --- ИСТОРИЯ ---
@dp.message(F.text.lower() == "лог")
async def show_log(message: Message):
    conn = sqlite3.connect(DB_PATH); cur = conn.cursor()
    cur.execute("SELECT number FROM history ORDER BY rowid DESC LIMIT 10")
    res = cur.fetchall(); conn.close()
    
    if not res: return await message.answer("История пуста")

    out = "📜 История:\n\n"
    for i, row in enumerate(res, 1):
        num = row[0]
        col = "🟢 ЗЕРО" if num == 0 else ("🔴 КРАСНОЕ" if num % 2 == 0 else "⚫ ЧЁРНОЕ")
        out += f"{i}. 🎰 {col} {num}\n"
    await message.answer(out)

# --- АДМИНКА ---
@dp.message(F.reply_to_message, lambda m: m.from_user.id == ADMIN_ID)
async def admin_power(message: Message):
    if message.text.startswith(("+", "-")):
        try:
            val = int(message.text.replace(" ", ""))
            update_balance(message.reply_to_message.from_user.id, val)
            await message.answer(f"👑 Изменено на {val}")
        except: pass

async def main():
    init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
