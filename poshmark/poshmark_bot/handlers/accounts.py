import asyncio
from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from ..storage import load_accounts, save_accounts
from ..utils.keyboards import kb_accounts, kb_main
from ..utils.helpers import safe_text
from ..core.smtp import SMTPMailSender
from ..models import Account
from ..states import AddAccount, SetLimit
from ..globals import is_sending

router = Router()

@router.callback_query(F.data == "menu:accounts")
async def cb_accounts(call: CallbackQuery):
    uid = call.from_user.id
    accounts = load_accounts(uid)
    await call.message.edit_text(
        f"📧 <b>Аккаунты</b>\n<code>━━━━━━━━━━━━━━━━━━━━━━</code>\n{len(accounts)} шт. · Нажмите для вкл/выкл:",
        reply_markup=kb_accounts(accounts),
    )
    await call.answer()

@router.callback_query(F.data.startswith("acc:toggle:"))
async def cb_acc_toggle(call: CallbackQuery):
    uid = call.from_user.id
    idx      = int(call.data.removeprefix("acc:toggle:"))
    accounts = load_accounts(uid)
    if 0 <= idx < len(accounts):
        accounts[idx].enabled = not accounts[idx].enabled
    save_accounts(uid, accounts)
    await call.message.edit_text(
        f"📧 <b>Аккаунты</b>\n<code>━━━━━━━━━━━━━━━━━━━━━━</code>\n{len(accounts)} шт. · Нажмите для вкл/выкл:",
        reply_markup=kb_accounts(accounts),
    )
    await call.answer()

@router.callback_query(F.data == "acc:clear_stats")
async def cb_acc_clear_stats(call: CallbackQuery):
    uid = call.from_user.id
    accounts = load_accounts(uid)
    for acc in accounts:
        acc.sent_count  = 0
        acc.error_count = 0
        acc.last_error  = ""
    save_accounts(uid, accounts)
    await call.message.edit_text(
        f"📧 <b>Аккаунты</b>\n<code>━━━━━━━━━━━━━━━━━━━━━━</code>\n✅ Статистика сброшена.",
        reply_markup=kb_accounts(accounts),
    )
    await call.answer("Статистика сброшена")

@router.callback_query(F.data.startswith("acc:limit:"))
async def cb_acc_limit(call: CallbackQuery, state: FSMContext):
    uid = call.from_user.id
    idx      = int(call.data.removeprefix("acc:limit:"))
    accounts = load_accounts(uid)
    if idx < 0 or idx >= len(accounts):
        await call.answer("Аккаунт не найден", show_alert=True)
        return
    acc     = accounts[idx]
    current = acc.send_limit if acc.send_limit > 0 else "∞ (без лимита)"
    await state.update_data(limit_email=acc.email)
    await state.set_state(SetLimit.waiting)
    await call.message.edit_text(
        f"⚙️ <b>Лимит отправок</b>\n\n"
        f"Аккаунт: <code>{acc.email}</code>\n"
        f"Текущий лимит: <b>{current}</b>\n"
        f"Отправлено: <b>{acc.sent_count}</b>\n\n"
        "Введи максимальное кол-во писем для этого аккаунта.\n"
        "<code>0</code> — без лимита (неограниченно)\n\n"
        "/cancel — отмена"
    )
    await call.answer()

@router.message(SetLimit.waiting)
async def fsm_set_limit(message: Message, state: FSMContext):
    uid = message.from_user.id
    text = safe_text(message)
    try:
        limit = int(text.strip())
        if limit < 0:
            raise ValueError
    except (ValueError, AttributeError):
        await message.answer("⚠️ Введи целое число ≥ 0. /cancel — отмена")
        return

    data  = await state.get_data()
    email = data["limit_email"]
    accounts = load_accounts(uid)
    for acc in accounts:
        if acc.email == email:
            acc.send_limit = limit
            break
    save_accounts(uid, accounts)
    await state.clear()

    label = f"<b>{limit}</b> писем" if limit > 0 else "<b>без лимита</b>"
    await message.answer(
        f"✅ Лимит для <code>{email}</code> установлен: {label}",
        reply_markup=kb_main(is_sending(uid)),
    )

@router.callback_query(F.data.startswith("acc:delete:"))
async def cb_acc_delete(call: CallbackQuery):
    uid = call.from_user.id
    idx      = int(call.data.removeprefix("acc:delete:"))
    accounts = load_accounts(uid)
    if idx < 0 or idx >= len(accounts):
        await call.answer("Аккаунт не найден", show_alert=True)
        return
    email = accounts[idx].email
    b = InlineKeyboardBuilder()
    b.button(text="✅ Да, удалить", callback_data=f"acc:dc:{idx}")
    b.button(text="❌ Отмена",      callback_data="acc:delete_cancel")
    b.adjust(1)
    await call.message.edit_text(
        f"🗑 <b>Удалить аккаунт?</b>\n\n"
        f"<code>{email}</code>\n\n"
        "Это действие необратимо.",
        reply_markup=b.as_markup(),
    )
    await call.answer()

@router.callback_query(F.data == "acc:delete_cancel")
async def cb_acc_delete_cancel(call: CallbackQuery):
    uid = call.from_user.id
    accounts = load_accounts(uid)
    await call.message.edit_text(
        f"📧 <b>Аккаунты</b>\n<code>━━━━━━━━━━━━━━━━━━━━━━</code>\n{len(accounts)} шт. · Нажмите для вкл/выкл:",
        reply_markup=kb_accounts(accounts),
    )
    await call.answer()

@router.callback_query(F.data.startswith("acc:dc:"))
async def cb_acc_delete_confirm(call: CallbackQuery):
    uid = call.from_user.id
    idx      = int(call.data.removeprefix("acc:dc:"))
    accounts = load_accounts(uid)
    if 0 <= idx < len(accounts):
        email = accounts[idx].email
        accounts.pop(idx)
    else:
        email = "?"
    save_accounts(uid, accounts)
    await call.message.edit_text(
        f"✅ Аккаунт <code>{email}</code> удалён.\n\n"
        f"📧 <b>Аккаунты</b>\n<code>━━━━━━━━━━━━━━━━━━━━━━</code>\n{len(accounts)} шт.",
        reply_markup=kb_accounts(accounts),
    )
    await call.answer("Аккаунт удалён")

@router.callback_query(F.data == "acc:add")
async def cb_acc_add(call: CallbackQuery, state: FSMContext):
    await state.set_state(AddAccount.email)
    await call.message.edit_text(
        "Введите email аккаунта:\n"
        "<i>Поддерживаются: @seznam.cz, @email.cz, @post.cz</i>\n\n"
        "/cancel — отмена"
    )
    await call.answer()

@router.message(AddAccount.email)
async def fsm_acc_email(message: Message, state: FSMContext):
    text = safe_text(message)
    if not text:
        await message.answer("⚠️ Отправьте email текстом. /cancel — отмена")
        return
    await state.update_data(email=text.strip())
    await state.set_state(AddAccount.password)
    await message.answer("Введи пароль от аккаунта:\n\n/cancel — отмена")

@router.message(AddAccount.password)
async def fsm_acc_password(message: Message, state: FSMContext):
    uid = message.from_user.id
    text = safe_text(message)
    if not text:
        await message.answer("⚠️ Отправьте пароль текстом. /cancel — отмена")
        return
    data  = await state.get_data()
    email = data["email"]
    pwd   = text.strip()
    await state.clear()

    wait = await message.answer(f"🔄 Проверяю подключение…")
    ok, result = await asyncio.get_running_loop().run_in_executor(
        None, SMTPMailSender.test, email, pwd
    )
    await wait.delete()

    if ok:
        accounts = load_accounts(uid)
        accounts = [a for a in accounts if a.email != email]
        accounts.append(Account(email=email, password=pwd))
        save_accounts(uid, accounts)
        await message.answer(
            f"✅ {result}\nАккаунт <code>{email}</code> добавлен!",
            reply_markup=kb_main(is_sending(uid)),
        )
    else:
        await message.answer(f"❌ {result}\nАккаунт НЕ добавлен.", reply_markup=kb_main(uid))
