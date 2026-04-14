import asyncio
import html
import os
import re
import uuid
from datetime import datetime
from threading import Thread

from flask import Flask, request
from pymongo import MongoClient
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

# Force a stable asyncio policy
asyncio.set_event_loop_policy(asyncio.DefaultEventLoopPolicy())

# ---------------------------
# ENV HELPERS
# ---------------------------
def must_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing environment variable: {name}")
    return value

def optional_env(name: str, default: str = "") -> str:
    return os.getenv(name, default)

# ---------------------------
# CONFIG
# ---------------------------
API_ID = int(must_env("API_ID"))
API_HASH = must_env("API_HASH")
BOT_TOKEN = must_env("BOT_TOKEN")
MONGO_URL = must_env("MONGO_URL")
CHANNEL_ID = int(must_env("CHANNEL_ID"))
ADMIN_ID = int(must_env("ADMIN_ID"))

DB_NAME = optional_env("DB_NAME", "renamer_bot")
WEB_URL = optional_env("WEB_URL", "").rstrip("/")
DASHBOARD_KEY = optional_env("DASHBOARD_KEY", "")
STARTING_COINS = int(optional_env("STARTING_COINS", "1"))
PORT = int(os.getenv("PORT", "10000"))

# ---------------------------
# MONGODB
# ---------------------------
mongo = MongoClient(MONGO_URL)
db = mongo[DB_NAME]
users_col = db["users"]
queue_col = db["queue"]

# ---------------------------
# PYROGRAM BOT
# ---------------------------
bot = Client(
    "renamer_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
)

# ---------------------------
# WEB APP
# ---------------------------
web = Flask(__name__)

@web.route("/")
def home():
    return "Bot is alive."

@web.route("/dashboard")
def dashboard():
    if request.args.get("key") != DASHBOARD_KEY:
        return "Forbidden", 403

    total_users = users_col.count_documents({})
    total_queue = queue_col.count_documents({})
    total_coins = 0

    rows = ""
    for user in users_col.find().sort("_id", 1):
        uid = user["_id"]
        username = user.get("username", "")
        first_name = user.get("first_name", "")
        display_name = username or first_name or ""
        queued = queue_col.count_documents({"user_id": uid})

        total_coins += int(user.get("coins", 0))

        rows += (
            "<tr>"
            f"<td>{uid}</td>"
            f"<td>{html.escape(display_name)}</td>"
            f"<td>{int(user.get('coins', 0))}</td>"
            f"<td>{int(user.get('files_used', 0))}</td>"
            f"<td>{queued}</td>"
            "</tr>"
        )

    if not rows:
        rows = "<tr><td colspan='5'>No users yet</td></tr>"

    return (
        "<!doctype html>"
        "<html><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<title>Bot Dashboard</title>"
        "<style>"
        "body{font-family:Arial,sans-serif;background:#111;color:#fff;margin:0;padding:20px}"
        ".card{background:#1b1b1b;border:1px solid #2a2a2a;border-radius:14px;padding:16px;margin-bottom:14px}"
        "table{width:100%;border-collapse:collapse;overflow:hidden;border-radius:12px;background:#1b1b1b}"
        "th,td{border:1px solid #2a2a2a;padding:10px;text-align:left}"
        "th{background:#222}"
        "</style>"
        "</head><body>"
        "<div class='card'><h1>📊 Bot Dashboard</h1></div>"
        "<div class='card'>"
        f"<p><b>Users:</b> {total_users}<br>"
        f"<b>Queued files:</b> {total_queue}<br>"
        f"<b>Total coins:</b> {total_coins}</p>"
        "</div>"
        "<div class='card'>"
        "<table>"
        "<tr><th>User ID</th><th>Name</th><th>Coins</th><th>Files Used</th><th>Queued</th></tr>"
        f"{rows}"
        "</table>"
        "</div>"
        "</body></html>"
    )

def dashboard_url() -> str | None:
    if WEB_URL:
        return f"{WEB_URL}/dashboard?key={DASHBOARD_KEY}"
    return None

def run_web():
    web.run(host="0.0.0.0", port=PORT, use_reloader=False)

# ---------------------------
# HELPERS
# ---------------------------
def touch_user(user_id: int, first_name: str = "", username: str = ""):
    now = datetime.utcnow()
    users_col.update_one(
        {"_id": user_id},
        {
            "$setOnInsert": {
                "coins": STARTING_COINS,
                "files_used": 0,
                "created_at": now,
            },
            "$set": {
                "first_name": first_name,
                "username": username,
                "last_seen": now,
            },
        },
        upsert=True,
    )

def safe_name_part(text: str) -> str:
    text = re.sub(r"[^\w\s\.-]", "", text, flags=re.UNICODE)
    text = re.sub(r"\s+", " ", text).strip()
    text = text.replace("..", ".")
    return text or "file"

def original_filename(message) -> tuple[str, str]:
    media = (
        message.document
        or message.video
        or message.audio
        or message.voice
        or message.animation
    )

    name = getattr(media, "file_name", None)
    if name:
        kind = (
            "document" if message.document else
            "video" if message.video else
            "audio" if message.audio else
            "voice" if message.voice else
            "animation"
        )
        return name, kind

    if message.video:
        return f"video_{message.id}.mp4", "video"
    if message.audio:
        return f"audio_{message.id}.mp3", "audio"
    if message.voice:
        return f"voice_{message.id}.ogg", "voice"
    if message.animation:
        return f"animation_{message.id}.mp4", "animation"

    return f"file_{message.id}.bin", "document"

def kind_extension(kind: str) -> str:
    return {
        "video": ".mp4",
        "audio": ".mp3",
        "voice": ".ogg",
        "animation": ".mp4",
        "document": ".bin",
    }.get(kind, ".bin")

def progress_bar(current: int, total: int) -> str:
    total = max(total, 1)
    pct = current * 100 / total
    filled = int(pct // 5)
    filled = min(max(filled, 0), 20)
    return "█" * filled + "░" * (20 - filled) + f" {pct:.1f}%"

# ---------------------------
# HANDLERS
# ---------------------------
@bot.on_message(filters.command("start"))
async def start(_, message):
    uid = message.from_user.id
    touch_user(uid, message.from_user.first_name or "", message.from_user.username or "")

    user = users_col.find_one({"_id": uid}) or {"coins": STARTING_COINS, "files_used": 0}

    text = (
        "🚀 Renamer Bot\n\n"
        f"🆔 ID: {uid}\n"
        f"💰 Coins: {user.get('coins', STARTING_COINS)}\n"
        "📦 Send files, then use /process\n"
        "📊 Use /me for your stats"
    )

    buttons = []
    if uid == ADMIN_ID:
        url = dashboard_url()
        if url:
            buttons.append([InlineKeyboardButton("📊 Open Dashboard", url=url)])

    reply_markup = InlineKeyboardMarkup(buttons) if buttons else None
    await message.reply_text(text, reply_markup=reply_markup)

@bot.on_message(filters.document | filters.video | filters.audio | filters.voice | filters.animation)
async def save_file(_, message):
    uid = message.from_user.id
    touch_user(uid, message.from_user.first_name or "", message.from_user.username or "")

    file_name, kind = original_filename(message)
    file_id = (
        message.document.file_id if message.document else
        message.video.file_id if message.video else
        message.audio.file_id if message.audio else
        message.voice.file_id if message.voice else
        message.animation.file_id
    )

    queue_col.insert_one({
        "_id": uuid.uuid4().hex,
        "user_id": uid,
        "file_id": file_id,
        "file_name": file_name,
        "kind": kind,
        "added_at": datetime.utcnow(),
    })

    queued = queue_col.count_documents({"user_id": uid})
    await message.reply_text(f"✅ File saved.\n📦 Queued: {queued}")

@bot.on_message(filters.command("me"))
async def me(_, message):
    uid = message.from_user.id
    touch_user(uid, message.from_user.first_name or "", message.from_user.username or "")

    user = users_col.find_one({"_id": uid}) or {}
    queued = queue_col.count_documents({"user_id": uid})

    await message.reply_text(
        "👤 Your Stats\n\n"
        f"🆔 ID: {uid}\n"
        f"💰 Coins: {int(user.get('coins', STARTING_COINS))}\n"
        f"📦 Files Used: {int(user.get('files_used', 0))}\n"
        f"🕒 Queued Files: {queued}"
    )

@bot.on_message(filters.command("process"))
async def process(_, message):
    uid = message.from_user.id
    touch_user(uid, message.from_user.first_name or "", message.from_user.username or "")

    queued_files = list(queue_col.find({"user_id": uid}).sort("added_at", 1))
    if not queued_files:
        return await message.reply_text("❌ No files queued.")

    total = len(queued_files)

    if uid != ADMIN_ID:
        user = users_col.find_one({"_id": uid}) or {"coins": 0}
        coins = int(user.get("coins", 0))
        if coins < total:
            return await message.reply_text(
                f"❌ Not enough coins.\n\n"
                f"Need: {total}\n"
                f"You have: {coins}"
            )
        users_col.update_one(
            {"_id": uid},
            {"$inc": {"coins": -total}, "$set": {"last_seen": datetime.utcnow()}},
            upsert=True,
        )

    os.makedirs("downloads", exist_ok=True)

    status = await message.reply_text(f"⚡ Starting...\n\n{progress_bar(0, total)}")

    processed = 0

    for item in queued_files:
        downloaded_path = None
        original_name = item["file_name"]
        base, ext = os.path.splitext(original_name)

        if not ext:
            ext = kind_extension(item.get("kind", "document"))

        clean_base = safe_name_part(base)
        temp_name = f"{uid}_{item['_id']}_{clean_base}{ext}"
        temp_path = os.path.join("downloads", temp_name)

        try:
            downloaded_path = await bot.download_media(item["file_id"], file_name=temp_path)

            sent = await bot.send_document(
                CHANNEL_ID,
                downloaded_path,
                caption=os.path.basename(downloaded_path)
            )

            link = f"https://t.me/c/{str(CHANNEL_ID)[4:]}/{sent.id}"

            processed += 1
            await status.edit_text(f"📊 Processing {processed}/{total}\n\n{progress_bar(processed, total)}")

            await message.reply_text(
                f"✅ {os.path.basename(downloaded_path)}\n"
                f"🔗 {link}"
            )

            queue_col.delete_one({"_id": item["_id"]})

            if downloaded_path and os.path.exists(downloaded_path):
                os.remove(downloaded_path)

        except Exception as e:
            if downloaded_path and os.path.exists(downloaded_path):
                os.remove(downloaded_path)

            await message.reply_text(f"❌ Failed for:\n{original_name}\n\n{e}")

    if processed:
        users_col.update_one(
            {"_id": uid},
            {"$inc": {"files_used": processed}, "$set": {"last_seen": datetime.utcnow()}},
            upsert=True,
        )

    await status.edit_text(f"✅ Done!\n\nProcessed: {processed}/{total}")

@bot.on_message(filters.command("stats"))
async def stats(_, message):
    if message.from_user.id != ADMIN_ID:
        return

    total_users = users_col.count_documents({})
    total_queued = queue_col.count_documents({})
    total_coins = 0

    for user in users_col.find({}, {"coins": 1}):
        total_coins += int(user.get("coins", 0))

    url = dashboard_url() or "Set WEB_URL and DASHBOARD_KEY"

    await message.reply_text(
        "📊 Admin Stats\n\n"
        f"👥 Users: {total_users}\n"
        f"📦 Queued Files: {total_queued}\n"
        f"💰 Total Coins: {total_coins}\n\n"
        f"🌐 Dashboard: {url}"
    )

@bot.on_message(filters.command("addcoins"))
async def addcoins(_, message):
    if message.from_user.id != ADMIN_ID:
        return

    parts = message.text.split()
    if len(parts) != 3:
        return await message.reply_text("Use:\n/addcoins user_id amount")

    try:
        target_id = int(parts[1])
        amount = int(parts[2])
    except ValueError:
        return await message.reply_text("Use numeric user_id and amount.")

    touch_user(target_id)
    users_col.update_one(
        {"_id": target_id},
        {"$inc": {"coins": amount}, "$set": {"last_seen": datetime.utcnow()}},
        upsert=True,
    )

    await message.reply_text("✅ Coins updated.")

# ---------------------------
# MAIN
# ---------------------------
async def main():
    Thread(target=run_web, daemon=True).start()
    await bot.start()
    print("Bot Started ✅")
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
