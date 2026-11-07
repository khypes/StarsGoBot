import asyncio
import json
import re

from aiogram import Router, F, Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery

import database.db as db
from emojis import em
from handlers.user import cmd_start
from keyboards.admin_kb import (
    admin_panel_kb, system_settings_kb, order_action_kb, channels_kb,
)
from keyboards.user_kb import main_menu, back_menu
from states.states import (
    AdminNav, AdminSettings, AdminBroadcast, AdminUserManage, AdminChannel, AdminEmoji,
)
from texts import order_card, topup_card
from ui import Btn, AnyBtn, IsAdmin, card, note, esc, price, currency

router = Router()
# Barcha admin handlerlari faqat adminlar uchun. Oddiy foydalanuvchi hodisalari bu routerdan
# o'tib, user routerga tushadi (shuning uchun admin handlerlari boshqalarning xabarini yutib yubormaydi).
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())

ADMIN_STATES = StateFilter(
    AdminNav, AdminSettings, AdminBroadcast, AdminUserManage, AdminChannel, AdminEmoji
)


# ==================== navigatsiya ====================

async def go_panel(message: Message, state: FSMContext, text: str | None = None):
    await state.clear()
    await state.set_state(AdminNav.panel)
    await message.answer(
        text or card("panel", "Admin panel", "Kerakli bo'limni tanlang."),
        reply_markup=admin_panel_kb(),
    )


async def go_settings(message: Message, state: FSMContext, text: str | None = None):
    await state.clear()
    await state.set_state(AdminNav.settings)
    await message.answer(
        text or card("settings", "Sozlamalar", "Boshqariladigan bo'limni tanlang."),
        reply_markup=system_settings_kb(),
    )


async def prompt(message: Message, state: FSMContext, new_state, back: str, text: str):
    """Qiymat kutish holatiga o'tadi. `back` — Orqaga bosilganda qayerga qaytish ('panel'/'settings')."""
    await state.set_state(new_state)
    await state.update_data(back=back)
    await message.answer(text, reply_markup=back_menu())


async def edit_card(call: CallbackQuery, text: str):
    """Xabar matnini yoki (chek rasmi bo'lsa) captionni yangilaydi; tugmalar olib tashlanadi."""
    try:
        if call.message.text is not None:
            await call.message.edit_text(text)
        else:
            await call.message.edit_caption(caption=text)
    except TelegramBadRequest:
        pass


@router.message(CommandStart(), ADMIN_STATES)
async def admin_start(message: Message, state: FSMContext, bot: Bot):
    """Admin biror kiritish holatida /start bossa — holat tozalanib, bosh menyu ochiladi."""
    await cmd_start(message, state, bot)


PROMPT_STATES = StateFilter(AdminSettings, AdminBroadcast, AdminUserManage, AdminChannel, AdminEmoji)


@router.message(PROMPT_STATES, AnyBtn("stars", "premium", "orders", "account", "topup", "referral", "appeal", "guide"))
async def admin_leaves_prompt(message: Message, state: FSMContext):
    """Admin kiritish holatida oddiy menyu tugmasini bossa, tugma matni qiymat sifatida saqlanib qolmasin."""
    await state.clear()
    await message.answer(note("home", "Bosh menyu. Bo'limni qayta tanlang."), reply_markup=main_menu(True))


@router.message(Btn("panel"))
async def open_admin_panel(message: Message, state: FSMContext):
    await go_panel(message, state)


@router.message(Btn("back"), ADMIN_STATES)
async def admin_back(message: Message, state: FSMContext):
    cur = await state.get_state()
    data = await state.get_data()
    if cur == AdminNav.panel.state:
        await state.clear()
        await message.answer(note("home", "Bosh menyu"), reply_markup=main_menu(True))
    elif cur == AdminNav.settings.state or data.get("back") == "settings":
        if cur == AdminNav.settings.state:
            await go_panel(message, state)
        else:
            await go_settings(message, state, note("cancel", "Bekor qilindi."))
    else:
        await go_panel(message, state, note("cancel", "Bekor qilindi."))


# ==================== Statistika ====================

@router.message(Btn("stats"))
async def stats(message: Message):
    users = await db.user_count()
    total, revenue, pending = await db.order_stats()
    await message.answer(card(
        "stats", "Statistika",
        f"{em('people')} Foydalanuvchilar: <b>{users}</b>",
        f"{em('done')} Bajarilgan buyurtmalar: <b>{total}</b>",
        f"{em('pending')} Kutilayotgan buyurtmalar: <b>{pending}</b>",
        f"{em('money')} Umumiy tushum: <b>{await price(revenue)}</b>",
    ))


# ==================== Xabar yuborish (broadcast) ====================

@router.message(Btn("broadcast"))
async def broadcast_start(message: Message, state: FSMContext):
    await prompt(message, state, AdminBroadcast.waiting_message, "panel", card(
        "broadcast", "Xabar yuborish",
        "Barcha foydalanuvchilarga yubormoqchi bo'lgan xabaringizni yuboring (matn, rasm, video...).",
    ))


@router.message(AdminBroadcast.waiting_message)
async def broadcast_send(message: Message, state: FSMContext):
    await state.clear()
    user_ids = await db.all_user_ids()
    sent = failed = 0
    status_msg = await message.answer(note("pending", f"Yuborilmoqda... 0/{len(user_ids)}"))
    for i, uid in enumerate(user_ids, 1):
        for attempt in range(2):
            try:
                await message.copy_to(uid)
                sent += 1
                break
            except TelegramRetryAfter as e:
                await asyncio.sleep(e.retry_after + 1)
            except (TelegramForbiddenError, TelegramBadRequest):
                failed += 1
                break
            except Exception:
                failed += 1
                break
        else:
            failed += 1
        if i % 25 == 0:
            try:
                await status_msg.edit_text(note("pending", f"Yuborilmoqda... {i}/{len(user_ids)}"))
            except Exception:
                pass
        await asyncio.sleep(0.05)
    await go_panel(message, state, card(
        "done", "Xabar yuborildi", f"Muvaffaqiyatli: <b>{sent}</b>", f"Xatolik: <b>{failed}</b>",
    ))


# ==================== Foydalanuvchini boshqarish ====================

@router.message(Btn("users"))
async def user_manage_start(message: Message, state: FSMContext):
    await prompt(message, state, AdminUserManage.waiting_user_id, "panel", card(
        "users", "Foydalanuvchini boshqarish",
        "ID raqam yoki @username yuboring.",
        "",
        "Topilgach:",
        "<code>+50000</code> — balansni oshirish",
        "<code>-50000</code> — balansni kamaytirish",
        "/ban — bloklash, /unban — blokdan chiqarish",
    ))


async def _target(message: Message, state: FSMContext):
    uid = (await state.get_data()).get("target_user_id")
    if not uid:
        await message.answer(note("warn", "Avval foydalanuvchi ID yoki @username yuboring."))
    return uid


@router.message(AdminUserManage.waiting_user_id, Command("ban"))
async def user_manage_ban(message: Message, state: FSMContext):
    uid = await _target(message, state)
    if uid:
        await db.set_ban(uid, True)
        await message.answer(note("ban", f"Foydalanuvchi <code>{uid}</code> bloklandi."))


@router.message(AdminUserManage.waiting_user_id, Command("unban"))
async def user_manage_unban(message: Message, state: FSMContext):
    uid = await _target(message, state)
    if uid:
        await db.set_ban(uid, False)
        await message.answer(note("done", f"Foydalanuvchi <code>{uid}</code> blokdan chiqarildi."))


@router.message(AdminUserManage.waiting_user_id, F.text.regexp(r"^[+-]\s*\d+$"))
async def user_manage_balance(message: Message, state: FSMContext):
    uid = await _target(message, state)
    if not uid:
        return
    text = message.text.replace(" ", "")
    delta = int(text)  # "+500" va "-500" ikkalasi ham int() da ishlaydi
    if not await db.adjust_balance(uid, delta):
        await message.answer(note("warn", "Foydalanuvchi topilmadi."))
        return
    await db.create_transaction(
        uid, delta, "admin_adjust", note=f"admin {message.from_user.id}", status="tasdiqlandi"
    )
    user = await db.get_user(uid)
    await message.answer(note("done", f"Bajarildi. Yangi balans: <b>{await price(user['balance'])}</b>"))


@router.message(AdminUserManage.waiting_user_id, F.text)
async def user_manage_lookup(message: Message, state: FSMContext):
    text = message.text.strip()
    if text.startswith("@"):
        user = await db.get_user_by_username(text)
    elif text.isascii() and text.isdigit():
        user = await db.get_user(int(text))
    else:
        await message.answer(note("warn", "ID raqam yoki @username yuboring."))
        return
    if not user:
        await message.answer(note("cancel", "Bunday foydalanuvchi topilmadi."))
        return
    uid = user["user_id"]
    banned = "Ha" if user["is_banned"] else "Yo'q"
    await state.update_data(target_user_id=uid)
    await message.answer(card(
        "account", "Foydalanuvchi ma'lumotlari",
        f"{em('id')} ID: <code>{uid}</code>",
        f"{em('account')} Ism: {esc(user['full_name'])}",
        f"{em('link')} Username: {('@' + esc(user['username'])) if user['username'] else '—'}",
        f"{em('money')} Balans: <b>{await price(user['balance'])}</b>",
        f"{em('ban')} Bloklangan: {banned}",
        f"{em('people')} Referallar: {await db.referral_count(uid)}",
    ))


@router.message(AdminUserManage.waiting_user_id)
async def user_manage_invalid(message: Message):
    await message.answer(note("warn", "ID raqam yoki @username yuboring."))


# ==================== To'lov tizimi ====================

@router.message(Btn("payment"))
async def payment_system(message: Message, state: FSMContext):
    card_no = await db.get_setting("card_number")
    ton = await db.get_setting("ton_wallet")
    await prompt(message, state, AdminSettings.waiting_card_number, "panel", card(
        "payment", "To'lov tizimi",
        f"Joriy karta: <code>{esc(card_no) or 'kiritilmagan'}</code>",
        f"Joriy TON hamyon: <code>{esc(ton) or 'kiritilmagan'}</code>",
        "",
        "Yangi karta raqamini yuboring (TON hamyon «Sozlamalar» bo'limida).",
    ))


@router.message(AdminSettings.waiting_card_number, F.text)
async def payment_set_card(message: Message, state: FSMContext):
    await db.set_setting("card_number", message.text.strip())
    await go_panel(message, state, note("done", "Karta raqami yangilandi."))


# ==================== Kanallar (majburiy obuna) ====================

async def _channels_text() -> str:
    channels = await db.list_channels()
    if channels:
        lines = [f"<b>#{c['id']}</b> · {esc(c['title'])} <code>{esc(c['chat_id'])}</code>" for c in channels]
        lines += ["", "O'chirish uchun kanal nomini bosing."]
    else:
        lines = ["Hozircha majburiy obuna kanallari yo'q."]
    return card("channels", "Majburiy obuna kanallari", *lines)


@router.message(Btn("channels"))
async def channels_menu(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(AdminNav.panel)
    await message.answer(await _channels_text(), reply_markup=channels_kb(await db.list_channels()))


@router.callback_query(F.data == "ch:add")
async def channel_add_start(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await prompt(call.message, state, AdminChannel.waiting_add, "panel", card(
        "plus", "Kanal qo'shish",
        "Kanal usernamesini yuboring: <code>@kanal</code>",
        "Maxfiy kanal uchun: <code>-100123456789 | https://t.me/+havola</code>",
        "",
        "Bot kanalda administrator bo'lishi kerak.",
    ))


@router.message(AdminChannel.waiting_add, F.text)
async def channel_add(message: Message, state: FSMContext, bot: Bot):
    parts = [p.strip() for p in message.text.split("|")]
    ref, url = parts[0], (parts[1] if len(parts) > 1 else "")
    if not (ref.startswith("@") or re.fullmatch(r"-?\d+", ref)):
        await message.answer(note("warn", "Format noto'g'ri. Masalan: <code>@kanal</code>"))
        return
    try:
        chat = await bot.get_chat(ref)
    except Exception:
        await message.answer(note("warn", "Kanal topilmadi. Bot kanalga qo'shilganini tekshiring."))
        return
    if not url:
        if not chat.username:
            await message.answer(note("warn", "Maxfiy kanal uchun havola ham kerak: <code>ID | https://t.me/+...</code>"))
            return
        url = f"https://t.me/{chat.username}"
    warning = ""
    try:
        me = await bot.get_me()
        member = await bot.get_chat_member(chat.id, me.id)
        if member.status not in ("administrator", "creator"):
            warning = "\n" + em("warn") + " Bot kanalda administrator emas — obunani tekshira olmaydi."
    except Exception:
        warning = "\n" + em("warn") + " Botning kanaldagi huquqlarini tekshirib bo'lmadi."
    await db.add_channel(str(chat.id), chat.title or ref, url)
    await state.clear()
    await state.set_state(AdminNav.panel)
    await message.answer(
        note("done", f"Kanal qo'shildi: {esc(chat.title or ref)}") + warning,
        reply_markup=admin_panel_kb(),
    )
    await message.answer(await _channels_text(), reply_markup=channels_kb(await db.list_channels()))


@router.callback_query(F.data.startswith("ch:del:"))
async def channel_remove(call: CallbackQuery):
    try:
        await db.remove_channel(int(call.data.split(":")[2]))
    except (ValueError, IndexError):
        pass
    await call.answer("Kanal o'chirildi")
    try:
        await call.message.edit_text(await _channels_text(), reply_markup=channels_kb(await db.list_channels()))
    except TelegramBadRequest:
        pass


# ==================== Tizim sozlamalari ====================

@router.message(Btn("settings"))
async def system_settings(message: Message, state: FSMContext):
    await go_settings(message, state)


@router.message(Btn("currency"))
async def currency_start(message: Message, state: FSMContext):
    await prompt(message, state, AdminSettings.waiting_currency, "settings", card(
        "currency", "Valyuta", f"Joriy: <b>{esc(await currency())}</b>",
        "Yangi valyuta belgisini yuboring (masalan: <code>so'm</code>).",
    ))


@router.message(AdminSettings.waiting_currency, F.text)
async def currency_set(message: Message, state: FSMContext):
    value = message.text.strip()
    if not value or len(value) > 12:
        await message.answer(note("warn", "Valyuta belgisi 1–12 belgidan iborat bo'lsin."))
        return
    await db.set_setting("currency", value)
    await go_settings(message, state, note("done", "Valyuta yangilandi."))


@router.message(Btn("ref_percent"))
async def referral_percent_start(message: Message, state: FSMContext):
    await prompt(message, state, AdminSettings.waiting_referral_percent, "settings", card(
        "ref_percent", "Referal foizi",
        f"Joriy: <b>{esc(await db.get_setting('referral_percent'))}%</b>",
        "Yangi foizni yuboring (0–100).",
    ))


@router.message(AdminSettings.waiting_referral_percent, F.text)
async def referral_percent_set(message: Message, state: FSMContext):
    raw = message.text.strip()
    if not (raw.isascii() and raw.isdigit()) or not (0 <= int(raw) <= 100):
        await message.answer(note("warn", "0 dan 100 gacha butun son kiriting."))
        return
    await db.set_setting("referral_percent", str(int(raw)))
    await go_settings(message, state, note("done", "Referal foizi yangilandi."))


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


async def _prices_start(message, state, kind: str):
    if kind == "stars":
        current, field, st, title, key = await db.get_stars_prices(), "stars", AdminSettings.waiting_stars_prices, "Stars narxlari", "stars_prices"
        example = "100=20000"
    else:
        current, field, st, title, key = await db.get_premium_prices(), "months", AdminSettings.waiting_premium_prices, "Premium narxlari", "premium_prices"
        example = "3=155000"
    lines = [f"<code>{p[field]}={p['price']}</code>" for p in current]
    await prompt(message, state, st, "settings", card(
        key, title, *lines, "",
        f"Yangi ro'yxatni har qatorga bittadan yuboring: <code>{example}</code>",
        f"(chapda {'Stars miqdori' if kind == 'stars' else 'oy soni'}, o'ngda narx). JSON ham qabul qilinadi.",
    ))


@router.message(Btn("stars_prices"))
async def stars_prices_start(message: Message, state: FSMContext):
    await _prices_start(message, state, "stars")


@router.message(Btn("premium_prices"))
async def premium_prices_start(message: Message, state: FSMContext):
    await _prices_start(message, state, "premium")


@router.message(AdminSettings.waiting_stars_prices, F.text)
async def stars_prices_set(message: Message, state: FSMContext):
    data = parse_prices(message.text, "stars")
    if data is None:
        await message.answer(note("warn", "Format noto'g'ri. Masalan: <code>100=20000</code> (har qatorda bittadan)."))
        return
    await db.set_setting("stars_prices", json.dumps(data, ensure_ascii=False))
    await go_settings(message, state, note("done", "Stars narxlari yangilandi."))


@router.message(AdminSettings.waiting_premium_prices, F.text)
async def premium_prices_set(message: Message, state: FSMContext):
    data = parse_prices(message.text, "months")
    if data is None:
        await message.answer(note("warn", "Format noto'g'ri. Masalan: <code>3=155000</code> (har qatorda bittadan)."))
        return
    await db.set_setting("premium_prices", json.dumps(data, ensure_ascii=False))
    await go_settings(message, state, note("done", "Premium narxlari yangilandi."))


@router.message(Btn("notify"))
async def toggle_notify(message: Message, state: FSMContext):
    new_val = "0" if (await db.get_setting("order_notify")) == "1" else "1"
    await db.set_setting("order_notify", new_val)
    status = "yoqildi" if new_val == "1" else "o'chirildi"
    await message.answer(note("notify", f"Buyurtma bildirishnomasi {status}."))


@router.message(Btn("ton"))
async def ton_wallet_start(message: Message, state: FSMContext):
    current = await db.get_setting("ton_wallet")
    await prompt(message, state, AdminSettings.waiting_ton_wallet, "settings", card(
        "ton", "TON hamyon", f"Joriy: <code>{esc(current) or 'kiritilmagan'}</code>",
        "Yangi manzilni yuboring.",
    ))


@router.message(AdminSettings.waiting_ton_wallet, F.text)
async def ton_wallet_set(message: Message, state: FSMContext):
    await db.set_setting("ton_wallet", message.text.strip())
    await go_settings(message, state, note("done", "TON hamyon yangilandi."))


@router.message(Btn("admins"))
async def admins_menu(message: Message, state: FSMContext):
    admins = await db.list_admins()
    await prompt(message, state, AdminSettings.waiting_add_admin, "settings", card(
        "admins", "Adminlar",
        *[f"• <code>{a}</code>" for a in admins], "",
        "Qo'shish: <code>+ID</code>, o'chirish: <code>-ID</code>",
    ))


@router.message(AdminSettings.waiting_add_admin, F.text.regexp(r"^[+-]\s*\d+$"))
async def admin_edit(message: Message):
    text = message.text.replace(" ", "")
    uid = int(text[1:])
    if text[0] == "+":
        await db.add_admin(uid)
        await message.answer(note("done", f"<code>{uid}</code> admin sifatida qo'shildi."))
    elif await db.remove_admin(uid):
        await message.answer(note("done", f"<code>{uid}</code> adminlikdan chiqarildi."))
    else:
        await message.answer(note("warn", "Bosh adminni o'chirib bo'lmaydi."))


@router.message(AdminSettings.waiting_add_admin)
async def admin_edit_invalid(message: Message):
    await message.answer(note("warn", "Format: <code>+ID</code> yoki <code>-ID</code>"))


# ==================== Buyurtmalarni tasdiqlash ====================

@router.callback_query(F.data.startswith("order_done:"))
async def order_done(call: CallbackQuery):
    res = await db.complete_order(int(call.data.split(":")[1]))
    if res is None:
        await call.answer("Allaqachon ko'rib chiqilgan yoki topilmadi", show_alert=True)
        return
    order, bonus = res
    user = await db.get_user(order["user_id"])
    await call.answer("Bajarildi deb belgilandi")
    await edit_card(call, await order_card(order, user, f"{em('done')} <b>BAJARILDI</b>"))
    try:
        await call.bot.send_message(order["user_id"], card(
            "done", f"Buyurtma #{order['id']} bajarildi",
            f"{esc(order['detail'])} muvaffaqiyatli yetkazildi!",
        ))
    except Exception:
        pass
    if bonus:
        try:
            await call.bot.send_message(bonus[0], card(
                "bonus", "Referal bonusi",
                f"Taklif qilgan do'stingiz xarid qildi: <b>+{await price(bonus[1])}</b> balansingizga qo'shildi.",
            ))
        except Exception:
            pass


@router.callback_query(F.data.startswith("order_cancel:"))
async def order_cancel(call: CallbackQuery):
    order = await db.cancel_order(int(call.data.split(":")[1]))
    if order is None:
        await call.answer("Allaqachon ko'rib chiqilgan yoki topilmadi", show_alert=True)
        return
    user = await db.get_user(order["user_id"])
    await call.answer("Bekor qilindi, mablag' qaytarildi")
    await edit_card(call, await order_card(
        order, user, f"{em('cancel')} <b>BEKOR QILINDI</b> (mablag' qaytarildi)"))
    try:
        await call.bot.send_message(order["user_id"], card(
            "cancel", f"Buyurtma #{order['id']} bekor qilindi",
            f"{esc(order['detail'])}",
            "Mablag' balansingizga qaytarildi.",
        ))
    except Exception:
        pass


# ==================== Hisob to'ldirishni tasdiqlash ====================

@router.callback_query(F.data.startswith("topup_ok:"))
async def topup_ok(call: CallbackQuery):
    tx = await db.approve_topup(int(call.data.split(":")[1]))
    if tx is None:
        await call.answer("Allaqachon ko'rib chiqilgan yoki topilmadi", show_alert=True)
        return
    user = await db.get_user(tx["user_id"])
    await call.answer("Tasdiqlandi")
    await edit_card(call, await topup_card(tx, user, f"{em('done')} <b>TASDIQLANDI</b>"))
    try:
        await call.bot.send_message(tx["user_id"], card(
            "done", "Hisob to'ldirildi", f"<b>+{await price(tx['amount'])}</b> balansingizga qo'shildi!",
        ))
    except Exception:
        pass


@router.callback_query(F.data.startswith("topup_no:"))
async def topup_no(call: CallbackQuery):
    tx = await db.reject_topup(int(call.data.split(":")[1]))
    if tx is None:
        await call.answer("Allaqachon ko'rib chiqilgan yoki topilmadi", show_alert=True)
        return
    user = await db.get_user(tx["user_id"])
    await call.answer("Rad etildi")
    await edit_card(call, await topup_card(tx, user, f"{em('cancel')} <b>RAD ETILDI</b>"))
    try:
        await call.bot.send_message(tx["user_id"], card(
            "cancel", f"So'rov #{tx['id']} rad etildi",
            "Savollaringiz bo'lsa, «Murojaat» orqali yozing.",
        ))
    except Exception:
        pass
