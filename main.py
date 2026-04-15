import telebot
from telebot import types
import random
import json
import os
import time
import threading
import psycopg2
import os

DATABASE_URL = os.getenv("DATABASE_URL")

conn = psycopg2.connect(DATABASE_URL)
cursor = conn.cursor()

# ====================== НАСТРОЙКИ ======================
import os
TOKEN = os.getenv("TOKEN")
ADMIN_ID = 1316137517  # <-- ВСТАВЬ СВОЙ ID


MIN_BET = 10
MAX_BETS_PER_PLAYER = 30
GO_DELAY = 10

BONUS_MIN = 100
BONUS_MAX = 1000

bot = telebot.TeleBot(TOKEN)

# ====================== ДАННЫЕ ======================
cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id BIGINT PRIMARY KEY,
    name TEXT,
    coins INTEGER,
    wins INTEGER,
    last_bonus DOUBLE PRECISION,
    level INTEGER DEFAULT 1
    )
    """)
conn.commit()

# ====================== ФУНКЦИИ ДАННЫЕ ======================
def get_user(uid, name):
    try:
        cursor.execute("SELECT * FROM users WHERE user_id=%s", (uid,))
        user = cursor.fetchone()

        if not user:
            cursor.execute(
                "INSERT INTO users (user_id, name, coins, wins, last_bonus, level) VALUES (%s, %s, %s, %s, %s, %s)",
                (uid, name, 50, 0, 0, 1)
            )
            conn.commit()
            return {
                "coins": 50,
                "wins": 0,
                "last_bonus": 0,
                "level": 1,
                "name": name
            }

        return {
            "coins": user[2],
            "wins": user[3],
            "last_bonus": user[4],
            "level": user[5],
            "name": user[1]
        }

    except Exception as e:
        print("DB ERROR:", e)
        return {
            "coins": 0,
            "wins": 0,
            "last_bonus": 0,
            "level": 1,
            "name": name
        }

def update_user(uid, coins=None, wins=None, last_bonus=None):
    if coins is not None:
        cursor.execute("UPDATE users SET coins=%s WHERE user_id=%s", (coins, uid))
    if wins is not None:
        cursor.execute("UPDATE users SET wins=%s WHERE user_id=%s", (wins, uid))
    if last_bonus is not None:
        cursor.execute("UPDATE users SET last_bonus=%s WHERE user_id=%s", (last_bonus, uid))

    conn.commit()

# ====================== ФАЙЛ ======================
current_bets = {}
user_games = {}
bet_timers = {}
roulette_history = {}
user_states = {}

# ====================== ВСПОМОГАТЕЛЬНОЕ ======================
def get_name(u):
    return f"{u.first_name} {u.last_name or ''}".strip()

def send(chat_id, text, kb=None):
    bot.send_message(chat_id, text, reply_markup=kb)

def format_money(n):
    full = f"{n:,}".replace(",", " ")

    if n >= 1_000_000:
        short = f"{round(n / 1_000_000, 1)} млн"
    elif n >= 1_000:
        short = f"{round(n / 1_000, 1)} тыс"
    else:
        return full

    return f"{full} ({short})"


def level_price(level):
    500 * level
    return

    if n >= 1_000_000:
        short = f"{round(n / 1_000_000, 1)} млн"
    elif n >= 1_000:
        short = f"{round(n / 1_000, 1)} тыс"
    else:
        return full

    return f"{full} ({short})"


def format_full(n):
    if n >= 1_000_000:
        short = f"{n/1_000_000:.1f} млн"
    elif n >= 1_000:
        short = f"{n/1_000:.1f} тыс"
    else:
        return str(n)

    return f"{format_money(n)} ({short})"

def spin():
    n = random.randint(0, 36)
    if n == 0:
        return n, "🟢 ЗЕЛЁНОЕ", "зелёное"
    return n, ("🔴 КРАСНОЕ" if n % 2 else "⚫ ЧЁРНОЕ"), ("нечётное" if n % 2 else "чётное")

def keyboard(is_private):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    if is_private:
        kb.add("🎮 Играть", "👤 Профиль")
        kb.add("🏆 Рейтинг", "🎁 Бонус")
    else:
        kb.add("🎮 Играть", "🎰 Рулетка")
        kb.add("📜 История", "📊 Ставки")
        kb.add("❌ Отменить", "👤 Профиль")
    return kb

# ====================== START ======================
@bot.message_handler(commands=['start'])
def start(m):
    send(m.chat.id, "👋 Бот готов!", keyboard(m.chat.type == "private"))

# ====================== ОСНОВНОЙ ХЕНДЛЕР ======================
@bot.message_handler(func=lambda m: True)
def handle(m):
    if not m.text:
        return

    uid = m.from_user.id
    chat = m.chat.id
    text = m.text.strip()
    lower = text.lower()
    is_private = m.chat.type == "private"

    name = get_name(m.from_user)
    user = get_user(uid, name)

    # ====================== КНОПКА ПОВЫШЕНИЯ УРОВНЯ ======================
    if text == "⬆️ Повысить уровень":
        user_states[uid] = "upgrade_level"
        
        level = user.get("level", 1)
        price = level_price(level)
        
        send(chat, f"⬆️ Повысить уровень?\n💰 Цена: {format_money(price)}\n\nНапиши: да / нет")
        return

    # обновляем имя если изменилось
    if user["name"] != name:
        cursor.execute("UPDATE users SET name=%s WHERE user_id=%s", (name, uid))
        conn.commit()
        user["name"] = name



                    # сохраняем уровень и деньги
                    cursor.execute(
                        "UPDATE users SET coins=%s, level=%s WHERE user_id=%s",
                        (user["coins"], level, uid)
                    )
                    conn.commit()
                    
        
    # ====================== ПРОФИЛЬ ======================
    if text == "👤 Профиль":
        kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
        kb.add("⬆️ Повысить уровень")
        
        send(chat,
             f"{user['name']}\n"
             f"💰 {format_money(user['coins'])}\n"
             f"🏆 Победы: {user['wins']}\n"
             f"🎖 Уровень: {user['level']}",
             kb)
        return

    # ====================== БАЛАНС ======================
    if lower in ["б", "баланс"]:
        send(chat, f"💰 Баланс: {format_money(user['coins'])} Угадайек")
        return

    # ====================== БОНУС ======================
    if text == "🎁 Бонус":
        now = time.time()
        if now - user["last_bonus"] >= 86400:
            reward = random.randint(BONUS_MIN, BONUS_MAX)
            user["coins"] += reward
            user["last_bonus"] = now

            update_user(uid, coins=user["coins"], last_bonus=user["last_bonus"])
            send(chat, f"🎁 Ты получил {format_money(reward)} Угадайек!")
        else:
            send(chat, "⏳ Раз в 24 часа")
        return

    # ====================== ПЕРЕВОД ======================
    if lower.startswith("п"):
        if not m.reply_to_message:
            send(chat, "❌ Ответь на сообщение игрока")
            return

        parts = lower.split()
        if len(parts) < 2 or not parts[1].isdigit():
            send(chat, "❌ Пример: П 100")
            return

        amount = int(parts[1])
        if amount <= 0:
            send(chat, "❌ Неверная сумма")
            return

        receiver = str(m.reply_to_message.from_user.id)

        if uid == receiver:
            send(chat, "❌ Нельзя себе")
            return

        receiver_user = get_user(receiver, get_name(m.reply_to_message.from_user))

        if user["coins"] < amount:
            send(chat, "❌ Недостаточно средств")
            return

        user["coins"] -= amount
        receiver_user["coins"] += amount

        update_user(uid, coins=user["coins"])
        update_user(receiver, coins=receiver_user["coins"])

        send(chat, f"💸 Переведено {format_money(amount)} Угадайек")
        return

    # ====================== УГАДАЙ ======================
    if uid in user_games:
        if not text.isdigit():
            send(chat, "❌ Введи число")
            return

        g = user_games[uid]
        num = int(text)

        if num == g["num"]:
            user["coins"] += 10
            user["wins"] += 1

            update_user(uid, coins=user["coins"], wins=user["wins"])
            send(chat, "🎉 Угадал! +10")
            del user_games[uid]
        else:
            g["tries"] -= 1
            if g["tries"] <= 0:
                send(chat, f"😢 Было {g['num']}")
                del user_games[uid]
            else:
                send(chat, "🔼 Больше" if num < g["num"] else "🔽 Меньше")
        return

    if text == "🎮 Играть":
        user_games[uid] = {"num": random.randint(1, 10), "tries": 3}
        send(chat, "🔢 Угадай число 1–10")
        return

    # ====================== АДМИН ======================
    if m.from_user.id == ADMIN_ID:
        if text.startswith("+") or text.startswith("-"):
            try:
                amount = int(text)

                if not m.reply_to_message:
                    return

                target = str(m.reply_to_message.from_user.id)
                target_user = get_user(target, get_name(m.reply_to_message.from_user))

                target_user["coins"] += amount
                update_user(target, coins=target_user["coins"])

                send(chat, "✅ Готово")
            except:
                send(chat, "❌ Ошибка")
            return

    # ====================== СТАВКИ ======================
    if not is_private and uid not in user_games:
        parts = lower.split()

        if len(parts) > 0 and (parts[0].isdigit() or parts[0] == "все"):
            try:
                first = parts[0]
                bets_input = parts[1:]

                if not bets_input:
                    send(chat, "❌ Укажи ставки")
                    return

                if first == "все":
                    amount = user["coins"] // len(bets_input)
                else:
                    amount = int(first)

                if amount < MIN_BET:
                    send(chat, f"❌ Минимум {MIN_BET}")
                    return

                total_cost = amount * len(bets_input)
                if user["coins"] < total_cost:
                    send(chat, f"❌ Нужно {total_cost}, у тебя {user['coins']}")
                    return

                current_bets.setdefault(chat, {}).setdefault(uid, [])

                added = 0
                bet_list_text = []

                for bet in bets_input:
                    if len(current_bets[chat][uid]) >= MAX_BETS_PER_PLAYER:
                        break

                    # тип ставки
                    if bet in ["к", "красное"]:
                        t, mult, name = "red", 2, "красное"
                    elif bet in ["ч", "черное", "чёрное"]:
                        t, mult, name = "black", 2, "чёрное"
                    elif bet in ["нч"]:
                        t, mult, name = "odd", 2, "нечёт"
                    elif bet in ["чт"]:
                        t, mult, name = "even", 2, "чёт"
                    elif bet.isdigit():
                        num = int(bet)
                        if 0 <= num <= 36:
                            t, mult, name = ("num", num), 36, f"число {num}"
                        else:
                            continue
                    else:
                        continue

                    current_bets[chat][uid].append((amount, t, mult))
                    added += 1
                    bet_list_text.append(f"• {amount} → {name}")

                if added == 0:
                    send(chat, "❌ Нет валидных ставок")
                    return

                user["coins"] -= amount * added
                update_user(uid, coins=user["coins"])

                if chat not in bet_timers:
                    bet_timers[chat] = time.time()

                send(chat, f"✅ Ставок: {added}\n💸 Потрачено: {amount * added}\n\n" + "\n".join(bet_list_text))

            except:
                send(chat, "❌ Ошибка ставки")
            return

    # ====================== РУЛЕТКА ======================
    if text == "🎰 Рулетка":
        send(chat, "Ставь и пиши ГО")
        return

    if lower == "го" and not is_private:
        if chat not in current_bets or not current_bets[chat]:
            send(chat, "❌ Нет ставок!")
            return

        if chat not in bet_timers or time.time() - bet_timers[chat] < GO_DELAY:
            send(chat, "⏳ Подожди перед запуском")
            return

        n, col, eo = spin()
        result = f"🎰 {col} {n}"

        roulette_history.setdefault(chat, []).append(result)

        full_report = result + "\n\n"

        for uid, bts in current_bets[chat].items():
            u = get_user(uid, "Игрок")
            win = 0
            user_text = f"👤 {u['name']}:\n"

            for amount, t, mult in bts:
                ok = False

                if t == "red":
                    ok = "КРАСНОЕ" in col
                elif t == "black":
                    ok = "ЧЁРНОЕ" in col
                elif t == "odd":
                    ok = eo == "нечётное"
                elif t == "even":
                    ok = eo == "чётное"
                elif isinstance(t, tuple) and t[0] == "num":
                    ok = t[1] == n

                if ok:
                    prize = int(amount * mult)
                    win += prize
                    user_text += f"✅ {amount} (+{prize})\n"
                else:
                    user_text += f"❌ {amount}\n"

            u["coins"] += win
            update_user(uid, coins=u["coins"])
            user_text += f"💰 Итог: +{win}\n\n"

            full_report += user_text

        current_bets[chat] = {}
        bet_timers.pop(chat, None)

        send(chat, full_report)
        return

    # ====================== РЕЙТИНГ ======================
    if text == "🏆 Рейтинг":
        cursor.execute("SELECT name, coins FROM users ORDER BY coins DESC LIMIT 10")
        top = cursor.fetchall()

        txt = "🏆 Топ игроков:\n\n"
        for i, (name, coins) in enumerate(top, 1):
            txt += f"{i}. {name} — {format_money(coins)}\n"

        send(chat, txt)
        return

    # ====================== ИСТОРИЯ ======================
    if lower == "лог":
        history = roulette_history.get(chat, [])

        if not history:
            send(chat, "📭 Истории нет")
            return

        txt = "📜 История:\n\n"
        for i, res in enumerate(history[-10:], 1):
            txt += f"{i}. {res}\n"

        send(chat, txt)
        return

# ====================== ЗАПУСК ======================
print("Бот запущен")
bot.infinity_polling()
