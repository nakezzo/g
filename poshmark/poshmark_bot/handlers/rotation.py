from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from ..storage import load_parser_config, save_parser_config
from ..utils.keyboards import kb_main
from ..utils.helpers import safe_text
from ..states import EditRotation
from ..globals import is_sending

router = Router()

ROT_LABELS = {
    "sender":  "👤 {sender} — Имя отправителя",
    "title":   "🏷 {title} — Заголовок",
    "text":    "📝 {text} — Текст письма",
    "button":  "🔘 {button} — Кнопка",
    "link":    "🔗 {link} — Ссылка",
    "subject": "📩 subject — Тема письма",
}

def _rot_summary(cfg: dict) -> str:
    rot = cfg.get("rotate_every", {})
    counter = cfg.get("send_counter", 0)
    lines = []
    for key, label in ROT_LABELS.items():
        every = rot.get(key, 0)
        if every <= 0:
            mode = "🎲 рандом"
        elif every == 1:
            mode = "🔁 каждое письмо по кругу"
        else:
            mode = f"🔁 каждые {every} писем по кругу"
        lines.append(f"• {label}\n  → {mode}")
    lines.append(f"\n📬 Счётчик отправок: <code>{counter}</code>")
    return "\n".join(lines)

def kb_rotation(cfg: dict) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    rot = cfg.get("rotate_every", {})
    for key, label in ROT_LABELS.items():
        every = rot.get(key, 0)
        if every <= 0:
            mark = "🎲"
        elif every == 1:
            mark = "🔁1"
        else:
            mark = f"🔁{every}"
        b.button(text=f"{mark} {label}", callback_data=f"rot:edit:{key}")
    b.button(text="🔄 Сбросить счётчик", callback_data="rot:reset_counter")
    b.button(text="◀️ Назад",            callback_data="menu:main")
    b.adjust(1)
    return b.as_markup()

@router.callback_query(F.data == "menu:rotation")
async def cb_rotation_menu(call: CallbackQuery):
    uid = call.from_user.id
    cfg = load_parser_config(uid)
    await call.message.edit_text(
        "🔁 <b>Ротация переменных</b>\n<code>━━━━━━━━━━━━━━━━━━━━━━</code>\n"
        "🎲 = рандом  ·  🔁N = каждые N писем по кругу\n"
        "🔁N = каждые N писем — следующее значение по кругу\n\n"
        + _rot_summary(cfg)
        + "\n\nНажмите на переменную чтобы изменить:",
        reply_markup=kb_rotation(cfg),
    )
    await call.answer()

@router.callback_query(F.data.startswith("rot:edit:"))
async def cb_rotation_edit(call: CallbackQuery, state: FSMContext):
    uid = call.from_user.id
    key = call.data.removeprefix("rot:edit:")
    cfg = load_parser_config(uid)
    every = cfg.get("rotate_every", {}).get(key, 0)
    label = ROT_LABELS.get(key, key)
    if every <= 0:
        cur = "🎲 рандом"
    elif every == 1:
        cur = "🔁 каждое письмо по кругу"
    else:
        cur = f"🔁 каждые {every} писем по кругу"
    await state.update_data(rot_key=key)
    await state.set_state(EditRotation.waiting)
    await call.message.edit_text(
        f"🔁 <b>{label}</b>\n\n"
        f"Текущее: {cur}\n\n"
        "Введи число:\n"
        "<code>х</code> или <code>0</code> — случайно при каждой отправке 🎲\n"
        "<code>1</code> — каждое письмо следующее по кругу (1→2→3→1...)\n"
        "<code>5</code> — каждые 5 писем следующее по кругу\n\n"
        "/cancel — отмена"
    )
    await call.answer()

@router.message(EditRotation.waiting)
async def fsm_rotation(message: Message, state: FSMContext):
    uid = message.from_user.id
    text = safe_text(message)
    if not text:
        await message.answer("⚠️ Отправьте число или х. /cancel — отмена")
        return

    val = text.strip().lower()
    if val in ("х", "x", "0"):
        every = 0
    else:
        try:
            every = int(val)
            if every < 0:
                raise ValueError
        except ValueError:
            await message.answer(
                "⚠️ Введи целое число ≥ 1, или <code>х</code> для рандома. /cancel — отмена"
            )
            return

    data = await state.get_data()
    key  = data["rot_key"]
    cfg  = load_parser_config(uid)
    if "rotate_every" not in cfg:
        cfg["rotate_every"] = {}
    cfg["rotate_every"][key] = every
    save_parser_config(uid, cfg)
    await state.clear()

    label = ROT_LABELS.get(key, key)
    if every <= 0:
        mode = "случайно при каждой отправке 🎲"
    elif every == 1:
        mode = "каждое письмо по кругу 🔁"
    else:
        mode = f"каждые {every} писем по кругу 🔁"
    await message.answer(
        f"✅ <b>{label}</b>\n→ {mode}",
        reply_markup=kb_main(is_sending(uid)),
    )

@router.callback_query(F.data == "rot:reset_counter")
async def cb_rotation_reset(call: CallbackQuery):
    uid = call.from_user.id
    cfg = load_parser_config(uid)
    cfg["send_counter"] = 0
    save_parser_config(uid, cfg)
    await call.message.edit_text(
        "🔁 <b>Ротация переменных</b>\n<code>━━━━━━━━━━━━━━━━━━━━━━</code>\n"
        "🎲 = рандом  ·  🔁N = каждые N писем по кругу\n\n"
        + _rot_summary(cfg)
        + "\n\nСчётчик сброшен! Нажмите на переменную чтобы изменить:",
        reply_markup=kb_rotation(cfg),
    )
    await call.answer("✅ Счётчик сброшен")
