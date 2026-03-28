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
    return "Bot is running!"

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

CHANNEL_USERNAME = "@name2character"  # change

# 🔗 Generate message link
def generate_link(chat_id, message_id):
    try:
        if str(chat_id).startswith("-100"):
            chat_id = str(chat_id)[4:]
            return f"https://t.me/c/{chat_id}/{message_id}"
        else:
            return None
    except:
        return None

# START
@bot.message_handler(commands=['start'])
def start(message):
    bot.reply_to(message, "✅ Bot is working!\nUse /create <minutes> <winners>")

# FORCE JOIN
def is_joined(user_id):
    try:
        member = bot.get_chat_member(CHANNEL_USERNAME, user_id)
        return member.status in ["member", "administrator", "creator"]
    except:
        return False

# AUTO END
def auto_end():
    while True:
        try:
            now = int(time.time())
            cursor.execute("SELECT id FROM giveaways WHERE active=TRUE AND end_time<=%s", (now,))
            expired = cursor.fetchall()

            for g in expired:
                end_giveaway(g[0])
        except:
            pass
        time.sleep(10)

threading.Thread(target=auto_end, daemon=True).start()

# CREATE
@bot.message_handler(commands=['create'])
def create(message):
    try:
        _, minutes, winners = message.text.split()
        minutes = int(minutes)
        winners = int(winners)

        end_time = int(time.time()) + minutes * 60

        msg = bot.send_message(
            message.chat.id,
            f"🎉 Giveaway Started!\n⏱ {minutes} min\n🏆 Winners: {winners}"
        )

        cursor.execute("""
        INSERT INTO giveaways (chat_id, message_id, creator_id, winners_count, end_time, active)
        VALUES (%s,%s,%s,%s,%s,TRUE) RETURNING id
        """, (message.chat.id, msg.message_id, message.from_user.id, winners, end_time))

        giveaway_id = cursor.fetchone()[0]
        conn.commit()

        # Buttons
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("🎟 Join", callback_data=f"join_{giveaway_id}"))
        markup.add(InlineKeyboardButton("📊 Participants", callback_data=f"count_{giveaway_id}"))

        bot.edit_message_reply_markup(message.chat.id, msg.message_id, reply_markup=markup)

        # 🔗 Send share link
        link = generate_link(message.chat.id, msg.message_id)

        if link:
            bot.send_message(message.chat.id, f"🔗 Share this giveaway:\n{link}")

    except Exception as e:
        print("CREATE ERROR:", e)
        bot.reply_to(message, "Usage: /create <minutes> <winners>")

# JOIN
@bot.callback_query_handler(func=lambda c: c.data.startswith("join_"))
def join(call):
    try:
        giveaway_id = int(call.data.split("_")[1])

        if not is_joined(call.from_user.id):
            bot.answer_callback_query(call.id, "❌ Join channel first!")
            return

        cursor.execute("SELECT active FROM giveaways WHERE id=%s", (giveaway_id,))
        result = cursor.fetchone()

        if not result or not result[0]:
            bot.answer_callback_query(call.id, "❌ Ended!")
            return

        user_id = call.from_user.id
        username = call.from_user.username or call.from_user.first_name

        cursor.execute("SELECT 1 FROM participants WHERE giveaway_id=%s AND user_id=%s",
                       (giveaway_id, user_id))

        if cursor.fetchone():
            bot.answer_callback_query(call.id, "⚠️ Already joined!")
        else:
            cursor.execute("INSERT INTO participants VALUES (%s,%s,%s)",
                           (giveaway_id, user_id, username))
            conn.commit()
            bot.answer_callback_query(call.id, "✅ Joined!")

    except Exception as e:
        print("JOIN ERROR:", e)

# COUNT
@bot.callback_query_handler(func=lambda c: c.data.startswith("count_"))
def count(call):
    try:
        gid = int(call.data.split("_")[1])
        cursor.execute("SELECT COUNT(*) FROM participants WHERE giveaway_id=%s", (gid,))
        count = cursor.fetchone()[0]
        bot.answer_callback_query(call.id, f"👥 {count} users")
    except Exception as e:
        print("COUNT ERROR:", e)

# END
def end_giveaway(gid):
    try:
        cursor.execute("SELECT chat_id,winners_count FROM giveaways WHERE id=%s", (gid,))
        data = cursor.fetchone()

        if not data:
            return

        chat_id, winners_count = data

        cursor.execute("SELECT username FROM participants WHERE giveaway_id=%s", (gid,))
        users = [u[0] for u in cursor.fetchall()]

        if not users:
            bot.send_message(chat_id, "⚠️ No participants!")
            return

        winners = random.sample(users, min(len(users), winners_count))

        bot.send_message(chat_id, "🏆 Winners:\n" + "\n".join([f"@{w}" for w in winners]))

        cursor.execute("UPDATE giveaways SET active=FALSE WHERE id=%s", (gid,))
        conn.commit()

    except Exception as e:
        print("END ERROR:", e)

# ADMIN
@bot.message_handler(commands=['admin'])
def admin(message):
    try:
        cursor.execute("SELECT COUNT(*) FROM giveaways")
        total = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM participants")
        users = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM giveaways WHERE active=TRUE")
        active = cursor.fetchone()[0]

        bot.reply_to(message,
            f"📊 Dashboard\n\n"
            f"🎁 Total giveaways: {total}\n"
            f"👥 Total joins: {users}\n"
            f"🔥 Active: {active}"
        )
    except:
        pass

# RUN
def run_bot():
    print("BOT STARTED 🔥")
    bot.infinity_polling(timeout=10, long_polling_timeout=5)

def run_web():
    app.run(host='0.0.0.0', port=10000)

threading.Thread(target=run_bot).start()
threading.Thread(target=run_web).start()
