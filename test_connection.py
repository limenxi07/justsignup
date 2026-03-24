import asyncio
import os
from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from telethon.network import ConnectionTcpFull

load_dotenv()

API_ID = int(os.getenv("TELEGRAM_API_ID"))
API_HASH = os.getenv("TELEGRAM_API_HASH")

async def main():
    client = TelegramClient("justsignup_test", API_ID, API_HASH, connection=ConnectionTcpFull)
    
    await client.connect()

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
    
    await client.disconnect()

asyncio.run(main())