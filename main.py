import asyncio
import nest_asyncio
nest_asyncio.apply()

import os
import re
from threading import Thread
from flask import Flask
from pyrogram import Client, filters

# ---------------- CONFIG ----------------
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

# Render gives PORT to web services.
PORT = int(os.getenv("PORT", "10000"))

# Optional: show dashboard button URL if you set it.
WEB_URL = os.getenv("WEB_URL", "")

# ---------------- BOT ----------------
bot = Client(
    "bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

# ---------------- DATA ----------------
user_files = {}   # uid -> [Message, Message, ...]
users_db = {}     # uid -> {"coins": int, "files_used": int}

# ---------------- WEB DASHBOARD ----------------
web = Flask(__name__)

@web.route("/")
def dashboard():
    total_users = len(users_db)
    total_files_used = sum(v["files_used"] for v in users_db.values())
    total_coins = sum(v["coins"] for v in users_db.values())

    rows = ""
    for uid, data in sorted(users_db.items(), key=lambda x: x[0]):
        rows += (
            f"<tr>"
            f"<td>{uid}</td>"
            f"<td>{data['coins']}</td>"
            f"<td>{data['files_used']}</td>"
            f"</tr>"
        )

    html = f"""
    <!doctype html>
    <html>
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>Bot Dashboard</title>
        <style>
            body {{
                font-family: Arial, sans-serif;
                background: #111;
                color: #fff;
                margin: 0;
                padding: 20px;
            }}
            .card {{
                background: #1b1b1b;
                border: 1px solid #2a2a2a;
                border-radius: 14px;
                padding: 16px;
                margin-bottom: 14px;
            }}
            .grid {{
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
                gap: 12px;
            }}
            .stat {{
                background: #222;
                border-radius: 14px;
                padding: 14px;
                text-align: center;
            }}
            .num {{
                font-size: 28px;
                font-weight: 700;
                margin-top: 6px;
            }}
            table {{
                width: 100%;
                border-collapse: collapse;
                overflow: hidden;
                border-radius: 12px;
                background: #1b1b1b;
            }}
            th, td {{
                border: 1px solid #2a2a2a;
                padding: 10px;
                text-align: left;
            }}
            th {{
                background: #222;
            }}
            .muted {{
                color: #aaa;
                font-size: 14px;
            }}
        </style>
    </head>
    <body>
        <div class="card">
            <h1>📊 Bot Dashboard</h1>
            <div class="muted">Live stats from the bot memory</div>
        </div>

        <div class="grid">
            <div class="stat">
                <div class="muted">Users</div>
                <div class="num">{total_users}</div>
            </div>
            <div class="stat">
                <div class="muted">Files Used</div>
                <div class="num">{total_files_used}</div>
            </div>
            <div class="stat">
                <div class="muted">Coins</div>
                <div class="num">{total_coins}</div>
            </div>
        </div>

        <div class="card">
            <h2>Users</h2>
            <table>
                <thead>
                    <tr>
                        <th>User ID</th>
                        <th>Coins</th>
                        <th>Files Used</th>
                    </tr>
                </thead>
                <tbody>
                    {rows if rows else '<tr><td colspan="3">No users yet</td></tr>'}
                </tbody>
            </table>
        </div>
    </body>
    </html>
    """
    return html

def run_web():
    web.run(host="0.0.0.0", port=PORT, use_reloader=False)

# ---------------- HELPERS ----------------
def clean_base_name(filename: str) -> str:
    base, _ = os.path.splitext(filename)
    base = base.replace(".", " ")
    base = re.sub(r"\s+", " ", base).strip()
    return base

# ---------------- START ----------------
@bot.on_message(filters.command("start"))
async def start(_, message):
    uid = message.from_user.id
    users_db.setdefault(uid, {"coins": 5, "files_used": 0})
    user_files.setdefault(uid, [])

    text = (
        "🚀 Bot Started\n\n"
        f"💰 Coins: {users_db[uid]['coins']}\n"
        "Send files, then use /process"
    )

    keyboard = []
    if WEB_URL:
        keyboard.append([{"text": "📊 Open Dashboard", "url": WEB_URL}])

    await message.reply_text(
        text,
        reply_markup={"inline_keyboard": keyboard} if keyboard else None
    )

# ---------------- SAVE FILES ----------------
@bot.on_message(filters.document | filters.video | filters.audio)
async def save(_, message):
    uid = message.from_user.id
    users_db.setdefault(uid, {"coins": 5, "files_used": 0})
    user_files.setdefault(uid, [])

    user_files[uid].append(message)
    await message.reply_text(f"📦 Files: {len(user_files[uid])}")

# ---------------- PROCESS ----------------
@bot.on_message(filters.command("process"))
async def process(_, message):
    uid = message.from_user.id
    users_db.setdefault(uid, {"coins": 5, "files_used": 0})
    user_files.setdefault(uid, [])

    files = user_files.get(uid, [])
    if not files:
        return await message.reply_text("❌ No files")

    # Admin bypass
    if uid != ADMIN_ID:
        coins = users_db[uid]["coins"]
        if coins < len(files):
            return await message.reply_text(
                f"❌ Not enough coins\n\nNeed: {len(files)}\nYou have: {coins}"
            )
        users_db[uid]["coins"] -= len(files)

    status = await message.reply_text("⚡ Processing...")

    for i, msg in enumerate(files, 1):
        file = msg.document or msg.video or msg.audio
        original_name = file.file_name or f"file_{i}"
        base, ext = os.path.splitext(original_name)
        cleaned = clean_base_name(base)

        # keep original extension
        new_name = f"{cleaned}_{i}{ext or ''}"

        path = await msg.download()
        os.rename(path, new_name)

        sent = await bot.send_document(CHANNEL_ID, new_name)
        link = f"https://t.me/c/{str(CHANNEL_ID)[4:]}/{sent.id}"

        await message.reply_text(f"📤 {link}")
        await status.edit_text(f"📊 Processing... {i}/{len(files)}")

        os.remove(new_name)

    users_db[uid]["files_used"] += len(files)
    user_files[uid] = []

    await status.edit_text("✅ Done!")

# ---------------- ADMIN STATS ----------------
@bot.on_message(filters.command("stats"))
async def stats(_, message):
    if message.from_user.id != ADMIN_ID:
        return

    total_users = len(users_db)
    total_files = sum(v["files_used"] for v in users_db.values())
    total_coins = sum(v["coins"] for v in users_db.values())

    await message.reply_text(
        "📊 Dashboard Stats\n\n"
        f"👥 Users: {total_users}\n"
        f"📦 Files Used: {total_files}\n"
        f"💰 Coins in System: {total_coins}\n\n"
        f"🌐 Dashboard: {WEB_URL or 'Not set'}"
    )

# ---------------- MAIN ----------------
async def main():
    await bot.start()
    print("Bot Started ✅")

    Thread(target=run_web, daemon=True).start()

    # Keep the asyncio loop alive cleanly
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
