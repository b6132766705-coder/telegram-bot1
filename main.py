import telebot
from telebot import types
import random
import json
import os
import time
import threading

# ====================== НАСТРОЙКИ ======================
import os
TOKEN = os.getenv("TOKEN")
ADMIN_ID = 1316137517  # <-- ВСТАВЬ СВОЙ ID

FILE_PATH = "data.json"

MIN_BET = 10
MAX_BETS_PER_PLAYER = 30
GO_DELAY = 10

BONUS_MIN = 100
BONUS_MAX = 1000

bot = telebot.TeleBot(TOKEN)

# ====================== ДАННЫЕ ======================
data = {}
current_bets = {}
roulette_history = {}
user_games = {}
bet_timers = {}

lock = threading.Lock()

# ====================== ФАЙЛ ======================
def load_data():
    global data
    if os.path.exists(FILE_PATH):
        with open(FILE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)

def save_data():
    with open(FILE_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

load_data()

# ====================== ВСПОМОГАТЕЛЬНОЕ ======================
def get_name(u):
    return f"{u.first_name} {u.last_name or ''}".strip()

def send(chat_id, text, kb=None):
    bot.send_message(chat_id, text, reply_markup=kb)

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

    uid = str(m.from_user.id)
    chat = m.chat.id
    text = m.text.strip()
    lower = text.lower()
    is_private = m.chat.type == "private"

    if uid not in data:
        data[uid] = {"coins": 0, "wins": 0, "name": get_name(m.from_user), "bonus": 0}

    # ====================== ПЕРЕВОД ДЕНЕГ ======================
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

        sender = uid
        receiver = str(m.reply_to_message.from_user.id)

        if sender == receiver:
            send(chat, "❌ Нельзя себе")
            return

        if data[sender]["coins"] < amount:
            send(chat, "❌ Недостаточно средств")
            return

        # перевод
        data[sender]["coins"] -= amount

        if receiver not in data:
            data[receiver] = {
                "coins": 0,
                "wins": 0,
                "name": m.reply_to_message.from_user.first_name,
                "bonus": 0
            }

        data[receiver]["coins"] += amount

        if random.randint(1, 3) == 1:
            save_data()

        send(chat, f"💸 Переведено {amount} Угадайек")
        return

    # ====================== УГАДАЙ ======================
    if uid in user_games:
        if not text.isdigit():
            send(chat, "❌ Введи число")
            return

        g = user_games[uid]
        num = int(text)

        if num == g["num"]:
            data[uid]["coins"] += 10
            data[uid]["wins"] += 1
            send(chat, "🎉 Угадал! +10")
            del user_games[uid]
        else:
            g["tries"] -= 1
            if g["tries"] <= 0:
                send(chat, f"😢 Было {g['num']}")
                del user_games[uid]
            else:
                send(chat, "🔼 Больше" if num < g["num"] else "🔽 Меньше")
        if random.randint(1, 3) == 1:
            save_data()
        return

    if text == "🎮 Играть":
        user_games[uid] = {"num": random.randint(1, 10), "tries": 3}
        send(chat, "🔢 Угадай число 1–10")
        return

    # ====================== БОНУС ======================
    if text == "🎁 Бонус":
        now = time.time()
        if now - data[uid]["bonus"] >= 86400:
            reward = random.randint(BONUS_MIN, BONUS_MAX)
            data[uid]["coins"] += reward
            data[uid]["bonus"] = now
            send(chat, f"🎁 Ты получил {reward} Угадайек!")
            save_data()
        else:
            send(chat, "⏳ Раз в 24 часа")
        return

    # ====================== АДМИН ======================
    if m.from_user.id == ADMIN_ID:
        if text.startswith("+") or text.startswith("-"):
            try:
                amount = int(text)

                target = None
                if m.reply_to_message:
                    target = str(m.reply_to_message.from_user.id)
                else:
                    return

                data[target]["coins"] += amount
                send(chat, "✅ Готово")
                save_data()
            except:
                send(chat, "❌ Ошибка")
            return

    # ====================== СТАВКИ ======================
    if not is_private and uid not in user_games and (text.split()[0].isdigit() or text.split()[0] == "все"):
        try:
            parts = lower.split()
            first = parts[0]

            if first == "все":
                amount = data[uid]["coins"]
            else:
                if not first.isdigit():
                    send(chat, "❌ Неверная сумма")
                    return
                amount = int(first)
            bets_input = parts[1:]
            if first == "все":
                if len(bets_input) == 0:
                    send(chat, "❌ Укажи ставки")
                    return

                amount = data[uid]["coins"] // len(bets_input)

            if amount < MIN_BET:
                send(chat, f"❌ Минимум {MIN_BET}")
                return



            current_bets.setdefault(chat, {}).setdefault(uid, [])

            if first == "все":
                # делим баланс на количество ставок
                amount = data[uid]["coins"] // len(bets_input)

            total_cost = amount * len(bets_input)

            if data[uid]["coins"] < total_cost:
                send(chat, f"❌ Нужно {total_cost}, у тебя {data[uid]['coins']}")
                return

            added = 0
            bet_list_text = []

            for bet in bets_input:

                # 🔴 красное
                if bet in ["к", "красное"]:
                    t, mult = "red", 2

                # ⚫ чёрное
                elif bet in ["ч", "черное", "чёрное"]:
                    t, mult = "black", 2

                # 🔢 нечёт
                elif bet in ["нч", "odd"]:
                    t, mult = "odd", 2

                # 🔢 чёт
                elif bet in ["чт", "even"]:
                    t, mult = "even", 2

                # 📊 диапазон
                elif "-" in bet:
                    try:
                        a, b = map(int, bet.split("-"))

                        if 0 <= a <= 36 and 0 <= b <= 36:
                            if a > b:
                                a, b = b, a

                            count = b - a + 1
                            mult = 36 / count
                            t = ("range", a, b)
                        else:
                            continue
                    except:
                        continue

                # 🎯 число
                elif bet.isdigit():
                    num = int(bet)
                    if 0 <= num <= 36:
                        t, mult = ("num", num), 36
                    else:
                        continue

                else:
                    continue

                # лимит ставок
                if len(current_bets[chat][uid]) >= MAX_BETS_PER_PLAYER:
                    break

                current_bets[chat][uid].append((amount, t, mult))
                added += 1

                # 📊 красивое имя ставки
                if t == "red":
                    name = "красное"
                elif t == "black":
                    name = "чёрное"
                elif t == "odd":
                    name = "нечёт"
                elif t == "even":
                    name = "чёт"
                elif isinstance(t, tuple):
                    if t[0] == "num":
                        name = f"число {t[1]}"
                    elif t[0] == "range":
                        name = f"{t[1]}-{t[2]}"
                else:
                    name = "?"

                bet_list_text.append(f"• {amount} → {name}")

            if added == 0:
                send(chat, "❌ Нет валидных ставок")
                return

            # списание денег
            total_spent = amount * added
            data[uid]["coins"] -= total_spent

            if chat not in bet_timers:
                bet_timers[chat] = time.time()

            text_out = f"✅ Ставок: {added}\n💸 Потрачено: {total_spent}\n\n📊 Ты поставил:\n"
            text_out += "\n".join(bet_list_text)

            send(chat, text_out)
            if random.randint(1, 3) == 1:
                save_data()

        except:
            send(chat, "❌ Ошибка ставки")
        return

    # ====================== СТАВКИ ПРОСМОТР ======================
    if text == "📊 Ставки":
        bets = current_bets.get(chat, {}).get(uid, [])
        if not bets:
            send(chat, "❌ Нет ставок")
            return

        txt = "📊 Твои ставки:\n\n"

        for amount, t, mult in bets:
            if t == "red":
                name = "к"
            elif t == "black":
                name = "ч"
            elif t == "odd":
                name = "нечёт"
            elif t == "even":
                name = "чёт"
            elif isinstance(t, tuple):
                if t[0] == "num":
                    name = f"число {t[1]}"
                elif t[0] == "range":
                    name = f"{t[1]}-{t[2]}"
            else:
                name = "?"

            txt += f"• {amount} → {name}\n"

        send(chat, txt)

    # ====================== ОТМЕНА ======================
    if text == "❌ Отменить":
        bets = current_bets.get(chat, {}).get(uid, [])
        if not bets:
            send(chat, "❌ Нет ставок")
            return
        refund = sum(b[0] for b in bets)
        data[uid]["coins"] += refund
        current_bets[chat][uid] = []
        send(chat, f"💰 Возврат {refund}")
        save_data()

    # ====================== РУЛЕТКА ======================
    if text == "🎰 Рулетка":
        send(chat, "Ставь и пиши ГО")
        return

    if lower == "го" and not is_private:
        # проверка ставок
        if chat not in current_bets or not current_bets[chat]:
            send(chat, "❌ Нет ставок!")
            return

        # проверка таймера
        if chat not in bet_timers or time.time() - bet_timers[chat] < GO_DELAY:
            send(chat, "⏳ Подожди перед запуском")
            return

        # 🎰 крутим рулетку
        n, col, eo = spin()
        result = f"🎰 {col} {n}"

        roulette_history.setdefault(chat, []).append(result)

        bets = current_bets.get(chat, {})
        full_report = result + "\n\n"

        for uid, bts in bets.items():
            win = 0
            user_text = f"👤 {data[uid]['name']}:\n"

            for amount, t, mult in bts:
                ok = False

                if t == "red":
                    name = "к"
                    ok = "КРАСНОЕ" in col
                elif t == "black":
                    name = "ч"
                    ok = "ЧЁРНОЕ" in col
                elif t == "odd":
                    name = "нечёт"
                    ok = eo == "нечётное"
                elif t == "even":
                    name = "чёт"
                    ok = eo == "чётное"
                elif isinstance(t, tuple):
                    if t[0] == "num":
                        name = f"число {t[1]}"
                        ok = t[1] == n
                    elif t[0] == "range":
                        name = f"{t[1]}-{t[2]}"
                        ok = t[1] <= n <= t[2]

                if ok:
                    prize = int(amount * mult)
                    win += prize
                    user_text += f"✅ {amount} → {name} (+{prize})\n"
                else:
                    user_text += f"❌ {amount} → {name}\n"

            data[uid]["coins"] += win
            user_text += f"💰 Итог: +{win}\n\n"

            full_report += user_text

        # очистка
        current_bets[chat] = {}
        bet_timers.pop(chat, None)

        save_data()

        send(chat, full_report)
        return

    # ====================== ПРОФИЛЬ ======================
    if text == "👤 Профиль":
        u = data[uid]
        send(chat, f"{u['name']}\n💰 {u['coins']}\n🏆 {u['wins']}")

    if lower in ["б", "баланс"]:
        send(chat, f"💰 Баланс: {data[uid]['coins']} Угадайек")
        return

    # ====================== РЕЙТИНГ ======================
    if text == "🏆 Рейтинг":
        s = sorted(data.items(), key=lambda x: x[1]["coins"], reverse=True)
        txt = "\n".join([f"{i+1}. {v['name']} — {v['coins']}" for i, (_, v) in enumerate(s[:10])])
        send(chat, txt)

    # ====================== ИСТОРИЯ ======================
    if lower == "лог":
        history = roulette_history.get(chat, [])

        if not history:
            send(chat, "📭 Истории нет")
            return

        txt = "📜 История:\n\n"

        for i, res in enumerate(history[-10:], 1):  # 👈 без reversed
            txt += f"{i}. {res}\n"

        send(chat, txt)
        return


# ====================== ЗАПУСК ======================
print("Бот запущен")
bot.infinity_polling()
