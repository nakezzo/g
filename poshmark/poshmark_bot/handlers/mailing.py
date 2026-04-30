import asyncio
import io
import re
import random
from datetime import datetime
from typing import List, Tuple, Dict
from aiogram import Router, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, Document
from aiogram.utils.keyboard import InlineKeyboardBuilder
from ..storage import (
    load_accounts, save_accounts, load_templates, load_subjects,
    load_variables, load_parser_config, save_parser_config, append_log
)
from ..utils.keyboards import kb_main
from ..utils.helpers import (
    safe_text, gen_random_id, apply_vars, pick_rotated, random_delay, replace_random_ids
)
from ..core.smtp import SMTPMailSender
from ..models import Account, SentLog
from ..states import SendMail, EditDelay
from ..globals import (
    get_stop_event, is_sending, _active_sends, _send_status_msg
)

router = Router()

@router.callback_query(F.data == "menu:send")
async def cb_send(call: CallbackQuery, state: FSMContext):
    uid = call.from_user.id
    accounts    = load_accounts(uid)
    _, selected = load_templates(uid)
    enabled     = [a for a in accounts if a.enabled]

    if not enabled:
        await call.message.edit_text(
            "⚠️ Нет активных аккаунтов!\nДобавьте в разделе <b>Аккаунты</b>.",
            reply_markup=kb_main(is_sending(uid)),
        )
        await call.answer()
        return

    if not selected:
        await call.message.edit_text(
            "⚠️ Нет выбранных HTML шаблонов!\nДобавьте в разделе <b>HTML шаблоны</b>.",
            reply_markup=kb_main(is_sending(uid)),
        )
        await call.answer()
        return

    await state.set_state(SendMail.recipients)
    await call.message.edit_text(
        f"🚀 <b>Отправка писем</b>\n<code>━━━━━━━━━━━━━━━━━━━━━━</code>\n"
        f"Аккаунтов активных: {len(enabled)}\n"
        f"Шаблонов выбрано: {len(selected)}\n\n"
        "Отправьте:\n"
        "• Список email-адресов (каждый на новой строке)\n"
        "• <b>Или прикрепите .txt файл</b> со списком email\n\n"
        "/cancel — отмена"
    )
    await call.answer()

@router.message(SendMail.recipients, F.document)
async def fsm_recipients_file(message: Message, state: FSMContext, bot: Bot):
    doc: Document = message.document
    fname = (doc.file_name or "").lower()
    if fname and not fname.endswith(".txt") and "." in fname:
        await message.answer(
            f"⚠️ Получен файл <code>{doc.file_name}</code>.\n"
            "Ожидается <b>.txt</b> файл со списком email (по одному на строку).\n\n"
            "Попробуйте ещё раз:"
        )
        return

    try:
        file_info = await bot.get_file(doc.file_id)
        buf = io.BytesIO()
        await bot.download_file(file_info.file_path, destination=buf)
        raw = buf.getvalue()
    except Exception as e:
        await message.answer(f"❌ Не удалось скачать файл: <code>{e}</code>")
        return

    content = None
    for enc in ("utf-8", "cp1251", "latin-1"):
        try:
            content = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if content is None:
        content = raw.decode("utf-8", errors="replace")

    seen = set()
    emails = []
    for line in content.splitlines():
        for em in re.findall(r"[\w.+\-]+@[\w.\-]+\.\w+", line):
            em = em.strip().lower()
            if em not in seen:
                seen.add(em)
                emails.append(em)

    if not emails:
        await message.answer(
            f"❌ В файле <code>{doc.file_name}</code> не найдено ни одного email.\n\n"
            f"Убедитесь что файл содержит адреса вида <code>user@example.com</code>, "
            f"по одному на строку.\n\nПопробуйте ещё раз:"
        )
        return

    await message.answer(f"📂 Файл принят. Найдено адресов: <b>{len(emails)}</b>")
    await _confirm_send(message, state, emails)

@router.message(SendMail.recipients, F.text)
async def fsm_recipients_text(message: Message, state: FSMContext):
    raw_emails = re.findall(r"[\w.+\-]+@[\w.\-]+\.\w+", message.text)
    seen = set()
    emails = []
    for em in raw_emails:
        em = em.strip().lower()
        if em not in seen:
            seen.add(em)
            emails.append(em)
    if not emails:
        await message.answer("❌ Не найдено ни одного email. Попробуйте ещё раз:")
        return
    dupes = len(raw_emails) - len(emails)
    msg_dupes = f"ℹ️ Удалено дублей: {dupes}. " if dupes else ""
    await message.answer(f"{msg_dupes}Найдено email'ов: <b>{len(emails)}</b>\n\nПервые 5: <code>{', '.join(emails[:5])}</code>")
    await _confirm_send(message, state, emails)

async def _confirm_send(message: Message, state: FSMContext, emails: List[str]):
    uid = message.from_user.id
    await state.update_data(recipients=emails)
    await state.set_state(SendMail.confirm)
    subjects = load_subjects(uid)
    accounts = load_accounts(uid)
    enabled  = [a for a in accounts if a.enabled]
    variables = load_variables(uid)

    b = InlineKeyboardBuilder()
    b.button(text="✅ Да, отправить", callback_data="send:go")
    b.button(text="✖️ Отмена",        callback_data="menu:main")
    b.adjust(2)

    rot_vars = [k for k in ["sender", "title", "text", "button", "link"]
                if len(variables.get(k, [])) > 1]
    rot_line = ("🔀 " + "  ".join(f"<code>{{{k}}}</code>" for k in rot_vars)) if rot_vars else ""

    subj_line = (f"✉️ Тем: <b>{len(subjects)}</b> 🔁" if len(subjects) > 1
                 else f"✉️ Тема: <code>{subjects[0] if subjects else '—'}</code>")

    await message.answer(
        f"📋 <b>Подтверждение отправки</b>\n<code>━━━━━━━━━━━━━━━━━━━━━━</code>\n\n"
        f"📬 Получателей:  <b>{len(emails)}</b>\n"
        f"📧 Аккаунтов:    <b>{len(enabled)}</b>\n"
        f"{subj_line}\n"
        + (f"{rot_line}\n" if rot_line else "")
        + "\n▸ Начать отправку?",
        reply_markup=b.as_markup(),
    )

@router.callback_query(F.data == "send:stop_inactive")
async def cb_stop_inactive(call: CallbackQuery):
    await call.answer("Рассылка не запущена", show_alert=False)

@router.callback_query(F.data == "send:stop")
async def cb_send_stop(call: CallbackQuery):
    uid = call.from_user.id
    if not is_sending(uid):
        await call.answer("Рассылка не запущена или уже остановлена", show_alert=True)
        return
    get_stop_event(uid).set()
    await call.answer("⏹ Останавливаю после текущего письма...", show_alert=True)
    try:
        b = InlineKeyboardBuilder()
        b.button(text="⏳ Останавливается...", callback_data="noop")
        await call.message.edit_reply_markup(reply_markup=b.as_markup())
    except Exception:
        pass

@router.callback_query(F.data == "send:go", SendMail.confirm)
async def cb_send_go(call: CallbackQuery, state: FSMContext):
    data       = await state.get_data()
    recipients = data.get("recipients", [])
    uid        = call.from_user.id
    await state.clear()
    b_stop = InlineKeyboardBuilder()
    b_stop.button(text="⏹ Остановить рассылку", callback_data="send:stop")
    await call.message.edit_text(
        f"⏳ <b>Рассылка запущена...</b>\n\n"
        f"📬 Получателей: <b>{len(recipients)}</b>\n\n"
        "Нажми кнопку ниже чтобы остановить:",
        reply_markup=b_stop.as_markup(),
    )
    get_stop_event(uid).clear()
    await call.answer()
    asyncio.create_task(_send_campaign(call.message, recipients, uid))

async def _send_campaign(message: Message, recipients: List[str], uid):
    _active_sends.add(int(uid))
    try:
        await _do_send_campaign(message, recipients, uid)
    finally:
        _active_sends.discard(int(uid))

async def _do_send_campaign(message: Message, recipients: List[str], uid):
    accounts       = load_accounts(uid)
    variables      = load_variables(uid)
    templates, sel = load_templates(uid)
    subjects       = load_subjects(uid)
    enabled        = [a for a in accounts if a.enabled]

    if not enabled or not sel:
        await message.answer("❌ Нет аккаунтов или шаблонов.", reply_markup=kb_main(is_sending(uid)))
        return

    cfg = load_parser_config(uid)
    acc_lines = "\n".join(
        f"  • <code>{a.email}</code>: отправлено {a.sent_count}"
        + (f" / лимит {a.send_limit}" if a.send_limit > 0 else " / ∞")
        for a in enabled
    )
    await message.answer(
        f"📡 SMTP: определяется по домену аккаунта\n"
        f"📧 Аккаунтов активных: <code>{len(enabled)}</code>\n"
        f"📄 Шаблонов выбрано:   <code>{len(sel)}</code>\n"
        f"📝 Тем для ротации:    <code>{len(subjects)}</code>\n"
        f"📬 Получателей:        <code>{len(recipients)}</code>\n"
        f"⏱ Задержка: <code>{cfg.get('delay_min', 17)}–{cfg.get('delay_max', 24)} сек</code> (рандом)\n"
        f"⚡ <b>Режим: распределение писем между аккаунтами</b>\n\n"
        f"<b>Статистика аккаунтов:</b>\n{acc_lines}"
    )

    # ═══ РАСПРЕДЕЛЕНИЕ: Каждый email один раз (разные аккаунты) ═══
    num_accounts = len(enabled)
    num_recipients = len(recipients)
    
    # Round-robin распределение: письма по очереди между аккаунтами
    buckets = {i: [] for i in range(num_accounts)}
    for idx, recipient in enumerate(recipients):
        account_idx = idx % num_accounts  # 0, 1, 2, 0, 1, 2, ...
        buckets[account_idx].append((idx, recipient))

    # Лог распределения
    dist_info = " | ".join(f"Акк{i}: {len(buckets[i])} писем" for i in range(num_accounts))
    try:
        await message.answer(
            f"📊 <b>Распределение:</b> {dist_info}\n"
            f"<b>Каждый email одному аккаунту (10 писем)</b>"
        )
    except Exception: pass

    counters = [0, 0]
    lock = asyncio.Lock()

    async def worker(acc: Account, bucket: List[Tuple[int, str]], acc_index: int):
        _cfg = load_parser_config(uid)
        _rot = _cfg.get("rotate_every", {})
        local_counter = _cfg.get("send_counter", 0) + acc_index
        stop_ev = get_stop_event(uid)
        
        bucket_size = len(bucket)
        sent_this_acc = 0
        
        # Логирование старта worker'а
        try:
            await message.answer(f"🔄 [{acc_index+1}] <code>{acc.email}</code> начал рассылку ({bucket_size} писем)...")
        except Exception: pass

        for bucket_pos, (i, recipient) in enumerate(bucket):
            if stop_ev.is_set():
                break
            is_last = bucket_pos == len(bucket) - 1

            # ═══ ФИКС: Правильная проверка лимита ═══
            if acc.send_limit > 0 and acc.sent_count >= acc.send_limit:
                try:
                    await message.answer(
                        f"🚫 <code>{acc.email}</code> достиг лимита "
                        f"<b>{acc.send_limit}</b> писем"
                    )
                except Exception: pass
                break

            tpl_name = random.choice(sel)
            html_raw = templates.get(tpl_name, "")
            if not html_raw:
                async with lock:
                    counters[1] += 1
                    acc.error_count += 1
                try:
                    await message.answer(
                        f"❌ <b>Пустой шаблон</b> [{i+1}]\n"
                        f"С: <code>{acc.email}</code> → <code>{recipient}</code>\n"
                        f"Шаблон: <code>{tpl_name}</code>"
                    )
                except Exception: pass
                continue

            sender_name = replace_random_ids(pick_rotated(variables.get("sender", []), "sender", local_counter, _rot))
            title       = replace_random_ids(pick_rotated(variables.get("title",  []), "title",  local_counter, _rot))
            body        = replace_random_ids(pick_rotated(variables.get("text",   []), "text",   local_counter, _rot))
            button      = replace_random_ids(pick_rotated(variables.get("button", []), "button", local_counter, _rot))
            link        = replace_random_ids(pick_rotated(variables.get("link",   []), "link",   local_counter, _rot))
            subject_tpl = pick_rotated(subjects, "subject", local_counter, _rot, "Hello from Poshmark")

            rid     = gen_random_id()
            subject = apply_vars(subject_tpl, recipient, sender_name, title, body, button, link, fixed_random_id=rid)
            html    = apply_vars(html_raw,    recipient, sender_name, title, body, button, link, fixed_random_id=rid)

            try:
                loop       = asyncio.get_running_loop()
                sender_obj = SMTPMailSender(acc.email, acc.password)
                ok, status = await loop.run_in_executor(
                    None, lambda s=sender_obj: s.send_email(recipient, subject, html, sender_name)
                )
            except Exception as e:
                ok     = False
                status = f"{type(e).__name__}: {e}"

            delay = random_delay(uid)
            local_counter += num_accounts  # ← ФИКС: использовать actual number of accounts

            async with lock:
                if ok:
                    counters[0] += 1
                    acc.sent_count += 1
                    sent_this_acc += 1
                else:
                    counters[1] += 1
                    acc.error_count += 1
                    acc.last_error = status[:100]

                append_log(uid, SentLog(
                    from_email=acc.email, to_email=recipient, subject=subject,
                    status="✅" if ok else "❌",
                    timestamp=datetime.now().isoformat(),
                    error="" if ok else status,
                ))

            try:
                if ok:
                    await message.answer(f"✅ <b>[{i+1}]</b> <code>{recipient}</code>\n  ↳ <code>{acc.email}</code>")
                else:
                    await message.answer(f"❌ <b>[{i+1}]</b> <code>{recipient}</code>\n  ↳ <code>{acc.email}</code>\n  ✗ <code>{status[:80]}</code>")
            except Exception: pass

            if not is_last:
                await asyncio.sleep(delay)
        
        # Логирование окончания worker'а
        try:
            await message.answer(f"✓ [{acc_index+1}] <code>{acc.email}</code> завершил (отправлено {sent_this_acc}/{bucket_size})")
        except Exception: pass

    # ═══ ФИКС: Создать tasks для всех аккаунтов (даже если bucket пуст) ═══
    tasks = [asyncio.create_task(worker(enabled[i], buckets[i], i)) for i in range(num_accounts)]
    await asyncio.gather(*tasks, return_exceptions=True)

    _cfg_final = load_parser_config(uid)
    _cfg_final["send_counter"] = _cfg_final.get("send_counter", 0) + counters[0] + counters[1]
    save_parser_config(uid, _cfg_final)
    save_accounts(uid, accounts)

    was_stopped = get_stop_event(uid).is_set() or (counters[0] + counters[1] < len(recipients))
    get_stop_event(uid).clear()

    title = "⏹ <b>Рассылка остановлена</b>" if was_stopped else "🏁 <b>Готово!</b>"
    await message.answer(
        f"{title}\n<code>━━━━━━━━━━━━━━━━━━━━━━</code>\n\n"
        f"📬 Всего:      <b>{len(recipients)}</b>\n"
        f"📤 Отправлено: <b>{counters[0] + counters[1]}</b>\n"
        f"✅ Успешно:   <b>{counters[0]}</b>\n"
        f"❌ Ошибок:    <b>{counters[1]}</b>",
        reply_markup=kb_main(is_sending(uid)),
    )

@router.callback_query(F.data == "menu:delay")
async def cb_delay_menu(call: CallbackQuery, state: FSMContext):
    uid = call.from_user.id
    cfg = load_parser_config(uid)
    d_min = cfg.get("delay_min", 17)
    d_max = cfg.get("delay_max", 24)
    await state.set_state(EditDelay.waiting)
    await call.message.edit_text(
        f"⏱ <b>Задержка отправки</b>\n<code>━━━━━━━━━━━━━━━━━━━━━━</code>\n"
        f"Текущий диапазон: <code>{d_min}–{d_max} сек</code>\n\n"
        f"Введите новый диапазон в формате:\n"
        f"<code>МИН МАКС</code>  (например: <code>10 30</code>)\n\n"
        f"/cancel — отмена"
    )
    await call.answer()

@router.message(EditDelay.waiting)
async def fsm_delay(message: Message, state: FSMContext):
    uid = message.from_user.id
    text = safe_text(message)
    if not text:
        await message.answer("⚠️ Отправьте два числа. /cancel — отмена")
        return
    parts = text.strip().split()
    if len(parts) != 2:
        await message.answer("⚠️ Нужно два числа через пробел, например: <code>10 30</code>\n\n/cancel — отмена")
        return
    try:
        d_min = float(parts[0]); d_max = float(parts[1])
    except ValueError:
        await message.answer("⚠️ Введите числа, например: <code>10 30</code>\n\n/cancel — отмена")
        return

    cfg = load_parser_config(uid)
    cfg["delay_min"] = d_min
    cfg["delay_max"] = d_max
    save_parser_config(uid, cfg)
    await state.clear()
    await message.answer(f"✅ Задержка установлена: <b>{d_min} – {d_max}</b> сек.", reply_markup=kb_main(is_sending(uid)))
