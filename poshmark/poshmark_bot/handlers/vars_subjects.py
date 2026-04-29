from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery
from ..storage import load_variables, save_variables, load_subjects, save_subjects
from ..utils.keyboards import kb_vars, kb_main
from ..utils.helpers import safe_text
from ..config import VAR_LABELS
from ..states import EditVar, EditSubject
from ..globals import is_sending

router = Router()

@router.callback_query(F.data == "menu:vars")
async def cb_vars(call: CallbackQuery):
    uid = call.from_user.id
    variables = load_variables(uid)
    lines = [
        f"• <code>{{{k}}}</code>: {len(variables.get(k, []))} значений"
        + (" 🔀" if len(variables.get(k, [])) > 1 else "")
        for k in VAR_LABELS
    ]
    await call.message.edit_text(
        "🔧 <b>Переменные</b>\n<code>━━━━━━━━━━━━━━━━━━━━━━</code>\n"
        + "\n".join(lines)
        + "\n\n🔀 — ротируется случайно при каждой отправке\n\nВыберите переменную:",
        reply_markup=kb_vars(),
    )
    await call.answer()

@router.callback_query(F.data.startswith("var:edit:"))
async def cb_var_edit(call: CallbackQuery, state: FSMContext):
    uid = call.from_user.id
    key = call.data.removeprefix("var:edit:")
    await state.update_data(var_key=key)
    await state.set_state(EditVar.values)
    variables = load_variables(uid)
    values    = variables.get(key, [])
    label     = VAR_LABELS.get(key, key)

    if key == "text":
        current_block = f"Сохранено значений: <b>{len(values)}</b> (предпросмотр недоступен — значения содержат HTML)"
    else:
        safe = "\n".join(
            v.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            for v in values
        )
        current_block = f"Текущие значения:\n<pre>{safe or '(пусто)'}</pre>"

    await call.message.edit_text(
        f"✏️ <b>{label}</b>\n\n"
        f"{current_block}\n\n"
        "Отправьте новые значения — <b>каждое на отдельной строке</b>.\n"
        "При каждой отправке выбирается случайное значение.\n\n"
        "/cancel — отмена"
    )
    await call.answer()

@router.message(EditVar.values)
async def fsm_var_values(message: Message, state: FSMContext):
    uid = message.from_user.id
    text = safe_text(message)
    if not text:
        await message.answer("⚠️ Отправьте значения текстом. /cancel — отмена")
        return
    data      = await state.get_data()
    key       = data["var_key"]
    values    = [l.strip() for l in text.split("\n") if l.strip()]
    variables = load_variables(uid)
    variables[key] = values
    save_variables(uid, variables)
    await state.clear()
    rot = " — ротируются случайно 🔀" if len(values) > 1 else ""
    await message.answer(
        f"✅ Сохранено <b>{len(values)}</b> значений для <code>{{{key}}}</code>{rot}",
        reply_markup=kb_main(is_sending(uid)),
    )

@router.callback_query(F.data == "menu:subject")
async def cb_subject(call: CallbackQuery, state: FSMContext):
    uid = call.from_user.id
    await state.set_state(EditSubject.subjects)
    subjects = load_subjects(uid)
    current  = "\n".join(subjects)
    await call.message.edit_text(
        f"✉️ <b>Темы письма</b>\n<code>━━━━━━━━━━━━━━━━━━━━━━</code>\n{len(subjects)} шт.\n\n"
        f"Текущие:\n<pre>{current}</pre>\n\n"
        "Отправьте новые темы — <b>каждая на отдельной строке</b>.\n"
        "При каждой отправке выбирается случайная тема.\n\n"
        "/cancel — отмена"
    )
    await call.answer()

@router.message(EditSubject.subjects)
async def fsm_subject(message: Message, state: FSMContext):
    uid = message.from_user.id
    text = safe_text(message)
    if not text:
        await message.answer("⚠️ Отправьте темы текстом. /cancel — отмена")
        return
    subjects = [l.strip() for l in text.split("\n") if l.strip()]
    if not subjects:
        await message.answer("⚠️ Не найдено ни одной темы. /cancel — отмена")
        return
    save_subjects(uid, subjects)
    await state.clear()
    preview = "\n".join(f"  • {s}" for s in subjects[:5])
    if len(subjects) > 5:
        preview += f"\n  … ещё {len(subjects) - 5}"
    await message.answer(
        f"✅ Сохранено <b>{len(subjects)}</b> тем:\n{preview}",
        reply_markup=kb_main(is_sending(uid)),
    )
