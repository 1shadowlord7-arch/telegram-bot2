import asyncio
import nest_asyncio
nest_asyncio.apply()

import os
import re
from flask import Flask
from pyrogram import Client, filters

# ✅ FIX PYTHON 3.14 LOOP
asyncio.set_event_loop_policy(asyncio.DefaultEventLoopPolicy())

# ---------------- WEB SERVER ----------------
web = Flask(__name__)

@web.route("/")
def home():
    return "Bot Alive ✅"

# ---------------- CONFIG ----------------
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))

app = Client("bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

user_files = {}

# ---------------- SMART NAME ----------------
def clean_name(name):
    name = name.replace(".", " ")
    name = re.sub(r"\W+", " ", name).strip()
    return name

# ---------------- PROGRESS ----------------
def progress(i, total):
    p = i * 100 / total
    return f"{'█'*int(p//5)}{'░'*(20-int(p//5))} {p:.1f}%"

# ---------------- START ----------------
@app.on_message(filters.command("start"))
async def start(client, message):
    await message.reply("🚀 Bot Ready\nSend files then /process")

# ---------------- SAVE ----------------
@app.on_message(filters.document | filters.video | filters.audio)
async def save(client, message):
    uid = message.from_user.id

    user_files.setdefault(uid, []).append(message)

    await message.reply(f"📦 Saved: {len(user_files[uid])}")

# ---------------- PROCESS ----------------
@app.on_message(filters.command("process"))
async def process(client, message):
    uid = message.from_user.id

    files = user_files.get(uid, [])
    if not files:
        return await message.reply("❌ No files")

    status = await message.reply("⚡ Processing...")

    for i, msg in enumerate(files, 1):
        file = msg.document or msg.video or msg.audio
        path = await msg.download()

        ext = file.file_name.split(".")[-1]
        new_name = f"{clean_name(file.file_name)}_{i}.{ext}"

        os.rename(path, new_name)

        sent = await client.send_document(CHANNEL_ID, new_name)

        link = f"https://t.me/c/{str(CHANNEL_ID)[4:]}/{sent.id}"

        await message.reply(f"📤 {link}")

        await status.edit(f"📊 {progress(i,len(files))}")

        os.remove(new_name)

    user_files[uid] = []
    await status.edit("✅ Done!")

# ---------------- MAIN ----------------
async def main():
    await app.start()
    print("Bot Started ✅")

    # run flask inside async loop
    from asyncio import to_thread
    await to_thread(web.run, "0.0.0.0", 8080)

asyncio.run(main())
