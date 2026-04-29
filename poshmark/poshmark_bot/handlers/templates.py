import io
from aiogram import Router, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, Document
from aiogram.utils.keyboard import InlineKeyboardBuilder
from ..storage import load_templates, save_templates
from ..utils.keyboards import kb_templates, kb_main
from ..utils.helpers import safe_text
from ..states import AddTemplate
from ..globals import is_sending

router = Router()

@router.callback_query(F.data == "menu:templates")
async def cb_templates(call: CallbackQuery):
    uid = call.from_user.id
    templates, selected = load_templates(uid)
    await call.message.edit_text(
        f"🗂 <b>HTML шаблоны</b>\n<code>━━━━━━━━━━━━━━━━━━━━━━</code>\nВсего: {len(templates)} · Активных: {len(selected)}",
        reply_markup=kb_templates(templates, selected),
    )
    await call.answer()

@router.callback_query(F.data.startswith("tpl:toggle:"))
async def cb_tpl_toggle(call: CallbackQuery):
    uid = call.from_user.id
    try:
        idx = int(call.data.removeprefix("tpl:toggle:"))
    except ValueError:
        await call.answer("Ошибка", show_alert=True); return
    templates, selected = load_templates(uid)
    names = list(templates.keys())
    if idx >= len(names):
        await call.answer("Шаблон не найден", show_alert=True); return
    name = names[idx]
    if name in selected:
        selected.remove(name)
    else:
        selected.append(name)
    save_templates(uid, templates, selected)
    await call.message.edit_text(
        f"🗂 <b>HTML шаблоны</b>\n<code>━━━━━━━━━━━━━━━━━━━━━━</code>\nВсего: {len(templates)} · Активных: {len(selected)}",
        reply_markup=kb_templates(templates, selected),
    )
    await call.answer()

@router.callback_query(F.data.startswith("tpl:del:"))
async def cb_tpl_delete(call: CallbackQuery):
    uid = call.from_user.id
    try:
        idx = int(call.data.removeprefix("tpl:del:"))
    except ValueError:
        await call.answer("Ошибка", show_alert=True); return
    templates, selected = load_templates(uid)
    names = list(templates.keys())
    if idx >= len(names):
        await call.answer("Шаблон не найден", show_alert=True); return
    name = names[idx]
    b = InlineKeyboardBuilder()
    b.button(text="✅ Да, удалить", callback_data=f"tpl:delok:{idx}")
    b.button(text="❌ Отмена",      callback_data="menu:templates")
    b.adjust(1)
    await call.message.edit_text(
        f"🗑 <b>Удалить шаблон?</b>\n\n"
        f"<code>{name}</code>\n\n"
        "Это действие необратимо.",
        reply_markup=b.as_markup(),
    )
    await call.answer()

@router.callback_query(F.data.startswith("tpl:delok:"))
async def cb_tpl_delete_confirm(call: CallbackQuery):
    uid = call.from_user.id
    try:
        idx = int(call.data.removeprefix("tpl:delok:"))
    except ValueError:
        await call.answer("Ошибка", show_alert=True); return
    templates, selected = load_templates(uid)
    names = list(templates.keys())
    if idx >= len(names):
        await call.answer("Шаблон не найден", show_alert=True); return
    name = names[idx]
    del templates[name]
    if name in selected:
        selected.remove(name)
    save_templates(uid, templates, selected)
    await call.message.edit_text(
        f"✅ Шаблон <code>{name}</code> удалён.\n\n"
        f"🗂 <b>HTML шаблоны</b>\n<code>━━━━━━━━━━━━━━━━━━━━━━</code>\nВсего: {len(templates)} · Активных: {len(selected)}",
        reply_markup=kb_templates(templates, selected),
    )
    await call.answer("Шаблон удалён")

@router.callback_query(F.data == "tpl:add")
async def cb_tpl_add(call: CallbackQuery):
    b = InlineKeyboardBuilder()
    b.button(text="✏️ Вставить HTML текстом",   callback_data="tpl:add:text")
    b.button(text="📎 Загрузить .html файлом",   callback_data="tpl:add:file")
    b.button(text="◀️ Назад",                    callback_data="menu:templates")
    b.adjust(1)
    await call.message.edit_text(
        "📄 <b>Добавить HTML шаблон</b>\n\nВыберите способ:",
        reply_markup=b.as_markup(),
    )
    await call.answer()

@router.callback_query(F.data == "tpl:add:text")
async def cb_tpl_add_text(call: CallbackQuery, state: FSMContext):
    await state.set_state(AddTemplate.name)
    await call.message.edit_text(
        "📄 Введите <b>название</b> шаблона (например: <code>promo.html</code>):\n\n/cancel — отмена"
    )
    await call.answer()

@router.callback_query(F.data == "tpl:add:file")
async def cb_tpl_add_file(call: CallbackQuery, state: FSMContext):
    await state.set_state(AddTemplate.file)
    await call.message.edit_text(
        "📎 Отправьте <b>.html файл</b> — он будет добавлен как шаблон.\n\n"
        "Переменные внутри файла: <code>{recipient}</code> <code>{sender}</code> "
        "<code>{title}</code> <code>{text}</code> <code>{button}</code> "
        "<code>{link}</code> <code>{randomID}</code>\n\n/cancel — отмена"
    )
    await call.answer()

@router.message(AddTemplate.name)
async def fsm_tpl_name(message: Message, state: FSMContext):
    text = safe_text(message)
    if not text:
        await message.answer("⚠️ Отправьте название текстом. /cancel — отмена")
        return
    await state.update_data(tpl_name=text.strip())
    await state.set_state(AddTemplate.content)
    await message.answer(
        "Отправьте HTML-содержимое шаблона.\n\n"
        "Переменные: <code>{recipient}</code> <code>{sender}</code> <code>{title}</code> "
        "<code>{text}</code> <code>{button}</code> <code>{link}</code> <code>{randomID}</code>\n\n"
        "/cancel — отмена"
    )

@router.message(AddTemplate.content)
async def fsm_tpl_content(message: Message, state: FSMContext):
    uid = message.from_user.id
    text = safe_text(message)
    if not text:
        await message.answer("⚠️ Отправьте HTML-содержимое текстом. /cancel — отмена")
        return
    data    = await state.get_data()
    name    = data["tpl_name"]
    templates, selected = load_templates(uid)
    templates[name] = text
    if name not in selected:
        selected.append(name)
    save_templates(uid, templates, selected)
    await state.clear()
    await message.answer(
        f"✅ Шаблон <code>{name}</code> сохранён и выбран.",
        reply_markup=kb_main(is_sending(uid)),
    )

@router.message(AddTemplate.file, F.document)
async def fsm_tpl_file(message: Message, state: FSMContext, bot: Bot):
    uid = message.from_user.id
    doc: Document = message.document
    if not doc.file_name.lower().endswith((".html", ".htm")):
        await message.answer("⚠️ Нужен файл с расширением .html или .htm. Попробуйте снова:")
        return

    file_info = await bot.get_file(doc.file_id)
    buf = io.BytesIO()
    await bot.download_file(file_info.file_path, destination=buf)

    try:
        html_content = buf.getvalue().decode("utf-8")
    except UnicodeDecodeError:
        html_content = buf.getvalue().decode("cp1251", errors="replace")

    name = doc.file_name
    templates, selected = load_templates(uid)
    templates[name] = html_content
    if name not in selected:
        selected.append(name)
    save_templates(uid, templates, selected)
    await state.clear()
    await message.answer(
        f"✅ Шаблон <code>{name}</code> загружен и выбран.\n"
        f"📏 Размер: {len(html_content)} символов",
        reply_markup=kb_main(is_sending(uid)),
    )
