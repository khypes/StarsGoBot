import contextlib
import re

from aiogram import Router, F, Bot
from aiogram.filters import CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, ReplyKeyboardRemove, InlineKeyboardMarkup

import database.db as db
import fulfillment
from config import ADMIN_CHAT_ID, MAX_TOPUP
from emojis import em, ibtn
from keyboards.admin_kb import topup_action_kb
from keyboards.user_kb import (
    main_menu, back_kb, stars_prices_kb, premium_prices_kb, uc_prices_kb, channels_check_kb,
    recipient_kb, confirm_kb,
)
from middlewares import missing_channels, forget
from nav import show, ask, invalid, finish, render_input, cancel_kb
from states.states import Purchase, TopUp, Appeal
from texts import topup_card
from ui import card, note, esc, fmt_num, price, currency

router = Router()
router.message.filter(F.chat.type == "private")

USERNAME_RE = re.compile(r"^@?([A-Za-z][A-Za-z0-9_]{4,31})$")
_buying: set[int] = set()  # bir foydalanuvchining parallel xaridlariga qarshi


# ==================== ekranlar (view) ====================

async def home_view(user_id: int, full_name: str):
    user = await db.get_user(user_id)
    uc_on = await db.uc_enabled()
    text = card(
        "wave", f"Assalomu alaykum, {esc(full_name)}!",
        f"{em('rocket')} StarsGo orqali Telegram Stars, Premium" + (" va PUBG Mobile UC" if uc_on else "")
        + " ni tez va qulay sotib olasiz.",
        "",
        f"{em('topup')} Balansingiz: <b>{await price(user['balance'] if user else 0)}</b>",
        "",
        f"{em('stars')} <b>Stars olish</b> — o'zingizga yoki do'stingizga",
        f"{em('premium')} <b>Premium olish</b> — 3, 6 yoki 12 oylik obuna",
        *([f"{em('uc')} <b>UC olish</b> — PUBG Mobile, Player ID orqali"] if uc_on else []),
        f"{em('topup')} <b>Hisob to'ldirish</b> — xaridlar uchun balans",
        "",
        f"{em('down')} Davom etish uchun bo'limni tanlang:",
    )
    return text, main_menu(await db.is_admin(user_id), uc_on)


async def account_view(user_id: int):
    user = await db.get_user(user_id)
    text = card(
        "account", "Mening hisobim",
        f"{em('id')} Telegram ID: <code>{user_id}</code>",
        f"{em('topup')} Balans: <b>{await price(user['balance'])}</b>",
        f"{em('orders')} Buyurtmalar soni: <b>{await db.user_order_count(user_id)}</b>",
        f"{em('people')} Taklif qilgan do'stlar: <b>{await db.referral_count(user_id)}</b>",
        "",
        f"{em('info')} Balans — bot ichidagi hisobingiz. Stars va Premium xaridlari shu balansdan to'lanadi.",
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [ibtn("topup", "Hisob to'ldirish", callback_data="m:topup"),
         ibtn("orders", "Buyurtmalarim", callback_data="m:orders")],
        [ibtn("back", "Orqaga", callback_data="m:home")],
    ])
    return text, kb


async def orders_view(user_id: int):
    orders = await db.user_orders(user_id, 10)
    if not orders:
        return card(
            "inbox", "Buyurtmalarim",
            "Sizda hali buyurtmalar yo'q.",
            "Birinchi buyurtmani «Stars olish» yoki «Premium olish» bo'limidan bering.",
        ), back_kb()
    icons = {"kutilmoqda": "pending", "bajarildi": "done", "bekor qilindi": "cancel"}
    words = {"kutilmoqda": "kutilmoqda", "bajarildi": "bajarildi", "bekor qilindi": "bekor qilindi, pul qaytarilgan"}
    cur = await currency()
    lines = ["Oxirgi buyurtmalaringiz:", ""]
    for o in orders:
        icon = em(icons.get(o["status"], "pending"))
        lines.append(f"{icon} <b>#{o['id']}</b> · {esc(o['detail'])}")
        lines.append(f"      {fmt_num(o['price'])} {cur} · {esc(words.get(o['status'], o['status']))}")
    lines += [
        "",
        f"{em('info')} Buyurtma yetkazilishi bilan sizga alohida xabar keladi.",
    ]
    return card("orders", "Buyurtmalarim", *lines, expandable=len(orders) > 4), back_kb()


_me = None


async def _bot_username(bot: Bot) -> str:
    global _me
    if _me is None:
        _me = await bot.get_me()
    return _me.username


async def referral_view(bot: Bot, user_id: int):
    link = f"https://t.me/{await _bot_username(bot)}?start=ref_{user_id}"
    percent = await db.get_setting("referral_percent") or "0"
    text = card(
        "referral", "Referal dasturi",
        "Do'stlaringizni taklif qiling va ularning xaridlaridan bonus oling.",
        "",
        f"{em('link')} Sizning havolangiz:\n{link}",
        "",
        f"{em('people')} Taklif qilgan do'stlaringiz: <b>{await db.referral_count(user_id)}</b> ta",
        "",
        "<b>Qanday ishlaydi:</b>",
        "1. Havolani do'stingizga yuboring.",
        "2. Do'stingiz havola orqali botga kirib, birinchi xaridini qiladi.",
        f"3. Buyurtma bajarilgach, narxning <b>{esc(percent)}%</b> miqdorida bonus sizning balansingizga tushadi.",
    )
    return text, back_kb()


def guide_view():
    text = card(
        "guide", "Qo'llanma",
        "<b>Qanday xarid qilinadi?</b>",
        f"1. «Hisob to'ldirish» orqali balansni to'ldiring.",
        f"2. «Stars olish» yoki «Premium olish» bo'limini oching.",
        "3. Paketni tanlang va qabul qiluvchi usernamesini kiriting.",
        "4. Ma'lumotlarni tekshirib, «Tasdiqlash» tugmasini bosing.",
        "5. Buyurtma yetkazilgach sizga xabar keladi.",
        "",
        f"{em('stars')} <b>Stars</b> — Telegram ichidagi virtual valyuta. O'zingizga yoki boshqa akkauntga yuborish mumkin.",
        "",
        f"{em('premium')} <b>Premium</b> — Telegram Premium obunasi (3, 6 yoki 12 oy). Qabul qiluvchining akkauntida yoqiladi.",
        "",
        f"{em('uc')} <b>UC</b> — PUBG Mobile valyutasi. O'yindagi Player ID ni kiritasiz, UC akkauntingizga tushadi.",
        "",
        f"{em('topup')} <b>Hisob to'ldirish</b> — kartaga to'lov qilib, chekni yuborasiz. Admin tasdiqlagach mablag' balansga tushadi.",
        "",
        f"{em('referral')} <b>Referal</b> — do'stingiz birinchi xarid qilsa, siz bonus olasiz.",
        "",
        f"{em('info')} Muammo bo'lsa, «Murojaat» orqali adminga yozing.",
        expandable=True,
    )
    return text, back_kb()


# ==================== /start ====================

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, bot: Bot):
    await state.clear()
    parts = (message.text or "").split(maxsplit=1)
    referrer_id = None
    if len(parts) > 1 and parts[1].startswith("ref_"):
        try:
            referrer_id = int(parts[1][4:])
        except ValueError:
            referrer_id = None

    uid = message.from_user.id
    await db.create_user_if_not_exists(
        uid, message.from_user.username or "", message.from_user.full_name or "", referrer_id
    )

    # Eski (reply) klaviatura qolib ketgan bo'lsa — olib tashlaymiz
    try:
        tmp = await message.answer("⏳", reply_markup=ReplyKeyboardRemove())
        await tmp.delete()
    except Exception:
        pass

    if not await db.is_admin(uid):
        missing = await missing_channels(bot, uid)
        if missing:
            await message.answer(
                card("megaphone", "Majburiy obuna",
                     "Botdan foydalanish uchun quyidagi kanallarga obuna bo'lishingiz kerak.",
                     "",
                     "Obuna bo'lgach, «Tekshirish» tugmasini bosing."),
                reply_markup=channels_check_kb(missing),
            )
            return
    text, kb = await home_view(uid, message.from_user.full_name)
    await message.answer(text, reply_markup=kb)


@router.callback_query(F.data == "check_subs")
async def cb_check_subs(call: CallbackQuery, bot: Bot):
    forget(call.from_user.id)
    if await missing_channels(bot, call.from_user.id):
        await call.answer("Hali barcha kanallarga obuna bo'lmagansiz.", show_alert=True)
        return
    await call.answer("Obuna tasdiqlandi, xush kelibsiz!")
    await show(call, *await home_view(call.from_user.id, call.from_user.full_name))


# ==================== menyu (hammasi inline, joyida tahrirlanadi) ====================

@router.callback_query(F.data == "m:home")
async def cb_home(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.answer()
    await show(call, *await home_view(call.from_user.id, call.from_user.full_name))


@router.callback_query(F.data == "m:account")
async def cb_account(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.answer()
    await show(call, *await account_view(call.from_user.id))


@router.callback_query(F.data == "m:orders")
async def cb_orders(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.answer()
    await show(call, *await orders_view(call.from_user.id))


@router.callback_query(F.data == "m:ref")
async def cb_referral(call: CallbackQuery, state: FSMContext, bot: Bot):
    await state.clear()
    await call.answer()
    await show(call, *await referral_view(bot, call.from_user.id))


@router.callback_query(F.data == "m:guide")
async def cb_guide(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.answer()
    await show(call, *guide_view())


@router.callback_query(F.data == "m:stars")
async def cb_stars(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.answer()
    prices = await db.get_stars_prices()
    if not prices:
        await show(call, card("inbox", "Stars olish", "Hozircha paketlar mavjud emas. Keyinroq urinib ko'ring."), back_kb())
        return
    await show(
        call,
        card("stars", "Stars olish — 1/3",
             "Kerakli Stars miqdorini tanlang. Narx tugmada ko'rsatilgan.",
             "",
             f"{em('info')} Keyingi qadamlarda qabul qiluvchini kiritasiz va buyurtmani tasdiqlaysiz. "
             "Pul faqat tasdiqlagandan keyin balansdan yechiladi."),
        stars_prices_kb(prices, await currency()),
    )


@router.callback_query(F.data == "m:premium")
async def cb_premium(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.answer()
    prices = await db.get_premium_prices()
    if not prices:
        await show(call, card("inbox", "Premium olish", "Hozircha tariflar mavjud emas. Keyinroq urinib ko'ring."), back_kb())
        return
    await show(
        call,
        card("premium", "Premium olish — 1/3",
             "Telegram Premium obunasi muddatini tanlang. Uzoq muddatli tarif odatda arzonroq.",
             "",
             f"{em('info')} Keyingi qadamlarda qabul qiluvchini kiritasiz va buyurtmani tasdiqlaysiz. "
             "Pul faqat tasdiqlagandan keyin balansdan yechiladi."),
        premium_prices_kb(prices, await currency()),
    )


# ==================== Murojaat ====================

@router.callback_query(F.data == "m:appeal")
async def cb_appeal(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await ask(call, state, Appeal.waiting_message, card(
        "pencil", "Murojaat",
        "Savol, taklif yoki muammoingizni yozib yuboring. Matn, rasm yoki fayl yuborishingiz mumkin.",
        "",
        f"{em('info')} Murojaat adminga yetkaziladi. Admin ko'rib chiqib, siz bilan bog'lanadi.",
    ), back="m:home")


@router.message(Appeal.waiting_message)
async def appeal_receive(message: Message, state: FSMContext, bot: Bot):
    if ADMIN_CHAT_ID:
        try:
            await bot.send_message(ADMIN_CHAT_ID, card(
                "appeal", "Yangi murojaat",
                f"{em('account')} {esc(message.from_user.full_name)} "
                f"(ID: <code>{message.from_user.id}</code>)",
            ))
            await bot.forward_message(ADMIN_CHAT_ID, message.chat.id, message.message_id)
        except Exception:
            pass
    await finish(message, state,
                 card("done", "Murojaat yuborildi",
                      "Murojaatingiz adminga yetkazildi.", "Ko'rib chiqilgach siz bilan bog'lanamiz."),
                 back_kb("m:home", "Bosh menyu"))


# ==================== Xarid (Stars / Premium) ====================

_ICON = {"stars": "stars", "premium": "premium", "uc": "uc"}
_BACK = {"stars": "m:stars", "premium": "m:premium", "uc": "m:uc"}
_KIND = {"s": "stars", "p": "premium", "u": "uc"}
PLAYER_RE = re.compile(r"^\d{6,15}$")


async def _catalog_item(kind: str, qty: int):
    if kind == "stars":
        return next((p for p in await db.get_stars_prices() if p["stars"] == qty), None)
    if kind == "uc":
        if not await db.uc_enabled():
            return None
        return next((p for p in await db.get_uc_prices() if p["uc"] == qty), None)
    return next((p for p in await db.get_premium_prices() if p["months"] == qty), None)


def _product_label(kind: str, qty: int, recipient: str | None = None) -> str:
    if kind == "uc":
        base = f"{fmt_num(qty)} UC (PUBG Mobile)"
        return f"{base} → ID {recipient}" if recipient else base
    base = f"{fmt_num(qty)} Stars" if kind == "stars" else f"{qty} oylik Premium"
    return f"{base} → @{recipient}" if recipient else base


# ==================== UC (PUBG Mobile) ro'yxati ====================

@router.callback_query(F.data == "m:uc")
async def cb_uc(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.answer()
    prices = await db.get_uc_prices() if await db.uc_enabled() else []
    if not prices:
        await show(call, card("inbox", "UC olish", "Hozircha UC sotuvi mavjud emas. Keyinroq urinib ko'ring."), back_kb())
        return
    await show(
        call,
        card("uc", "UC olish — 1/3",
             "PUBG Mobile uchun UC miqdorini tanlang. Narx tugmada ko'rsatilgan.",
             "",
             f"{em('info')} Keyingi qadamda o'yindagi Player ID ni kiritasiz va buyurtmani tasdiqlaysiz. "
             "Pul faqat tasdiqlagandan keyin balansdan yechiladi."),
        uc_prices_kb(prices, await currency()),
    )


@router.callback_query(F.data.regexp(r"^b:[spu]:\d+$"))
async def cb_choose_product(call: CallbackQuery, state: FSMContext):
    _, code, raw = call.data.split(":")
    kind, qty = _KIND[code], int(raw)
    item = await _catalog_item(kind, qty)
    if not item:
        await call.answer("Narxlar yangilangan. Ro'yxatni qayta oching.", show_alert=True)
        return
    back = _BACK[kind]
    await call.answer()
    if kind == "uc":
        await ask(
            call, state, Purchase.waiting_player,
            card("uc_player", "Player ID — 2/3",
                 f"{em('uc')} Tanlandi: <b>{_product_label(kind, qty)}</b> · {await price(item['price'])}",
                 "",
                 "PUBG Mobile akkauntingizning <b>Player ID</b> raqamini yuboring (faqat raqamlar).",
                 "O'yinda: profil rasmingiz → ID ko'rsatilgan joy.",
                 "",
                 f"{em('warn')} ID ni diqqat bilan tekshiring: UC noto'g'ri akkauntga tushsa, qaytarib bo'lmaydi."),
            back=back, kb=back_kb(back),
            kind=kind, qty=qty, price=item["price"], product_id=item.get("product_id"),
        )
        return
    own = call.from_user.username
    icon = _ICON[kind]
    own_hint = ("O'zingiz uchun bo'lsa — pastdagi «O'zimga» tugmasini bosing." if own
                else "Telegram usernamengiz yo'q, shuning uchun boshqa akkaunt usernamesini kiriting.")
    await ask(
        call, state, Purchase.waiting_recipient,
        card("account", "Qabul qiluvchi — 2/3",
             f"{em(icon)} Tanlandi: <b>{_product_label(kind, qty)}</b> · {await price(item['price'])}",
             "",
             "Buyurtma qaysi Telegram akkauntga yuborilsin?",
             "Qabul qiluvchining usernamesini yuboring, masalan: <code>@username</code>",
             own_hint,
             "",
             f"{em('info')} Username to'g'ri yozilganini tekshiring — noto'g'ri bo'lsa buyurtma bajarilmasligi mumkin."),
        back=back, kb=recipient_kb(own, back),
        kind=kind, qty=qty, price=item["price"],
    )


async def _confirm_view(user_id: int, data: dict, flash: str | None = None):
    kind, qty, recipient, cost = data["kind"], data["qty"], data["recipient"], data["price"]
    user = await db.get_user(user_id)
    left = user["balance"] - cost
    lines = []
    if flash:
        lines += [flash, ""]
    lines += [
        "Ma'lumotlarni tekshiring:",
        "",
        f"{em(_ICON[kind])} Mahsulot: <b>{_product_label(kind, qty)}</b>",
        (f"{em('uc_player')} Player ID: <code>{esc(recipient)}</code>" if kind == "uc"
         else f"{em('link')} Qabul qiluvchi: <code>@{esc(recipient)}</code>"),
        f"{em('money')} Narxi: <b>{await price(cost)}</b>",
        f"{em('topup')} Balansingiz: {await price(user['balance'])}"
        + (f" → xariddan keyin: <b>{await price(left)}</b>" if left >= 0 else ""),
        "",
    ]
    if left < 0:
        lines.append(f"{em('warn')} Balansingiz yetarli emas ({await price(-left)} yetishmayapti). "
                     "Avval hisobni to'ldiring.")
    else:
        lines.append("«Tasdiqlash» bosilgach summa balansingizdan yechiladi va buyurtma yetkazila boshlaydi.")
    return card("orders", "Buyurtmani tasdiqlang — 3/3", *lines), confirm_kb(await price(cost), _BACK[kind])


@router.message(Purchase.waiting_recipient, F.text)
async def purchase_recipient(message: Message, state: FSMContext):
    m = USERNAME_RE.match(message.text.strip())
    if not m:
        await invalid(message, state, "Username noto'g'ri. U lotin harfidan boshlanib, 5–32 ta harf, raqam yoki _ dan iborat bo'lishi kerak. Masalan: @username")
        return
    await state.update_data(recipient=m.group(1))
    data = await state.get_data()
    await state.set_state(None)  # ma'lumotlar saqlanadi, tasdiqlash tugma orqali
    text, kb = await _confirm_view(message.from_user.id, data)
    await render_input(message, state, text, kb)


@router.message(Purchase.waiting_player, F.text)
async def purchase_player(message: Message, state: FSMContext):
    raw = message.text.strip().replace(" ", "")
    if not PLAYER_RE.match(raw):
        await invalid(message, state, "Player ID noto'g'ri. Faqat raqamlar (6–15 ta) yuboring. Masalan: 5242571586")
        return
    await state.update_data(recipient=raw)
    data = await state.get_data()
    await state.set_state(None)
    text, kb = await _confirm_view(message.from_user.id, data)
    await render_input(message, state, text, kb)


@router.message(Purchase.waiting_player)
async def purchase_player_invalid(message: Message, state: FSMContext):
    await invalid(message, state, "Player ID ni matn (raqam) ko'rinishida yuboring.")


@router.message(Purchase.waiting_recipient)
async def purchase_recipient_invalid(message: Message, state: FSMContext):
    await invalid(message, state, "Iltimos, username'ni matn ko'rinishida yuboring.")


@router.callback_query(F.data == "b:self")
async def cb_self(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if not data.get("kind") or not call.from_user.username:
        await call.answer("Sessiya eskirdi. Qaytadan tanlang.", show_alert=True)
        return
    await state.update_data(recipient=call.from_user.username)
    await state.set_state(None)
    data = await state.get_data()
    await call.answer()
    await show(call, *await _confirm_view(call.from_user.id, data))


@router.callback_query(F.data == "b:ok")
async def cb_confirm(call: CallbackQuery, state: FSMContext, bot: Bot):
    uid = call.from_user.id
    data = await state.get_data()
    if not all(data.get(k) for k in ("kind", "qty", "recipient", "price")):
        await call.answer("Sessiya eskirdi. Qaytadan tanlang.", show_alert=True)
        return
    if uid in _buying:
        await call.answer("Buyurtma bajarilmoqda, kuting…")
        return
    _buying.add(uid)
    try:
        kind, qty, recipient = data["kind"], data["qty"], data["recipient"]
        item = await _catalog_item(kind, qty)
        if not item:
            await state.clear()
            await call.answer("Narxlar yangilangan. Qaytadan tanlang.", show_alert=True)
            await show(call, *await home_view(uid, call.from_user.full_name))
            return
        if item["price"] != data["price"]:
            await state.update_data(price=item["price"])
            data["price"] = item["price"]
            await call.answer("Narx o'zgargan!", show_alert=True)
            await show(call, *await _confirm_view(
                uid, data, flash=f"{em('warn')} <b>Narx yangilandi.</b> Qayta tasdiqlang."))
            return

        cost = item["price"]
        detail = _product_label(kind, qty, recipient)
        order_id = await db.purchase(
            uid, kind, detail, cost, recipient=recipient if kind == "uc" else f"@{recipient}",
            quantity=qty, product_id=item.get("product_id"))
        if order_id is None:
            await call.answer()
            user = await db.get_user(uid)
            bal = user["balance"] if user else 0
            await show(call, card(
                "warn", "Mablag' yetarli emas",
                f"Buyurtma narxi: <b>{await price(cost)}</b>",
                f"Sizning balansingiz: <b>{await price(bal)}</b>",
                f"Yetishmayapti: <b>{await price(max(cost - bal, 0))}</b>",
                "",
                "Hisobni to'ldiring, so'ng buyurtmani qaytadan bering.",
            ), InlineKeyboardMarkup(inline_keyboard=[
                [ibtn("topup", "Hisob to'ldirish", style="primary", callback_data="m:topup")],
                [ibtn("back", "Orqaga", callback_data="m:home")],
            ]))
            return

        await state.clear()
        await call.answer("Buyurtma qabul qilindi!")
        auto = await fulfillment.auto_ready(kind)
        await show(call, card(
            "done", f"Buyurtma #{order_id} qabul qilindi",
            f"{em(_ICON[kind])} Mahsulot: <b>{esc(detail)}</b>",
            f"{em('money')} To'langan: <b>{await price(cost)}</b>",
            "",
            (f"{em('auto')} <b>Avtomatik yetkazib berilmoqda.</b> Odatda bir necha daqiqa ichida tugaydi."
             if auto else
             f"{em('pending')} <b>Buyurtma ko'rib chiqilmoqda.</b> Admin tez orada bajaradi."),
            "",
            f"{em('info')} Yetkazilgach sizga xabar yuboramiz. Holatni «Buyurtmalarim» bo'limida ham ko'rishingiz mumkin.",
        ), InlineKeyboardMarkup(inline_keyboard=[
            [ibtn("orders", "Buyurtmalarim", callback_data="m:orders"),
             ibtn("home", "Bosh menyu", callback_data="m:home")],
        ]))
        await fulfillment.on_new_order(bot, order_id)
    finally:
        _buying.discard(uid)


# ==================== Hisob to'ldirish ====================

def _fmt_card(number: str) -> str:
    digits = "".join(ch for ch in number if ch.isdigit())
    return " ".join(digits[i:i + 4] for i in range(0, len(digits), 4))


@router.callback_query(F.data == "m:topup")
async def cb_topup(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await ask(call, state, TopUp.waiting_amount, card(
        "topup", "Hisob to'ldirish — 1/2",
        f"Balansni qancha ({esc(await currency())}) ga to'ldirmoqchisiz?",
        "Summani faqat raqam bilan yuboring, masalan: <code>50000</code>",
        "",
        f"{em('info')} Keyingi qadamda to'lov rekvizitlari ko'rsatiladi.",
    ), back="m:home")


@router.message(TopUp.waiting_amount, F.text)
async def topup_amount(message: Message, state: FSMContext):
    raw = message.text.replace(" ", "")
    if not (raw.isascii() and raw.isdigit()) or not (0 < int(raw) <= MAX_TOPUP):
        await invalid(message, state, "Faqat musbat raqam kiriting. Masalan: 50000")
        return
    amount = int(raw)
    await state.update_data(topup_amount=amount)
    await state.set_state(TopUp.waiting_receipt)

    number = await db.get_setting("card_number")
    holder = await db.get_setting("card_holder")
    if number:
        lines = [
            "Quyidagi kartaga to'lov qiling:",
            "",
            f"{em('payment')} Karta raqami: <code>{esc(_fmt_card(number))}</code>",
        ]
        if holder:
            lines.append(f"{em('name')} Karta egasi: <b>{esc(holder)}</b>")
        lines += [
            f"{em('money')} To'lov summasi: <b>{await price(amount)}</b>",
            "",
            "To'lovdan so'ng <b>chekni</b> (skrinshot yoki fayl) shu yerga yuboring.",
            "",
            f"{em('info')} Chekda summa va to'lov vaqti ko'rinib tursin. Admin tekshirib, mablag'ni balansingizga qo'shadi.",
        ]
    else:
        lines = [
            f"{em('warn')} To'lov rekvizitlari hali kiritilmagan.",
            "Iltimos, bosh menyudagi «Murojaat» orqali adminga yozing.",
        ]
    text = card("payment", "Hisob to'ldirish — 2/2", *lines)
    await state.update_data(prompt_text=text)
    await render_input(message, state, text, cancel_kb("m:home"))


@router.message(TopUp.waiting_amount)
async def topup_amount_invalid(message: Message, state: FSMContext):
    await invalid(message, state, "Summani matn ko'rinishida, faqat raqam bilan yozing. Masalan: 50000")


@router.message(TopUp.waiting_receipt, F.photo | F.document)
async def topup_receipt(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    amount = data.get("topup_amount")
    if not amount:
        await state.clear()
        return
    tx_id = await db.create_transaction(message.from_user.id, amount, "topup")
    if ADMIN_CHAT_ID:
        tx = await db.get_transaction(tx_id)
        user = await db.get_user(message.from_user.id)
        try:
            # chekning o'zi + ma'lumot + tugmalar bitta xabarda
            await bot.copy_message(
                ADMIN_CHAT_ID, message.chat.id, message.message_id,
                caption=await topup_card(tx, user), reply_markup=topup_action_kb(tx_id),
            )
        except Exception:
            with contextlib.suppress(Exception):
                await bot.send_message(ADMIN_CHAT_ID, await topup_card(tx, user),
                                       reply_markup=topup_action_kb(tx_id))
    await finish(message, state, card(
        "done", f"So'rov #{tx_id} qabul qilindi",
        "Chekingiz adminga yuborildi.",
        f"Tekshirilgach <b>{await price(amount)}</b> balansingizga qo'shiladi.",
        "",
        f"{em('info')} Natija haqida sizga alohida xabar yuboramiz.",
    ), back_kb("m:home", "Bosh menyu"), delete_input=False)


@router.message(TopUp.waiting_receipt)
async def topup_receipt_invalid(message: Message, state: FSMContext):
    await invalid(message, state, "Chekni rasm (skrinshot) yoki fayl ko'rinishida yuboring.")


# ==================== Noma'lum xabar (jumladan, eski reply tugmalar) ====================

@router.message(StateFilter(None))
async def unknown(message: Message, bot: Bot):
    try:  # eski reply klaviatura qolgan bo'lsa olib tashlaymiz
        tmp = await message.answer("⏳", reply_markup=ReplyKeyboardRemove())
        await tmp.delete()
    except Exception:
        pass
    text, kb = await home_view(message.from_user.id, message.from_user.full_name)
    await message.answer(text, reply_markup=kb)
