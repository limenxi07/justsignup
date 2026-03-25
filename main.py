import asyncio
import json
import os
import sys
import yaml
from bot import build_app
from db import init_db, save_event
from dotenv import load_dotenv
from pipeline import run_pipeline
from telethon import TelegramClient, events
from telethon.errors import SessionPasswordNeededError
from telethon.network import ConnectionTcpFull

sys.stdout.reconfigure(line_buffering=True)

load_dotenv()

API_ID = int(os.getenv("TELEGRAM_API_ID"))
API_HASH = os.getenv("TELEGRAM_API_HASH")

with open("config.yaml") as f:
    config = yaml.safe_load(f)

public_channels = config.get("channels") or []
private_ids = [
    int(os.getenv(k))
    for k in os.environ
    if k.startswith("PRIVATE_CHANNEL_ID_") and os.getenv(k)
]
CHANNELS = public_channels + private_ids


async def main():
    init_db()

    # build the bot app but don't start polling yet
    bot_app = build_app()
    await bot_app.initialize()
    await bot_app.start()
    await bot_app.updater.start_polling()
    print("Bot started.")

    # telegram client setup
    client = TelegramClient("justsignup", API_ID, API_HASH, connection=ConnectionTcpFull)
    await client.connect()

    if await client.is_user_authorized():
        print("Session found, skipping auth.")
    else:
        phone = input("Phone number (with country code): ")
        await client.send_code_request(phone)
        code = input("Code from Telegram: ")

        try:
            await client.sign_in(phone, code)
        except SessionPasswordNeededError:
            password = input("2FA password: ")
            await client.sign_in(password=password)

        me = await client.get_me()
        print(f"Signed in as: {me.username} ({me.id})")

    print("Userbot connected.")

    if not CHANNELS:
        print("No channels configured. Add public usernames to config.yaml or PRIVATE_CHANNEL_ID_x to .env.")
        print("Idling — will start listening once channels are configured and you restart.")
        try:
            await client.run_until_disconnected()
        finally:
            await bot_app.updater.stop()
            await bot_app.stop()
            await bot_app.shutdown()
            print("Bot stopped.")
        return

    channel_entities = []
    for ch in CHANNELS:
        try:
            entity = await client.get_entity(ch)
            channel_entities.append(entity)
            print(f"  Resolved: {ch} → {entity.id}")
        except Exception as e:
            print(f"  Could not resolve {ch}: {e}")

    if not channel_entities:
        print("No channels resolved successfully. Check your channel names/IDs.")
        return

    channel_ids = {e.id for e in channel_entities}

    @client.on(events.NewMessage())
    async def handler(event):
        if event.chat_id not in channel_ids:
            return

        message = event.raw_text
        if not message or not message.strip():
            return  # skip empty messages, stickers, media with no caption

        chat = await event.get_chat()
        channel_name = getattr(chat, "title", str(event.chat_id))

        print(f"\nNew message from {channel_name}")

        # Run pipeline in executor so it doesn't block the event loop
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, run_pipeline, message, channel_name)

        if result:
            event_id = save_event(channel_name, message, result)
            print(f"  Saved to DB with id: {event_id}")

            print(f"  Event: {result.get('title')}")
            print(f"  Type: {result.get('event_type')}")
            print(f"  Date: {result.get('date')}")
            print(f"  Fee: {result.get('fee')}")
            print(f"  Full extract: {json.dumps(result, indent=2)}")
        else:
            print("  Discarded.")

    print(f"Listening to {len(channel_entities)} channel(s). Waiting for messages...")

    try:
        await client.run_until_disconnected()
    finally:
        await bot_app.updater.stop()
        await bot_app.stop()
        await bot_app.shutdown()
        print("Bot stopped.")


if __name__ == "__main__":
    asyncio.run(main())