import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import psycopg2
import random
import os
import threading
import time
from flask import Flask

API_TOKEN = os.getenv("API_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

bot = telebot.TeleBot(API_TOKEN)
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot running"

# DB
conn = psycopg2.connect(DATABASE_URL)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS giveaways (
    id SERIAL PRIMARY KEY,
    chat_id BIGINT,
    message_id BIGINT,
    creator_id BIGINT,
    winners_count INT,
    end_time BIGINT,
    active BOOLEAN
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS participants (
    giveaway_id INT,
    user_id BIGINT,
    username TEXT
)
""")

conn.commit()

CHANNEL_USERNAME = "@name2character"  # CHANGE

# 🔗 LINK
def get_link(chat_id, message_id):
    if str(chat_id).startswith("-100"):
        return f"https://t.me/c/{str(chat_id)[4:]}/{message_id}"
    return None

# ✅ START
@bot.message_handler(commands=['start'])
def start(msg):
    bot.reply_to(msg, "✅ Bot ready\nUse /create <minutes> <winners>")

# 🔐 FORCE JOIN
def is_joined(user_id):
    try:
        member = bot.get_chat_member(CHANNEL_USERNAME, user_id)
        return member.status in ["member", "administrator", "creator"]
    except:
        return False

# 🔄 AUTO END (FIXED NO SPAM)
def auto_end():
    while True:
        try:
            now = int(time.time())
            cursor.execute("SELECT id FROM giveaways WHERE active=TRUE AND end_time<=%s", (now,))
            rows = cursor.fetchall()

            for r in rows:
                gid = r[0]

                cursor.execute("UPDATE giveaways SET active=FALSE WHERE id=%s", (gid,))
                conn.commit()

                pick_winner(gid)

        except Exception as e:
            print("AUTO ERROR:", e)

        time.sleep(10)

threading.Thread(target=auto_end, daemon=True).start()

# 🎉 CREATE
@bot.message_handler(commands=['create'])
def create(msg):
    try:
        _, minutes, winners = msg.text.split()
        minutes = int(minutes)
        winners = int(winners)

        end_time = int(time.time()) + minutes * 60

        text = f"🎉 Giveaway Started!\n⏱ {minutes} min\n🏆 Winners: {winners}"

        sent = bot.send_message(msg.chat.id, text)

        cursor.execute("""
        INSERT INTO giveaways (chat_id,message_id,creator_id,winners_count,end_time,active)
        VALUES (%s,%s,%s,%s,%s,TRUE) RETURNING id
        """, (msg.chat.id, sent.message_id, msg.from_user.id, winners, end_time))

        gid = cursor.fetchone()[0]
        conn.commit()

        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("🎟 Join Giveaway", callback_data=f"join_{gid}"))
        markup.add(InlineKeyboardButton("📊 Participants", callback_data=f"count_{gid}"))
        markup.add(InlineKeyboardButton("🎯 Pick Winner", callback_data=f"pick_{gid}"))

        bot.edit_message_reply_markup(msg.chat.id, sent.message_id, reply_markup=markup)

        # 🔗 SHARE LINK
        link = get_link(msg.chat.id, sent.message_id)
        if link:
            bot.send_message(msg.chat.id, f"🔗 Share this giveaway:\n{link}")

    except:
        bot.reply_to(msg, "Usage: /create <minutes> <winners>")

# 🎟 JOIN (FIXED BUTTON FLOW)
@bot.callback_query_handler(func=lambda c: c.data.startswith("join_"))
def join(call):
    gid = int(call.data.split("_")[1])

    if not is_joined(call.from_user.id):
        markup = InlineKeyboardMarkup()
        markup.add(
            InlineKeyboardButton("🔗 Join Channel", url=f"https://t.me/{CHANNEL_USERNAME.replace('@','')}"),
            InlineKeyboardButton("✅ I Joined", callback_data=f"recheck_{gid}")
        )

        bot.send_message(call.message.chat.id,
                         "⚠️ Join channel first to participate",
                         reply_markup=markup)
        return

    cursor.execute("SELECT active FROM giveaways WHERE id=%s", (gid,))
    res = cursor.fetchone()

    if not res or not res[0]:
        bot.answer_callback_query(call.id, "❌ Giveaway ended")
        return

    user = call.from_user.id
    name = call.from_user.username or call.from_user.first_name

    cursor.execute("SELECT 1 FROM participants WHERE giveaway_id=%s AND user_id=%s",(gid,user))

    if cursor.fetchone():
        bot.answer_callback_query(call.id, "⚠️ Already joined")
    else:
        cursor.execute("INSERT INTO participants VALUES (%s,%s,%s)",(gid,user,name))
        conn.commit()
        bot.answer_callback_query(call.id, "✅ Joined!")

# 🔁 RECHECK
@bot.callback_query_handler(func=lambda c: c.data.startswith("recheck_"))
def recheck(call):
    gid = int(call.data.split("_")[1])

    if is_joined(call.from_user.id):
        bot.answer_callback_query(call.id, "✅ Verified! Click join again")
    else:
        bot.answer_callback_query(call.id, "❌ Still not joined")

# 📊 COUNT (CREATOR ONLY)
@bot.callback_query_handler(func=lambda c: c.data.startswith("count_"))
def count(call):
    gid = int(call.data.split("_")[1])

    cursor.execute("SELECT creator_id FROM giveaways WHERE id=%s",(gid,))
    creator = cursor.fetchone()

    if not creator or call.from_user.id != creator[0]:
        bot.answer_callback_query(call.id, "❌ Only creator")
        return

    cursor.execute("SELECT COUNT(*) FROM participants WHERE giveaway_id=%s",(gid,))
    total = cursor.fetchone()[0]

    bot.answer_callback_query(call.id, f"👥 {total} users")

# 🎯 PICK
@bot.callback_query_handler(func=lambda c: c.data.startswith("pick_"))
def pick(call):
    gid = int(call.data.split("_")[1])

    cursor.execute("SELECT creator_id,active FROM giveaways WHERE id=%s",(gid,))
    data = cursor.fetchone()

    if not data:
        return

    creator, active = data

    if call.from_user.id != creator:
        bot.answer_callback_query(call.id, "❌ Only creator")
        return

    if not active:
        bot.answer_callback_query(call.id, "Already ended")
        return

    cursor.execute("UPDATE giveaways SET active=FALSE WHERE id=%s",(gid,))
    conn.commit()

    pick_winner(gid)

# 🏆 WINNER (NO SPAM)
def pick_winner(gid):
    cursor.execute("SELECT chat_id,winners_count FROM giveaways WHERE id=%s",(gid,))
    data = cursor.fetchone()

    if not data:
        return

    chat_id, winners_count = data

    cursor.execute("SELECT username FROM participants WHERE giveaway_id=%s",(gid,))
    users = [u[0] for u in cursor.fetchall()]

    if not users:
        bot.send_message(chat_id, "⚠️ No participants joined.")
        return

    winners = random.sample(users, min(len(users), winners_count))

    bot.send_message(chat_id,
        "🏆 Winners:\n" + "\n".join([f"@{w}" for w in winners])
    )

# 🚀 RUN
def run_bot():
    print("BOT STARTED")
    bot.infinity_polling(timeout=10, long_polling_timeout=5)

def run_web():
    app.run(host='0.0.0.0', port=10000)

threading.Thread(target=run_bot).start()
threading.Thread(target=run_web).start()
