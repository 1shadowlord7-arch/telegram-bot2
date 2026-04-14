import asyncio
import nest_asyncio
nest_asyncio.apply()

import os
import re
from flask import Flask
from threading import Thread
from pyrogram import Client, filters, idle

# ---------------- KEEP ALIVE WEB ----------------
web_app = Flask('')

@web_app.route('/')
def home():
    return "Bot is alive!"

def run_web():
    web_app.run(host="0.0.0.0", port=8080)

Thread(target=run_web).start()

# ---------------- CONFIG ----------------
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))

app = Client("bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# ---------------- DATA ----------------
user_files = {}

# ---------------- SMART RENAME ----------------
def netflix_name(filename):
    name = filename.replace(".", " ")

    match = re.search(r"(S\d+E\d+)", name, re.I)
    if match:
        ep = match.group(1).upper()
        title = name.split(ep)[0]
        title = re.sub(r"\W+", " ", title).strip()
        return f"{title} - {ep}"

    return re.sub(r"\W+", " ", name).strip()

# ---------------- PROGRESS ----------------
def progress_bar(i, total):
    p = i * 100 / total
    filled = int(p // 5)
    return "█" * filled + "░" * (20 - filled) + f" {p:.1f}%"

# ---------------- START ----------------
@app.on_message(filters.command("start"))
async def start(client, message):
    await message.reply(
        "🚀 Renamer SaaS Bot\n\n"
        "Send files then use /process"
    )

# ---------------- SAVE FILES ----------------
@app.on_message(filters.document | filters.video | filters.audio)
async def save_files(client, message):
    uid = message.from_user.id

    if uid not in user_files:
        user_files[uid] = []

    user_files[uid].append(message)

    await message.reply(f"📦 Files saved: {len(user_files[uid])}")

# ---------------- PROCESS ----------------
@app.on_message(filters.command("process"))
async def process(client, message):
    uid = message.from_user.id

    if uid not in user_files or not user_files[uid]:
        return await message.reply("❌ No files uploaded")

    files = user_files[uid]
    total = len(files)

    status = await message.reply("⚡ Starting processing...")

    for i, msg in enumerate(files, start=1):
        file = msg.document or msg.video or msg.audio

        # download
        path = await msg.download()

        ext = file.file_name.split(".")[-1]
        clean_name = netflix_name(file.file_name)

        new_name = f"{clean_name}_{i}.{ext}"
        os.rename(path, new_name)

        # upload to channel
        sent = await client.send_document(
            chat_id=CHANNEL_ID,
            document=new_name,
            caption=new_name
        )

        # generate link
        link = f"https://t.me/c/{str(CHANNEL_ID)[4:]}/{sent.id}"

        await message.reply(f"📤 Uploaded:\n{link}")

        # update progress
        await status.edit(
            f"📊 Processing...\n\n{progress_bar(i, total)}\n\nDone {i}/{total}"
        )

        # delete file
        os.remove(new_name)

    user_files[uid] = []

    await status.edit("🎉 All files processed!")

# ---------------- RUN BOT ----------------
async def main():
    await app.start()
    print("Bot Started ✅")
    await idle()

asyncio.run(main())
