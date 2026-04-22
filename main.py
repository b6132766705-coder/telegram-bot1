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

# 1. Инициализация
logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN)
dp = Dispatcher()

# 2. ШПИОН АКТИВНОСТИ (Асинхронный)
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

# --- ФУНКЦИИ ---
async def init_db():
    if not os.path.exists("/app/data"):
        os.makedirs("/app/data", exist_ok=True)
    
    async with aiosqlite.connect(DB_PATH) as db:
        # Старая таблица пользователей
        await db.execute('''CREATE TABLE IF NOT EXISTS users 
                       (id INTEGER PRIMARY KEY, balance INTEGER DEFAULT 10000, 
                        last_bonus TEXT, name TEXT, last_active TEXT, 
                        last_steal TEXT, shame_mark TEXT)''')
        
        # НОВАЯ ТАБЛИЦА КЛАНОВ
        await db.execute('''CREATE TABLE IF NOT EXISTS clans 
                           (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                            name TEXT UNIQUE, 
                            owner_id INTEGER, 
                            balance INTEGER DEFAULT 0)''')
        
        # Безопасное добавление колонок
        cols = ["name", "last_active", "last_steal", "shame_mark", "clan_id"] # Добавили clan_id
        for col in cols:
            try:
                await db.execute(f"ALTER TABLE users ADD COLUMN {col} {'INTEGER' if col == 'clan_id' else 'TEXT'}")
            except: pass
            
        await db.execute('''CREATE TABLE IF NOT EXISTS history (number INTEGER)''')
        await db.commit()
        
def fmt(amount):
    return "{:,}".format(amount).replace(",", " ")


async def get_user(user_id, name):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT balance, last_bonus FROM users WHERE id = ?", (user_id,)) as cursor:
            res = await cursor.fetchone()
            
        if not res:
            await db.execute("INSERT INTO users (id, balance, name) VALUES (?, ?, ?)", (user_id, 10000, name))
            await db.commit()
            return (10000, None)
        else:
            await db.execute("UPDATE users SET name = ? WHERE id = ?", (name, user_id))
            await db.commit()
            return res

async def update_balance(user_id, amount):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET balance = balance + ? WHERE id = ?", (int(amount), user_id))
        await db.commit()

# --- СОСТОЯНИЯ ---
class GameStates(StatesGroup):
    guessing = State()

pending_bets = {}
pending_duels = {}

class ClanStates(StatesGroup):
    waiting_for_name = State()


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

# --- КОМАНДЫ ---

@dp.message(Command("start"))
async def cmd_start(message: Message):
    await get_user(message.from_user.id, message.from_user.full_name)
    await message.answer(
        f"Привет! Я — <b>Угадайка бот</b>. 🎰\n"
        f"Даю тебе стартовый капитал: {fmt(10000)} Угадаек!\n\n"
        f"Жми «Играть», чтобы испытать удачу!", 
        reply_markup=get_main_kb(message.chat.type),
        parse_mode="HTML"
    )


# --- СПИСОК КОМАНД ---
@dp.message(Command("commands", "comands", "help"))
async def cmd_commands(message: Message):
    help_text = (
        "🎮 <b>Все команды «Угадайка бот»:</b>\n\n"
        "<b>💰 Экономика:</b>\n"
        "• /start — Начать игру и получить бонус\n"
        "• <code>👤 Профиль</code> или <code>б</code> — Баланс\n"
        "• <code>🎁 Бонус</code> — Ежедневный подарок\n"
        "• <code>п [сумма]</code> (ответ) — Передать Угадайки\n"
        "• <code>🏆 Рейтинг</code> — Топ богачей\n\n"
        
        "<b>🎰 Азарт:</b>\n"
        "• <code>[сумма] [ставка]</code> — Ставка (число, к, ч)\n"
        "• <code>го</code> — Запуск рулетки\n"
        "• <code>лог</code> — История игр\n"
        "• <code>дуэль [сумма]</code> — Вызвать на бой\n"
        "• <code>украсть</code> — Ограбить игрока\n\n"
        
        "<b>🛡 Кланы:</b>\n"
        "• <code>клан</code> — Меню клана\n"
        "• <code>Вступить [Название]</code> — Заявка\n\n"
        
        "<b>📜 Прочее:</b>\n"
        "• /rules — Правила игры\n"
        "• /commands — Этот список"
    )
    await message.answer(help_text, parse_mode="HTML")

# --- ПРАВИЛА ---
@dp.message(Command("rules"))
async def cmd_rules(message: Message):
    rules_text = (
        "📜 <b>Правила «Угадайка бот»</b>\n\n"
        "1️⃣ <b>Ставки:</b> Принимаются числа от 0 до 36, цвета (к, ч) и чет/нечет.\n"
        "2️⃣ <b>Запуск:</b> Только тот, кто сделал ставку, может прописать «го».\n"
        "3️⃣ <b>Кланы:</b> Создание клана стоит 200 000. Лидер управляет казной.\n"
        "4️⃣ <b>Награда:</b> Приглашай друзей в чат и получай <b>10 000</b> за каждого!\n"
        "5️⃣ <b>Штрафы:</b> Неудачная попытка кражи вешает клеймо клоуна на 3 часа.\n\n"
        "<i>Удачи в игре!</i>"
    )
    await message.answer(rules_text, parse_mode="HTML")


@dp.message(F.text == "👤 Профиль")
@dp.message(F.text.lower() == "б")
async def show_profile(message: Message):
    uid = message.from_user.id
    await get_user(uid, message.from_user.full_name) 
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT balance, shame_mark FROM users WHERE id = ?", (uid,)) as cursor:
            res = await cursor.fetchone()
    
    balance, shame_str = res
    status = "🟢 Обычный гражданин"
    
    if shame_str:
        shame_time = datetime.fromisoformat(shame_str)
        if datetime.now() < shame_time:
            left = shame_time - datetime.now()
            m = (left.seconds // 60) + 1
            status = f"🤡 Неудачливый воришка (еще {m} мин.)"

    await message.answer(f"👤 **Профиль:** {message.from_user.first_name}\n💰 **Баланс:** {fmt(balance)} Угадаек\n📝 **Статус:** {status}", parse_mode="Markdown")

@dp.message(F.text.lower().startswith("п "), F.reply_to_message)
async def transfer(message: Message):
    try:
        amount = int(message.text.split()[1])
        sender_id = message.from_user.id
        receiver = message.reply_to_message.from_user
        if amount <= 0 or sender_id == receiver.id: return
        
        res = await get_user(sender_id, message.from_user.full_name)
        bal = res[0]
        
        if bal < amount: return await message.answer("❌ Недостаточно Угадаек!")
        
        await update_balance(sender_id, -amount)
        await update_balance(receiver.id, amount)
        await message.answer(f"✅ Переведено {fmt(amount)} Угадаек для {receiver.first_name}")
    except: pass

@dp.message(F.text == "🎁 Бонус")
async def get_bonus(message: Message):
    res = await get_user(message.from_user.id, message.from_user.full_name)
    balance, last_bonus_str = res
    now = datetime.now()
    
    if last_bonus_str:
        last_b = datetime.fromisoformat(last_bonus_str)
        if now - last_b < timedelta(hours=24):
            left = timedelta(hours=24) - (now - last_b)
            h, rem = divmod(left.seconds, 3600)
            m, _ = divmod(rem, 60)
            return await message.answer(f"⏳ Бонус уже получен!\nВозвращайся через **{h} ч. {m} мин.**")

    bonus_amount = random.randint(100, 5000)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET balance = balance + ?, last_bonus = ? WHERE id = ?", 
                    (bonus_amount, now.isoformat(), message.from_user.id))
        await db.commit()
        
    await message.answer(f"🎁 Ты получил бонус: **{fmt(bonus_amount)}** Угадаек!")

@dp.message(F.text == "🏆 Рейтинг")
@dp.message(F.text.lower() == "/top")
async def show_rating(message: Message):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT name, balance, id FROM users ORDER BY balance DESC LIMIT 10") as cursor:
            top_users = await cursor.fetchall()
    
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
            await update_balance(uid, refund)
            return await message.answer(f"✅ Ставки отменены. Возвращено: {fmt(refund)}")
    await message.answer("У тебя нет активных Ставок")

# --- НАГРАДА ЗА ПРИГЛАШЕНИЕ ---
@dp.message(F.new_chat_members)
async def welcome_and_reward(message: Message):
    inviter = message.from_user
    new_members = message.new_chat_members
    
    humans_added = [m for m in new_members if not m.is_bot]
    if not humans_added: return

    total_reward = len(humans_added) * 10000
    await get_user(inviter.id, inviter.full_name)
    await update_balance(inviter.id, total_reward)
    
    names = ", ".join([m.first_name for m in humans_added])
    await message.answer(
        f"💎 <b>В Угадайка бот пополнение!</b>\n\n"
        f"👤 {inviter.first_name} привел новых игроков: <b>{names}</b>\n"
        f"💰 Твой баланс пополнен на <b>+{fmt(total_reward)}</b> Угадаек!",
        parse_mode="HTML"
    )



# --- МИНИ-ИГРА: УГАДАЙ ЧИСЛО ---
@dp.message(F.text == "🎮 Играть")
async def start_guess(message: Message, state: FSMContext):
    num = random.randint(1, 10)
    await state.set_state(GameStates.guessing)
    await state.update_data(target=num, attempts=3)
    await message.answer("Я загадал число от 1 до 10. У тебя 3 попытки! Пиши число:")

@dp.message(GameStates.guessing)
async def process_guess(message: Message, state: FSMContext):
    if not message.text.isdigit(): 
        return await message.answer("Пожалуйста, введи только цифры!")
        
    guess = int(message.text)
    data = await state.get_data()
    target = data['target']
    attempts = data['attempts'] - 1

    if guess == target:
        await update_balance(message.from_user.id, 50)
        await message.answer(f"🎉 Угадал! +{fmt(50)} Угадаек.", reply_markup=get_main_kb(message.chat.type))
        await state.clear()
    elif attempts > 0:
        hint = "Больше!" if target > guess else "Меньше!"
        await state.update_data(attempts=attempts)
        await message.answer(f"Неверно. {hint} Осталось попыток: {attempts}")
    else:
        await message.answer(f"Попытки кончились! Это было {target}.", reply_markup=get_main_kb(message.chat.type))
        await state.clear()

# ==========================================
#               СИСТЕМА КЛАНОВ (ФИНАЛЬНАЯ)
# ==========================================

@dp.message(F.text.lower() == "клан")
async def clan_info(message: Message, state: FSMContext):
    uid = message.from_user.id
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT clan_id FROM users WHERE id = ?", (uid,)) as cur:
            user_clan = await cur.fetchone()
            clan_id = user_clan[0] if user_clan else None

        if not clan_id:
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🛠 Создать клан (20 000)", callback_data="start_clan_creation")]
            ])
            return await message.answer(
                "🛡 <b>Ты не состоишь в клане.</b>\nХочешь создать свой собственный?\n\nИли напиши <code>Вступить [Название]</code>, чтобы подать заявку.",
                reply_markup=kb, parse_mode="HTML"
            )

        async with db.execute("SELECT name, owner_id, balance FROM clans WHERE id = ?", (clan_id,)) as cur:
            clan_data = await cur.fetchone()
            if not clan_data: return
            clan_name, owner_id, clan_bal = clan_data
            
        async with db.execute("SELECT COUNT(*) FROM users WHERE clan_id = ?", (clan_id,)) as cur:
            members_count = (await cur.fetchone())[0]

    role = "👑 Лидер" if uid == owner_id else "👤 Участник"
    await message.answer(
        f"🛡 <b>Клан:</b> {clan_name}\n"
        f"👥 <b>Участников:</b> {members_count}\n"
        f"💰 <b>Казна:</b> {fmt(clan_bal)} Угадаек\n\n"
        f"Твоя роль: {role}\n\n"
        f"<i>Команды:\n• Покинуть клан\n• В казну [Сумма]\n• Из казны [Сумма] (только Лидер)</i>", 
        parse_mode="HTML"
    )

@dp.callback_query(F.data == "start_clan_creation")
async def clan_creation_start(call: CallbackQuery, state: FSMContext):
    res = await get_user(call.from_user.id, call.from_user.full_name)
    if res[0] < 20000:
        return await call.answer("❌ Нужно 200 000 Угадаек!", show_alert=True)

    await call.message.edit_text("📝 Введи название для клана (до 20 символов):")
    await state.set_state(ClanStates.waiting_for_name)

@dp.message(ClanStates.waiting_for_name)
async def process_clan_name(message: Message, state: FSMContext):
    uid, clan_name = message.from_user.id, message.text.strip()
    if len(clan_name) > 20: return await message.answer("❌ Слишком длинное название!")

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT id FROM clans WHERE name = ?", (clan_name,)) as cur:
            if await cur.fetchone(): return await message.answer("❌ Название занято!")

        await update_balance(uid, -20000)
        await db.execute("INSERT INTO clans (name, owner_id, balance) VALUES (?, ?, 0)", (clan_name, uid))
        async with db.execute("SELECT last_insert_rowid()") as cur:
            new_id = (await cur.fetchone())[0]
        await db.execute("UPDATE users SET clan_id = ? WHERE id = ?", (new_id, uid))
        await db.commit()

    await state.clear()
    await message.answer(f"🛡 Клан <b>{clan_name}</b> создан!", parse_mode="HTML")

@dp.message(F.text.lower().startswith("вступить "))
async def request_join(message: Message):
    uid, clan_name = message.from_user.id, message.text[9:].strip()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT clan_id FROM users WHERE id = ?", (uid,)) as cur:
            if (await cur.fetchone())[0]: return await message.answer("❌ Ты уже в клане!")
        
        async with db.execute("SELECT id, owner_id FROM clans WHERE name = ?", (clan_name,)) as cur:
            data = await cur.fetchone()
            if not data: return await message.answer("❌ Клан не найден.")
            cid, oid = data

    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Принять", callback_data=f"c_acc_{uid}_{cid}"),
        InlineKeyboardButton(text="❌ Отклонить", callback_data=f"c_rej_{uid}_{cid}")
    ]])
    await message.answer(f"🔔 Лидер! Игрок {message.from_user.first_name} хочет в клан <b>{clan_name}</b>", reply_markup=kb, parse_mode="HTML")

@dp.callback_query(F.data.startswith("c_acc_") | F.data.startswith("c_rej_"))
async def clan_decision(call: CallbackQuery):
    act, target_id, cid = call.data.split("_")[1], int(call.data.split("_")[2]), int(call.data.split("_")[3])
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT owner_id FROM clans WHERE id = ?", (cid,)) as cur:
            if (await cur.fetchone())[0] != call.from_user.id:
                return await call.answer("❌ Ты не лидер!", show_alert=True)
        
        if act == "acc":
            await db.execute("UPDATE users SET clan_id = ? WHERE id = ?", (cid, target_id))
            await db.commit()
            await call.message.edit_text("✅ Игрок принят!")
        else:
            await call.message.edit_text("❌ Заявка отклонена.")


    await call.answer()


# --- СТАРЫЕ ФУНКЦИИ КАЗНЫ И ВЫХОДА ИЗ КЛАНА (Без изменений) ---
@dp.message(F.text.lower() == "покинуть клан")
async def leave_clan(message: Message):
    uid = message.from_user.id
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT clan_id FROM users WHERE id = ?", (uid,)) as cur:
            user_data = await cur.fetchone()
            if not user_data or not user_data[0]:
                return await message.answer("❌ Ты и так не состоишь в клане.")
            clan_id = user_data[0]
            
        async with db.execute("SELECT owner_id FROM clans WHERE id = ?", (clan_id,)) as cur:
            if (await cur.fetchone())[0] == uid:
                return await message.answer("❌ Ты лидер клана! Лидер не может просто так уйти. (Функция распуска клана пока не добавлена)")

        await db.execute("UPDATE users SET clan_id = NULL WHERE id = ?", (uid,))
        await db.commit()
    await message.answer("🏃 Ты покинул клан.")

@dp.message(F.text.lower().startswith("в казну "))
async def clan_deposit(message: Message):
    uid = message.from_user.id
    try:
        amount = int(message.text[8:].strip())
        if amount <= 0: return
    except: return

    res = await get_user(uid, message.from_user.full_name)
    if res[0] < amount:
        return await message.answer("❌ У тебя нет столько Угадаек!")

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT clan_id FROM users WHERE id = ?", (uid,)) as cur:
            user_data = await cur.fetchone()
            if not user_data or not user_data[0]: return await message.answer("❌ Ты не состоишь в клане.")
            clan_id = user_data[0]

        await update_balance(uid, -amount)
        await db.execute("UPDATE clans SET balance = balance + ? WHERE id = ?", (amount, clan_id))
        await db.commit()
        
    await message.answer(f"📥 Ты пожертвовал <b>{fmt(amount)}</b> Угадаек в казну клана!", parse_mode="HTML")

@dp.message(F.text.lower().startswith("из казны "))
async def clan_withdraw(message: Message):
    uid = message.from_user.id
    try:
        amount = int(message.text[9:].strip())
        if amount <= 0: return
    except: return

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT clan_id FROM users WHERE id = ?", (uid,)) as cur:
            user_data = await cur.fetchone()
            if not user_data or not user_data[0]: return await message.answer("❌ Ты не состоишь в клане.")
            clan_id = user_data[0]

        async with db.execute("SELECT owner_id, balance FROM clans WHERE id = ?", (clan_id,)) as cur:
            owner_id, clan_bal = await cur.fetchone()

        if uid != owner_id:
            return await message.answer("❌ Брать деньги из казны может только Лидер клана!")

        if clan_bal < amount:
            return await message.answer(f"❌ В казне клана нет столько денег! Там всего {fmt(clan_bal)}.")

        await db.execute("UPDATE clans SET balance = balance - ? WHERE id = ?", (amount, clan_id))
        await update_balance(uid, amount)
        await db.commit()

    await message.answer(f"📤 Лидер забрал <b>{fmt(amount)}</b> Угадаек из казны клана.", parse_mode="HTML")


# --- РУЛЕТКА ---
@dp.message(lambda m: m.text and (m.text.split()[0].isdigit() or m.text.lower().startswith("все") or m.text.lower().startswith("всё")))
async def take_bet(message: Message):
    if message.chat.type == "private":
        return await message.answer("🎰 В рулетку можно играть только в группах! Добавь меня в чат с друзьями.")
    parts = message.text.split()
    if len(parts) < 2:
        return 

    try:
        raw_targets = [t.lower() for t in parts[1:]]
        valid_targets = []
        invalid_targets = []
        
        for t in raw_targets:
            if t in ["к", "кр", "красное", "ч", "чр", "черное", "чет", "нечет"]:
                valid_targets.append(t)
            elif t.isdigit() and 0 <= int(t) <= 36:
                valid_targets.append(t)
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
                
        if invalid_targets:
            return await message.answer(f"❌ Ошибка в купоне!\nЯ не понимаю эти ставки: **{', '.join(invalid_targets)}**\n\nРазрешены: числа (0-36), цвета (к, ч), чет/нечет и диапазоны (например 1-18).", parse_mode="Markdown")
        
        targets = valid_targets
        count = len(targets)

        uid = message.from_user.id
        user_name = message.from_user.full_name
        res = await get_user(uid, user_name)
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
        
        await update_balance(uid, -total_needed)
        
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
        return await message.answer("🎰 В рулетку можно играть только в группах!")
    
    cid = message.chat.id
    uid = message.from_user.id # ID того, кто написал "го"

    # 1. Проверяем, есть ли вообще ставки в этом чате
    if cid not in pending_bets or not pending_bets[cid]:
        return await message.answer("🎰 Ставок пока нет! Сначала сделайте ставку.")

    # 2. ПРОВЕРКА: Делал ли ставку именно этот игрок?
    user_has_bet = any(bet['user_id'] == uid for bet in pending_bets[cid])
    
    if not user_has_bet:
        return await message.answer(f"❌ {message.from_user.first_name}, ты не можешь запустить рулетку, так как не сделал ставку!")

    # --- Дальше идет обычный код вращения ---
    win_num = random.randint(0, 36)
    
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO history (number) VALUES (?)", (win_num,))
        await db.commit()
    
    col_em = "🟢" if win_num == 0 else ("🔴" if win_num % 2 == 0 else "⚫")
    col_txt = "ЗЕРО" if win_num == 0 else ("КРАСНОЕ" if win_num % 2 == 0 else "ЧЁРНОЕ")
    res_text = f"🎰 {col_em} {col_txt} {win_num}\n\n"
    
    users_results = {} 
    for bet in pending_bets[cid]:
        u_id = bet['user_id']
        if u_id not in users_results:
            users_results[u_id] = {"name": bet['name'], "results": [], "total_win": 0, "total_spent": 0}
        
        users_results[u_id]["total_spent"] += bet['amount'] * len(bet['targets'])
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
                users_results[u_id]["total_win"] += win_v
                users_results[u_id]["results"].append(f"✅ {fmt(bet['amount'])} ➔ {t} (+{fmt(win_v)})")
            else:
                users_results[u_id]["results"].append(f"❌ {fmt(bet['amount'])} ➔ {t}")

    for u_id, data in users_results.items():
        res_text += f"👤 {data['name']}:\n" + "\n".join(data['results']) + "\n"
        prof = data['total_win'] - data['total_spent']
        res_text += f"💰 Итог: {'+' if prof >= 0 else ''}{fmt(prof)}\n\n"
        if data['total_win'] > 0: 
            await update_balance(u_id, data['total_win'])
            
    pending_bets[cid] = [] 
    await message.answer(res_text)


@dp.message(F.text.lower() == "лог")
async def show_log(message: Message):
    if message.chat.type == "private":
        return await message.answer("📜 История игр доступна только в группах.")

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT number FROM history ORDER BY rowid DESC LIMIT 10") as cursor:
            res = await cursor.fetchall()
            
    if not res: return await message.answer("История пуста")
    
    out = "📜 История:\n\n"
    for i, row in enumerate(res, 1):
        n = row[0]
        col = "🟢 ЗЕРО" if n == 0 else ("🔴 КРАСНОЕ" if n % 2 == 0 else "⚫ ЧЁРНОЕ")
        out += f"{i}. 🎰 {col} {n}\n"
    await message.answer(out)

# --- ИГРА: ДУЭЛЬ ---
@dp.message(F.text.lower().startswith("дуэль ") | F.text.lower().startswith("дуель "), F.reply_to_message)
async def start_duel(message: Message):
    if message.chat.type == "private":
        return await message.answer("❌ Дуэли возможны только в группах!")

    try:
        parts = message.text.split()
        if len(parts) < 2: return
        
        amount = int(parts[1])
        if amount <= 0: return
        
        challenger = message.from_user 
        victim = message.reply_to_message.from_user 
        
        if challenger.id == victim.id:
            return await message.answer("🤔 Самострел запрещен! Выбери другого оппонента.")
        if victim.is_bot:
            return await message.answer("🤖 Боты бессмертны, с ними нет смысла стреляться.")

        res_c = await get_user(challenger.id, challenger.full_name)
        c_bal = res_c[0]
        
        res_v = await get_user(victim.id, victim.full_name)
        v_bal = res_v[0]

        if c_bal < amount:
            return await message.answer(f"❌ У тебя не хватает {fmt(amount)} Угадаек!")
        if v_bal < amount:
            return await message.answer(f"❌ У {victim.first_name} маловато денег для такой дуэли.")

        cid = message.chat.id
        if cid not in pending_duels:
            pending_duels[cid] = {}
            
        pending_duels[cid][victim.id] = {
            "challenger_id": challenger.id,
            "challenger_name": challenger.first_name,
            "amount": amount
        }

        kb = ReplyKeyboardMarkup(keyboard=[
            [KeyboardButton(text="🤝 Принять дуэль")]
        ], resize_keyboard=True, one_time_keyboard=True)

        await message.answer(
            f"🔫 <b>{challenger.first_name}</b> вызывает на дуэль <b>{victim.first_name}</b>!\n"
            f"💰 Ставка: <b>{fmt(amount)}</b> Угадаек.\n\n"
            f"<i>{victim.first_name}, ты принимаешь вызов?</i>",
            reply_markup=kb, parse_mode="HTML"
        )
    except Exception as e:
        logging.error(f"Ошибка дуэли: {e}")

@dp.message(F.text == "🤝 Принять дуэль")
async def accept_duel(message: Message):
    if message.chat.type == "private": return
    
    cid = message.chat.id
    vid = message.from_user.id 
    
    if cid not in pending_duels or vid not in pending_duels[cid]:
        return 
        
    duel = pending_duels[cid].pop(vid) 
    amount = duel["amount"]
    cid_challenger = duel["challenger_id"]
    c_name = duel["challenger_name"]
    v_name = message.from_user.first_name
    
    res_c = await get_user(cid_challenger, c_name)
    c_bal = res_c[0]
    
    res_v = await get_user(vid, v_name)
    v_bal = res_v[0]
    
    if c_bal < amount or v_bal < amount:
        return await message.answer("❌ Дуэль сорвалась: у кого-то закончились деньги!", reply_markup=get_main_kb(message.chat.type))
        
    await update_balance(cid_challenger, -amount)
    await update_balance(vid, -amount)
    
    winner_is_challenger = random.choice([True, False])
    total_win = amount * 2
    
    if winner_is_challenger:
        await update_balance(cid_challenger, total_win)
        winner_name, loser_name = c_name, v_name
    else:
        await update_balance(vid, total_win)
        winner_name, loser_name = v_name, c_name

    await message.answer(
        f"💥 ПАХ!\n\n🏆 <b>{winner_name}</b> оказался быстрее и застрелил <b>{loser_name}</b>!\n"
        f"💰 Весь банк в размере <b>{fmt(total_win)}</b> Угадаек уходит победителю!",
        parse_mode="HTML", reply_markup=get_main_kb(message.chat.type)
    )

# --- ИГРА: ВОРОВСТВО ---
@dp.message(F.text.lower() == "украсть", F.reply_to_message)
async def try_steal(message: Message):
    if message.chat.type == "private":
        return await message.answer("❌ Воровать можно только в темных переулках групп!")

    thief = message.from_user
    victim = message.reply_to_message.from_user

    if thief.id == victim.id:
        return await message.answer("🤔 Зачем воровать у самого себя?")
    if victim.is_bot:
        return await message.answer("🤖 У ботов железные карманы, ничего не выйдет!")

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT balance, last_steal FROM users WHERE id = ?", (thief.id,)) as cur:
            t_data = await cur.fetchone()
            
        if not t_data: return
        t_bal, t_last_steal = t_data

        now = datetime.now()
        if t_last_steal:
            last_s = datetime.fromisoformat(t_last_steal)
            if now - last_s < timedelta(hours=2):
                left = timedelta(hours=2) - (now - last_s)
                h, rem = divmod(left.seconds, 3600)
                m, _ = divmod(rem, 60)
                return await message.answer(f"⏳ Полиция еще патрулирует твой район. Залечь на дно нужно еще {h} ч. {m} мин.")

        async with db.execute("SELECT balance, last_active FROM users WHERE id = ?", (victim.id,)) as cur:
            v_data = await cur.fetchone()
            
        if not v_data: return
        v_bal, v_last_active = v_data

        if v_bal < 5000:
            return await message.answer("❌ У этой жертвы меньше 5 000 Угадаек. Воровать у бедных — не по понятиям!")

        await db.execute("UPDATE users SET last_steal = ? WHERE id = ?", (now.isoformat(), thief.id))
        await db.commit()

        if v_last_active:
            last_a = datetime.fromisoformat(v_last_active)
            sleep_time = now - last_a

            if sleep_time < timedelta(hours=1): chance = 10  
            elif sleep_time < timedelta(hours=3): chance = 35 
            elif sleep_time < timedelta(hours=6): chance = 60 
            else: chance = 85 
        else:
            chance = 10

        success = random.randint(1, 100) <= chance

        if success:
            steal_amount = int(v_bal * 0.10)
            await update_balance(victim.id, -steal_amount) # Исправлено на вызов функции
            await update_balance(thief.id, steal_amount)   # Исправлено на вызов функции
            
            await message.answer(
                f"🕵️ <b>ИДЕАЛЬНОЕ ОГРАБЛЕНИЕ!</b>\n\n"
                f"Ты тихо подкрался и вытащил <b>{fmt(steal_amount)}</b> Угадаек у {victim.first_name}!\n"
                f"<i>(Шанс успеха был: {chance}%)</i>",
                parse_mode="HTML"
            )
        else:
            fine_victim = 2000 
            fine_police = 1000 
            total_fine = fine_victim + fine_police
            
            if t_bal < total_fine:
                total_fine = t_bal
                fine_victim = t_bal // 2
            
            await update_balance(thief.id, -total_fine)   # Исправлено на вызов функции
            await update_balance(victim.id, fine_victim)  # Исправлено на вызов функции

            shame_until = (now + timedelta(hours=3)).isoformat()
            await db.execute("UPDATE users SET shame_mark = ? WHERE id = ?", (shame_until, thief.id))
            await db.commit()

            await message.answer(
                f"🚨 <b>ВОР ПОЙМАН ЗА РУКУ!</b>\n\n"
                f"{victim.first_name} не спал! Охрана скрутила тебя.\n\n"
                f"💸 Изъято: <b>{fmt(total_fine)}</b> Угадаек (из них {fmt(fine_victim)} отдано жертве).\n"
                f"🤡 Ты получаешь статус <b>«Неудачливый воришка»</b> на 3 часа!",
                parse_mode="HTML"
            )

# --- АДМИН-ЧИТ: ОБНУЛЕНИЕ ТАЙМЕРОВ ---
@dp.message(lambda m: m.text and m.text.lower().startswith("обнулить"))
async def admin_reset(message: Message):
    logging.info(f"Команда 'обнулить' от ID: {message.from_user.id}")

    if message.from_user.id != ADMIN_ID:
        return 

    target_user = message.reply_to_message.from_user if message.reply_to_message else message.from_user
    
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""UPDATE users SET 
                           last_steal = NULL, 
                           shame_mark = NULL, 
                           last_bonus = NULL 
                           WHERE id = ?""", (target_user.id,))
            await db.commit()
        
        await message.answer(f"🪄 **Магия!** Таймеры для {target_user.first_name} сброшены.")
    except Exception as e:
        logging.error(f"Ошибка при обнулении: {e}")
        await message.answer("❌ Произошла ошибка в базе данных.")

# --- АДМИН ---
@dp.message(F.reply_to_message, lambda m: m.from_user.id == ADMIN_ID)
async def admin_power(message: Message):
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
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Бот выключен")
