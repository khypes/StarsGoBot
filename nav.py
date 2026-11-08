"""Inline navigatsiya yordamchilari: bitta xabarni tahrirlab, ekranlar orasida o'tish."""
import contextlib

from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup

from emojis import ibtn
from ui import note


def cancel_kb(back: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[ibtn("cancel", "Bekor qilish", callback_data=back)]])


async def show(event: CallbackQuery | Message, text: str, kb: InlineKeyboardMarkup | None = None) -> Message:
    """Callback bo'lsa xabarni joyida tahrirlaydi, bo'lmasa yangi xabar yuboradi."""
    if isinstance(event, CallbackQuery):
        msg = event.message
        try:
            if msg.text is not None:
                return await msg.edit_text(text, reply_markup=kb)
        except TelegramBadRequest as exc:
            if "message is not modified" in str(exc):
                return msg
        return await msg.answer(text, reply_markup=kb)
    return await event.answer(text, reply_markup=kb)


async def ask(call: CallbackQuery, state: FSMContext, new_state, text: str, back: str,
              kb: InlineKeyboardMarkup | None = None, **extra) -> None:
    """Qiymat kutish: promptni ko'rsatadi, holatga o'tadi. Bekor qilish `back` ekraniga qaytaradi."""
    await state.clear()
    msg = await show(call, text, kb or cancel_kb(back))
    await state.set_state(new_state)
    await state.update_data(
        prompt_mid=msg.message_id, prompt_cid=msg.chat.id, prompt_text=text, back=back, **extra
    )


async def _edit_prompt(message: Message, data: dict, text: str, kb, delete_input: bool = True) -> None:
    if delete_input:
        with contextlib.suppress(Exception):
            await message.delete()  # foydalanuvchi xabari chatni to'ldirmasin (maxfiy qiymatlar ham o'chadi)
    mid, cid = data.get("prompt_mid"), data.get("prompt_cid")
    if mid and cid:
        try:
            await message.bot.edit_message_text(text, chat_id=cid, message_id=mid, reply_markup=kb)
            return
        except TelegramBadRequest as exc:
            if "message is not modified" in str(exc):
                return
    await message.bot.send_message(message.chat.id, text, reply_markup=kb)


async def invalid(message: Message, state: FSMContext, error: str) -> None:
    """Noto'g'ri kiritish: prompt joyida xato izohi bilan qayta ko'rsatiladi (holat saqlanadi)."""
    data = await state.get_data()
    text = (data.get("prompt_text") or "") + "\n" + note("warn", error)
    await _edit_prompt(message, data, text, cancel_kb(data.get("back", "m:home")))


async def finish(message: Message, state: FSMContext, text: str, kb, flash: str | None = None,
                 delete_input: bool = True) -> None:
    """Kiritish muvaffaqiyatli: holat tozalanadi, prompt xabari yangi ekranga aylanadi."""
    data = await state.get_data()
    await state.clear()
    await _edit_prompt(message, data, (flash + "\n" if flash else "") + text, kb, delete_input)


async def render_input(message: Message, state: FSMContext, text: str, kb) -> None:
    """Holatni saqlagan holda prompt xabarini yangi ekranga almashtiradi (foydalanuvchi xabari o'chiriladi)."""
    await _edit_prompt(message, await state.get_data(), text, kb)
