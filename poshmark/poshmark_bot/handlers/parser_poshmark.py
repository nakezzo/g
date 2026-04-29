import asyncio
import re
import random
from datetime import datetime
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from ..storage import (
    load_accounts, load_templates, load_variables, load_parser_config,
    save_parser_config, save_accounts, append_log
)
from ..utils.keyboards import kb_parser, kb_back, kb_categories
from ..utils.helpers import safe_text, gen_random_id, apply_vars, pick_rotated, random_delay, replace_random_ids
from ..core.parser.poshmark import PoshmarkParser
from ..core.smtp import SMTPMailSender
from ..models import Account, SentLog, PoshmarkItem
from ..states import ParserProxy
from ..globals import parser_state, is_sending
import io

router = Router()

@router.callback_query(F.data == "menu:parser")
async def cb_parser_menu(call: CallbackQuery):
    uid = call.from_user.id
    cfg     = load_parser_config(uid)
    running = parser_state["running"]
    stats   = ""
    if running and parser_state["parser"]:
        s = parser_state["parser"].stats
        stats = (f"\n\n📈 <b>Статистика:</b> найдено {s['found']}, "
                 f"валидных {s['valid']}, ошибок {s['errors']}")
    await call.message.edit_text(
        f"🕷 <b>Парсер Poshmark</b>\n<code>━━━━━━━━━━━━━━━━━━━━━━</code>\n"
        f"Статус: {'🟢 Работает' if running else '🔴 Остановлен'}\n"
        f"Категорий: {len(cfg.get('selected_categories', []))}\n"
        f"Авто-отправка: {'✅' if cfg.get('auto_send') else '⬜'}"
        f"{stats}",
        reply_markup=kb_parser(running, cfg),
    )
    await call.answer()

@router.callback_query(F.data == "parser:start")
async def cb_parser_start(call: CallbackQuery):
    uid = call.from_user.id
    if parser_state["running"]:
        await call.answer("Парсер уже запущен", show_alert=True)
        return

    accounts    = load_accounts(uid)
    _, selected = load_templates(uid)
    enabled     = [a for a in accounts if a.enabled]
    cfg         = load_parser_config(uid)

    if cfg.get("auto_send") and (not enabled or not selected):
        await call.answer("⚠️ Нет аккаунтов или шаблонов для авто-отправки!", show_alert=True)
        return

    chat_id = call.message.chat.id
    bot     = call.bot

    parser_state["running"] = True
    parser_state["chat_id"] = chat_id
    parser_state["bot"]     = bot
    parser_state["queue"]   = asyncio.Queue()

    def log_cb(msg: str):
        asyncio.create_task(bot.send_message(chat_id, f"🕷 {msg}"))

    p = PoshmarkParser(cfg, log_cb=log_cb)
    parser_state["parser"] = p

    task = asyncio.create_task(_parser_run(p, parser_state["queue"], chat_id, bot))
    parser_state["task"] = task

    await call.message.edit_text(
        "🟢 <b>Парсер запущен!</b>\n\nНайденные email будут отправляться сюда.",
        reply_markup=kb_back(),
    )
    await call.answer()

async def _parser_run(parser: PoshmarkParser, q: asyncio.Queue,
                      chat_id: int, bot: Bot):
    uid  = chat_id
    cfg  = load_parser_config(uid)
    auto = cfg.get("auto_send", True)

    async def consume():
        while parser.is_running:
            try:
                item: PoshmarkItem = await asyncio.wait_for(q.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue

            await bot.send_message(
                chat_id,
                f"📦 <b>Найден:</b> <code>{item.email}</code>\n"
                f"👤 {item.username} | 💰 {item.price or 'N/A'} | "
                f"📦 Продаж: {item.sold_count or '0'}\n"
                f"<a href='{item.item_url}'>{item.item_title}</a>"
            )

            if auto:
                asyncio.create_task(_send_to_item(item, chat_id, bot))

    await asyncio.gather(
        parser.start(q),
        consume(),
        return_exceptions=True,
    )

    parser_state["running"] = False
    parser_state["parser"]  = None
    try:
        await bot.send_message(chat_id, "⏹ <b>Парсер остановлен.</b>")
    except Exception:
        pass

async def _send_to_item(item: PoshmarkItem, chat_id: int, bot: Bot):
    uid            = chat_id
    accounts       = load_accounts(uid)
    variables      = load_variables(uid)
    templates, sel = load_templates(uid)
    subjects       = load_subjects(uid)
    enabled        = [a for a in accounts if a.enabled]

    if not enabled or not sel:
        return

    _cfg = load_parser_config(uid)
    _rot = _cfg.get("rotate_every", {})
    base_counter = _cfg.get("send_counter", 0)

    async def _do_send(acc: Account, acc_index: int):
        if acc.send_limit > 0 and acc.sent_count >= acc.send_limit:
            return

        tpl_name = random.choice(sel)
        html_raw = templates.get(tpl_name, "")
        if not html_raw:
            return

        _counter = base_counter + acc_index
        sender_name = replace_random_ids(pick_rotated(variables.get("sender", []), "sender", _counter, _rot))
        title       = replace_random_ids(pick_rotated(variables.get("title",  []), "title",  _counter, _rot))
        body        = replace_random_ids(pick_rotated(variables.get("text",   []), "text",   _counter, _rot))
        button      = replace_random_ids(pick_rotated(variables.get("button", []), "button", _counter, _rot))
        link        = replace_random_ids(pick_rotated(variables.get("link",   []), "link",   _counter, _rot))
        subject_tpl = pick_rotated(subjects, "subject", _counter, _rot, "Hello from Poshmark")

        rid = gen_random_id()
        subject = apply_vars(subject_tpl, item.email, sender_name, title, body, button, link, fixed_random_id=rid)
        html    = apply_vars(html_raw,    item.email, sender_name, title, body, button, link, fixed_random_id=rid)

        delay = random_delay(uid)
        await asyncio.sleep(delay)

        loop       = asyncio.get_running_loop()
        sender_obj = SMTPMailSender(acc.email, acc.password)
        ok, status = await loop.run_in_executor(
            None, lambda s=sender_obj: s.send_email(item.email, subject, html, sender_name)
        )

        if ok:
            acc.sent_count += 1
        else:
            acc.error_count += 1
            acc.last_error = status[:100]

        _cfg2 = load_parser_config(uid)
        _cfg2["send_counter"] = _cfg2.get("send_counter", 0) + 1
        save_parser_config(uid, _cfg2)

        append_log(uid, SentLog(
            from_email=acc.email, to_email=item.email, subject=subject,
            status="✅" if ok else "❌",
            timestamp=datetime.now().isoformat(),
            error="" if ok else status,
        ))

        icon = "✅" if ok else "❌"
        try:
            await bot.send_message(
                chat_id,
                f"{icon} Авто-отправка <code>{acc.email}</code> → <code>{item.email}</code>: {status}"
            )
        except Exception:
            pass

    await asyncio.gather(
        *[_do_send(acc, idx) for idx, acc in enumerate(enabled)],
        return_exceptions=True,
    )
    save_accounts(uid, accounts)

@router.callback_query(F.data == "parser:stop")
async def cb_parser_stop(call: CallbackQuery):
    uid = call.from_user.id
    if not parser_state["running"]:
        await call.answer("Парсер не запущен", show_alert=True)
        return

    if parser_state["parser"]:
        parser_state["parser"].stop()
    if parser_state["task"]:
        parser_state["task"].cancel()

    parser_state["running"] = False
    parser_state["parser"]  = None
    parser_state["task"]    = None

    cfg = load_parser_config(uid)
    await call.message.edit_text(
        "🔴 <b>Парсер остановлен.</b>",
        reply_markup=kb_parser(False, cfg),
    )
    await call.answer()

@router.callback_query(F.data == "parser:toggle_auto")
async def cb_parser_toggle_auto(call: CallbackQuery):
    uid = call.from_user.id
    cfg = load_parser_config(uid)
    cfg["auto_send"] = not cfg.get("auto_send", True)
    save_parser_config(uid, cfg)
    running = parser_state["running"]
    stats = ""
    if running and parser_state["parser"]:
        s = parser_state["parser"].stats
        stats = (f"\n\n📈 найдено {s['found']}, валидных {s['valid']}, ошибок {s['errors']}")
    await call.message.edit_text(
        f"🕷 <b>Парсер Poshmark</b>\n<code>━━━━━━━━━━━━━━━━━━━━━━</code>\n"
        f"Статус: {'🟢 Работает' if running else '🔴 Остановлен'}\n"
        f"Категорий: {len(cfg.get('selected_categories', []))}\n"
        f"Авто-отправка: {'✅' if cfg.get('auto_send') else '⬜'}{stats}",
        reply_markup=kb_parser(running, cfg),
    )
    await call.answer()

@router.callback_query(F.data == "parser:categories")
async def cb_parser_cats(call: CallbackQuery):
    uid = call.from_user.id
    cfg = load_parser_config(uid)
    await call.message.edit_text(
        "📂 <b>Категории Poshmark</b>\n<code>━━━━━━━━━━━━━━━━━━━━━━</code>\nВыберите категории для парсинга:",
        reply_markup=kb_categories(cfg),
    )
    await call.answer()

@router.callback_query(F.data.startswith("parser:cat:"))
async def cb_parser_cat_toggle(call: CallbackQuery):
    uid = call.from_user.id
    path = call.data.removeprefix("parser:cat:")
    cfg  = load_parser_config(uid)
    sel  = cfg.get("selected_categories", [])
    if path in sel:
        sel.remove(path)
    else:
        sel.append(path)
    cfg["selected_categories"] = sel
    save_parser_config(uid, cfg)
    await call.message.edit_reply_markup(reply_markup=kb_categories(cfg))
    await call.answer()

@router.callback_query(F.data == "parser:proxy")
async def cb_parser_proxy(call: CallbackQuery):
    uid = call.from_user.id
    cfg     = load_parser_config(uid)
    proxies = cfg.get("proxies", [])
    prev    = "\n".join(f"  <code>{p[:60]}</code>" for p in proxies[:5])
    if len(proxies) > 5:
        prev += f"\n  <i>... и ещё {len(proxies)-5}</i>"

    b = InlineKeyboardBuilder()
    b.button(text="➕ Добавить прокси (текстом)",  callback_data="parser:proxy:add")
    b.button(text="📎 Загрузить из файла .txt",    callback_data="parser:proxy:file")
    b.button(text="🗑 Очистить все прокси",        callback_data="parser:proxy:clear")
    b.button(text="◀️ Назад к парсеру",           callback_data="menu:parser")
    b.adjust(1)

    await call.message.edit_text(
        f"🌐 <b>Прокси парсера</b>\n<code>━━━━━━━━━━━━━━━━━━━━━━</code>\n\n"
        f"Всего: <b>{len(proxies)}</b>\n\n"
        f"{prev if prev else '<i>Список пуст — работает без прокси</i>'}\n\n"
        "<b>Форматы:</b>\n"
        "<code>http://ip:port</code>\n"
        "<code>http://user:pass@ip:port</code>\n"
        "<code>socks5://ip:port</code>",
        reply_markup=b.as_markup(),
    )
    await call.answer()

@router.callback_query(F.data == "parser:proxy:add")
async def cb_parser_proxy_add(call: CallbackQuery, state: FSMContext):
    await state.set_state(ParserProxy.input)
    await state.update_data(proxy_input_mode="text")
    b = InlineKeyboardBuilder()
    b.button(text="◀️ Отмена", callback_data="parser:proxy")
    await call.message.edit_text(
        "🌐 <b>Добавить прокси</b>\n\n"
        "Введи прокси (каждый с новой строки):\n\n"
        "<code>http://1.2.3.4:8080\n"
        "http://user:pass@5.6.7.8:3128\n"
        "socks5://9.10.11.12:1080</code>\n\n"
        "/cancel — отмена",
        reply_markup=b.as_markup(),
    )
    await call.answer()

@router.callback_query(F.data == "parser:proxy:file")
async def cb_parser_proxy_file(call: CallbackQuery, state: FSMContext):
    await state.set_state(ParserProxy.input)
    await state.update_data(proxy_input_mode="file")
    b = InlineKeyboardBuilder()
    b.button(text="◀️ Отмена", callback_data="parser:proxy")
    await call.message.edit_text(
        "📎 <b>Загрузить прокси из файла</b>\n\n"
        "Отправь .txt файл — один прокси на строку:\n\n"
        "<code>http://ip:port\nhttp://user:pass@ip:port</code>\n\n"
        "/cancel — отмена",
        reply_markup=b.as_markup(),
    )
    await call.answer()

@router.callback_query(F.data == "parser:proxy:clear")
async def cb_parser_proxy_clear(call: CallbackQuery):
    uid = call.from_user.id
    cfg = load_parser_config(uid)
    cfg["proxies"]   = []
    cfg["proxy_idx"] = 0
    save_parser_config(uid, cfg)
    await call.answer("✅ Прокси очищены", show_alert=True)
    await cb_parser_proxy(call)

@router.message(ParserProxy.input)
async def fsm_parser_proxy_text(message: Message, state: FSMContext):
    if message.document: return
    text = message.text or ""
    await _save_parser_proxies(message, state, text)

@router.message(ParserProxy.input, F.document)
async def fsm_parser_proxy_doc(message: Message, state: FSMContext, bot: Bot):
    doc  = message.document
    if not doc.file_name.lower().endswith(".txt"):
        await message.answer("⚠️ Нужен .txt файл. /cancel — отмена")
        return
    file = await bot.get_file(doc.file_id)
    buf  = io.BytesIO()
    await bot.download_file(file.file_path, buf)
    text = buf.getvalue().decode("utf-8", errors="ignore")
    await _save_parser_proxies(message, state, text)

async def _save_parser_proxies(message: Message, state: FSMContext, text: str):
    uid = message.from_user.id
    lines   = [l.strip() for l in text.splitlines() if l.strip()]
    valid   = [l for l in lines if re.match(r"(https?|socks[45])://", l)]
    invalid = len(lines) - len(valid)

    if not valid:
        await message.answer(
            "❌ Прокси не найдены.\n\n"
            "Нужен формат: <code>http://ip:port</code>\n/cancel — отмена"
        )
        return

    cfg = load_parser_config(uid)
    existing = cfg.get("proxies", [])
    merged   = list(dict.fromkeys(existing + valid))
    cfg["proxies"]   = merged
    cfg["proxy_idx"] = 0
    save_parser_config(uid, cfg)
    await state.clear()

    warn = f"\n⚠️ Пропущено {invalid} невалидных" if invalid else ""
    b = InlineKeyboardBuilder()
    b.button(text="🌐 К прокси",        callback_data="parser:proxy")
    b.button(text="◀️ Назад к парсеру", callback_data="menu:parser")
    b.adjust(1)
    await message.answer(
        f"✅ <b>Прокси сохранены!</b>\n\n"
        f"Добавлено: <b>{len(valid)}</b>\n"
        f"Всего в списке: <b>{len(merged)}</b>{warn}",
        reply_markup=b.as_markup(),
    )
