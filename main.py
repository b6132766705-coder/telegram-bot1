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
from aiogram.utils.keyboard import InlineKeyboardBuilder # Нужно для кнопок "Отмена"


TOKEN = os.getenv("BOT_TOKEN")
bot = Bot(token=TOKEN)
dp = Dispatcher()

# Состояния для игры "Угадай число"
class GuessState(StatesGroup):
    guessing = State()

# Хранилище ставок: {chat_id: {user_id: [список ставок]}}
active_bets = {}

# Цвета рулетки
RED_NUMS = [1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36]


# --- КЛАВИАТУРА ---
def get_main_keyboard():
    builder = ReplyKeyboardBuilder()
    builder.button(text="👤 Профиль")
    builder.button(text="🔢 Угадай число")
    builder.button(text="📜 Помощь")
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)

def get_bet_control_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="📝 Мои ставки", callback_data="my_bets"))
    builder.row(types.InlineKeyboardButton(text="❌ Отменить всё", callback_data="cancel_bets"))
    return builder.as_markup()


# --- МАТЕМАТИКА РУЛЕТКИ ---
def check_win(bet_target, res_num):
    res_num = int(res_num)
    is_red = res_num in RED_NUMS
    is_even = res_num % 2 == 0 and res_num != 0

    if bet_target == 'к': return (is_red and res_num != 0), 2
    if bet_target == 'ч': return (not is_red and res_num != 0), 2
    if bet_target == 'чт': return is_even, 2
    if bet_target == 'нч': return (not is_even and res_num != 0), 2
    
    if '-' in bet_target:
        try:
            start, end = map(int, bet_target.split('-'))
            count = (end - start) + 1
            if count <= 0 or count > 37: return False, 0
            multiplier = 36 / count
            return (start <= res_num <= end), multiplier
        except: return False, 0
        
    if bet_target.isdigit():
        return (int(bet_target) == res_num), 36
    return False, 0

# --- ХЕНДЛЕРЫ ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    async with async_session() as session:
        user = await session.get(User, message.from_user.id)
        if not user:
            session.add(User(tg_id=message.from_user.id))
            await session.commit()
    await message.answer("🎰 Добро пожаловать! Используй кнопки ниже:", reply_markup=get_main_keyboard())

# Баланс по кнопке "👤 Профиль" или по букве "б"
@dp.message(F.text.lower().in_(["б", "b", "баланс"]))
@dp.message(F.text == "👤 Профиль")
async def show_profile(message: types.Message):
    async with async_session() as session:
        user = await session.get(User, message.from_user.id)
        # Если пользователя нет в базе (например, зашел в чат и сразу нажал 'б')
        if not user:
            user = User(tg_id=message.from_user.id)
            session.add(user)
            await session.commit()
            
        await message.answer(f"👤 Игрок: {message.from_user.first_name}\n💰 Баланс: {user.balance} 🔘\n🏆 Побед: {user.wins}")


# --- ИГРА УГАДАЙ ЧИСЛО ---
@dp.message(F.text == "🔢 Угадай число")
async def start_guess(message: types.Message, state: FSMContext):
    number = random.randint(1, 10)
    await state.update_data(secret=number, attempts=3)
    await state.set_state(GuessState.guessing)
    await message.answer("🔢 Я загадал число от 1 до 10. У тебя 3 попытки! Твой вариант?")

@dp.message(GuessState.guessing)
async def process_guess(message: types.Message, state: FSMContext):
    if not message.text.isdigit(): return
    user_guess = int(message.text)
    data = await state.get_data()
    secret, attempts = data['secret'], data['attempts'] - 1

    if user_guess == secret:
        async with async_session() as session:
            user = await session.get(User, message.from_user.id)
            user.balance += 200
            user.wins += 1
            await session.commit()
        await message.answer(f"🎉 Угадал! +200 🔘", reply_markup=get_main_keyboard())
        await state.clear()
    elif attempts > 0:
        hint = "🔼 Больше" if secret > user_guess else "🔽 Меньше"
        await state.update_data(attempts=attempts)
        await message.answer(f"{hint}! Попыток: {attempts}")
    else:
        await message.answer(f"💀 Проигрыш! Было {secret}", reply_markup=get_main_keyboard())
        await state.clear()

@dp.message(F.text == "📜 Помощь")
async def btn_help(message: types.Message):
    await message.answer("🎰 **Рулетка:** `сумма` `цели` (через пробел)\nПример: `100 к 7 1-12` \nНапиши **'го'** для запуска!", parse_mode="Markdown")

# --- СТАВКИ ---
@dp.message(lambda m: re.match(r'^(все|\d+)\s+', m.text.lower()))
async def place_smart_bet(message: types.Message):
    chat_id = message.chat.id
    parts = message.text.lower().split()
    if len(parts) < 2: return

    async with async_session() as session:
        user = await session.get(User, message.from_user.id)
        if parts[0] == "все":
            if user.balance <= 0: return
            amount = user.balance // (len(parts) - 1)
        else:
            amount = int(parts[0])

        user_bets = []
        total_cost = 0
        for target in parts[1:]:
            if re.match(r'^(к|ч|чт|нч|\d+-\d+|\d+)$', target):
                if user.balance >= total_cost + amount:
                    user_bets.append({"amount": amount, "target": target})
                    total_cost += amount

        if not user_bets: return
        user.balance -= total_cost
        await session.commit()

    if chat_id not in active_bets: active_bets[chat_id] = {}
    if message.from_user.id not in active_bets[chat_id]: active_bets[chat_id][message.from_user.id] = []
    active_bets[chat_id][message.from_user.id].extend(user_bets)
      # Формируем красивый отчет
    report = (
        f"✅ Ставок: {len(user_bets)}\n"
        f"💸 Потрачено: {total_cost}\n\n"
        f"📊 Твои ставки:\n"
    )
    
    for b in user_bets:
        report += f"• {b['amount']} ➔ {b['target']}\n"
        
    await message.answer(report)


# --- ЗАПУСК РУЛЕТКИ ---
@dp.message(F.text.lower() == "го")
async def spin_roulette(message: types.Message):
    chat_id = message.chat.id
    if chat_id not in active_bets or not active_bets[chat_id]:
        return await message.answer("🎰 Ставок нет!")

    res_num = random.randint(0, 36)
    color = "🔴 КРАСНОЕ" if res_num in RED_NUMS else "⚫️ ЧЕРНОЕ" if res_num != 0 else "🟢 ЗЕРО"
    final_report = f"🎰 {color} {res_num}\n\n"
        # Внутри spin_roulette сразу после генерации res_num
    async with async_session() as session:
        new_log = RouletteLog(number=res_num, color=color_emoji)
        session.add(new_log)
        await session.commit() # Сначала сохраняем лог
        
        # ... дальше идет твой старый цикл обработки выигрышей ...

    
    async with async_session() as session:
        for user_id, bets in active_bets[chat_id].items():
            user = await session.get(User, user_id)
            user_total_win = 0
            user_info = await bot.get_chat(user_id)
            final_report += f"👤 {user_info.first_name}:\n"
            
            for b in bets:
                is_win, mult = check_win(b['target'], res_num)
                if is_win:
                    prize = int(b['amount'] * mult)
                    user_total_win += prize
                    final_report += f"✅ {b['amount']} ➔ {b['target']} (+{prize})\n"
                else:
                    final_report += f"❌ {b['amount']} ➔ {b['target']}\n"
            
            user.balance += user_total_win
            if user_total_win > 0: user.wins += 1
            final_report += f"💰 Итог: +{user_total_win}\n\n"
        await session.commit()

    active_bets[chat_id] = {}
    await message.answer(final_report)

# --- СЕКЦИЯ УПРАВЛЕНИЯ СТАВКАМИ И ЛОГАМИ ---

# 1. Команда ЛОГ (показывает историю)
@dp.message(F.text.lower() == "лог")
async def show_roulette_log(message: types.Message):
    async with async_session() as session:
        from sqlalchemy import select
        # Берем последние 10 записей из базы
        result = await session.execute(select(RouletteLog).order_by(RouletteLog.id.desc()).limit(10))
        logs = result.scalars().all()
        
        if not logs:
            return await message.answer("📜 История пуста.")
        
        text = "📜 Последние 10 выпадений:\n\n"
        for log in logs:
            text += f"▫️ {log.color} {log.number}\n"
        
        await message.answer(text)

# 2. Обработка кнопки "Мои ставки"
@dp.callback_query(F.data == "my_bets")
async def cb_my_bets(callback: types.CallbackQuery):
    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    
    # Ищем ставки игрока в оперативной памяти
    user_bets = active_bets.get(chat_id, {}).get(user_id, [])
    
    if not user_bets:
        return await callback.answer("У тебя нет активных ставок!", show_alert=True)
    
    text = "📊 Твои текущие ставки:\n"
    total = 0
    for b in user_bets:
        text += f"• {b['amount']} ➔ {b['target']}\n"
        total += b['amount']
    text += f"\n💰 Всего: {total}"
    
    # Показываем уведомлением внутри Телеграм
    await callback.answer(text, show_alert=True)

# 3. Обработка кнопки "Отмена"
@dp.callback_query(F.data == "cancel_bets")
async def cb_cancel_bets(callback: types.CallbackQuery):
    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    
    user_bets = active_bets.get(chat_id, {}).get(user_id, [])
    
    if not user_bets:
        return await callback.answer("Нечего отменять!", show_alert=True)
    
    total_return = sum(b['amount'] for b in user_bets)
    
    # Возвращаем деньги в базу данных
    async with async_session() as session:
        user = await session.get(User, user_id)
        if user:
            user.balance += total_return
            await session.commit()
    
    # Удаляем ставки из памяти
    del active_bets[chat_id][user_id]
    
    await callback.message.edit_text(f"❌ {callback.from_user.first_name}, твои ставки отменены. {total_return} 🔘 вернулись на баланс.")

# --- КОНЕЦ НОВОГО БЛОКА ---

# СЮДА НИЖЕ ИДЕТ ТВОЯ ФУНКЦИЯ main()

async def main():
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
