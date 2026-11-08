import asyncio
import contextlib
import json
import re

from aiogram import Router, F, Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery

import database.db as db
import fulfillment
from config import SUPER_ADMIN_ID
from emojis import em
from keyboards.admin_kb import (
    admin_home_kb, back_admin_kb, settings_kb, payment_kb, admins_kb, user_manage_kb,
    topup_action_kb, channels_kb,
)
from nav import show, ask, invalid, finish
from states.states import (
    AdminSettings, AdminBroadcast, AdminUserManage, AdminChannel,
)
from texts import topup_card, provider_locked
from ui import IsAdmin, card, note, esc, price, currency

router = Router()
# Admin handlerlari faqat adminlar uchun; oddiy foydalanuvchi hodisalari user routerga o'tadi.
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())


async def edit_card(call: CallbackQuery, text: str, kb=None):
    """Xabar matnini yoki (chek rasmi bo'lsa) captionni yangilaydi."""
    try:
        if call.message.text is not None:
            await call.message.edit_text(text, reply_markup=kb)
        else:
            await call.message.edit_caption(caption=text, reply_markup=kb)
    except TelegramBadRequest:
        pass


# ==================== bosh ekran ====================

async def home_view():
    _, _, pending = await db.order_stats()
    users = await db.user_count()
    text = card(
        "panel", "Admin panel",
        f"{em('people')} Foydalanuvchilar: <b>{users}</b>",
        f"{em('pending')} Kutilayotgan buyurtmalar: <b>{pending}</b>",
        "",
        f"{em('down')} Kerakli bo'limni tanlang:",
    )
    return text, admin_home_kb()


@router.callback_query(F.data == "a:home")
async def cb_home(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.answer()
    await show(call, *await home_view())


# ==================== statistika ====================

async def stats_view():
    users = await db.user_count()
    total, revenue, pending = await db.order_stats()
    text = card(
        "stats", "Statistika",
        f"{em('people')} Foydalanuvchilar: <b>{users}</b>",
        f"{em('done')} Bajarilgan buyurtmalar: <b>{total}</b>",
        f"{em('pending')} Kutilayotgan buyurtmalar: <b>{pending}</b>",
        f"{em('money')} Umumiy tushum: <b>{await price(revenue)}</b>",
    )
    from emojis import ibtn
    from aiogram.types import InlineKeyboardMarkup
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [ibtn("refresh", "Yangilash", callback_data="a:stats")],
        [ibtn("back", "Orqaga", callback_data="a:home")],
    ])
    return text, kb


@router.callback_query(F.data == "a:stats")
async def cb_stats(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.answer()
    await show(call, *await stats_view())


# ==================== xabar yuborish ====================

@router.callback_query(F.data == "a:bc")
async def cb_broadcast(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await ask(call, state, AdminBroadcast.waiting_message, card(
        "broadcast", "Xabar yuborish",
        f"Xabar botdagi barcha foydalanuvchilarga yuboriladi: <b>{await db.user_count()}</b> kishi.",
        "Matn, rasm, video yoki fayl yuborishingiz mumkin.",
        "",
        f"{em('warn')} Yuborilgan xabarni qaytarib bo'lmaydi — jo'natishdan oldin yaxshilab tekshiring.",
    ), back="a:home")


@router.message(AdminBroadcast.waiting_message)
async def broadcast_send(message: Message, state: FSMContext):
    user_ids = await db.all_user_ids()
    sent = failed = 0
    status = await message.answer(note("pending", f"Yuborilmoqda... 0/{len(user_ids)}"))
    for i, uid in enumerate(user_ids, 1):
        for _ in range(2):
            try:
                await message.copy_to(uid)
                sent += 1
                break
            except TelegramRetryAfter as exc:
                await asyncio.sleep(exc.retry_after + 1)
            except (TelegramForbiddenError, TelegramBadRequest):
                failed += 1
                break
            except Exception:
                failed += 1
                break
        else:
            failed += 1
        if i % 25 == 0:
            with contextlib.suppress(Exception):
                await status.edit_text(note("pending", f"Yuborilmoqda... {i}/{len(user_ids)}"))
        await asyncio.sleep(0.05)
    with contextlib.suppress(Exception):
        await status.delete()
    await finish(
        message, state,
        card("done", "Xabar yuborildi", f"Muvaffaqiyatli: <b>{sent}</b>", f"Xatolik: <b>{failed}</b>"),
        back_admin_kb(), delete_input=False,
    )


# ==================== foydalanuvchilarni boshqarish ====================

async def user_view(uid: int, flash: str | None = None):
    user = await db.get_user(uid)
    if not user:
        return note("cancel", "Foydalanuvchi topilmadi."), back_admin_kb("a:users")
    banned = bool(user["is_banned"])
    ban_text = "Ha" if banned else "Yo'q"
    lines = [flash, ""] if flash else []
    lines += [
        f"{em('id')} ID: <code>{uid}</code>",
        f"{em('account')} Ism: {esc(user['full_name'])}",
        f"{em('link')} Username: {('@' + esc(user['username'])) if user['username'] else '—'}",
        f"{em('money')} Balans: <b>{await price(user['balance'])}</b>",
        f"{em('ban')} Bloklangan: {ban_text}",
        f"{em('people')} Referallar: {await db.referral_count(uid)}",
    ]
    return card("account", "Foydalanuvchi", *lines), user_manage_kb(uid, banned)


@router.callback_query(F.data == "a:users")
async def cb_users(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await ask(call, state, AdminUserManage.waiting_user_id, card(
        "users", "Foydalanuvchini boshqarish",
        "Foydalanuvchining Telegram ID raqamini yoki @username ini yuboring.",
        "",
        f"{em('info')} Topilgach balansni o'zgartirish, bloklash yoki blokdan chiqarish mumkin.",
    ), back="a:home")


@router.message(AdminUserManage.waiting_user_id, F.text)
async def user_lookup(message: Message, state: FSMContext):
    text = message.text.strip()
    if text.startswith("@"):
        user = await db.get_user_by_username(text)
    elif text.isascii() and text.isdigit():
        user = await db.get_user(int(text))
    else:
        await invalid(message, state, "ID raqam yoki @username yuboring.")
        return
    if not user:
        await invalid(message, state, "Bunday foydalanuvchi topilmadi.")
        return
    await finish(message, state, *await user_view(user["user_id"]))


@router.message(AdminUserManage.waiting_user_id)
async def user_lookup_invalid(message: Message, state: FSMContext):
    await invalid(message, state, "ID raqam yoki @username yuboring.")


@router.callback_query(F.data.regexp(r"^u:view:\d+$"))
async def cb_user_view(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.answer()
    await show(call, *await user_view(int(call.data.split(":")[2])))


@router.callback_query(F.data.regexp(r"^u:(ban|unban):\d+$"))
async def cb_user_ban(call: CallbackQuery):
    _, action, raw = call.data.split(":")
    uid = int(raw)
    if await db.is_admin(uid):
        await call.answer("Adminni bloklab bo'lmaydi", show_alert=True)
        return
    await db.set_ban(uid, action == "ban")
    await call.answer("Bajarildi")
    await show(call, *await user_view(uid))


@router.callback_query(F.data.regexp(r"^u:bal:\d+:[pm]$"))
async def cb_user_balance(call: CallbackQuery, state: FSMContext):
    _, _, raw, sign = call.data.split(":")
    word = "qo'shiladigan" if sign == "p" else "ayiriladigan"
    await call.answer()
    await ask(call, state, AdminUserManage.waiting_amount, card(
        "money", "Balansni o'zgartirish", f"{word.capitalize()} summani kiriting (faqat raqam).",
    ), back=f"u:view:{raw}", target=int(raw), sign=sign)


@router.message(AdminUserManage.waiting_amount, F.text)
async def user_balance_apply(message: Message, state: FSMContext):
    raw = message.text.replace(" ", "")
    if not (raw.isascii() and raw.isdigit()) or int(raw) <= 0:
        await invalid(message, state, "Musbat butun son kiriting.")
        return
    data = await state.get_data()
    uid, sign = data["target"], data["sign"]
    delta = int(raw) if sign == "p" else -int(raw)
    if not await db.adjust_balance(uid, delta):
        await invalid(message, state, "Foydalanuvchi topilmadi.")
        return
    await db.create_transaction(uid, delta, "admin_adjust", note=f"admin {message.from_user.id}",
                                status="tasdiqlandi")
    await finish(message, state, *await user_view(uid, flash=f"{em('done')} <b>Balans yangilandi.</b>"))


@router.message(AdminUserManage.waiting_amount)
async def user_balance_invalid(message: Message, state: FSMContext):
    await invalid(message, state, "Musbat butun son kiriting.")


# ==================== to'lov tizimi ====================

def fmt_card(number: str) -> str:
    """8600123412341234 -> 8600 1234 1234 1234"""
    digits = re.sub(r"\D", "", number)
    return " ".join(digits[i:i + 4] for i in range(0, len(digits), 4))


async def payment_view(flash: str | None = None):
    number = await db.get_setting("card_number")
    holder = await db.get_setting("card_holder")
    lines = [flash, ""] if flash else []
    lines += [
        "Foydalanuvchilar hisobni shu karta orqali to'ldiradi. Raqam va egasining ismi to'lov oynasida ko'rsatiladi.",
        "",
        f"{em('payment')} Karta raqami: <code>{esc(fmt_card(number)) or 'kiritilmagan'}</code>",
        f"{em('name')} Karta egasi: <b>{esc(holder) or 'kiritilmagan'}</b>",
    ]
    if not number or not holder:
        lines += ["", f"{em('warn')} Ikkala maydonni ham to'ldiring — shunda foydalanuvchi to'lovni adashmay qiladi."]
    return card("payment", "To'lov tizimi", *lines), payment_kb()


@router.callback_query(F.data == "a:pay")
async def cb_payment(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.answer()
    await show(call, *await payment_view())


@router.callback_query(F.data == "p:card")
async def cb_pay_card(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await ask(call, state, AdminSettings.waiting_card_number, card(
        "payment", "Karta raqami",
        "Yangi karta raqamini yuboring (masalan: <code>8600 1234 5678 9012</code>).",
        "Raqamni o'chirish uchun <code>-</code> yuboring.",
    ), back="a:pay")


@router.callback_query(F.data == "p:holder")
async def cb_pay_holder(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await ask(call, state, AdminSettings.waiting_card_holder, card(
        "name", "Karta egasi",
        "Karta egasining ism-familiyasini yuboring (masalan: <code>ALISHER VALIYEV</code>).",
        "Foydalanuvchi to'lovdan oldin ismni ko'rib, to'g'ri kartaga o'tkazganini tekshira oladi.",
        "O'chirish uchun <code>-</code> yuboring.",
    ), back="a:pay")


@router.message(AdminSettings.waiting_card_number, F.text)
async def card_set(message: Message, state: FSMContext):
    raw = message.text.strip()
    if raw == "-":
        value = ""
    else:
        digits = re.sub(r"[\s-]", "", raw)
        if not (digits.isascii() and digits.isdigit() and 12 <= len(digits) <= 19):
            await invalid(message, state, "Karta raqami 12–19 ta raqamdan iborat bo'lsin. Masalan: 8600 1234 5678 9012")
            return
        value = digits
    await db.set_setting("card_number", value)
    word = "yangilandi" if value else "o'chirildi"
    await finish(message, state, *await payment_view(f"{em('done')} <b>Karta raqami {word}.</b>"))


@router.message(AdminSettings.waiting_card_holder, F.text)
async def holder_set(message: Message, state: FSMContext):
    raw = " ".join(message.text.split())
    if raw == "-":
        value = ""
    else:
        if not (2 <= len(raw) <= 40):
            await invalid(message, state, "Ism 2–40 ta belgidan iborat bo'lsin.")
            return
        value = raw.upper()
    await db.set_setting("card_holder", value)
    word = "yangilandi" if value else "o'chirildi"
    await finish(message, state, *await payment_view(f"{em('done')} <b>Karta egasi {word}.</b>"))


# ==================== kanallar (majburiy obuna) ====================

async def channels_view(flash: str | None = None):
    channels = await db.list_channels()
    lines = [flash, ""] if flash else []
    if channels:
        lines += [f"<b>#{c['id']}</b> · {esc(c['title'])} <code>{esc(c['chat_id'])}</code>" for c in channels]
        lines += ["", "O'chirish uchun kanal nomini bosing."]
    else:
        lines.append("Hozircha majburiy obuna kanallari yo'q.")
    return card("channels", "Majburiy obuna kanallari", *lines), channels_kb(channels)


@router.callback_query(F.data == "a:ch")
async def cb_channels(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.answer()
    await show(call, *await channels_view())


@router.callback_query(F.data == "ch:add")
async def cb_channel_add(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await ask(call, state, AdminChannel.waiting_add, card(
        "plus", "Kanal qo'shish",
        "Kanal usernamesini yuboring: <code>@kanal</code>",
        "Maxfiy kanal uchun: <code>-100123456789 | https://t.me/+havola</code>",
        "",
        f"{em('warn')} Bot kanalda administrator bo'lishi shart, aks holda obunani tekshira olmaydi.",
        "Foydalanuvchilar shu kanallarga obuna bo'lmaguncha botdan foydalana olmaydi.",
    ), back="a:ch")


@router.message(AdminChannel.waiting_add, F.text)
async def channel_add(message: Message, state: FSMContext, bot: Bot):
    parts = [p.strip() for p in message.text.split("|")]
    ref, url = parts[0], (parts[1] if len(parts) > 1 else "")
    if not (ref.startswith("@") or re.fullmatch(r"-?\d+", ref)):
        await invalid(message, state, "Format noto'g'ri. Masalan: @kanal")
        return
    try:
        chat = await bot.get_chat(ref)
    except Exception:
        await invalid(message, state, "Kanal topilmadi. Bot kanalga qo'shilganini tekshiring.")
        return
    if not url:
        if not chat.username:
            await invalid(message, state, "Maxfiy kanal uchun havola ham kerak: ID | https://t.me/+...")
            return
        url = f"https://t.me/{chat.username}"
    warning = ""
    try:
        me = await bot.get_me()
        member = await bot.get_chat_member(chat.id, me.id)
        if member.status not in ("administrator", "creator"):
            warning = f"\n{em('warn')} Bot kanalda administrator emas — obunani tekshira olmaydi."
    except Exception:
        warning = f"\n{em('warn')} Botning kanaldagi huquqlarini tekshirib bo'lmadi."
    await db.add_channel(str(chat.id), chat.title or ref, url)
    await finish(message, state, *await channels_view(
        f"{em('done')} <b>Kanal qo'shildi:</b> {esc(chat.title or ref)}{warning}"))


@router.callback_query(F.data.regexp(r"^ch:del:\d+$"))
async def cb_channel_remove(call: CallbackQuery):
    await db.remove_channel(int(call.data.split(":")[2]))
    await call.answer("Kanal o'chirildi")
    await show(call, *await channels_view())


# ==================== sozlamalar ====================

async def settings_view(flash: str | None = None):
    notify_on = (await db.get_setting("order_notify")) == "1"
    lines = [flash, ""] if flash else []
    lines += [
        f"{em('currency')} Valyuta: <b>{esc(await currency())}</b>",
        f"{em('ref_percent')} Referal foizi: <b>{esc(await db.get_setting('referral_percent'))}%</b>",
        f"{em('stars_prices')} Stars paketlari: <b>{len(await db.get_stars_prices())}</b> ta",
        f"{em('premium_prices')} Premium tariflari: <b>{len(await db.get_premium_prices())}</b> ta",
    ]
    return card("settings", "Sozlamalar", *lines), settings_kb(notify_on)


@router.callback_query(F.data == "a:set")
async def cb_settings(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.answer()
    await show(call, *await settings_view())


@router.callback_query(F.data == "s:notify")
async def cb_notify(call: CallbackQuery):
    new_val = "0" if (await db.get_setting("order_notify")) == "1" else "1"
    await db.set_setting("order_notify", new_val)
    await call.answer("Yoqildi" if new_val == "1" else "O'chirildi")
    await show(call, *await settings_view())


@router.callback_query(F.data == "s:cur")
async def cb_currency(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await ask(call, state, AdminSettings.waiting_currency, card(
        "currency", "Valyuta", f"Joriy: <b>{esc(await currency())}</b>",
        "Yangi valyuta belgisini yuboring, masalan: <code>so'm</code>.",
        "",
        f"{em('info')} Barcha narxlar va balanslar shu nom bilan ko'rsatiladi.",
    ), back="a:set")


@router.message(AdminSettings.waiting_currency, F.text)
async def currency_set(message: Message, state: FSMContext):
    value = message.text.strip()
    if not value or len(value) > 12:
        await invalid(message, state, "Valyuta belgisi 1–12 belgidan iborat bo'lsin.")
        return
    await db.set_setting("currency", value)
    await finish(message, state, *await settings_view(f"{em('done')} <b>Valyuta yangilandi.</b>"))


@router.callback_query(F.data == "s:ref")
async def cb_ref_percent(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await ask(call, state, AdminSettings.waiting_referral_percent, card(
        "ref_percent", "Referal foizi",
        f"Joriy: <b>{esc(await db.get_setting('referral_percent'))}%</b>",
        "Yangi foizni yuboring (0–100).",
    ), back="a:set")


@router.message(AdminSettings.waiting_referral_percent, F.text)
async def ref_percent_set(message: Message, state: FSMContext):
    raw = message.text.strip()
    if not (raw.isascii() and raw.isdigit()) or not (0 <= int(raw) <= 100):
        await invalid(message, state, "0 dan 100 gacha butun son kiriting.")
        return
    await db.set_setting("referral_percent", str(int(raw)))
    await finish(message, state, *await settings_view(f"{em('done')} <b>Referal foizi yangilandi.</b>"))


def parse_prices(text: str, field: str):
    """JSON yoki oddiy qatorlar ("100=20000") ko'rinishidagi narxlarni o'qiydi."""
    items: list[tuple[int, int]] = []
    try:
        data = json.loads(text)
        items = [(int(it[field]), int(it["price"])) for it in data]
    except Exception:
        items = []
        for line in text.splitlines():
            if not line.strip():
                continue
            nums = re.findall(r"\d+", line)
            if len(nums) != 2:
                return None
            items.append((int(nums[0]), int(nums[1])))
    if not items or any(a <= 0 or b <= 0 for a, b in items):
        return None
    unique = dict(items)
    return [{field: a, "price": unique[a]} for a in sorted(unique)]


async def _prices_prompt(call: CallbackQuery, state: FSMContext, kind: str):
    if kind == "stars":
        current, field, st = await db.get_stars_prices(), "stars", AdminSettings.waiting_stars_prices
        title, key, example, left = "Stars narxlari", "stars_prices", "100=20000", "Stars miqdori"
    else:
        current, field, st = await db.get_premium_prices(), "months", AdminSettings.waiting_premium_prices
        title, key, example, left = "Premium narxlari", "premium_prices", "3=155000", "oy soni (3, 6 yoki 12)"
    lines = [f"<code>{p[field]}={p['price']}</code>" for p in current]
    await call.answer()
    await ask(call, state, st, card(
        key, title, *lines, "",
        f"Yangi ro'yxatni har qatorga bittadan yuboring: <code>{example}</code>",
        f"(chapda {left}, o'ngda narx). JSON ham qabul qilinadi.",
    ), back="a:set")


@router.callback_query(F.data == "s:sp")
async def cb_stars_prices(call: CallbackQuery, state: FSMContext):
    await _prices_prompt(call, state, "stars")


@router.callback_query(F.data == "s:pp")
async def cb_premium_prices(call: CallbackQuery, state: FSMContext):
    await _prices_prompt(call, state, "premium")


@router.message(AdminSettings.waiting_stars_prices, F.text)
async def stars_prices_set(message: Message, state: FSMContext):
    data = parse_prices(message.text, "stars")
    if data is None:
        await invalid(message, state, "Format noto'g'ri. Masalan: 100=20000 (har qatorda bittadan).")
        return
    await db.set_setting("stars_prices", json.dumps(data, ensure_ascii=False))
    flash = f"{em('done')} <b>Stars narxlari yangilandi.</b>"
    if await fulfillment.is_enabled() and any(not (50 <= p["stars"] <= 10000) for p in data):
        flash += f"\n{em('warn')} 50–10000 oralig'idan tashqari paketlar API orqali avtomatik yetkazilmaydi."
    await finish(message, state, *await settings_view(flash))


@router.message(AdminSettings.waiting_premium_prices, F.text)
async def premium_prices_set(message: Message, state: FSMContext):
    data = parse_prices(message.text, "months")
    if data is None:
        await invalid(message, state, "Format noto'g'ri. Masalan: 3=155000 (har qatorda bittadan).")
        return
    await db.set_setting("premium_prices", json.dumps(data, ensure_ascii=False))
    flash = f"{em('done')} <b>Premium narxlari yangilandi.</b>"
    if await fulfillment.is_enabled() and any(p["months"] not in (3, 6, 12) for p in data):
        flash += f"\n{em('warn')} Faqat 3, 6 va 12 oylik tariflar API orqali avtomatik yetkaziladi."
    await finish(message, state, *await settings_view(flash))


# ==================== adminlar ====================

async def admins_view(flash: str | None = None):
    ids = await db.list_admins()
    lines = [flash, ""] if flash else []
    lines += [f"• <code>{a}</code>" + (" (bosh admin)" if a == SUPER_ADMIN_ID else "") for a in ids]
    lines += ["", "O'chirish uchun ID ni bosing."]
    return card("admins", "Adminlar", *lines), admins_kb(ids, SUPER_ADMIN_ID)


@router.callback_query(F.data == "s:adm")
async def cb_admins(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.answer()
    await show(call, *await admins_view())


@router.callback_query(F.data == "adm:add")
async def cb_admin_add(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await ask(call, state, AdminSettings.waiting_add_admin, card(
        "plus", "Admin qo'shish",
        "Yangi adminning Telegram ID raqamini yuboring (faqat raqam).",
        "",
        f"{em('info')} Admin buyurtmalar, to'lovlar va sozlamalarni boshqara oladi. "
        "ID ni @userinfobot orqali bilib olish mumkin."), back="s:adm")


@router.message(AdminSettings.waiting_add_admin, F.text)
async def admin_add(message: Message, state: FSMContext):
    raw = message.text.strip().lstrip("+")
    if not (raw.isascii() and raw.isdigit()) or int(raw) <= 0:
        await invalid(message, state, "Faqat ID raqam yuboring.")
        return
    await db.add_admin(int(raw))
    await finish(message, state, *await admins_view(f"{em('done')} <b>Qo'shildi:</b> <code>{int(raw)}</code>"))


@router.callback_query(F.data.regexp(r"^adm:del:\d+$"))
async def cb_admin_remove(call: CallbackQuery):
    uid = int(call.data.split(":")[2])
    if not await db.remove_admin(uid):
        await call.answer("Bosh adminni o'chirib bo'lmaydi", show_alert=True)
        return
    await call.answer("O'chirildi")
    await show(call, *await admins_view())


# ==================== buyurtmalar ====================

_RETRY_RESULT = {
    "disabled": "Avto-yetkazish yoqilmagan",
    "closed": "Buyurtma allaqachon yopilgan",
    "manual": "Bu buyurtmani avtomatik yuborib bo'lmaydi",
    "busy": "Buyurtma hozir API da ishlanmoqda",
    "processing": "API ga yuborildi — jarayonda",
    "delivered": "Yetkazildi!",
    "failed": "Provayder bajara olmadi, mablag' qaytarildi",
    "retry": "API vaqtincha javob bermadi — qayta uriniladi",
    "error": "API xatosi — kartani ko'ring",
}


async def _render_order(call: CallbackQuery, order_id: int):
    view = await fulfillment.order_view(order_id)
    if view:
        await edit_card(call, *view)


@router.callback_query(F.data.regexp(r"^order_done:\d+$"))
async def order_done(call: CallbackQuery):
    oid = int(call.data.split(":")[1])
    order = await db.get_order(oid)
    if order and provider_locked(order):
        await call.answer("Buyurtma API orqali bajarilmoqda — kuting", show_alert=True)
        return
    res = await db.complete_order(oid)
    if res is None:
        await call.answer("Allaqachon ko'rib chiqilgan yoki topilmadi", show_alert=True)
        await _render_order(call, oid)
        return
    order, bonus = res
    await call.answer("Bajarildi deb belgilandi")
    await _render_order(call, oid)
    with contextlib.suppress(Exception):
        await call.bot.send_message(order["user_id"], card(
            "done", f"Buyurtma #{order['id']} bajarildi",
            f"{esc(order['detail'])} muvaffaqiyatli yetkazildi.",
            "",
            "Xaridingiz uchun rahmat! Yana kutib qolamiz.",
        ))
    if bonus:
        with contextlib.suppress(Exception):
            await call.bot.send_message(bonus[0], card(
                "bonus", "Referal bonusi",
                f"Taklif qilgan do'stingiz xarid qildi: <b>+{await price(bonus[1])}</b> balansingizga qo'shildi.",
            ))


@router.callback_query(F.data.regexp(r"^order_cancel:\d+$"))
async def order_cancel(call: CallbackQuery):
    oid = int(call.data.split(":")[1])
    order = await db.get_order(oid)
    if order and provider_locked(order):
        await call.answer("Buyurtma API orqali bajarilmoqda — kuting", show_alert=True)
        return
    order = await db.cancel_order(oid)
    if order is None:
        await call.answer("Allaqachon ko'rib chiqilgan yoki topilmadi", show_alert=True)
        await _render_order(call, oid)
        return
    await call.answer("Bekor qilindi, mablag' qaytarildi")
    await _render_order(call, oid)
    with contextlib.suppress(Exception):
        await call.bot.send_message(order["user_id"], card(
            "cancel", f"Buyurtma #{order['id']} bekor qilindi",
            f"{esc(order['detail'])}",
            "",
            "Buyurtma admin tomonidan bekor qilindi. To'langan mablag' balansingizga to'liq qaytarildi.",
            "Savollaringiz bo'lsa, «Murojaat» orqali yozing.",
        ))


@router.callback_query(F.data.regexp(r"^order_retry:\d+$"))
async def order_retry(call: CallbackQuery, bot: Bot):
    oid = int(call.data.split(":")[1])
    await call.answer("API ga yuborilmoqda…")
    result = await fulfillment.fulfill(bot, oid)
    await call.message.answer(note("api", f"Buyurtma #{oid}: {_RETRY_RESULT.get(result, result)}"))
    await _render_order(call, oid)


# ==================== hisob to'ldirishni tasdiqlash ====================

@router.callback_query(F.data.regexp(r"^topup_ok:\d+$"))
async def topup_ok(call: CallbackQuery):
    tx = await db.approve_topup(int(call.data.split(":")[1]))
    if tx is None:
        await call.answer("Allaqachon ko'rib chiqilgan yoki topilmadi", show_alert=True)
        return
    user = await db.get_user(tx["user_id"])
    await call.answer("Tasdiqlandi")
    await edit_card(call, await topup_card(tx, user, f"{em('done')} <b>TASDIQLANDI</b>"))
    with contextlib.suppress(Exception):
        await call.bot.send_message(tx["user_id"], card(
            "done", "Hisob to'ldirildi",
            f"{em('topup')} Balansingizga <b>+{await price(tx['amount'])}</b> qo'shildi.",
            f"{em('money')} Joriy balans: <b>{await price((await db.get_user(tx['user_id']))['balance'])}</b>",
            "",
            "Endi Stars yoki Premium xarid qilishingiz mumkin.",
        ))


@router.callback_query(F.data.regexp(r"^topup_no:\d+$"))
async def topup_no(call: CallbackQuery):
    tx = await db.reject_topup(int(call.data.split(":")[1]))
    if tx is None:
        await call.answer("Allaqachon ko'rib chiqilgan yoki topilmadi", show_alert=True)
        return
    user = await db.get_user(tx["user_id"])
    await call.answer("Rad etildi")
    await edit_card(call, await topup_card(tx, user, f"{em('cancel')} <b>RAD ETILDI</b>"))
    with contextlib.suppress(Exception):
        await call.bot.send_message(tx["user_id"], card(
            "cancel", f"So'rov #{tx['id']} rad etildi",
            f"Summa: {await price(tx['amount'])}",
            "",
            "Chek tasdiqlanmadi: to'lov topilmadi yoki ma'lumotlar mos kelmadi.",
            "To'lov qilgan bo'lsangiz, «Murojaat» orqali chek bilan adminga yozing.",
        ))


# Har bir kiritish holatida matn bo'lmagan xabar kelsa (eng oxirida ro'yxatdan o'tkaziladi)
@router.message(AdminSettings.waiting_stars_prices)
@router.message(AdminSettings.waiting_premium_prices)
@router.message(AdminSettings.waiting_currency)
@router.message(AdminSettings.waiting_referral_percent)
@router.message(AdminSettings.waiting_card_number)
@router.message(AdminSettings.waiting_card_holder)
@router.message(AdminSettings.waiting_add_admin)
@router.message(AdminChannel.waiting_add)
async def text_expected(message: Message, state: FSMContext):
    await invalid(message, state, "Iltimos, matn ko'rinishida yuboring.")
