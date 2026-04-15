import asyncio
import random
import os
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext

from database import init_db, async_session, User

# Настройки
TOKEN = os.getenv("BOT_TOKEN")
bot = Bot(token=TOKEN)
dp = Dispatcher()

# Состояния для игры "Угадай число"
class GuessState(StatesGroup):
    guessing = State()

# --- ХЕНДЛЕРЫ ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    async with async_session() as session:
        user = await session.get(User, message.from_user.id)
        if not user:
            new_user = User(tg_id=message.from_user.id)
            session.add(new_user)
            await session.commit()
            await message.answer("🎁 Добро пожаловать! Тебе начислено 1000 угадаек!")
        else:
            await message.answer("👋 С возвращением! Твой баланс доступен в /profile")

@dp.message(Command("profile"))
async def cmd_profile(message: types.Message):
    async with async_session() as session:
        user = await session.get(User, message.from_user.id)
        await message.answer(f"👤 Профиль:\n💰 Баланс: {user.balance} 🔘\n🏆 Побед: {user.wins}")

# --- ИГРА: УГАДАЙ ЧИСЛО ---

@dp.message(Command("guess"))
async def start_guess(message: types.Message, state: FSMContext):
    number = random.randint(1, 10)
    await state.update_data(secret=number, attempts=3)
    await state.set_state(GuessState.guessing)
    await message.answer("🔢 Я загадал число от 1 до 10. У тебя 3 попытки! Твой вариант?")

@dp.message(GuessState.guessing)
async def process_guess(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        return await message.answer("Пиши только числа!")
    
    user_guess = int(message.text)
    data = await state.get_data()
    secret = data['secret']
    attempts = data['attempts'] - 1

    if user_guess == secret:
        async with async_session() as session:
            user = await session.get(User, message.from_user.id)
            user.balance += 200
            user.wins += 1
            await session.commit()
        await message.answer(f"🎉 Угадал! Это было {secret}. Тебе +200 🔘")
        await state.clear()
    elif attempts > 0:
        hint = "🔼 Больше" if secret > user_guess else "🔽 Меньше"
        await state.update_data(attempts=attempts)
        await message.answer(f"{hint}! Осталось попыток: {attempts}")
    else:
        await message.answer(f"💀 Попытки кончились! Это было {secret}.")
        await state.clear()

# --- ИГРА: РУЛЕТКА (УПРОЩЕННАЯ ЛОГИКА СТАВОК) ---

@dp.message(F.text.regexp(r'^(\d+)\s+(к|ч|чт|нч|\d+)$'))
async def bet_handler(message: types.Message):
    # Парсим сообщение типа "100 к"
    parts = message.text.split()
    amount = int(parts[0])
    target = parts[1]

    async with async_session() as session:
        user = await session.get(User, message.from_user.id)
        if user.balance < amount:
            return await message.answer("Недостаточно средств!")

        # Крутим рулетку
        res_num = random.randint(0, 36)
        is_red = res_num in [1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36]
        is_even = res_num % 2 == 0 and res_num != 0
        
        win = False
        multiplier = 0

        # Логика выигрыша
        if target == 'к' and is_red: win, multiplier = True, 2
        elif target == 'ч' and not is_red and res_num != 0: win, multiplier = True, 2
        elif target == 'чт' and is_even: win, multiplier = True, 2
        elif target == 'нч' and not is_even and res_num != 0: win, multiplier = True, 2
        elif target.isdigit() and int(target) == res_num: win, multiplier = True, 36

        if win:
            prize = amount * (multiplier - 1)
            user.balance += prize
            user.wins += 1
            await message.answer(f"🎰 Выпало: {res_num}!\n🔥 ТЫ ВЫИГРАЛ: {amount * multiplier} 🔘")
        else:
            user.balance -= amount
            await message.answer(f"🎰 Выпало: {res_num}!\nПроигрыш: -{amount} 🔘")
        
        await session.commit()

async def main():
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
