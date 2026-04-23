import os
import asyncio
import logging
import random
import aiosqlite
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram import BaseMiddleware

# --- НАСТРОЙКИ ---
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = 1316137517
DB_PATH = "/app/data/butya.db"

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN)
dp = Dispatcher()

# --- МИДЛВАРЬ АКТИВНОСТИ ---
class ActivityMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        if isinstance(event, Message) and event.from_user and not event.from_user.is_bot:
            uid = event.from_user.id
            name = event.from_user.full_name
            now_str = datetime.now().isoformat()
            
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("""
                    INSERT INTO users (id, name, last_active, balance) 
                    VALUES (?, ?, ?, 10000) 
                    ON CONFLICT(id) DO UPDATE SET last_active = ?, name = ?
                """, (uid, name, now_str, now_str, name))
                await db.commit()
        return await handler(event, data)

dp.message.middleware(ActivityMiddleware())

# --- БАЗА ДАННЫХ ---
async def init_db():
    if not os.path.exists("/app/data"):
        os.makedirs("/app/data", exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''CREATE TABLE IF NOT EXISTS users 
                       (id INTEGER PRIMARY KEY, balance INTEGER DEFAULT 10000, 
                        last_bonus TEXT, name TEXT, last_active TEXT)''')
        await db.execute('''CREATE TABLE IF NOT EXISTS history (number INTEGER)''')
        await db.execute('''CREATE TABLE IF NOT EXISTS inventory 
                           (user_id INTEGER, item_name TEXT, amount INTEGER DEFAULT 1,
                            PRIMARY KEY (user_id, item_name))''')
        await db.commit()

async def get_user(user_id, name):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT balance, last_bonus FROM users WHERE id = ?", (user_id,)) as cursor:
            res = await cursor.fetchone()
        if not res:
            await db.execute("INSERT INTO users (id, balance, name) VALUES (?, ?, ?)", (user_id, 10000, name))
            await db.commit()
            return (10000, None)
        return res

async def update_balance(user_id, amount):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET balance = balance + ? WHERE id = ?", (int(amount), user_id))
        await db.commit()

def fmt(num: int) -> str:
    return f"{num:,}".replace(",", " ")

# --- СОСТОЯНИЯ ---
class GameStates(StatesGroup):
    guessing = State()

pending_bets = {}
pending_duels = {}

# --- КЛАВИАТУРЫ (РАЗДЕЛЬНЫЕ) ---
def get_main_kb(chat_type: str):
    if chat_type == 'private':
        # Клавиатура для лички
        buttons = [
            [KeyboardButton(text="🎮 Играть"), KeyboardButton(text="👤 Профиль")],
            [KeyboardButton(text="🏆 Рейтинг"), KeyboardButton(text="🎒 Инвентарь")],
            [KeyboardButton(text="🎁 Бонус")]
        ]
    else:
        # Клавиатура для групп
        buttons = [
            [KeyboardButton(text="🎮 Играть"), KeyboardButton(text="👤 Профиль")],
            [KeyboardButton(text="📊 Ставки"), KeyboardButton(text="🚫 Отмена")]
        ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

# --- КОМАНДЫ ---

@dp.message(Command("start"))
async def cmd_start(message: Message):
    await get_user(message.from_user.id, message.from_user.full_name)
    await message.answer(
        f"🎰 <b>Угадайка бот готов к работе!</b>\n"
        f"Твой баланс: {fmt(10000)} Угадаек.", 
        reply_markup=get_main_kb(message.chat.type),
        parse_mode="HTML"
    )

@dp.message(F.text == "👤 Профиль")
@dp.message(F.text.lower() == "б")
async def show_profile(message: Message):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT balance FROM users WHERE id = ?", (message.from_user.id,)) as cursor:
            res = await cursor.fetchone()
    
    await message.answer(
        f"👤 <b>Профиль:</b> {message.from_user.first_name}\n"
        f"💰 <b>Баланс:</b> {fmt(res[0])} Угадаек", 
        reply_markup=get_main_kb(message.chat.type),
        parse_mode="HTML"
    )

@dp.message(F.text == "🎁 Бонус")
async def get_bonus(message: Message):
    if message.chat.type != 'private':
        return await message.answer("🎁 Бонус можно забрать только в личке у бота!")

    res = await get_user(message.from_user.id, message.from_user.full_name)
    last_bonus_str = res[1]
    now = datetime.now()
    
    if last_bonus_str:
        last_b = datetime.fromisoformat(last_bonus_str)
        if now - last_b < timedelta(hours=24):
            left = timedelta(hours=24) - (now - last_b)
            return await message.answer(f"⏳ Приходи через {left.seconds // 3600} ч. { (left.seconds % 3600) // 60 } мин.")

    bonus = random.randint(500, 5000)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET balance = balance + ?, last_bonus = ? WHERE id = ?", 
                    (bonus, now.isoformat(), message.from_user.id))
        await db.commit()
    await message.answer(f"🎁 Ты получил <b>{fmt(bonus)}</b> Угадаек!", parse_mode="HTML")

@dp.message(F.text == "🏆 Рейтинг")
async def show_rating(message: Message):
    if message.chat.type != 'private':
        return await message.answer("🏆 Рейтинг доступен в личных сообщениях.")

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT name, balance FROM users ORDER BY balance DESC LIMIT 10") as cursor:
            top_users = await cursor.fetchall()
    
    text = "🏆 <b>ТОП МИЛЛИОНЕРОВ:</b>\n\n"
    for i, (name, bal) in enumerate(top_users, 1):
        text += f"{i}. {name} — <b>{fmt(bal)}</b>\n"
    await message.answer(text, parse_mode="HTML")

# --- СТАВКИ И РУЛЕТКА ---
def is_bet(m: Message):
    if not m.text: return False
    parts = m.text.lower().split()
    return len(parts) >= 2 and (parts[0].isdigit() or parts[0] in ["все", "всё"])

@dp.message(is_bet)
async def take_bet(message: Message):
    if message.chat.type == "private":
        return await message.answer("🎰 В рулетку играют в группах! Добавь меня в чат.")
    
    parts = message.text.split()
    targets = [t.lower() for t in parts[1:]]
    uid = message.from_user.id
    res = await get_user(uid, message.from_user.full_name)
    
    amount = res[0] // len(targets) if parts[0] in ["все", "всё"] else int(parts[0])
    total = amount * len(targets)
    
    if res[0] < total or total <= 0: return await message.answer("❌ Недостаточно средств!")

    cid = message.chat.id
    if cid not in pending_bets: pending_bets[cid] = []
    pending_bets[cid].append({"user_id": uid, "name": message.from_user.first_name, "amount": amount, "targets": targets})
    
    await update_balance(uid, -total)
    await message.answer(f"✅ Ставка принята: {fmt(total)} Угадаек.")

@dp.message(F.text.lower() == "го")
async def spin(message: Message):
    cid = message.chat.id
    if cid not in pending_bets or not pending_bets[cid]: return
    
    if not any(b['user_id'] == message.from_user.id for b in pending_bets[cid]):
        return await message.answer("❌ Крутить может только тот, кто сделал ставку!")

    win_num = random.randint(0, 36)
    col = "🟢" if win_num == 0 else ("🔴" if win_num % 2 == 0 else "⚫")
    res_text = f"🎰 Выпало: {col} {win_num}\n\n"
    
    for bet in pending_bets[cid]:
        win_sum = 0
        for t in bet['targets']:
            if (t in ["к", "кр"] and win_num != 0 and win_num % 2 == 0) or \
               (t in ["ч", "чр"] and win_num % 2 != 0) or \
               (t.isdigit() and int(t) == win_num):
                win_sum += bet['amount'] * (36 if t.isdigit() else 2)
        
        if win_sum > 0:
            await update_balance(bet['user_id'], win_sum)
            res_text += f"👤 {bet['name']}: +{fmt(win_sum)}! 🎉\n"
        else:
            res_text += f"👤 {bet['name']}: мимо ❌\n"

    pending_bets[cid] = []
    await message.answer(res_text, reply_markup=get_main_kb('group'))

@dp.message(F.text == "📊 Ставки")
async def check_bets(message: Message):
    cid = message.chat.id
    if cid not in pending_bets or not pending_bets[cid]:
        return await message.answer("Ставок пока нет.")
    
    text = "📊 <b>Текущие ставки:</b>\n"
    for b in pending_bets[cid]:
        text += f"• {b['name']}: {fmt(b['amount'] * len(b['targets']))} Угад.\n"
    await message.answer(text, parse_mode="HTML")

@dp.message(F.text == "🚫 Отмена")
async def cancel_bets(message: Message):
    cid, uid = message.chat.id, message.from_user.id
    if cid in pending_bets:
        user_bets = [b for b in pending_bets[cid] if b['user_id'] == uid]
        if user_bets:
            refund = sum(b['amount'] * len(b['targets']) for b in user_bets)
            pending_bets[cid] = [b for b in pending_bets[cid] if b['user_id'] != uid]
            await update_balance(uid, refund)
            return await message.answer(f"✅ Ставки отменены. Возвращено: {fmt(refund)}")
    await message.answer("У тебя нет активных ставок.")

# --- ДУЭЛЬ ---
@dp.message(F.text.lower().startswith("дуэль "), F.reply_to_message)
async def start_duel(message: Message):
    try:
        amount = int(message.text.split()[1])
        challenger, victim = message.from_user, message.reply_to_message.from_user
        if challenger.id == victim.id or victim.is_bot: return
        
        c_res = await get_user(challenger.id, challenger.full_name)
        v_res = await get_user(victim.id, victim.full_name)
        
        if c_res[0] < amount or v_res[0] < amount:
            return await message.answer("❌ Недостаточно средств для дуэли.")

        cid = message.chat.id
        if cid not in pending_duels: pending_duels[cid] = {}
        pending_duels[cid][victim.id] = {"c_id": challenger.id, "c_name": challenger.first_name, "amount": amount}
        
        await message.answer(f"🔫 {challenger.first_name} вызывает {victim.first_name} на {fmt(amount)}!\nНажми кнопку ниже, чтобы принять.")
    except: pass

@dp.message(F.text == "🤝 Принять дуэль")
async def accept_duel(message: Message):
    cid, vid = message.chat.id, message.from_user.id
    if cid not in pending_duels or vid not in pending_duels[cid]: return
    
    duel = pending_duels[cid].pop(vid)
    await update_balance(duel['c_id'], -duel['amount'])
    await update_balance(vid, -duel['amount'])
    
    winner_id = random.choice([duel['c_id'], vid])
    win_name = duel['c_name'] if winner_id == duel['c_id'] else message.from_user.first_name
    
    await update_balance(winner_id, duel['amount'] * 2)
    await message.answer(
        f"💥 ПАХ! Победил <b>{win_name}</b>!\nЗабрал куш: {fmt(duel['amount']*2)} 💰", 
        parse_mode="HTML", reply_markup=get_main_kb('group')
    )

# --- ИНВЕНТАРЬ ---
@dp.message(F.text == "🎒 Инвентарь")
async def show_inventory(message: Message):
    if message.chat.type != 'private':
        return await message.answer("🎒 Инвентарь можно посмотреть только в личке.")

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT item_name, amount FROM inventory WHERE user_id = ?", (message.from_user.id,)) as cur:
            items = await cur.fetchall()
    
    if not items: return await message.answer("🎒 Твой рюкзак пуст.")
    text = "🎒 <b>Твой инвентарь:</b>\n" + "\n".join([f"• {n} — {a} шт." for n, a in items])
    await message.answer(text, parse_mode="HTML")

@dp.message(F.text.lower() == "лог")
async def show_log(message: Message):
    # Лог обычно смотрят в группах, чтобы видеть результаты последних игр
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT number FROM history ORDER BY rowid DESC LIMIT 10") as cursor:
            res = await cursor.fetchall()
            
    if not res: 
        return await message.answer("📜 История игр пока пуста.")
    
    out = "📜 <b>Последние 10 чисел:</b>\n\n"
    for i, row in enumerate(res, 1):
        n = row[0]
        # Определяем цвет для красоты
        if n == 0:
            col = "🟢 ЗЕРО"
        elif n % 2 == 0:
            col = "🔴 КРАСНОЕ"
        else:
            col = "⚫ ЧЁРНОЕ"
            
        out += f"{i}. 🎰 {col} {n}\n"
    
    await message.answer(out, parse_mode="HTML")


# --- АДМИН-ПАНЕЛЬ ---
@dp.message(F.reply_to_message, lambda m: m.from_user.id == ADMIN_ID)
async def admin_tools(message: Message):
    if message.text.startswith(("+", "-")):
        try:
            val = int(message.text.replace(" ", ""))
            await update_balance(message.reply_to_message.from_user.id, val)
            await message.answer(f"👑 Изменено на {fmt(val)}")
        except: pass

# --- ЗАПУСК ---
async def main():
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
