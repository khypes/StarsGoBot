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
    main_menu, back_kb, stars_prices_kb, premium_prices_kb, channels_check_kb,
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
    text = card(
        "wave", f"Assalomu alaykum, {esc(full_name)}!",
        f"{em('rocket')} Telegram Stars va Premium xarid qilish botiga xush kelibsiz.",
        f"{em('topup')} Balansingiz: <b>{await price(user['balance'] if user else 0)}</b>",
        "",
        f"{em('down')} Kerakli bo'limni tanlang.",
    )
    return text, main_menu(await db.is_admin(user_id))


async def account_view(user_id: int):
    user = await db.get_user(user_id)
    text = card(
        "account", "Mening hisobim",
        f"{em('id')} ID: <code>{user_id}</code>",
        f"{em('topup')} Balans: <b>{await price(user['balance'])}</b>",
        f"{em('orders')} Jami buyurtmalar: {await db.user_order_count(user_id)}",
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [ibtn("topup", "Hisob to'ldirish", style="primary", callback_data="m:topup"),
         ibtn("orders", "Buyurtmalarim", callback_data="m:orders")],
        [ibtn("back", "Orqaga", callback_data="m:home")],
    ])
    return text, kb


async def orders_view(user_id: int):
    orders = await db.user_orders(user_id, 10)
    if not orders:
        return note("inbox", "Sizda hali buyurtmalar mavjud emas."), back_kb()
    icons = {"kutilmoqda": "pending", "bajarildi": "done", "bekor qilindi": "cancel"}
    cur = await currency()
    lines = [
        f"{em(icons.get(o['status'], 'pending'))} <b>#{o['id']}</b> · {esc(o['detail'])} · "
        f"{fmt_num(o['price'])} {cur} · {esc(o['status'])}"
        for o in orders
    ]
    return card("orders", "So'nggi buyurtmalaringiz", *lines, expandable=len(lines) > 5), back_kb()


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
        f"{em('link')} Sizning havolangiz:\n{link}",
        "",
        f"{em('people')} Taklif qilingan do'stlar: <b>{await db.referral_count(user_id)}</b> ta",
        f"{em('bonus')} Har bir do'stingizning birinchi bajarilgan xarididan <b>{esc(percent)}%</b> "
        f"bonus balansingizga qo'shiladi.",
    )
    return text, back_kb()


def guide_view():
    text = card(
        "guide", "Qo'llanma",
        f"{em('stars')} <b>Stars</b> — miqdorni tanlang, qabul qiluvchi usernamesini kiriting va tasdiqlang. "
        f"Mablag' balansingizdan yechiladi.",
        "",
        f"{em('premium')} <b>Premium</b> — obunani o'zingizga yoki boshqa foydalanuvchiga sovg'a qilishingiz mumkin.",
        "",
        f"{em('topup')} <b>Hisob to'ldirish</b> — ko'rsatilgan rekvizitga to'lab, chekni yuboring. "
        f"Admin tasdiqlagach mablag' balansingizga tushadi.",
        "",
        f"{em('referral')} <b>Referal</b> — do'stlaringizni taklif qiling va bonus oling.",
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
                     "Botdan foydalanish uchun quyidagi kanallarga obuna bo'ling, "
                     "so'ng «Tekshirish» tugmasini bosing."),
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
    await call.answer("Obuna tasdiqlandi!")
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
    await show(
        call,
        card("stars", "Stars", "Sotib olmoqchi bo'lgan miqdorni tanlang:"),
        stars_prices_kb(prices, await currency()),
    )


@router.callback_query(F.data == "m:premium")
async def cb_premium(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.answer()
    prices = await db.get_premium_prices()
    await show(
        call,
        card("premium", "Premium", "Kerakli tarifni tanlang:"),
        premium_prices_kb(prices, await currency()),
    )


# ==================== Murojaat ====================

@router.callback_query(F.data == "m:appeal")
async def cb_appeal(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await ask(call, state, Appeal.waiting_message, card(
        "pencil", "Murojaat",
        "Murojaatingizni yozib yuboring (matn, rasm yoki hujjat bo'lishi mumkin).",
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
                 note("done", "Murojaatingiz qabul qilindi. Tez orada javob beramiz."),
                 back_kb("m:home", "Bosh menyu"))


# ==================== Xarid (Stars / Premium) ====================

async def _catalog_item(kind: str, qty: int):
    if kind == "stars":
        return next((p for p in await db.get_stars_prices() if p["stars"] == qty), None)
    return next((p for p in await db.get_premium_prices() if p["months"] == qty), None)


def _product_label(kind: str, qty: int, recipient: str | None = None) -> str:
    base = f"{fmt_num(qty)} Stars" if kind == "stars" else f"{qty} oylik Premium"
    return f"{base} → @{recipient}" if recipient else base


@router.callback_query(F.data.regexp(r"^b:[sp]:\d+$"))
async def cb_choose_product(call: CallbackQuery, state: FSMContext):
    _, code, raw = call.data.split(":")
    kind, qty = ("stars" if code == "s" else "premium"), int(raw)
    item = await _catalog_item(kind, qty)
    if not item:
        await call.answer("Narxlar yangilangan. Ro'yxatni qayta oching.", show_alert=True)
        return
    back = "m:stars" if kind == "stars" else "m:premium"
    await call.answer()
    own = call.from_user.username
    await ask(
        call, state, Purchase.waiting_recipient,
        card("account", "Qabul qiluvchi",
             f"{em('stars' if kind == 'stars' else 'premium')} <b>{_product_label(kind, qty)}</b> "
             f"({await price(item['price'])})",
             "",
             "Kim uchun? Qabul qiluvchining usernamesini yuboring (masalan: <code>@username</code>)."
             + ("" if own else "\nUsernamengiz yo'q — boshqa foydalanuvchi usernamesini kiriting.")),
        back=back, kb=recipient_kb(own, back),
        kind=kind, qty=qty, price=item["price"],
    )


async def _confirm_view(user_id: int, data: dict, flash: str | None = None):
    kind, qty, recipient, cost = data["kind"], data["qty"], data["recipient"], data["price"]
    user = await db.get_user(user_id)
    lines = []
    if flash:
        lines += [flash, ""]
    lines += [
        f"{em('stars' if kind == 'stars' else 'premium')} Mahsulot: <b>{_product_label(kind, qty)}</b>",
        f"{em('link')} Qabul qiluvchi: <code>@{esc(recipient)}</code>",
        f"{em('money')} Narx: <b>{await price(cost)}</b>",
        f"{em('topup')} Balansingiz: {await price(user['balance'])}",
    ]
    back = "m:stars" if kind == "stars" else "m:premium"
    return card("orders", "Buyurtmani tasdiqlang", *lines), confirm_kb(await price(cost), back)


@router.message(Purchase.waiting_recipient, F.text)
async def purchase_recipient(message: Message, state: FSMContext):
    m = USERNAME_RE.match(message.text.strip())
    if not m:
        await invalid(message, state, "To'g'ri username yuboring. Masalan: @username")
        return
    await state.update_data(recipient=m.group(1))
    data = await state.get_data()
    await state.set_state(None)  # ma'lumotlar saqlanadi, tasdiqlash tugma orqali
    text, kb = await _confirm_view(message.from_user.id, data)
    await render_input(message, state, text, kb)


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
        order_id = await db.purchase(uid, kind, detail, cost, recipient=f"@{recipient}", quantity=qty)
        if order_id is None:
            await call.answer()
            user = await db.get_user(uid)
            bal = user["balance"] if user else 0
            await show(call, card(
                "warn", "Mablag' yetarli emas",
                f"Kerak: <b>{await price(cost)}</b>",
                f"Mavjud: <b>{await price(bal)}</b>",
                f"Yetishmayapti: <b>{await price(max(cost - bal, 0))}</b>",
            ), InlineKeyboardMarkup(inline_keyboard=[
                [ibtn("topup", "Hisob to'ldirish", style="primary", callback_data="m:topup")],
                [ibtn("back", "Orqaga", callback_data="m:home")],
            ]))
            return

        await state.clear()
        await call.answer("Buyurtma qabul qilindi!")
        auto = await fulfillment.get_client() is not None
        await show(call, card(
            "done", f"Buyurtma #{order_id} qabul qilindi",
            f"{em('stars' if kind == 'stars' else 'premium')} {esc(detail)}",
            f"{em('money')} {await price(cost)}",
            "",
            f"{em('auto') if auto else em('pending')} "
            + ("Avtomatik yetkazib berilmoqda — odatda bir necha daqiqa ichida." if auto
               else "Holat: kutilmoqda. Tez orada yetkazib beramiz."),
        ), InlineKeyboardMarkup(inline_keyboard=[
            [ibtn("orders", "Buyurtmalarim", callback_data="m:orders"),
             ibtn("home", "Bosh menyu", callback_data="m:home")],
        ]))
        await fulfillment.on_new_order(bot, order_id)
    finally:
        _buying.discard(uid)


# ==================== Hisob to'ldirish ====================

@router.callback_query(F.data == "m:topup")
async def cb_topup(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await ask(call, state, TopUp.waiting_amount, card(
        "topup", "Hisob to'ldirish",
        f"To'ldirmoqchi bo'lgan summani kiriting ({esc(await currency())}, faqat raqam).",
        "Masalan: <code>50000</code>",
    ), back="m:home")


@router.message(TopUp.waiting_amount, F.text)
async def topup_amount(message: Message, state: FSMContext):
    raw = message.text.replace(" ", "")
    if not (raw.isascii() and raw.isdigit()) or not (0 < int(raw) <= MAX_TOPUP):
        await invalid(message, state, "Iltimos, to'g'ri musbat raqam kiriting.")
        return
    amount = int(raw)
    await state.update_data(topup_amount=amount)
    await state.set_state(TopUp.waiting_receipt)

    card_no = await db.get_setting("card_number")
    ton = await db.get_setting("ton_wallet")
    lines = []
    if card_no:
        lines.append(f"{em('payment')} Karta: <code>{esc(card_no)}</code>")
    if ton:
        lines.append(f"{em('ton')} TON hamyon: <code>{esc(ton)}</code>")
    if not lines:
        lines.append("To'lov rekvizitlari hali kiritilmagan. Admin bilan bog'laning.")
    lines += [
        "",
        f"{em('money')} To'lov summasi: <b>{await price(amount)}</b>",
        "",
        "To'lovdan so'ng chek (rasm yoki fayl) yuboring.",
    ]
    text = card("payment", "To'lov ma'lumotlari", *lines)
    await state.update_data(prompt_text=text)
    await render_input(message, state, text, cancel_kb("m:home"))


@router.message(TopUp.waiting_amount)
async def topup_amount_invalid(message: Message, state: FSMContext):
    await invalid(message, state, "Iltimos, summani raqam bilan yozing.")


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
        f"Admin tasdiqlagach <b>{await price(amount)}</b> balansingizga qo'shiladi.",
    ), back_kb("m:home", "Bosh menyu"), delete_input=False)


@router.message(TopUp.waiting_receipt)
async def topup_receipt_invalid(message: Message, state: FSMContext):
    await invalid(message, state, "Iltimos, to'lov chekini rasm yoki fayl shaklida yuboring.")


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
