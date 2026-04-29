import json
import os
from typing import Dict, List, Tuple
from .config import DATA_DIR, POSHMARK_CATEGORIES, _API_PARSERS
from .models import Account, SentLog

def _uid(tg_id) -> str:
    return str(tg_id)

def _udir(tg_id) -> str:
    d = os.path.join(DATA_DIR, _uid(tg_id))
    os.makedirs(d, exist_ok=True)
    return d

def _upath(tg_id, filename: str) -> str:
    return os.path.join(_udir(tg_id), filename)

def _load_json(path: str, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def _save_json(path: str, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def load_accounts(uid) -> List[Account]:
    data = _load_json(_upath(uid, "accounts.json"), [])
    accounts = []
    for d in data:
        d.setdefault("send_limit", 0)
        accounts.append(Account(**d))
    return accounts

def save_accounts(uid, accounts: List[Account]):
    _save_json(_upath(uid, "accounts.json"), [a.__dict__ for a in accounts])

def load_variables(uid) -> Dict[str, List[str]]:
    return _load_json(_upath(uid, "variables.json"),
                      {k: [] for k in ["sender", "title", "text", "button", "link"]})

def save_variables(uid, variables: dict):
    _save_json(_upath(uid, "variables.json"), variables)

def load_templates(uid) -> Tuple[Dict[str, str], List[str]]:
    data = _load_json(_upath(uid, "templates.json"), {})
    return data.get("templates", {}), data.get("selected", [])

def save_templates(uid, templates: dict, selected: list):
    _save_json(_upath(uid, "templates.json"), {"templates": templates, "selected": selected})

def load_subjects(uid) -> List[str]:
    data = _load_json(_upath(uid, "subjects.json"), ["Hello"])
    if isinstance(data, str):
        return [data] if data.strip() else ["Hello"]
    return [s for s in data if s.strip()] or ["Hello"]

def save_subjects(uid, subjects: List[str]):
    _save_json(_upath(uid, "subjects.json"), subjects)

def load_logs(uid) -> List[dict]:
    return _load_json(_upath(uid, "logs.json"), [])

def append_log(uid, log: SentLog):
    logs = load_logs(uid)
    logs.append(log.__dict__)
    _save_json(_upath(uid, "logs.json"), logs[-1000:])

def load_api_parsers_cfg(uid) -> dict:
    default = {
        pid: {
            "token":       "",
            "enabled":     False,
            "platform":    "vinted",
            "country":     "DE",
            "category":    "",
            "price":       "1..",
            "limit":       50,
            "auto_send":   True,
            "interval":    60,
            "publication": "",
            "reviews":     "",
            "ads":         "",
            "sells":       "",
            "buys":        "",
            "blacklist":   "",
            "email_only":  True,
            "total_found": 0,
            "last_run":    "",
        }
        for pid in _API_PARSERS
    }
    saved = _load_json(_upath(uid, "api_parsers.json"), {})
    for pid in default:
        if pid in saved:
            default[pid].update(saved[pid])
    return default

def save_api_parsers_cfg(uid, cfg: dict):
    _save_json(_upath(uid, "api_parsers.json"), cfg)

def _parser_defaults() -> dict:
    return {
        "selected_categories": list(POSHMARK_CATEGORIES.values()),
        "cycle_delay": 2.0,
        "request_delay": 0.3,
        "max_concurrent": 10,
        "items_per_page": 30,
        "max_sales": 0,
        "max_reviews": 0,
        "auto_send": True,
        "delay_min": 17,
        "delay_max": 24,
        "proxies": [],
        "proxy_idx": 0,
        "rotate_every": {
            "sender":  0,
            "title":   0,
            "text":    0,
            "button":  0,
            "link":    0,
            "subject": 0,
        },
        "send_counter": 0,
    }

def load_parser_config(uid) -> dict:
    defaults = _parser_defaults()
    data = _load_json(_upath(uid, "parser.json"), {})
    defaults.update(data)
    return defaults

def save_parser_config(uid, cfg: dict):
    _save_json(_upath(uid, "parser.json"), cfg)
