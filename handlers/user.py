import re

from aiogram import Router, F, Bot
from aiogram.filters import CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery

import database.db as db
from config import ADMIN_CHAT_ID, MAX_TOPUP
from emojis import em
from keyboards.admin_kb import order_action_kb, topup_action_kb
from keyboards.user_kb import (
    main_menu, back_menu, stars_prices_kb, premium_prices_kb, channels_check_kb,
)
from middlewares import missing_channels, forget
from states.states import PremiumOrder, TopUp, Appeal
from texts import order_card, topup_card
from ui import Btn, card, note, q, esc, fmt_num, price, currency

router = Router()

USERNAME_RE = re.compile(r"^@?([A-Za-z][A-Za-z0-9_]{4,31})$")


# ---------------- yordamchilar ----------------

async def send_home(message: Message, user_id: int, text: str):
    admin = await db.is_admin(user_id)
    await message.answer(text, reply_markup=main_menu(admin))


async def notify_admin_new_order(bot: Bot, order_id: int):
    if (await db.get_setting("order_notify")) != "1" or not ADMIN_CHAT_ID:
        return
    order = await db.get_order(order_id)
    user = await db.get_user(order["user_id"])
    try:
        await bot.send_message(
            ADMIN_CHAT_ID, await order_card(order, user), reply_markup=order_action_kb(order_id)
        )
    except Exception:
        pass


# ---------------- /start ----------------

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
    user, _ = await db.create_user_if_not_exists(
        uid, message.from_user.username or "", message.from_user.full_name or "", referrer_id
    )

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

    text = card(
        "wave", f"Assalomu alaykum, {esc(message.from_user.full_name)}!",
        f"{em('rocket')} Telegram Stars va Premium xarid qilish botiga xush kelibsiz.",
        f"{em('topup')} Balansingiz: <b>{await price(user['balance'])}</b>",
        "",
        f"{em('down')} Quyidagi menyudan kerakli bo'limni tanlang.",
    )
    await send_home(message, uid, text)


@router.callback_query(F.data == "check_subs")
async def cb_check_subs(call: CallbackQuery, bot: Bot):
    forget(call.from_user.id)
    if await missing_channels(bot, call.from_user.id):
        await call.answer("Hali barcha kanallarga obuna bo'lmagansiz.", show_alert=True)
        return
    await call.answer()
    try:
        await call.message.delete()
    except Exception:
        pass
    await send_home(call.message, call.from_user.id,
                    note("done", "Obuna tasdiqlandi! Botdan foydalanishingiz mumkin."))


# ---------------- Orqaga (umumiy) ----------------

@router.message(Btn("back"))
async def back_home(message: Message, state: FSMContext):
    await state.clear()
    await send_home(message, message.from_user.id, note("home", "Bosh menyu"))


# ---------------- Mening hisobim ----------------

@router.message(Btn("account"))
async def my_account(message: Message, state: FSMContext):
    await state.clear()
    user = await db.get_user(message.from_user.id)
    await message.answer(card(
        "account", "Mening hisobim",
        f"{em('id')} ID: <code>{message.from_user.id}</code>",
        f"{em('topup')} Balans: <b>{await price(user['balance'])}</b>",
        f"{em('orders')} Jami buyurtmalar: {await db.user_order_count(message.from_user.id)}",
    ))


# ---------------- Buyurtmalarim ----------------

@router.message(Btn("orders"))
async def my_orders(message: Message, state: FSMContext):
    await state.clear()
    orders = await db.user_orders(message.from_user.id)
    if not orders:
        await message.answer(note("inbox", "Sizda hali buyurtmalar mavjud emas."))
        return
    icons = {"kutilmoqda": "pending", "bajarildi": "done", "bekor qilindi": "cancel"}
    cur = await currency()
    lines = []
    for o in orders:
        icon = em(icons.get(o["status"], "pending"))
        lines.append(f"{icon} <b>#{o['id']}</b> · {esc(o['detail'])} · {fmt_num(o['price'])} {cur} · {esc(o['status'])}")
    await message.answer(card("orders", "So'nggi buyurtmalaringiz", *lines, expandable=len(lines) > 5))


# ---------------- Referal ----------------

@router.message(Btn("referral"))
async def referral(message: Message, state: FSMContext, bot: Bot):
    await state.clear()
    me = await bot.get_me()
    link = f"https://t.me/{me.username}?start=ref_{message.from_user.id}"
    count = await db.referral_count(message.from_user.id)
    percent = await db.get_setting("referral_percent") or "0"
    await message.answer(card(
        "referral", "Referal dasturi",
        f"{em('link')} Sizning havolangiz:\n{link}",
        "",
        f"{em('people')} Taklif qilingan do'stlar: <b>{count}</b> ta",
        f"{em('bonus')} Har bir do'stingizning birinchi bajarilgan xarididan <b>{esc(percent)}%</b> "
        f"bonus balansingizga qo'shiladi.",
    ))


# ---------------- Murojaat ----------------

@router.message(Btn("appeal"))
async def appeal_start(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(Appeal.waiting_message)
    await message.answer(
        card("pencil", "Murojaat",
             "Murojaatingizni yozib yuboring (matn, rasm yoki hujjat bo'lishi mumkin)."),
        reply_markup=back_menu(),
    )


@router.message(Appeal.waiting_message)
async def appeal_receive(message: Message, state: FSMContext, bot: Bot):
    await state.clear()
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
    await send_home(message, message.from_user.id,
                    note("done", "Murojaatingiz qabul qilindi. Tez orada javob beramiz."))


# ---------------- Qo'llanma ----------------

@router.message(Btn("guide"))
async def guide(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(card(
        "guide", "Qo'llanma",
        f"{em('stars')} <b>Stars</b> — kerakli miqdorni tanlang, balansingizdan mablag' yechiladi "
        f"va buyurtma tez orada bajariladi.",
        "",
        f"{em('premium')} <b>Premium</b> — obunani o'zingizga yoki boshqa foydalanuvchiga sovg'a qilishingiz mumkin.",
        "",
        f"{em('topup')} <b>Hisob to'ldirish</b> — ko'rsatilgan karta/TON hamyonga to'lov qilib, chekni yuboring. "
        f"Admin tasdiqlagach mablag' balansingizga tushadi.",
        "",
        f"{em('referral')} <b>Referal</b> — do'stlaringizni taklif qiling va bonus oling.",
        expandable=True,
    ))


# ---------------- Stars ----------------

@router.message(Btn("stars"))
async def stars_menu(message: Message, state: FSMContext):
    await state.clear()
    prices = await db.get_stars_prices()
    await message.answer(
        card("stars", "Stars", "Sotib olmoqchi bo'lgan miqdorni tanlang:"),
        reply_markup=stars_prices_kb(prices, await currency()),
    )


@router.callback_query(F.data.startswith("buy_stars:"))
async def buy_stars(call: CallbackQuery, bot: Bot):
    try:
        stars = int(call.data.split(":")[1])
    except (ValueError, IndexError):
        await call.answer()
        return
    item = next((p for p in await db.get_stars_prices() if p["stars"] == stars), None)
    if not item:
        await call.answer("Narxlar yangilangan. Ro'yxatni qayta oching.", show_alert=True)
        return
    cost = item["price"]
    order_id = await db.purchase(call.from_user.id, "stars", f"{stars} Stars", cost)
    if order_id is None:
        await call.answer()
        await call.message.answer(await _insufficient(call.from_user.id, cost))
        return
    await call.answer("Buyurtma qabul qilindi!")
    await call.message.answer(card(
        "done", f"Buyurtma #{order_id} qabul qilindi",
        f"{em('stars')} {stars} Stars — {await price(cost)}",
        f"{em('pending')} Holat: kutilmoqda. Tez orada yetkazib beramiz.",
    ))
    await notify_admin_new_order(bot, order_id)


async def _insufficient(user_id: int, cost: int) -> str:
    user = await db.get_user(user_id)
    bal = user["balance"] if user else 0
    return card(
        "warn", "Mablag' yetarli emas",
        f"Kerak: <b>{await price(cost)}</b>",
        f"Mavjud: <b>{await price(bal)}</b>",
        f"Yetishmayapti: <b>{await price(max(cost - bal, 0))}</b>",
        "",
        f"{em('topup')} «Hisob to'ldirish» bo'limi orqali balansni to'ldiring.",
    )


# ---------------- Premium ----------------

@router.message(Btn("premium"))
async def premium_menu(message: Message, state: FSMContext):
    await state.clear()
    prices = await db.get_premium_prices()
    await message.answer(
        card("premium", "Premium", "Kerakli tarifni tanlang:"),
        reply_markup=premium_prices_kb(prices, await currency()),
    )


@router.callback_query(F.data.startswith("buy_premium:"))
async def buy_premium(call: CallbackQuery, state: FSMContext):
    try:
        months = int(call.data.split(":")[1])
    except (ValueError, IndexError):
        await call.answer()
        return
    item = next((p for p in await db.get_premium_prices() if p["months"] == months), None)
    if not item:
        await call.answer("Narxlar yangilangan. Ro'yxatni qayta oching.", show_alert=True)
        return
    await state.set_state(PremiumOrder.waiting_username)
    await state.update_data(premium_months=months)
    await call.answer()
    await call.message.answer(
        card("account", "Qabul qiluvchi",
             "Premium sovg'a qilinadigan foydalanuvchi usernamesini yuboring (masalan: <code>@username</code>).",
             "O'zingiz uchun bo'lsa, o'z usernamengizni yuboring."),
        reply_markup=back_menu(),
    )


@router.message(PremiumOrder.waiting_username, F.text)
async def premium_receive_username(message: Message, state: FSMContext, bot: Bot):
    m = USERNAME_RE.match(message.text.strip())
    if not m:
        await message.answer(note("warn", "To'g'ri username yuboring. Masalan: <code>@username</code>"))
        return
    username = "@" + m.group(1)

    data = await state.get_data()
    months = data.get("premium_months")
    item = next((p for p in await db.get_premium_prices() if p["months"] == months), None)
    if not item:
        await state.clear()
        await send_home(message, message.from_user.id,
                        note("warn", "Narxlar yangilangan. Premium bo'limini qayta oching."))
        return

    cost = item["price"]
    detail = f"{months} oylik Premium ({username})"
    order_id = await db.purchase(message.from_user.id, "premium", detail, cost)
    await state.clear()
    if order_id is None:
        await send_home(message, message.from_user.id, await _insufficient(message.from_user.id, cost))
        return
    await send_home(message, message.from_user.id, card(
        "done", f"Buyurtma #{order_id} qabul qilindi",
        f"{em('premium')} {esc(detail)} — {await price(cost)}",
        f"{em('pending')} Holat: kutilmoqda.",
    ))
    await notify_admin_new_order(bot, order_id)


@router.message(PremiumOrder.waiting_username)
async def premium_username_invalid(message: Message):
    await message.answer(note("warn", "Iltimos, username'ni matn ko'rinishida yuboring."))


# ---------------- Hisob to'ldirish ----------------

@router.message(Btn("topup"))
async def topup_start(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(TopUp.waiting_amount)
    await message.answer(
        card("topup", "Hisob to'ldirish",
             f"To'ldirmoqchi bo'lgan summani kiriting ({esc(await currency())}, faqat raqam).",
             "Masalan: <code>50000</code>"),
        reply_markup=back_menu(),
    )


@router.message(TopUp.waiting_amount, F.text)
async def topup_amount(message: Message, state: FSMContext):
    raw = message.text.replace(" ", "")
    if not (raw.isascii() and raw.isdigit()) or not (0 < int(raw) <= MAX_TOPUP):
        await message.answer(note("warn", "Iltimos, to'g'ri musbat raqam kiriting."))
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
    await message.answer(card("payment", "To'lov ma'lumotlari", *lines))


@router.message(TopUp.waiting_amount)
async def topup_amount_invalid(message: Message):
    await message.answer(note("warn", "Iltimos, summani raqam bilan yozing."))


@router.message(TopUp.waiting_receipt, F.photo | F.document)
async def topup_receipt(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    amount = data.get("topup_amount")
    if not amount:
        await state.clear()
        await send_home(message, message.from_user.id, note("warn", "Qaytadan boshlang."))
        return
    tx_id = await db.create_transaction(message.from_user.id, amount, "topup")
    await state.clear()
    await send_home(message, message.from_user.id, card(
        "done", f"So'rov #{tx_id} qabul qilindi",
        f"Admin tasdiqlagach <b>{await price(amount)}</b> balansingizga qo'shiladi.",
    ))
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
            try:
                await bot.send_message(ADMIN_CHAT_ID, await topup_card(tx, user),
                                       reply_markup=topup_action_kb(tx_id))
            except Exception:
                pass


@router.message(TopUp.waiting_receipt)
async def topup_receipt_invalid(message: Message):
    await message.answer(note("warn", "Iltimos, to'lov chekini rasm yoki fayl shaklida yuboring."))


# ---------------- Noma'lum xabar ----------------

@router.message(StateFilter(None))
async def unknown(message: Message):
    await send_home(message, message.from_user.id, note("down", "Iltimos, menyudan bo'limni tanlang."))
