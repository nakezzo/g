import asyncio
import aiohttp
import os
from datetime import datetime
from typing import Dict
from aiogram import Router, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from ..storage import (
    load_api_parsers_cfg, save_api_parsers_cfg, _upath
)
from ..config import _API_PARSERS, VVS_PLATFORMS
from ..utils.keyboards import kb_main
from ..states import ApiParserSt

router = Router()

_api_parser_tasks: Dict[str, asyncio.Task] = {}
_api_parser_stop:  Dict[str, bool] = {}

def load_emails_list(uid) -> list:
    path = _upath(uid, "emails.txt")
    if not os.path.exists(path): return []
    with open(path, encoding="utf-8") as f:
        return [l.strip() for l in f if l.strip() and "@" in l]

def save_emails_list(uid, emails: list):
    path = _upath(uid, "emails.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(emails))

async def _vvs_fetch(session, token: str, platform: str, params: dict) -> list:
    url = f"https://vvs.cx/ads/{platform}"
    headers = {"api-key": token}
    clean = {k: v for k, v in params.items() if v not in ("", None)}
    async with session.get(url, headers=headers, params=clean, timeout=aiohttp.ClientTimeout(total=30)) as r:
        if r.status == 402: raise Exception("❌ VVS: нет подписки (402)")
        if r.status == 403: raise Exception("❌ VVS: неверный API ключ (403)")
        if r.status == 429: raise Exception("⚠️ VVS: превышен лимит (429)")
        if r.status != 200: raise Exception(f"❌ VVS: HTTP {r.status}")
        data = await r.json()
    items = data.values() if isinstance(data, dict) else data
    results = []
    for item in items:
        if isinstance(item, dict) and item.get("email"):
            results.append({"email": item["email"], "seller": item.get("seller", ""), "price": item.get("price", ""), "title": item.get("title", "")})
    return results

async def _storm_fetch(session, token: str, platform: str, params: dict) -> list:
    url = f"https://stormparser.lol/api/parse/{platform}"
    headers = {"Authorization": f"Bearer {token}"}
    clean = {k: v for k, v in params.items() if v not in ("", None)}
    async with session.get(url, headers=headers, params=clean, timeout=aiohttp.ClientTimeout(total=30)) as r:
        if r.status in (401, 403): raise Exception("❌ Storm: неверный токен")
        if r.status == 429: raise Exception("⚠️ Storm: превышен лимит")
        if r.status != 200: raise Exception(f"❌ Storm: HTTP {r.status}")
        data = await r.json()
    items = data.get("data", data) if isinstance(data, dict) else data
    results = []
    for item in (items if isinstance(items, list) else list(items.values())):
        if isinstance(item, dict) and item.get("email"):
            results.append({"email": item["email"], "seller": item.get("username", item.get("seller", "")), "price": item.get("price", ""), "title": item.get("title", "")})
    return results

async def _xproject_fetch(session, token: str, platform: str, params: dict) -> list:
    url = f"https://api.xproject.icu/api/parse/{platform}"
    headers = {"X-API-Key": token}
    clean = {k: v for k, v in params.items() if v not in ("", None)}
    async with session.get(url, headers=headers, params=clean, timeout=aiohttp.ClientTimeout(total=30)) as r:
        if r.status in (401, 403): raise Exception("❌ xProject: неверный токен")
        if r.status == 429: raise Exception("⚠️ xProject: превышен лимит")
        if r.status != 200: raise Exception(f"❌ xProject: HTTP {r.status}")
        data = await r.json()
    items = data.get("results", data.get("data", data))
    results = []
    for item in (items if isinstance(items, list) else list(items.values())):
        if isinstance(item, dict) and item.get("email"):
            results.append({"email": item["email"], "seller": item.get("username", item.get("seller", "")), "price": item.get("price", ""), "title": item.get("title", "")})
    return results

_FETCH_FN = {"vvs": _vvs_fetch, "storm": _storm_fetch, "xproject": _xproject_fetch}

async def _run_api_parser(bot: Bot, chat_id: int, uid: int, parser_id: str, cfg_all: dict):
    pcfg     = cfg_all[parser_id]
    pname    = _API_PARSERS[parser_id]["name"]
    token    = pcfg["token"]
    platform = pcfg["platform"]
    auto     = pcfg.get("auto_send", True)
    stop_key = f"{uid}:{parser_id}"
    params = {
        "country": pcfg.get("country", ""), "price": pcfg.get("price", ""), "limit": pcfg.get("limit", 50),
        "publication": pcfg.get("publication", ""), "reviews": pcfg.get("reviews", ""), "ads": pcfg.get("ads", ""),
        "sells": pcfg.get("sells", ""), "buys": pcfg.get("buys", ""), "blacklist": pcfg.get("blacklist", ""),
    }
    if pcfg.get("category"): params["category"] = pcfg["category"]
    if pcfg.get("email_only"): params["email"] = "true"
    fetch_fn = _FETCH_FN.get(parser_id, _vvs_fetch)
    seen_emails = set()
    found_total = 0
    interval = pcfg.get("interval", 60)
    try:
        await bot.send_message(chat_id, f"{_API_PARSERS[parser_id]['icon']} <b>{pname}</b> запущен\nИнтервал: <b>{interval}с</b>\nАвто→список: {'✅' if auto else '⬜'}")
        async with aiohttp.ClientSession() as session:
            while not _api_parser_stop.get(stop_key):
                try:
                    items = await fetch_fn(session, token, platform, params)
                except Exception as ex:
                    await bot.send_message(chat_id, f"⚠️ <b>{pname}</b> ошибка: {ex}")
                    await asyncio.sleep(60); continue
                new_items = [it for it in items if it["email"] not in seen_emails]
                for it in new_items:
                    seen_emails.add(it["email"]); found_total += 1
                    try: await bot.send_message(chat_id, f"{_API_PARSERS[parser_id]['icon']} {it['email']}\n👤 {it.get('seller','—')} 💰 {it.get('price','—')}")
                    except Exception: pass
                    if auto:
                        emails = load_emails_list(uid)
                        if it["email"] not in emails: emails.append(it["email"]); save_emails_list(uid, emails)
                if new_items:
                    cfg_upd = load_api_parsers_cfg(uid)
                    cfg_upd[parser_id]["total_found"] = cfg_upd[parser_id].get("total_found",0) + len(new_items)
                    cfg_upd[parser_id]["last_run"] = datetime.now().strftime("%d.%m %H:%M")
                    save_api_parsers_cfg(uid, cfg_upd)
                    try:
                        await bot.send_message(chat_id, f"📊 <b>{pname}</b>: +{len(new_items)} новых  (сессия: {found_total})")
                    except Exception: pass
                if _api_parser_stop.get(stop_key): break
                await asyncio.sleep(interval)
    except asyncio.CancelledError: pass
    finally:
        _api_parser_stop.pop(stop_key, None); _api_parser_tasks.pop(stop_key, None)
        try: await bot.send_message(chat_id, f"⏹ <b>{pname}</b> остановлен. Найдено: {found_total}")
        except Exception: pass

@router.callback_query(F.data == "apip:menu")
async def apip_menu(call: CallbackQuery):
    uid = call.from_user.id
    cfg = load_api_parsers_cfg(uid)
    b = InlineKeyboardBuilder()
    total_found_all = 0; any_running = False
    for pid, info in _API_PARSERS.items():
        pcfg = cfg[pid]; running = f"{uid}:{pid}" in _api_parser_tasks
        if running: any_running = True
        has_tok = "✅" if pcfg["token"] else "❌"
        status = "🟢" if running else "⚪"
        found = pcfg.get("total_found", 0); total_found_all += found
        last = pcfg.get("last_run", "")
        last_s = f"  ·  {last}" if last else ""
        b.button(text=f"{info['icon']} {info['name']} {status}{has_tok} →{found}{last_s}", callback_data=f"apip:view:{pid}")
    b.button(text="⏹ Стоп все" if any_running else "▶️ Старт все", callback_data="apip:all_stop" if any_running else "apip:all_start")
    b.button(text="🗑 Сбросить статистику", callback_data="apip:reset_stats")
    b.button(text="◀️ Назад", callback_data="menu:main")
    b.adjust(1)
    emails_count = len(load_emails_list(uid))
    lines = [
        "📡 <b>Парсеры</b>", "<code>━━━━━━━━━━━━━━━━━━━━━━</code>", "",
        f"📧 Собрано email: <b>{total_found_all}</b>   В списке: <b>{emails_count}</b>", "",
        "🟢 работает  ✅ токен задан  →N найдено", "",
        "Каждый парсер имеет <b>свой API токен</b> и настройки.",
        "Нажми на парсер чтобы настроить и запустить:",
    ]
    await call.message.edit_text("\n".join(lines), reply_markup=b.as_markup()); await call.answer()

@router.callback_query(F.data == "apip:all_start")
async def apip_all_start(call: CallbackQuery):
    uid = call.from_user.id; started = []
    for pid in _API_PARSERS:
        cfg = load_api_parsers_cfg(uid); pcfg = cfg[pid]
        if not pcfg.get("token"): continue
        key = f"{uid}:{pid}"
        if key in _api_parser_tasks: continue
        _api_parser_stop[key] = False
        _api_parser_tasks[key] = asyncio.create_task(_run_api_parser(call.bot, call.message.chat.id, uid, pid, cfg))
        started.append(_API_PARSERS[pid]["name"])
    await call.answer(f"▶️ Запущено: {', '.join(started)}" if started else "⚠️ Нет токенов"); await apip_menu(call)

@router.callback_query(F.data == "apip:all_stop")
async def apip_all_stop(call: CallbackQuery):
    uid = call.from_user.id
    for pid in _API_PARSERS:
        key = f"{uid}:{pid}"; _api_parser_stop[key] = True
        task = _api_parser_tasks.get(key)
        if task: task.cancel()
    await call.answer("⏹ Все остановлены"); await apip_menu(call)

@router.callback_query(F.data == "apip:reset_stats")
async def apip_reset_stats(call: CallbackQuery):
    uid = call.from_user.id; cfg = load_api_parsers_cfg(uid)
    for pid in cfg: cfg[pid]["total_found"] = 0; cfg[pid]["last_run"] = ""
    save_api_parsers_cfg(uid, cfg); await call.answer("✅ Статистика сброшена"); await apip_menu(call)

async def _show_parser_page(call: CallbackQuery, pid: str):
    uid = call.from_user.id; cfg = load_api_parsers_cfg(uid); pcfg = cfg[pid]; info = _API_PARSERS[pid]
    running = f"{uid}:{pid}" in _api_parser_tasks; tok_ok = bool(pcfg["token"])
    tok_s = (pcfg["token"][:10] + "…") if tok_ok else "❌ не задан"
    auto_s = "✅" if pcfg.get("auto_send") else "⬜"; em_s = "✅" if pcfg.get("email_only") else "⬜"
    interval = pcfg.get("interval", 60)
    b = InlineKeyboardBuilder()
    if running: b.button(text="⏹ Остановить", callback_data=f"apip:stop:{pid}")
    else: b.button(text="▶️ Запустить", callback_data=f"apip:start:{pid}")
    b.button(text="🔑 API Токен", callback_data=f"apip:token:{pid}")
    b.button(text="🗂 Платформа", callback_data=f"apip:platform:{pid}")
    b.button(text="🌍 Страна", callback_data=f"apip:country:{pid}")
    b.button(text="💰 Цена", callback_data=f"apip:price:{pid}")
    b.button(text="📊 Лимит/запрос", callback_data=f"apip:limit:{pid}")
    b.button(text=f"⏱ Интервал ({interval}с)", callback_data=f"apip:interval:{pid}")
    b.button(text="⏰ Публикация", callback_data=f"apip:pub:{pid}")
    b.button(text="🚫 Фильтры", callback_data=f"apip:filters:{pid}")
    b.button(text=f"{auto_s} Авто в список", callback_data=f"apip:auto:{pid}")
    b.button(text=f"{em_s} Только с email", callback_data=f"apip:emailonly:{pid}")
    b.button(text="📋 Список email", callback_data="menu:send")
    b.button(text="◀️ Назад", callback_data="apip:menu")
    b.adjust(1)
    
    cat_s = pcfg.get("category", "") or "все"
    pub_s = pcfg.get("publication", "") or "любое"
    fparts = []
    if pcfg.get("reviews"): fparts.append(f"отзывы≥{pcfg['reviews']}")
    if pcfg.get("ads"): fparts.append(f"объявл≥{pcfg['ads']}")
    if pcfg.get("sells"): fparts.append(f"продаж≥{pcfg['sells']}")
    if pcfg.get("buys"): fparts.append(f"покупок≥{pcfg['buys']}")
    if pcfg.get("blacklist"): fparts.append(f"стоп: {pcfg['blacklist'][:20]}")
    filt_s = " · ".join(fparts) or "—"

    lines = [
        f"{info['icon']} <b>{info['name']}</b>", "<code>━━━━━━━━━━━━━━━━━━━━━━</code>", "",
        f"Статус: {'🟢 Работает' if running else '🔴 Остановлен'}",
        f"Токен:  {'✅' if tok_ok else '❌'} <code>{tok_s}</code>", "",
        f"Платформа: <b>{pcfg['platform']}</b>   Страна: <b>{pcfg.get('country','—')}</b>",
        f"Категория: <b>{cat_s}</b>   Цена: <b>{pcfg.get('price','1..')}</b>",
        f"Лимит:     <b>{pcfg.get('limit',50)}/запр</b>   Интервал: <b>{interval}с</b>",
        f"Публикация:<b>{pub_s}</b>   Фильтры: <b>{filt_s}</b>", "",
        f"{auto_s} Авто→список   {em_s} Только с email", "",
        f"📊 Найдено: <b>{pcfg.get('total_found',0)}</b>   Последний: <b>{pcfg.get('last_run','—')}</b>",
    ]
    await call.message.edit_text("\n".join(lines), reply_markup=b.as_markup()); await call.answer()

@router.callback_query(F.data.startswith("apip:view:"))
async def apip_view(call: CallbackQuery): await _show_parser_page(call, call.data.removeprefix("apip:view:"))

@router.callback_query(F.data.startswith("apip:start:"))
async def apip_start(call: CallbackQuery):
    uid = call.from_user.id; pid = call.data.removeprefix("apip:start:"); cfg = load_api_parsers_cfg(uid)
    if not cfg[pid]["token"]: await call.answer("❌ Нет токена!", show_alert=True); return
    key = f"{uid}:{pid}"
    if key in _api_parser_tasks: await call.answer("Уже запущен", show_alert=True); return
    _api_parser_stop[key] = False
    _api_parser_tasks[key] = asyncio.create_task(_run_api_parser(call.bot, call.message.chat.id, uid, pid, cfg))
    await call.answer(f"▶️ {_API_PARSERS[pid]['name']} запущен!"); await _show_parser_page(call, pid)

@router.callback_query(F.data.startswith("apip:stop:"))
async def apip_stop(call: CallbackQuery):
    uid = call.from_user.id; pid = call.data.removeprefix("apip:stop:"); key = f"{uid}:{pid}"
    _api_parser_stop[key] = True; task = _api_parser_tasks.get(key)
    if task: task.cancel()
    await call.answer("⏹ Останавливаю..."); await _show_parser_page(call, pid)

@router.callback_query(F.data.startswith("apip:auto:"))
async def apip_auto(call: CallbackQuery):
    uid = call.from_user.id; pid = call.data.removeprefix("apip:auto:"); cfg = load_api_parsers_cfg(uid)
    cfg[pid]["auto_send"] = not cfg[pid].get("auto_send", True); save_api_parsers_cfg(uid, cfg)
    await _show_parser_page(call, pid)

@router.callback_query(F.data.startswith("apip:emailonly:"))
async def apip_emailonly(call: CallbackQuery):
    uid = call.from_user.id; pid = call.data.removeprefix("apip:emailonly:"); cfg = load_api_parsers_cfg(uid)
    cfg[pid]["email_only"] = not cfg[pid].get("email_only", True); save_api_parsers_cfg(uid, cfg)
    await _show_parser_page(call, pid)

@router.callback_query(F.data.startswith("apip:token:"))
async def apip_set_token(call: CallbackQuery, state: FSMContext):
    pid = call.data.removeprefix("apip:token:")
    await state.update_data(apip_pid=pid); await state.set_state(ApiParserSt.token)
    await call.message.edit_text(f"🔑 Токен для {_API_PARSERS[pid]['name']}\nВведи токен:", reply_markup=InlineKeyboardBuilder().button(text="◀️ Отмена", callback_data=f"apip:view:{pid}").as_markup()); await call.answer()

@router.message(ApiParserSt.token)
async def apip_fsm_token(m: Message, state: FSMContext):
    uid = m.from_user.id; d = await state.get_data(); pid = d["apip_pid"]
    cfg = load_api_parsers_cfg(uid); cfg[pid]["token"] = m.text.strip(); save_api_parsers_cfg(uid, cfg)
    try: await m.delete()
    except: pass
    await state.clear(); await m.answer("✅ Токен сохранён", reply_markup=kb_main(uid))

@router.callback_query(F.data.startswith("apip:platform:"))
async def apip_platform(call: CallbackQuery, state: FSMContext):
    pid = call.data.removeprefix("apip:platform:")
    uid = call.from_user.id; cfg = load_api_parsers_cfg(uid); cur = cfg[pid]["platform"]
    await state.update_data(apip_pid=pid); await state.set_state(ApiParserSt.platform)
    b = InlineKeyboardBuilder()
    for p in VVS_PLATFORMS[:24]: b.button(text=p, callback_data=f"apip:pf:{pid}:{p}")
    b.button(text="◀️ Отмена", callback_data=f"apip:view:{pid}")
    b.adjust(3)
    await call.message.edit_text(f"🗂 <b>Платформа</b> (текущая: {cur})", reply_markup=b.as_markup()); await call.answer()

@router.callback_query(F.data.startswith("apip:pf:"))
async def apip_pf_pick(call: CallbackQuery, state: FSMContext):
    uid = call.from_user.id; pid, platform = call.data.removeprefix("apip:pf:").split(":", 1)
    cfg = load_api_parsers_cfg(uid); cfg[pid]["platform"] = platform; save_api_parsers_cfg(uid, cfg)
    await state.clear(); await _show_parser_page(call, pid)

@router.message(ApiParserSt.platform)
async def apip_fsm_platform(m: Message, state: FSMContext):
    uid = m.from_user.id; d = await state.get_data(); pid = d["apip_pid"]
    cfg = load_api_parsers_cfg(uid); cfg[pid]["platform"] = m.text.strip().lower(); save_api_parsers_cfg(uid, cfg)
    await state.clear(); await m.answer(f"✅ Платформа: {m.text}", reply_markup=kb_main(uid))

@router.callback_query(F.data.startswith("apip:country:"))
async def apip_country(call: CallbackQuery, state: FSMContext):
    pid = call.data.removeprefix("apip:country:")
    uid = call.from_user.id; cfg = load_api_parsers_cfg(uid)
    await state.update_data(apip_pid=pid); await state.set_state(ApiParserSt.country)
    b = InlineKeyboardBuilder()
    for c in ["DE", "GB", "FR", "US", "NL", "BE", "AT", "PL", "IT", "ES", "CA", "AU"]: b.button(text=c, callback_data=f"apip:cnt:{pid}:{c}")
    b.button(text="◀️ Отмена", callback_data=f"apip:view:{pid}")
    b.adjust(4)
    await call.message.edit_text(f"🌍 <b>Страна</b> (текущая: {cfg[pid].get('country','—')})", reply_markup=b.as_markup()); await call.answer()

@router.callback_query(F.data.startswith("apip:cnt:"))
async def apip_cnt_pick(call: CallbackQuery, state: FSMContext):
    uid = call.from_user.id; pid, country = call.data.removeprefix("apip:cnt:").split(":", 1)
    cfg = load_api_parsers_cfg(uid); cfg[pid]["country"] = country; save_api_parsers_cfg(uid, cfg)
    await state.clear(); await _show_parser_page(call, pid)

@router.message(ApiParserSt.country)
async def apip_fsm_country(m: Message, state: FSMContext):
    uid = m.from_user.id; d = await state.get_data(); pid = d["apip_pid"]
    cfg = load_api_parsers_cfg(uid); cfg[pid]["country"] = m.text.strip().upper()[:2]; save_api_parsers_cfg(uid, cfg)
    await state.clear(); await m.answer(f"✅ Страна: {cfg[pid]['country']}", reply_markup=kb_main(uid))

@router.callback_query(F.data.startswith("apip:price:"))
async def apip_price(call: CallbackQuery, state: FSMContext):
    pid = call.data.removeprefix("apip:price:")
    uid = call.from_user.id; cfg = load_api_parsers_cfg(uid)
    await state.update_data(apip_pid=pid); await state.set_state(ApiParserSt.price)
    b = InlineKeyboardBuilder()
    for p in ["1..", "1..50", "1..100", "10..200", "50.."]: b.button(text=p, callback_data=f"apip:pr:{pid}:{p}")
    b.button(text="◀️ Отмена", callback_data=f"apip:view:{pid}")
    b.adjust(3)
    await call.message.edit_text(f"💰 <b>Цена</b> (текущая: {cfg[pid].get('price','1..')})", reply_markup=b.as_markup()); await call.answer()

@router.callback_query(F.data.startswith("apip:pr:"))
async def apip_pr_pick(call: CallbackQuery, state: FSMContext):
    uid = call.from_user.id; pid, price = call.data.removeprefix("apip:pr:").split(":", 1)
    cfg = load_api_parsers_cfg(uid); cfg[pid]["price"] = price; save_api_parsers_cfg(uid, cfg)
    await state.clear(); await _show_parser_page(call, pid)

@router.message(ApiParserSt.price)
async def apip_fsm_price(m: Message, state: FSMContext):
    uid = m.from_user.id; d = await state.get_data(); pid = d["apip_pid"]
    cfg = load_api_parsers_cfg(uid); cfg[pid]["price"] = m.text.strip(); save_api_parsers_cfg(uid, cfg)
    await state.clear(); await m.answer(f"✅ Цена: {m.text}", reply_markup=kb_main(uid))

@router.callback_query(F.data.startswith("apip:limit:"))
async def apip_limit(call: CallbackQuery, state: FSMContext):
    pid = call.data.removeprefix("apip:limit:")
    uid = call.from_user.id; cfg = load_api_parsers_cfg(uid)
    await state.update_data(apip_pid=pid); await state.set_state(ApiParserSt.limit)
    b = InlineKeyboardBuilder()
    for lim in [10, 25, 50, 100]: b.button(text=str(lim), callback_data=f"apip:lim:{pid}:{lim}")
    b.button(text="◀️ Отмена", callback_data=f"apip:view:{pid}")
    b.adjust(4)
    await call.message.edit_text(f"📊 <b>Лимит</b> (текущий: {cfg[pid].get('limit',50)})", reply_markup=b.as_markup()); await call.answer()

@router.callback_query(F.data.startswith("apip:lim:"))
async def apip_lim_pick(call: CallbackQuery, state: FSMContext):
    uid = call.from_user.id; pid, lim = call.data.removeprefix("apip:lim:").split(":", 1)
    cfg = load_api_parsers_cfg(uid); cfg[pid]["limit"] = int(lim); save_api_parsers_cfg(uid, cfg)
    await state.clear(); await _show_parser_page(call, pid)

@router.message(ApiParserSt.limit)
async def apip_fsm_limit(m: Message, state: FSMContext):
    uid = m.from_user.id; d = await state.get_data(); pid = d["apip_pid"]
    try: val = int(m.text.strip()); cfg = load_api_parsers_cfg(uid); cfg[pid]["limit"] = val; save_api_parsers_cfg(uid, cfg)
    except: await m.answer("⚠️ Введи число"); return
    await state.clear(); await m.answer(f"✅ Лимит: {val}", reply_markup=kb_main(uid))

@router.callback_query(F.data.startswith("apip:interval:"))
async def apip_interval(call: CallbackQuery, state: FSMContext):
    pid = call.data.removeprefix("apip:interval:")
    uid = call.from_user.id; cfg = load_api_parsers_cfg(uid)
    await state.update_data(apip_pid=pid); await state.set_state(ApiParserSt.interval)
    b = InlineKeyboardBuilder()
    for s in [30, 60, 120, 300]: b.button(text=f"{s}с", callback_data=f"apip:int_p:{pid}:{s}")
    b.button(text="◀️ Отмена", callback_data=f"apip:view:{pid}")
    b.adjust(4)
    await call.message.edit_text(f"⏱ <b>Интервал</b> (текущий: {cfg[pid].get('interval',60)}с)", reply_markup=b.as_markup()); await call.answer()

@router.callback_query(F.data.startswith("apip:int_p:"))
async def apip_int_pick(call: CallbackQuery, state: FSMContext):
    uid = call.from_user.id; pid, val = call.data.removeprefix("apip:int_p:").split(":", 1)
    cfg = load_api_parsers_cfg(uid); cfg[pid]["interval"] = int(val); save_api_parsers_cfg(uid, cfg)
    await state.clear(); await _show_parser_page(call, pid)

@router.message(ApiParserSt.interval)
async def apip_fsm_interval(m: Message, state: FSMContext):
    uid = m.from_user.id; d = await state.get_data(); pid = d["apip_pid"]
    try: val = int(m.text.strip()); cfg = load_api_parsers_cfg(uid); cfg[pid]["interval"] = val; save_api_parsers_cfg(uid, cfg)
    except: await m.answer("⚠️ Введи число"); return
    await state.clear(); await m.answer(f"✅ Интервал: {val}с", reply_markup=kb_main(uid))

@router.callback_query(F.data.startswith("apip:pub:"))
async def apip_pub(call: CallbackQuery, state: FSMContext):
    pid = call.data.removeprefix("apip:pub:")
    uid = call.from_user.id; cfg = load_api_parsers_cfg(uid); cur = cfg[pid].get("publication", "") or "любое"
    await state.update_data(apip_pid=pid); await state.set_state(ApiParserSt.pub)
    b = InlineKeyboardBuilder()
    for p in ["5m", "15m", "30m", "1h", "3h", "6h", "24h"]: b.button(text=p, callback_data=f"apip:pub_p:{pid}:{p}")
    b.button(text="Любое", callback_data=f"apip:pub_p:{pid}:")
    b.button(text="◀️ Отмена", callback_data=f"apip:view:{pid}")
    b.adjust(4)
    await call.message.edit_text(f"⏰ <b>Публикация</b> (текущее: {cur})", reply_markup=b.as_markup()); await call.answer()

@router.callback_query(F.data.startswith("apip:pub_p:"))
async def apip_pub_pick(call: CallbackQuery, state: FSMContext):
    uid = call.from_user.id; pid, pub = call.data.removeprefix("apip:pub_p:").split(":", 1)
    cfg = load_api_parsers_cfg(uid); cfg[pid]["publication"] = pub; save_api_parsers_cfg(uid, cfg)
    await state.clear(); await _show_parser_page(call, pid)

@router.callback_query(F.data.startswith("apip:filters:"))
async def apip_filters(call: CallbackQuery, state: FSMContext):
    pid = call.data.removeprefix("apip:filters:")
    uid = call.from_user.id; cfg = load_api_parsers_cfg(uid); pcfg = cfg[pid]
    await state.update_data(apip_pid=pid); await state.set_state(ApiParserSt.filters)
    await call.message.edit_text(f"🚫 <b>Фильтры</b>\n\nОтзывы: <code>{pcfg.get('reviews') or '—'}</code>\nОбъявл: <code>{pcfg.get('ads') or '—'}</code>\nПродаж: <code>{pcfg.get('sells') or '—'}</code>\nПокупок: <code>{pcfg.get('buys') or '—'}</code>\n\nВведи построчно (напр. reviews=5..):", reply_markup=InlineKeyboardBuilder().button(text="◀️ Отмена", callback_data=f"apip:view:{pid}").as_markup()); await call.answer()

@router.message(ApiParserSt.filters)
async def apip_fsm_filters(m: Message, state: FSMContext):
    uid = m.from_user.id; d = await state.get_data(); pid = d["apip_pid"]; cfg = load_api_parsers_cfg(uid)
    for line in m.text.splitlines():
        if "=" in line:
            k, _, v = line.partition("="); k = k.strip().lower()
            if k in ("reviews", "ads", "blacklist", "sells", "buys"): cfg[pid][k] = v.strip()
    save_api_parsers_cfg(uid, cfg); await state.clear(); await m.answer("✅ Фильтры сохранены", reply_markup=kb_main(uid))
