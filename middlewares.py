"""Barcha foydalanuvchi hodisalari uchun: ro'yxatga olish, ban tekshiruvi, majburiy obuna."""
import time

from aiogram import BaseMiddleware, Bot
from aiogram.types import CallbackQuery, Message

import database.db as db
from keyboards.user_kb import channels_check_kb
from ui import card, note

_SUB_TTL = 60  # sekund: obuna tekshiruvi natijasini keshlash
_sub_ok: dict[int, float] = {}


async def missing_channels(bot: Bot, user_id: int) -> list:
    """Foydalanuvchi obuna bo'lmagan kanallar ro'yxati."""
    missing = []
    for ch in await db.list_channels():
        try:
            member = await bot.get_chat_member(ch["chat_id"], user_id)
            if member.status in ("left", "kicked"):
                missing.append(ch)
        except Exception:
            missing.append(ch)
    return missing


def forget(user_id: int) -> None:
    _sub_ok.pop(user_id, None)


class AccessMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user = data.get("event_from_user")
        if user is None or user.is_bot:
            return await handler(event, data)

        if await db.is_admin(user.id):
            return await handler(event, data)

        is_start = isinstance(event, Message) and (event.text or "").startswith("/start")
        is_check = isinstance(event, CallbackQuery) and event.data == "check_subs"

        row = await db.get_user(user.id)
        if row is None and not is_start:
            row, _ = await db.create_user_if_not_exists(user.id, user.username or "", user.full_name or "", None)

        if row is not None and row["is_banned"]:
            text = card("ban", "Bloklangansiz", "Siz botdan foydalanishdan chetlatilgansiz.", "Xato deb o'ylasangiz, admin bilan bog'laning.")
            if isinstance(event, CallbackQuery):
                await event.answer("Siz bloklangansiz", show_alert=True)
            elif isinstance(event, Message):
                await event.answer(text)
            return None

        if is_start or is_check:
            return await handler(event, data)

        if _sub_ok.get(user.id, 0) > time.time():
            return await handler(event, data)

        bot: Bot = data["bot"]
        missing = await missing_channels(bot, user.id)
        if not missing:
            _sub_ok[user.id] = time.time() + _SUB_TTL
            return await handler(event, data)

        text = card(
            "megaphone", "Majburiy obuna",
            "Botdan foydalanish uchun quyidagi kanallarga obuna bo'lishingiz kerak.",
            "",
            "Obuna bo'lgach, «Tekshirish» tugmasini bosing.",
        )
        if isinstance(event, CallbackQuery):
            await event.answer("Avval kanallarga obuna bo'ling", show_alert=True)
            if event.message:
                await event.message.answer(text, reply_markup=channels_check_kb(missing))
        elif isinstance(event, Message):
            await event.answer(text, reply_markup=channels_check_kb(missing))
        return None
