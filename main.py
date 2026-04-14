import asyncio

try:
    asyncio.get_running_loop()
except RuntimeError:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

import nest_asyncio
nest_asyncio.apply()

import os
from pyrogram import Client, filters

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))

app = Client("bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# user file storage (simple)
user_files = {}

@app.on_message(filters.command("start"))
async def start(client, message):
    await message.reply(
        "🚀 Renamer SaaS Bot\n\n"
        "Send files → /process\n"
        "Open Dashboard below 👇",
        reply_markup={
            "inline_keyboard": [
                [{"text": "👥 Open Dashboard", "web_app": {"url": os.getenv("WEB_URL")}}]
            ]
        }
    )

# save files
@app.on_message(filters.document | filters.video | filters.audio)
async def save(client, message):
    uid = message.from_user.id

    if uid not in user_files:
        user_files[uid] = []

    user_files[uid].append(message)

    await message.reply(f"📦 Files: {len(user_files[uid])}")

# process
@app.on_message(filters.command("process"))
async def process(client, message):
    uid = message.from_user.id

    if uid not in user_files:
        return await message.reply("❌ No files")

    for msg in user_files[uid]:
        file = msg.document or msg.video or msg.audio
        path = await msg.download()

        new_name = file.file_name.replace(".", " ")
        os.rename(path, new_name)

        sent = await client.send_document(CHANNEL_ID, new_name)

        link = f"https://t.me/c/{str(CHANNEL_ID)[4:]}/{sent.id}"

        # save link
        user_files[uid].append(link)

        await message.reply(f"📤 Uploaded:\n{link}")

        os.remove(new_name)

    await message.reply("✅ Done!")

app.run()
