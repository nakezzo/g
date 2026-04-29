import random
from typing import List, Optional
from aiogram.types import Message
from ..config import SMTP_MAP

def get_smtp_server(email: str) -> str:
    domain = email.split("@")[-1].lower() if "@" in email else ""
    return SMTP_MAP.get(domain, f"smtp.{domain}")

def random_delay(uid) -> float:
    cfg = load_parser_config(uid)
    d_min = cfg.get("delay_min", 17)
    d_max = cfg.get("delay_max", 24)
    return random.uniform(d_min, d_max)

def gen_random_id() -> str:
    return str(random.randint(1000000000, 9999999999))

def replace_random_ids(text: str, fixed_id: str = None) -> str:
    if fixed_id is not None:
        return text.replace("{randomID}", fixed_id)
    while "{randomID}" in text:
        text = text.replace("{randomID}", str(random.randint(1000000000, 9999999999)), 1)
    return text

def apply_vars(text: str, recipient: str, sender: str,
               title: str, body: str, button: str, link: str,
               fixed_random_id: str = None) -> str:
    if fixed_random_id is None:
        fixed_random_id = gen_random_id()
    for k, v in [("{recipient}", recipient), ("{sender}", sender),
                 ("{title}", title), ("{text}", body),
                 ("{button}", button), ("{link}", link)]:
        text = text.replace(k, v)
    return replace_random_ids(text, fixed_random_id)

def pick(lst: List[str], default: str = "") -> str:
    return random.choice(lst) if lst else default

def pick_rotated(lst: List[str], key: str, counter: int, rotate_every: dict, default: str = "") -> str:
    if not lst:
        return default
    every = int(rotate_every.get(key, 0))
    if every <= 0:
        return random.choice(lst)
    idx = (counter // every) % len(lst)
    return lst[idx]

def safe_text(msg: Message) -> Optional[str]:
    return msg.text if msg.text else None
