import asyncio
import os
import sys
import yaml
from dotenv import load_dotenv
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
        await client.run_until_disconnected()
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

        chat = await event.get_chat()
        sender = await event.get_sender()

        print("\n" + "=" * 60)
        print(f"CHANNEL : {getattr(chat, 'title', chat.id)}")
        print(f"SENDER  : {getattr(sender, 'username', sender.id)}")
        print(f"TIME    : {event.date}")
        print(f"MESSAGE :\n{event.raw_text}")
        print("=" * 60)

    print(f"Listening to {len(channel_entities)} channel(s). Waiting for messages...")
    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())