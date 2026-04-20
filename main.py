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
ADMIN_ID = 1316137517 
DB_PATH = "/app/data/butya.db"

# --- ФУНКЦИЯ ДЛЯ КРАСИВЫХ ЧИСЕЛ ---
def fmt(num):
    return f"{int(num):,}".replace(",", " ")

# --- БАЗА ДАННЫХ ---
def init_db():
    if not os.path.exists("/app/data"):
        os.makedirs("/app/data")
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('''CREATE TABLE IF NOT EXISTS users 
                   (id INTEGER PRIMARY KEY, balance INTEGER DEFAULT 10000, last_bonus TEXT, name TEXT)''')
    try:
        cur.execute("ALTER TABLE users ADD COLUMN name TEXT")
    except:
        pass
    cur.execute('''CREATE TABLE IF NOT EXISTS history (number INTEGER)''')
    conn.commit()
    conn.close()

def get_user(user_id, name):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT balance, last_bonus FROM users WHERE id = ?", (user_id,))
    res = cur.fetchone()
    if not res:
        cur.execute("INSERT INTO users (id, balance, name) VALUES (?, ?, ?)", (user_id, 10000, name))
        conn.commit()
        res = (10000, None)
    else:
        cur.execute("UPDATE users SET name = ? WHERE id = ?", (name, user_id))
        conn.commit()
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

bot = Bot(token=TOKEN)
dp = Dispatcher()
logging.basicConfig(level=logging.INFO)

# --- КОМАНДЫ ---
@dp.message(Command("start"))
async def cmd_start(message: Message):
    get_user(message.from_user.id, message.from_user.full_name)
    await message.answer(f"Привет! Я Бутя. Даю {fmt(10000)} Угадаек!", reply_markup=get_main_kb(message.chat.type))

@dp.message(F.text == "👤 Профиль")
@dp.message(F.text.lower() == "б")
async def show_profile(message: Message):
    balance, _ = get_user(message.from_user.id, message.from_user.full_name)
    await message.answer(f"💰 Ваш баланс: **{fmt(balance)}** Угадаек.", parse_mode="Markdown")

@dp.message(F.text.lower().startswith("п "), F.reply_to_message)
async def transfer(message: Message):
    try:
        amount = int(message.text.split()[1])
        sender_id = message.from_user.id
        receiver = message.reply_to_message.from_user
        if amount <= 0 or sender_id == receiver.id: return
        
        bal, _ = get_user(sender_id, message.from_user.full_name)
        if bal < amount: return await message.answer("❌ Недостаточно Угадаек!")
        
        update_balance(sender_id, -amount)
        update_balance(receiver.id, amount)
        await message.answer(f"✅ Переведено {fmt(amount)} Угадаек для {receiver.first_name}")
    except: pass

@dp.message(F.text == "🎁 Бонус")
async def get_bonus(message: Message):
    # Тут важно передать full_name
    res = get_user(message.from_user.id, message.from_user.full_name)
    balance, last_bonus_str = res
    
    now = datetime.now()
    if last_bonus_str:
        last_b = datetime.fromisoformat(last_bonus_str)
        if now - last_b < timedelta(hours=24):
            left = timedelta(hours=24) - (now - last_b)
            hours, remainder = divmod(left.seconds, 3600)
            minutes, _ = divmod(remainder, 60)
            return await message.answer(f"⏳ Бонус уже получен!\nВозвращайся через **{hours} ч. {minutes} мин.**")

    bonus_amount = random.randint(100, 5000)
    conn = sqlite3.connect(DB_PATH); cur = conn.cursor()
    cur.execute("UPDATE users SET balance = balance + ?, last_bonus = ? WHERE id = ?", 
                (bonus_amount, now.isoformat(), message.from_user.id))
    conn.commit(); conn.close()
    await message.answer(f"🎁 Ты получил бонус: **{fmt(bonus_amount)}** Угадаек!")

@dp.message(F.text == "🏆 Рейтинг")
async def show_rating(message: Message):
    conn = sqlite3.connect(DB_PATH); cur = conn.cursor()
    cur.execute("SELECT name, balance, id FROM users ORDER BY balance DESC LIMIT 10")
    top_users = cur.fetchall(); conn.close()
    if not top_users: return await message.answer("Рейтинг пока пуст.")

    text = "🏆 <b>ТОП-10 БОГАЧЕЙ:</b>\n\n"
    medals = ["🥇", "🥈", "🥉"]
    for i, (name, bal, uid) in enumerate(top_users):
        medal = medals[i] if i < 3 else f"<b>{i+1}.</b>"
        display_name = name if name else "Игрок"
        text += f"{medal} <a href='tg://user?id={uid}'>{display_name}</a> — <b>{fmt(bal)}</b>\n"
    await message.answer(text, parse_mode="HTML")

@dp.message(F.text == "📊 Ставки")
async def show_my_bets(message: Message):
    cid = message.chat.id
    uid = message.from_user.id
    if cid not in pending_bets or not any(b['user_id'] == uid for b in pending_bets[cid]):
        return await message.answer("У тебя нет активных ставок.")
    
    my_bets = [b for b in pending_bets[cid] if b['user_id'] == uid]
    text = "📝 Твои текущие ставки:\n"
    for b in my_bets:
        for t in b['targets']:
            text += f"• {fmt(b['amount'])} ➔ {t}\n"
    await message.answer(text)

@dp.message(F.text == "🚫 Отмена")
async def cancel_my_bets(message: Message):
    cid = message.chat.id
    uid = message.from_user.id
    if cid in pending_bets:
        user_bets = [b for b in pending_bets[cid] if b['user_id'] == uid]
        if user_bets:
            refund = sum(b['amount'] * len(b['targets']) for b in user_bets)
            pending_bets[cid] = [b for b in pending_bets[cid] if b['user_id'] != uid]
            update_balance(uid, refund)
            return await message.answer(f"✅ Ставки отменены. Возвращено: {fmt(refund)}")
    await message.answer("У тебя нет активных Ставок")

#--------Рулетка-------
@dp.message(lambda m: m.text and (m.text.split()[0].isdigit() or m.text.lower().startswith("все") or m.text.lower().startswith("всё")))
async def take_bet(message: Message):
    if message.chat.type == "private":
    return await message.answer("🎰 В рулетку можно играть только в группах! Добавь меня в чат с друзьями.")
    parts = message.text.split()
    if len(parts) < 2:
        return 

    try:
        # === НОВАЯ ПРОВЕРКА ЦЕЛЕЙ СТАВКИ ===
        raw_targets = [t.lower() for t in parts[1:]]
        valid_targets = []
        invalid_targets = []
        
        for t in raw_targets:
            # Проверяем цвета и чет/нечет
            if t in ["к", "кр", "красное", "ч", "чр", "черное", "чет", "нечет"]:
                valid_targets.append(t)
            # Проверяем конкретные числа от 0 до 36
            elif t.isdigit() and 0 <= int(t) <= 36:
                valid_targets.append(t)
            # Проверяем диапазоны (например, 1-12)
            elif "-" in t:
                try:
                    low, high = map(int, t.split("-"))
                    if 0 <= low <= 36 and 0 <= high <= 36 and low < high:
                        valid_targets.append(t)
                    else:
                        invalid_targets.append(t)
                except:
                    invalid_targets.append(t)
            else:
                invalid_targets.append(t)
                
        # Если есть хоть одна ошибка (опечатка), отменяем ставку полностью
        if invalid_targets:
            return await message.answer(f"❌ Ошибка в купоне!\nЯ не понимаю эти ставки: **{', '.join(invalid_targets)}**\n\nРазрешены: числа (0-36), цвета (к, ч), чет/нечет и диапазоны (например 1-18).", parse_mode="Markdown")
        
        # Если всё верно, продолжаем работу
        targets = valid_targets
        count = len(targets)

        uid = message.from_user.id
        user_name = message.from_user.full_name
        res = get_user(uid, user_name)
        bal = res[0]
        
        first_word = parts[0].lower() 

        if first_word in ["все", "всё"]:
            amount = bal // count  
            if amount <= 0:
                return await message.answer("❌ Твоего баланса не хватит!")
        else:
            amount = int(first_word)
            if amount <= 0: return

        total_needed = amount * count
        if bal < total_needed:
            return await message.answer(f"❌ Не хватает Угадаек!\nВаш баланс: {fmt(bal)}\nНужно: {fmt(total_needed)}")

        cid = message.chat.id
        if cid not in pending_bets:
            pending_bets[cid] = []
        
        pending_bets[cid].append({
            "user_id": uid, 
            "name": message.from_user.first_name, 
            "amount": amount, 
            "targets": targets
        })
        
        update_balance(uid, -total_needed)
        
        report = f"✅ Ставок принято: {count}\n"
        if first_word in ["все", "всё"]:
            report += f"🔥 **ВА-БАНК!**\n"
        
        report += f"💸 Потрачено: {fmt(total_needed)}\n\n📊 **Ваш купон:**\n"
        for t in targets:
            report += f"• {fmt(amount)} ➔ {t}\n"
            
        await message.answer(report, parse_mode="Markdown")
        
    except Exception as e:
        logging.error(f"Ошибка в ставке: {e}")


@dp.message(F.text.lower() == "го")
async def spin(message: Message):
    if message.chat.type == "private":
    return await message.answer("🎰 В рулетку можно играть только в группах! Добавь меня в чат с друзьями.")
    cid = message.chat.id
    if cid not in pending_bets or not pending_bets[cid]:
        return await message.answer("🎰 Ставок пока нет!")
    
    win_num = random.randint(0, 36)
    conn = sqlite3.connect(DB_PATH); cur = conn.cursor()
    cur.execute("INSERT INTO history (number) VALUES (?)", (win_num,))
    conn.commit(); conn.close()
    
    col_em = "🟢" if win_num == 0 else ("🔴" if win_num % 2 == 0 else "⚫")
    col_txt = "ЗЕРО" if win_num == 0 else ("КРАСНОЕ" if win_num % 2 == 0 else "ЧЁРНОЕ")
    res_text = f"🎰 {col_em} {col_txt} {win_num}\n\n"
    
    users_results = {} 
    for bet in pending_bets[cid]:
        uid = bet['user_id']
        if uid not in users_results:
            users_results[uid] = {"name": bet['name'], "results": [], "total_win": 0, "total_spent": 0}
        
        users_results[uid]["total_spent"] += bet['amount'] * len(bet['targets'])
        for t in bet['targets']:
            is_win = False
            mult = 0
            if t in ["к", "кр", "красное"] and win_num != 0 and win_num % 2 == 0: is_win, mult = True, 2
            elif t in ["ч", "чр", "черное"] and win_num % 2 != 0: is_win, mult = True, 2
            elif t == "чет" and win_num != 0 and win_num % 2 == 0: is_win, mult = True, 2
            elif t == "нечет" and win_num % 2 != 0: is_win, mult = True, 2
            elif "-" in t:
                try:
                    l, h = map(int, t.split("-")); 
                    if l <= win_num <= h: is_win, mult = True, 36/(h-l+1)
                except: pass
            elif t.isdigit() and int(t) == win_num: is_win, mult = True, 36
            
            if is_win:
                win_v = int(bet['amount'] * mult)
                users_results[uid]["total_win"] += win_v
                users_results[uid]["results"].append(f"✅ {fmt(bet['amount'])} ➔ {t} (+{fmt(win_v)})")
            else:
                users_results[uid]["results"].append(f"❌ {fmt(bet['amount'])} ➔ {t}")

    for uid, data in users_results.items():
        res_text += f"👤 {data['name']}:\n" + "\n".join(data['results']) + "\n"
        prof = data['total_win'] - data['total_spent']
        res_text += f"💰 Итог: {'+' if prof >= 0 else ''}{fmt(prof)}\n\n"
        if data['total_win'] > 0: update_balance(uid, data['total_win'])
            
    pending_bets[cid] = [] 
    await message.answer(res_text)

@dp.message(F.text.lower() == "лог")
async def show_log(message: Message):
    conn = sqlite3.connect(DB_PATH); cur = conn.cursor()
    cur.execute("SELECT number FROM history ORDER BY rowid DESC LIMIT 10")
    res = cur.fetchall(); conn.close()
    if not res: return await message.answer("История пуста")
    out = "📜 История:\n\n"
    for i, row in enumerate(res, 1):
        n = row[0]
        col = "🟢 ЗЕРО" if n == 0 else ("🔴 КРАСНОЕ" if n % 2 == 0 else "⚫ ЧЁРНОЕ")
        out += f"{i}. 🎰 {col} {n}\n"
    await message.answer(out)

#-----Админ-------
@dp.message(F.reply_to_message, lambda m: m.from_user.id == ADMIN_ID)
async def admin_power(message: Message):
    if message.text.startswith(("+", "-")):
        try:
            val = int(message.text.replace(" ", ""))
            update_balance(message.reply_to_message.from_user.id, val)
            await message.answer(f"👑 Изменено на {fmt(val)}")
        except: pass

async def main():
    init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
