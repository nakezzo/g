import asyncio
from typing import Dict, Optional

parser_state: Dict = {
    "running":  False,
    "parser":   None,
    "task":     None,
    "queue":    None,
    "chat_id":  None,
    "bot":      None,
}

_stop_events: Dict[int, asyncio.Event] = {}
_active_sends: set = set()
_send_status_msg: Dict[int, "Message"] = {}

def get_stop_event(uid) -> asyncio.Event:
    key = int(uid)
    if key not in _stop_events:
        _stop_events[key] = asyncio.Event()
    return _stop_events[key]

def is_sending(uid) -> bool:
    return int(uid) in _active_sends
