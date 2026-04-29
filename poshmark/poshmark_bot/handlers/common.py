import asyncio
from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery
from ..config import MAIN_TEXT
from ..utils.keyboards import kb_main
from ..storage import load_accounts, load_logs
from ..core.smtp import SMTPMailSender
from ..globals import is_sending

router = Router()

@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    tg_id = message.from_user.id
    await message.answer(MAIN_TEXT, reply_markup=kb_main(is_sending(tg_id)))

@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    await state.clear()
    uid = message.from_user.id
    await message.answer("◀️ Отменено.", reply_markup=kb_main(is_sending(uid)))

@router.message(Command("testsmtp"))
async def cmd_testsmtp(message: Message):
    uid = message.from_user.id
    args = (message.text or "").split(maxsplit=2)
    if len(args) == 3:
        email, pwd = args[1], args[2]
        wait = await message.answer(f"Тестирую <code>{email}</code>…")
        ok, result = await asyncio.get_running_loop().run_in_executor(
            None, SMTPMailSender.test, email, pwd
        )
        await wait.edit_text(
            f"{'✅' if ok else '❌'} <b>Результат:</b>\n<code>{result}</code>"
        )
        return
    accounts = load_accounts(uid)
    if not accounts:
        await message.answer(
            "Нет сохранённых аккаунтов.\n"
            "Использование: <code>/testsmtp email@icloud.com app_password</code>"
        )
        return
    wait = await message.answer(f"Тестирую {len(accounts)} аккаунт(ов)…")
    lines = []
    for acc in accounts:
        ok, result = await asyncio.get_running_loop().run_in_executor(
            None, SMTPMailSender.test, acc.email, acc.password
        )
        icon = "✅" if ok else "❌"
        lines.append(f"{icon} <code>{acc.email}</code>\n   <code>{result}</code>")
    await wait.edit_text("🔬 <b>SMTP-тест</b>\n<code>━━━━━━━━━━━━━━━━━━━━━━</code>\n\n" + "\n\n".join(lines))

@router.callback_query(F.data == "menu:logs")
async def cb_logs(call: CallbackQuery):
    uid = call.from_user.id
    logs = load_logs(uid)
    if not logs:
        await call.answer("История пуста", show_alert=True)
        return
    
    lines = []
    for l in logs[-15:]:
        status = l.get("status", "❓")
        to = l.get("to_email", "???")
        lines.append(f"{status} <code>{to}</code>")
    
    await call.message.edit_text(
        f"📊 <b>Последние 15 отправок:</b>\n\n" + "\n".join(lines),
        reply_markup=kb_main(is_sending(uid))
    )
    await call.answer()

@router.callback_query(F.data == "menu:main")
async def cb_main(call: CallbackQuery, state: FSMContext):
    await state.clear()
    tg_id = call.from_user.id
    await call.message.edit_text(MAIN_TEXT, reply_markup=kb_main(is_sending(tg_id)))
    await call.answer()
