import asyncio
import random
import os
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext

from database import init_db, async_session, User

TOKEN = os.getenv("BOT_TOKEN")
bot = Bot(token=TOKEN)
dp = Dispatcher()

# Временное хранилище ставок для рулетки {chat_id: [список ставок]}
active_bets = {}

# --- КЛАВИАТУРЫ ---

def main_menu():
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="👤 Профиль", callback_data="profile"))
    builder.row(types.InlineKeyboardButton(text="🔢 Угадай число", callback_data="start_guess"))
    builder.row(types.InlineKeyboardButton(text="🎰 Как ставить в рулетке?", callback_data="roulette_help"))
    return builder.as_markup()

def roulette_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="🔥 КРУТИТЬ РУЛЕТКУ", callback_data="spin_roulette"))
    return builder.as_markup()

# --- ХЕНДЛЕРЫ ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    async with async_session() as session:
        user = await session.get(User, message.from_user.id)
        if not user:
            session.add(User(tg_id=message.from_user.id))
            await session.commit()
    await message.answer("🎰 Добро пожаловать в Казино! Выбирай игру:", reply_markup=main_menu())

@dp.callback_query(F.data == "profile")
async def cb_profile(callback: types.CallbackQuery):
    async with async_session() as session:
        user = await session.get(User, callback.from_user.id)
        await callback.message.edit_text(
            f"👤 Профиль {callback.from_user.first_name}:\n💰 Баланс: {user.balance} 🔘\n🏆 Побед: {user.wins}",
            reply_markup=main_menu()
        )

# --- ЛОГИКА РУЛЕТКИ (ГРУППОВАЯ) ---

@dp.message(F.text.regexp(r'^(\d+)\s+(к|ч|чт|нч|\d+)$'))
async def place_bet(message: types.Message):
    parts = message.text.split()
    amount, target = int(parts[0]), parts[1]
    chat_id = message.chat.id

    async with async_session() as session:
        user = await session.get(User, message.from_user.id)
        if user.balance < amount:
            return await message.reply("❌ Недостаточно угадаек!")

        # Снимаем деньги сразу при ставке
        user.balance -= amount
        await session.commit()

    # Записываем ставку в память
    if chat_id not in active_bets:
        active_bets[chat_id] = []
    
    active_bets[chat_id].append({
        "user_id": message.from_user.id,
        "name": message.from_user.first_name,
        "amount": amount,
        "target": target
    })

    await message.answer(f"✅ {message.from_user.first_name}, ставка {amount} на '{target}' принята!", 
                         reply_markup=roulette_keyboard())

@dp.callback_query(F.data == "spin_roulette")
async def spin_logic(callback: types.CallbackQuery):
    chat_id = callback.message.chat.id
    if chat_id not in active_bets or not active_bets[chat_id]:
        return await callback.answer("Ставок еще нет!", show_alert=True)

    res_num = random.randint(0, 36)
    is_red = res_num in [1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36]
    is_even = res_num % 2 == 0 and res_num != 0
    
    text = f"🎰 Рулетка крутится... Выпало: **{res_num}** {'🔴' if is_red else '⚫️' if res_num != 0 else '🟢'}\n\nРезультаты:\n"
    
    async with async_session() as session:
        for bet in active_bets[chat_id]:
            win = False
            mult = 0
            t = bet['target']
            
            if t == 'к' and is_red: win, mult = True, 2
            elif t == 'ч' and not is_red and res_num != 0: win, mult = True, 2
            elif t == 'чт' and is_even: win, mult = True, 2
            elif t == 'нч' and not is_even and res_num != 0: win, mult = True, 2
            elif t.isdigit() and int(t) == res_num: win, mult = True, 36

            user = await session.get(User, bet['user_id'])
            if win:
                prize = bet['amount'] * mult
                user.balance += prize
                user.wins += 1
                text += f"✅ {bet['name']}: +{prize} 🔘\n"
            else:
                text += f"❌ {bet['name']}: -{bet['amount']} 🔘\n"
        
        await session.commit()
    
    active_bets[chat_id] = [] # Очищаем стол
    await callback.message.answer(text)
    await callback.answer()

# --- ПОМОЩЬ ПО РУЛЕТКЕ ---
@dp.callback_query(F.data == "roulette_help")
async def help_roulette(callback: types.CallbackQuery):
    help_text = (
        "Как делать ставки:\n"
        "Пиши в чат: `сумма` `на что` \n\n"
        "Примеры:\n"
        "▫️ `100 к` — на красное (x2)\n"
        "▫️ `100 ч` — на черное (x2)\n"
        "▫️ `100 чт` — на четное (x2)\n"
        "▫️ `100 7` — на число 7 (x36)"
    )
    await callback.message.answer(help_text)
    await callback.answer()

async def main():
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
