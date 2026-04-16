import telebot
from telebot import types
import random
import os
import time
import psycopg2

# ====================== ПОДКЛЮЧЕНИЕ ======================
TOKEN = os.getenv("TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

bot = telebot.TeleBot(TOKEN)

conn = psycopg2.connect(DATABASE_URL)
cursor = conn.cursor()

# ====================== НАСТРОЙКИ ======================
MIN_BET = 10
BONUS_MIN = 100
BONUS_MAX = 1000

# ====================== БД ======================
cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id BIGINT PRIMARY KEY,
    name TEXT,
    coins INTEGER,
    wins INTEGER,
    last_bonus DOUBLE PRECISION
)
""")
conn.commit()

# ====================== ДАННЫЕ ======================
user_games = {}
current_bets = {}

# ====================== ВСПОМОГАТЕЛЬНОЕ ======================
def get_name(u):
    return f"{u.first_name} {u.last_name or ''}".strip()

def send(chat_id, text, kb=None):
    bot.send_message(chat_id, text, reply_markup=kb)

def format_money(n):
    return f"{n:,}".replace(",", " ")

# ====================== USER ======================
def get_user(uid, name):
    cursor.execute("SELECT * FROM users WHERE user_id=%s", (uid,))
    user = cursor.fetchone()

    if not user:
        cursor.execute(
            "INSERT INTO users VALUES (%s,%s,%s,%s,%s)",
            (uid, name, 50, 0, 0)
        )
        conn.commit()
        return {"coins":50,"wins":0,"last_bonus":0,"name":name}

    return {
        "coins": user[2],
        "wins": user[3],
        "last_bonus": user[4],
        "name": user[1]
    }

def update_user(uid, coins=None, wins=None, last_bonus=None):
    if coins is not None:
        cursor.execute("UPDATE users SET coins=%s WHERE user_id=%s",(coins,uid))
    if wins is not None:
        cursor.execute("UPDATE users SET wins=%s WHERE user_id=%s",(wins,uid))
    if last_bonus is not None:
        cursor.execute("UPDATE users SET last_bonus=%s WHERE user_id=%s",(last_bonus,uid))
    conn.commit()

# ====================== РУЛЕТКА ======================
def spin():
    n = random.randint(0,36)
    if n == 0:
        return n,"🟢 ЗЕЛЁНОЕ","зелёное"
    return n,("🔴 КРАСНОЕ" if n%2 else "⚫ ЧЁРНОЕ"),("нечётное" if n%2 else "чётное")

# ====================== КЛАВИАТУРА ======================
def keyboard(private):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    if private:
        kb.add("🎮 Играть","👤 Профиль")
        kb.add("🏆 Рейтинг","🎁 Бонус")
    else:
        kb.add("🎮 Играть","🎰 Рулетка")
        kb.add("👤 Профиль")
    return kb

# ====================== START ======================
@bot.message_handler(commands=['start'])
def start(m):
    send(m.chat.id,"👋 Бот готов!",keyboard(m.chat.type=="private"))

# ====================== HANDLE ======================
@bot.message_handler(func=lambda m: True)
def handle(m):
    if not m.text:
        return

    uid = m.from_user.id
    chat = m.chat.id
    text = m.text.strip()
    lower = text.lower()
    is_private = m.chat.type=="private"

    name = get_name(m.from_user)
    user = get_user(uid,name)

    # ===== ПРОФИЛЬ =====
    if text == "👤 Профиль":
        send(chat,
            f"{user['name']}\n"
            f"💰 {format_money(user['coins'])}\n"
            f"🏆 Победы: {user['wins']}")
        return

    # ===== БОНУС =====
    if text == "🎁 Бонус":
        now = time.time()
        if now - user["last_bonus"] >= 86400:
            reward = random.randint(BONUS_MIN,BONUS_MAX)
            user["coins"] += reward
            user["last_bonus"] = now
            update_user(uid,coins=user["coins"],last_bonus=now)
            send(chat,f"🎁 +{format_money(reward)}")
        else:
            send(chat,"⏳ Раз в 24 часа")
        return

    # ===== УГАДАЙ =====
    if uid in user_games:
        if not text.isdigit():
            send(chat,"❌ Введи число")
            return

        g = user_games[uid]
        num = int(text)

        if num == g["num"]:
            user["coins"] += 10
            user["wins"] += 1
            update_user(uid,coins=user["coins"],wins=user["wins"])
            send(chat,"🎉 Угадал! +10")
            del user_games[uid]
        else:
            g["tries"] -= 1
            if g["tries"] <= 0:
                send(chat,f"😢 Было {g['num']}")
                del user_games[uid]
            else:
                send(chat,f"{'🔼 Больше' if num<g['num'] else '🔽 Меньше'} ({g['tries']} попытки)")
        return

    if text == "🎮 Играть":
        user_games[uid] = {"num":random.randint(1,10),"tries":3}
        send(chat,"🎮 Угадай число от 1 до 10")
        return

    # ===== СТАВКИ =====
    if not is_private:
        parts = lower.split()
        if len(parts)>1 and parts[0].isdigit():
            amount = int(parts[0])
            bets = parts[1:]

            if amount < MIN_BET:
                send(chat,"❌ Минимальная ставка 10")
                return

            if user["coins"] < amount*len(bets):
                send(chat,"❌ Недостаточно денег")
                return

            current_bets.setdefault(chat,{}).setdefault(uid,[])

            for bet in bets:

                if bet in ["к"]:
                    t,mult="red",2
                elif bet in ["ч"]:
                    t,mult="black",2
                elif bet=="нч":
                    t,mult="odd",2
                elif bet=="чт":
                    t,mult="even",2
                elif bet.isdigit():
                    t=("num",int(bet))
                    mult=36
                else:
                    continue

                current_bets[chat][uid].append((amount,t,mult))

            user["coins"] -= amount*len(bets)
            update_user(uid,coins=user["coins"])
            send(chat,"✅ Ставка принята")
            return

    # ===== РУЛЕТКА =====
    if text == "🎰 Рулетка":
        send(chat,"Ставь и пиши ГО")
        return

    if lower=="го" and not is_private:
        if chat not in current_bets:
            send(chat,"❌ Нет ставок")
            return

        n,col,eo = spin()
        result = f"🎰 {col} {n}\n\n"

        for uid,bets in current_bets[chat].items():
            u = get_user(uid,"игрок")
            win = 0

            for amount,t,mult in bets:
                ok=False

                if t=="red": ok="КРАСНОЕ" in col
                elif t=="black": ok="ЧЁРНОЕ" in col
                elif t=="odd": ok=eo=="нечётное"
                elif t=="even": ok=eo=="чётное"
                elif isinstance(t,tuple):
                    ok=t[1]==n

                if ok:
                    win+=amount*mult

            u["coins"]+=win
            update_user(uid,coins=u["coins"])
            result+=f"{u['name']} +{win}\n"

        current_bets[chat]={}
        send(chat,result)
        return

    # ===== РЕЙТИНГ =====
    if text == "🏆 Рейтинг":
        cursor.execute("SELECT name,coins FROM users ORDER BY coins DESC LIMIT 10")
        top = cursor.fetchall()
        txt="🏆 Топ:\n\n"
        for i,(n,c) in enumerate(top,1):
            txt+=f"{i}. {n} — {format_money(c)}\n"
        send(chat,txt)
        return

# ====================== ЗАПУСК ======================
print("Бот запущен")
bot.infinity_polling()
