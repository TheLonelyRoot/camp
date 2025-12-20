import os
import re
from ..core.config import ENV

def telethon_session_filepath(user_id:int, phone:str)->str:
    slug = re.sub(r"[^0-9+]", "", phone)
    return os.path.join(ENV.SESSIONS_DIR, f"{user_id}_{slug}.session")

def write_string_session(path:str, session_str:str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(session_str)

def read_string_session(path:str)->str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read().strip()
