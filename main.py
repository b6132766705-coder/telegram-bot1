import asyncio
import random
import os
import re
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import ReplyKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from database import init_db, async_session, User, RouletteLog

TOKEN = os.getenv("BOT_TOKEN")
bot = Bot(token=TOKEN)
dp = Dispatcher()

class GuessState(StatesGroup):
    guessing = State()

active_bets = {}
RED_NUMS = [1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36]

# ---------- КЛАВИАТУРА ----------
def get_main_keyboard(chat_type: str):
    builder = ReplyKeyboardBuilder()
    
    if chat_type == 'private':
        builder.button(text="👤 Профиль")
        builder.button(text="🔢 Угадай число")
        builder.button(text="📜 Помощь")
        builder.button(text="🏆 Рейтинг")
    else:
        builder.button(text="👤 Профиль")
        builder.button(text="🔢 Угадай число")
        builder.button(text="📊 Ставки")
        builder.button(text="❌ Отменить")
    
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)

# ---------- МАТЕМАТИКА ----------
def check_win(bet_target, res_num):
    res_num = int(res_num)
    is_red = res_num in RED_NUMS
    if bet_target == 'к': return (is_red and res_num != 0), 2
    if bet_target == 'ч': return (not is_red and res_num != 0), 2
    if bet_target == 'чт': return (res_num % 2 == 0 and res_num != 0), 2
    if bet_target == 'нч': return (res_num % 2 != 0 and res_num != 0), 2
    if '-' in bet_target:
        try:
            start, end = map(int, bet_target.split('-'))
            count = (end - start) + 1
            return (start <= res_num <= end), (36 / count)
        except: return False, 0
    if bet_target.isdigit(): return (int(bet_target) == res_num), 36
    return False, 0

# ---------- ХЕНДЛЕРЫ ----------

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    async with async_session() as session:
        user = await session.get(User, message.from_user.id)
        if not user:
            session.add(User(tg_id=message.from_user.id, username=message.from_user.first_name))
        else:
            user.username = message.from_user.first_name
        await session.commit()
    await message.answer("🎰 Добро пожаловать!", reply_markup=get_main_keyboard(message.chat.type))

# Профиль и Баланс
@dp.message(lambda m: m.text == "👤 Профиль" or m.text.lower() in ["б", "b", "баланс"])
async def show_profile(message: types.Message):
    async with async_session() as session:
        user = await session.get(User, message.from_user.id)
        if not user:
            user = User(tg_id=message.from_user.id, username=message.from_user.first_name)
            session.add(user)
            await session.commit()
        
        response = f"👤 **Игрок:** {user.username}\n💰 **Баланс:** {user.balance} 🔘\n🏆 **Побед:** {user.wins}"
        await message.answer(response, reply_markup=get_main_keyboard(message.chat.type), parse_mode="Markdown")

# Угадай число
@dp.message(F.text == "🔢 Угадай число")
async def start_guess(message: types.Message, state: FSMContext):
    number = random.randint(1, 10)
    await state.update_data(secret=number, attempts=3)
    await state.set_state(GuessState.guessing)
    await message.answer("🔢 Загадал от 1 до 10. Твой вариант?")

@dp.message(GuessState.guessing)
async def process_guess(message: types.Message, state: FSMContext):
    if not message.text.isdigit(): return
    user_guess = int(message.text)
    data = await state.get_data()
    secret, attempts = data['secret'], data['attempts'] - 1
    if user_guess == secret:
        async with async_session() as session:
            user = await session.get(User, message.from_user.id)
            user.balance += 200; user.wins += 1; await session.commit()
        await message.answer("🎉 +200 🔘", reply_markup=get_main_keyboard(message.chat.type)); await state.clear()
    elif attempts > 0:
        await state.update_data(attempts=attempts)
        await message.answer(f"{'🔼 Больше' if secret > user_guess else '🔽 Меньше'}! Попыток: {attempts}")
    else:
        await message.answer(f"💀 Было {secret}", reply_markup=get_main_keyboard(message.chat.type)); await state.clear()

# Рейтинг
@dp.message(F.text == "🏆 Рейтинг")
async def show_leaderboard(message: types.Message):
    async with async_session() as session:
        from sqlalchemy import select
        result = await session.execute(select(User).order_by(User.balance.desc()).limit(10))
        top_users = result.scalars().all()
        text = "🏆 **ТОП-10 БОГАЧЕЙ:**\n\n"
        for i, user in enumerate(top_users, 1):
            name = user.username if user.username else f"ID: {user.tg_id}"
            text += f"{i}. {name} — {user.balance} 🔘\n"
        await message.answer(text, reply_markup=get_main_keyboard(message.chat.type), parse_mode="Markdown")

@dp.message(F.text == "📜 Помощь")
async def btn_help(message: types.Message):
    await message.answer("🎰 **Рулетка:** `сумма` `цели` (100 к 7)\nНапиши **'го'** для запуска!", parse_mode="Markdown")

@dp.message(F.text == "📊 Ставки")
async def txt_my_bets(message: types.Message):
    user_bets = active_bets.get(message.chat.id, {}).get(message.from_user.id, [])
    if not user_bets: return await message.answer("❌ У тебя нет активных ставок.")
    text = "📊 **Твои текущие ставки:**\n"
    total = sum(b['amount'] for b in user_bets)
    for b in user_bets: text += f"• {b['amount']} ➔ {b['target']}\n"
    text += f"\n💰 **Всего:** {total}"
    await message.answer(text, parse_mode="Markdown")

@dp.message(F.text == "❌ Отменить")
async def txt_cancel_bets(message: types.Message):
    chat_id, user_id = message.chat.id, message.from_user.id
    user_bets = active_bets.get(chat_id, {}).get(user_id, [])
    if not user_bets: return await message.answer("Нечего отменять!")
    total_return = sum(b['amount'] for b in user_bets)
    async with async_session() as session:
        user = await session.get(User, user_id)
        user.balance += total_return; await session.commit()
    del active_bets[chat_id][user_id]
    await message.answer(f"❌ Ставки отменены!", reply_markup=get_main_keyboard(message.chat.type))

# Логика ставок
@dp.message(lambda m: re.match(r'^(все|\d+)\s+', m.text.lower()))
async def place_smart_bet(message: types.Message):
    if message.chat.type == 'private': return await message.answer("🎰 В рулетку играем только в группах!")
    parts = message.text.lower().split()
    async with async_session() as session:
        user = await session.get(User, message.from_user.id)
        if not user: user = User(tg_id=message.from_user.id, username=message.from_user.first_name); session.add(user)
        amount = (user.balance // (len(parts) - 1)) if parts[0] == "все" else int(parts[0])
        if amount <= 0: return
        user_bets, total_cost = [], 0
        for target in parts[1:]:
            if re.match(r'^(к|ч|чт|нч|\d+-\d+|\d+)$', target) and user.balance >= total_cost + amount:
                user_bets.append({"amount": amount, "target": target}); total_cost += amount
        if not user_bets: return
        user.balance -= total_cost; await session.commit()
    active_bets.setdefault(message.chat.id, {}).setdefault(message.from_user.id, []).extend(user_bets)
    await message.answer(f"✅ Ставки приняты!", reply_markup=get_main_keyboard(message.chat.type))

# Рулетка
@dp.message(F.text.lower() == "го")
async def spin_roulette(message: types.Message):
    chat_id = message.chat.id
    if chat_id not in active_bets or not active_bets[chat_id]: return await message.answer("🎰 Ставок нет!")
    res_num = random.randint(0, 36)
    color = "🔴 КРАСНОЕ" if res_num in RED_NUMS else "⚫️ ЧЕРНОЕ" if res_num != 0 else "🟢 ЗЕРО"
    final_report = f"🎰 {color} {res_num}\n\n"
    async with async_session() as session:
        session.add(RouletteLog(number=res_num, color=color))
        for user_id, bets in list(active_bets[chat_id].items()):
            user = await session.get(User, user_id)
            if not user: continue
            user_total_win = 0
            final_report += f"👤 {user.username}:\n"
            for b in bets:
                win, mult = check_win(b['target'], res_num)
                if win:
                    prize = int(b['amount'] * mult); user_total_win += prize
                    final_report += f"✅ {b['amount']} ➔ {b['target']} (+{prize})\n"
                else: final_report += f"❌ {b['amount']} ➔ {b['target']}\n"
            user.balance += user_total_win
            if user_total_win > 0: user.wins += 1
            final_report += f"💰 Итог: +{user_total_win}\n\n"
        await session.commit()
    active_bets[chat_id] = {}
    await message.answer(final_report, reply_markup=get_main_keyboard(message.chat.type))

# Лог последних игр
@dp.message(F.text.lower() == "лог")
async def show_roulette_log(message: types.Message):
    async with async_session() as session:
        from sqlalchemy import select
        result = await session.execute(select(RouletteLog).order_by(RouletteLog.id.desc()).limit(10))
        logs = result.scalars().all()
        if not logs: return await message.answer("📜 История пуста.")
        text = "📜 Последние 10 выпадений:\n\n"
        for log in logs: text += f"▫️ {log.color} {log.number}\n"
        await message.answer(text)

async def main():
    await init_db(); await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
