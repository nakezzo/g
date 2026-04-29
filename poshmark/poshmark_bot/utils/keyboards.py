from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from ..config import POSHMARK_CATEGORIES, VAR_LABELS
from ..models import Account
from typing import List

def kb_main(is_sending_active: bool) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="📧 Аккаунты",        callback_data="menu:accounts")
    b.button(text="🗂 HTML шаблоны",    callback_data="menu:templates")
    b.button(text="🔧 Переменные",      callback_data="menu:vars")
    b.button(text="✉️ Темы писем",       callback_data="menu:subject")
    b.button(text="🚀 Отправить письма", callback_data="menu:send")
    if is_sending_active:
        b.button(text="⏹ Стоп",         callback_data="send:stop")
    else:
        b.button(text="⏹ Стоп",         callback_data="send:stop_inactive")
    b.button(text="🕷 Парсер Poshmark", callback_data="menu:parser")
    b.button(text="📡 Парсеры",          callback_data="apip:menu")
    b.button(text="⏱ Задержка",         callback_data="menu:delay")
    b.button(text="🔁 Ротация",         callback_data="menu:rotation")
    b.button(text="📊 Статистика",      callback_data="menu:logs")
    b.adjust(2)
    return b.as_markup()

def kb_back() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="◀️ Главное меню", callback_data="menu:main")
    return b.as_markup()

def kb_accounts(accounts: List[Account]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for idx, acc in enumerate(accounts):
        icon  = "🟢" if acc.enabled else "🔴"
        limit = f"лим:{acc.send_limit}" if acc.send_limit > 0 else "∞"
        b.button(
            text=f"{icon} {acc.email}  (→{acc.sent_count} ✗{acc.error_count} [{limit}])",
            callback_data=f"acc:toggle:{idx}",
        )
        b.button(
            text=f"⚙️ Лимит: {acc.send_limit if acc.send_limit > 0 else '∞'}",
            callback_data=f"acc:limit:{idx}",
        )
        b.button(
            text="🗑",
            callback_data=f"acc:delete:{idx}",
        )
    b.button(text="➕ Добавить аккаунт",    callback_data="acc:add")
    b.button(text="🗑 Очистить статистику", callback_data="acc:clear_stats")
    b.button(text="◀️ Назад",              callback_data="menu:main")
    sizes = [3] * len(accounts) + [1, 1, 1]
    b.adjust(*sizes)
    return b.as_markup()

def kb_vars() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for key, label in VAR_LABELS.items():
        b.button(text=label, callback_data=f"var:edit:{key}")
    b.button(text="◀️ Назад", callback_data="menu:main")
    b.adjust(1)
    return b.as_markup()

def kb_templates(templates: dict, selected: list) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    names = list(templates.keys())
    for idx, name in enumerate(names):
        check = "✅" if name in selected else "⬜"
        b.button(text=f"{check} {name[:40]}", callback_data=f"tpl:toggle:{idx}")
        b.button(text="🗑", callback_data=f"tpl:del:{idx}")
    b.button(text="➕ Добавить шаблон (текстом)", callback_data="tpl:add")
    b.button(text="◀️ Назад", callback_data="menu:main")
    sizes = [2] * len(templates) + [1, 1]
    b.adjust(*sizes)
    return b.as_markup()

def kb_parser(running: bool, cfg: dict) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    cats_count   = len(cfg.get("selected_categories", []))
    proxy_count  = len(cfg.get("proxies", []))
    auto         = "✅" if cfg.get("auto_send") else "⬜"
    if running:
        b.button(text="⏹ Остановить", callback_data="parser:stop")
    else:
        b.button(text="▶️ Запустить парсер", callback_data="parser:start")
    b.button(text=f"📂 Категории ({cats_count})",          callback_data="parser:categories")
    b.button(text=f"🌐 Прокси ({proxy_count})",            callback_data="parser:proxy")
    b.button(text=f"{auto} Авто-отправка",                 callback_data="parser:toggle_auto")
    b.button(text="◀️ Назад",                              callback_data="menu:main")
    b.adjust(1)
    return b.as_markup()

def kb_categories(cfg: dict) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    sel = cfg.get("selected_categories", [])
    for name, path in POSHMARK_CATEGORIES.items():
        check = "✅" if path in sel else "⬜"
        b.button(text=f"{check} {name.capitalize()}", callback_data=f"parser:cat:{path}")
    b.button(text="◀️ Назад к парсеру", callback_data="menu:parser")
    b.adjust(2)
    return b.as_markup()
