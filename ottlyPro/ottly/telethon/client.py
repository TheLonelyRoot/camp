from telethon import TelegramClient
from telethon.sessions import StringSession
from ..core.config import ENV
from .sessions import read_string_session

async def client_from_session_file(path:str) -> TelegramClient:
    sess = read_string_session(path)
    client = TelegramClient(StringSession(sess), ENV.API_ID_DEFAULT, ENV.API_HASH_DEFAULT)
    await client.connect()
    return client
