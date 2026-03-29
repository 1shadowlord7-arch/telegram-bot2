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

BOT_USERNAME = "CreatorSuiteBot"
CHANNEL_USERNAME = "@name2character"

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

# 🔐 JOIN CHECK
def is_joined(user_id):
    try:
        member = bot.get_chat_member(CHANNEL_USERNAME, user_id)
        return member.status in ["member", "administrator", "creator"]
    except:
        return False

# 🔄 AUTO END
def auto_end():
    while True:
        now = int(time.time())
        cursor.execute("SELECT id FROM giveaways WHERE active=TRUE AND end_time<=%s", (now,))
        rows = cursor.fetchall()

        for r in rows:
            gid = r[0]
            cursor.execute("UPDATE giveaways SET active=FALSE WHERE id=%s", (gid,))
            conn.commit()
            pick_winner(gid)

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

        cursor.execute("""
        INSERT INTO giveaways (chat_id,creator_id,winners_count,end_time,active)
        VALUES (%s,%s,%s,%s,TRUE) RETURNING id
        """, (msg.chat.id, msg.from_user.id, winners, end_time))

        gid = cursor.fetchone()[0]
        conn.commit()

        deep_link = f"https://t.me/{BOT_USERNAME}?start=giveaway_{gid}"

        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("🎟 Join Giveaway", url=deep_link))
        markup.add(
            InlineKeyboardButton("👥 Participants", callback_data=f"count_{gid}"),
            InlineKeyboardButton("🎯 Pick Winner", callback_data=f"pick_{gid}")
        )

        bot.send_message(
            msg.chat.id,
            f"🎉 Giveaway Started!\n⏱ {minutes} min\n🏆 Winners: {winners}",
            reply_markup=markup
        )

        bot.send_message(msg.chat.id, f"🔗 Share this link:\n{deep_link}")

    except:
        bot.reply_to(msg, "Usage: /create <minutes> <winners>")

# 🚀 START MENU
@bot.message_handler(commands=['start'])
def start(msg):
    args = msg.text.split()

    # Deep link join
    if len(args) > 1 and args[1].startswith("giveaway_"):
        gid = int(args[1].split("_")[1])

        if not is_joined(msg.from_user.id):
            markup = InlineKeyboardMarkup()
            markup.add(InlineKeyboardButton(
                "🔗 Join Channel",
                url=f"https://t.me/{CHANNEL_USERNAME.replace('@','')}"
            ))
            bot.send_message(msg.chat.id, "Join channel first", reply_markup=markup)
            return

        cursor.execute("SELECT active FROM giveaways WHERE id=%s", (gid,))
        res = cursor.fetchone()

        if not res or not res[0]:
            bot.send_message(msg.chat.id, "❌ Giveaway ended")
            return

        user = msg.from_user.id
        name = msg.from_user.username or msg.from_user.first_name

        cursor.execute("SELECT 1 FROM participants WHERE giveaway_id=%s AND user_id=%s",(gid,user))

        if cursor.fetchone():
            bot.send_message(msg.chat.id, "⚠️ Already joined")
        else:
            cursor.execute("INSERT INTO participants VALUES (%s,%s,%s)",(gid,user,name))
            conn.commit()
            bot.send_message(msg.chat.id, "✅ Joined!")

    else:
        bot.send_message(
            msg.chat.id,
            "👋 Welcome!\n\n📌 Commands:\n"
            "/create <minutes> <winners>\n"
            "/help"
        )

# 📊 COUNT (CREATOR ONLY)
@bot.callback_query_handler(func=lambda c: c.data.startswith("count_"))
def count(call):
    gid = int(call.data.split("_")[1])

    cursor.execute("SELECT creator_id FROM giveaways WHERE id=%s", (gid,))
    creator = cursor.fetchone()

    if not creator or call.from_user.id != creator[0]:
        bot.answer_callback_query(call.id, "❌ Only creator")
        return

    cursor.execute("SELECT COUNT(*) FROM participants WHERE giveaway_id=%s", (gid,))
    total = cursor.fetchone()[0]

    bot.answer_callback_query(call.id, f"👥 {total} users")

# 🎯 PICK WINNER (CREATOR ANYTIME)
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

# 🏆 WINNER
def pick_winner(gid):
    cursor.execute("SELECT chat_id,winners_count FROM giveaways WHERE id=%s",(gid,))
    data = cursor.fetchone()

    if not data:
        return

    chat_id, winners_count = data

    cursor.execute("SELECT username FROM participants WHERE giveaway_id=%s",(gid,))
    users = [u[0] for u in cursor.fetchall()]

    if not users:
        bot.send_message(chat_id, "⚠️ No participants")
        return

    winners = random.sample(users, min(len(users), winners_count))

    bot.send_message(chat_id,
        "🏆 Winners:\n" + "\n".join([f"@{w}" for w in winners])
    )

# 🚀 RUN
def run_bot():
    bot.infinity_polling()

def run_web():
    app.run(host='0.0.0.0', port=10000)

threading.Thread(target=run_bot).start()
threading.Thread(target=run_web).start()
