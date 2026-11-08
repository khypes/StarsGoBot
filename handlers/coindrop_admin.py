"""Admin panel: Coindrop.uz API sozlamalari (kalit, avto-yetkazish, balans, narx sinxronlash)."""
import json
from decimal import Decimal, ROUND_CEILING
import re

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup

import database.db as db
import fulfillment
from coindrop import CoinDrop, CoinDropError, STARS_GAME, PREMIUM_GAME, STARS_MIN
from emojis import em, ibtn
from keyboards.admin_kb import coindrop_kb
from nav import show, ask, invalid, finish
from states.states import AdminCoinDrop
from ui import IsAdmin, card, esc, fmt_num, currency

router = Router()
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())

KEY_RE = re.compile(r"^cd_[A-Za-z0-9_\-]{8,}$")
MAX_STARS_PACKAGES = 20


def mask(key: str) -> str:
    return f"{key[:5]}…{key[-4:]}" if len(key) > 10 else "•••"


# ==================== asosiy ekran ====================

async def cd_view(flash: str | None = None):
    key = await fulfillment.api_key()
    enabled = await fulfillment.is_enabled()
    lines = [flash, ""] if flash else []
    if not key:
        lines += [
            "API kalit hali kiritilmagan.",
            "",
            "Kalitni olish: coindrop.uz → Profil → Security &amp; API Key (<code>cd_</code> bilan boshlanadi).",
            "Kalit kiritilgach Stars va Premium buyurtmalari avtomatik yetkaziladi.",
        ]
    else:
        auto_text = "yoqilgan" if enabled else "o'chirilgan"
        lines += [
            f"{em('apikey')} Kalit: <code>{esc(mask(key))}</code>",
            f"{em('auto')} Avto-yetkazish: <b>{auto_text}</b>",
            f"{em('ref_percent')} Narx ustamasi: <b>{esc(await db.get_setting('coindrop_markup'))}%</b>",
        ]
        try:
            data = await CoinDrop(key).account()
            acc = data.get("account") or {}
            lines += [
                "",
                f"{em('account')} Akkaunt: {esc(acc.get('name') or '—')}",
                f"{em('money')} Balans: <b>${float(acc.get('balance_usd') or 0):.2f}</b> "
                f"({fmt_num(int(float(acc.get('balance_uzs') or 0)))} so'm)",
            ]
            if data.get("usd_to_uzs"):
                lines.append(f"{em('currency')} Kurs: 1$ = {fmt_num(int(float(data['usd_to_uzs'])))} so'm")
            if not acc.get("api_enabled", True):
                lines.append(f"{em('warn')} Akkauntda API o'chirilgan!")
        except CoinDropError as exc:
            lines += ["", f"{em('warn')} <b>Ulanib bo'lmadi:</b> {esc(exc.human())}"]
    return card("api", "Coindrop.uz API", *lines), coindrop_kb(enabled, bool(key))


@router.callback_query(F.data.in_({"a:cd", "cd:refresh"}))
async def cb_open(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.answer()
    await show(call, *await cd_view())


# ==================== kalit ====================

@router.callback_query(F.data == "cd:key")
async def cb_key(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await ask(call, state, AdminCoinDrop.waiting_key, card(
        "apikey", "API kalit",
        "Coindrop kalitingizni yuboring (<code>cd_...</code>).",
        "Xavfsizlik uchun xabaringiz darhol o'chiriladi.",
    ), back="a:cd")


@router.message(AdminCoinDrop.waiting_key, F.text)
async def key_receive(message: Message, state: FSMContext):
    key = message.text.strip()
    if not KEY_RE.match(key):
        await invalid(message, state, "Kalit noto'g'ri ko'rinishda. U cd_ bilan boshlanadi.")
        return
    try:
        await CoinDrop(key).account()
    except CoinDropError as exc:
        await invalid(message, state, exc.human())
        return
    await db.set_setting("coindrop_api_key", key)
    await db.set_setting("coindrop_enabled", "1")
    await finish(message, state, *await cd_view(
        f"{em('done')} <b>Ulandi!</b> Avto-yetkazish yoqildi — endi Stars va Premium buyurtmalari avtomatik bajariladi."))


@router.message(AdminCoinDrop.waiting_key)
async def key_invalid(message: Message, state: FSMContext):
    await invalid(message, state, "Kalitni matn ko'rinishida yuboring.")


@router.callback_query(F.data == "cd:toggle")
async def cb_toggle(call: CallbackQuery):
    if not await fulfillment.has_key():
        await call.answer("Avval API kalitni kiriting", show_alert=True)
        return
    new_val = "0" if await fulfillment.is_enabled() else "1"
    await db.set_setting("coindrop_enabled", new_val)
    await call.answer("Yoqildi" if new_val == "1" else "O'chirildi")
    await show(call, *await cd_view())


@router.callback_query(F.data == "cd:delkey")
async def cb_delete_key(call: CallbackQuery):
    await call.answer()
    await show(call, card(
        "warn", "Kalitni o'chirishni tasdiqlang",
        "Avto-yetkazish to'xtaydi, buyurtmalar qo'lda bajariladi.",
        "API da jarayonda turgan buyurtmalar kuzatilmay qoladi.",
    ), InlineKeyboardMarkup(inline_keyboard=[[
        ibtn("done", "Ha, o'chirish", style="danger", callback_data="cd:delkey_yes"),
        ibtn("cancel", "Yo'q", callback_data="a:cd"),
    ]]))


@router.callback_query(F.data == "cd:delkey_yes")
async def cb_delete_key_yes(call: CallbackQuery):
    await db.set_setting("coindrop_api_key", "")
    await db.set_setting("coindrop_enabled", "0")
    await call.answer("Kalit o'chirildi")
    await show(call, *await cd_view())


# ==================== ustama foiz ====================

@router.callback_query(F.data == "cd:markup")
async def cb_markup(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await ask(call, state, AdminCoinDrop.waiting_markup, card(
        "ref_percent", "Narx ustamasi",
        f"Joriy: <b>{esc(await db.get_setting('coindrop_markup'))}%</b>",
        "Narxlarni sinxronlashda Coindrop narxiga qo'shiladigan foizni yuboring (0–500).",
    ), back="a:cd")


@router.message(AdminCoinDrop.waiting_markup, F.text)
async def markup_set(message: Message, state: FSMContext):
    raw = message.text.strip().rstrip("%")
    if not (raw.isascii() and raw.isdigit()) or not (0 <= int(raw) <= 500):
        await invalid(message, state, "0 dan 500 gacha butun son kiriting.")
        return
    await db.set_setting("coindrop_markup", str(int(raw)))
    await finish(message, state, *await cd_view(f"{em('done')} <b>Ustama foiz yangilandi.</b>"))


@router.message(AdminCoinDrop.waiting_markup)
async def markup_invalid(message: Message, state: FSMContext):
    await invalid(message, state, "Iltimos, son yuboring.")


# ==================== narxlarni sinxronlash ====================

def _sale(cost_uzs: float, markup: int) -> int:
    """Coindrop narxi + ustama, 100 so'mga yuqoriga yaxlitlanadi."""
    value = Decimal(str(cost_uzs)) * (100 + markup) / 100
    return int((value / 100).to_integral_value(rounding=ROUND_CEILING) * 100)


async def build_sync(client: CoinDrop, markup: int):
    stars, premium = [], []
    for p in await client.products(STARS_GAME):
        amount, cost = p.get("amount"), p.get("price_uzs")
        if str(p.get("id", "")).startswith("amt_") and amount and cost and int(amount) >= STARS_MIN:
            stars.append({"stars": int(amount), "price": _sale(float(cost), markup), "cost": int(float(cost))})
    for p in await client.products(PREMIUM_GAME):
        m = re.fullmatch(r"prem_(\d+)m", str(p.get("id", "")))
        cost = p.get("price_uzs")
        if m and cost:
            premium.append({"months": int(m.group(1)), "price": _sale(float(cost), markup), "cost": int(float(cost))})
    stars.sort(key=lambda x: x["stars"])
    premium.sort(key=lambda x: x["months"])
    return stars[:MAX_STARS_PACKAGES], premium, len(stars) > MAX_STARS_PACKAGES


@router.callback_query(F.data == "cd:sync")
async def cb_sync(call: CallbackQuery, state: FSMContext):
    key = await fulfillment.api_key()
    if not key:
        await call.answer("Avval API kalitni kiriting", show_alert=True)
        return
    await call.answer("Narxlar yuklanmoqda…")
    markup = int(await db.get_setting("coindrop_markup") or 0)
    try:
        stars, premium, truncated = await build_sync(CoinDrop(key), markup)
    except CoinDropError as exc:
        await show(call, *await cd_view(f"{em('warn')} <b>Narxlarni olib bo'lmadi:</b> {esc(exc.human())}"))
        return
    if not stars and not premium:
        await show(call, *await cd_view(f"{em('warn')} Coindrop mahsulotlar ro'yxatini qaytarmadi."))
        return
    await state.update_data(sync_stars=stars, sync_premium=premium)

    lines = [f"Ustama: <b>{markup}%</b> (Coindrop narxi → sizning narxingiz)", ""]
    lines += [f"{em('stars')} {fmt_num(s['stars'])} Stars: {fmt_num(s['cost'])} → <b>{fmt_num(s['price'])}</b>" for s in stars]
    if truncated:
        lines.append(f"(birinchi {MAX_STARS_PACKAGES} ta paket)")
    lines += [f"{em('premium')} {p['months']} oy: {fmt_num(p['cost'])} → <b>{fmt_num(p['price'])}</b>" for p in premium]
    cur = (await currency()).lower()
    if cur not in ("so'm", "som", "uzs", "сум", "so`m", "soʻm"):
        lines += ["", f"{em('warn')} Valyuta «{esc(cur)}» — narxlar so'mda yoziladi. Valyutani «so'm» ga o'zgartiring."]
    await show(call, card("sync", "Narxlarni sinxronlash", *lines, expandable=True), InlineKeyboardMarkup(inline_keyboard=[
        [ibtn("done", "Narxlarni qo'llash", style="success", callback_data="cd:sync_ok")],
        [ibtn("cancel", "Bekor qilish", callback_data="a:cd")],
    ]))


@router.callback_query(F.data == "cd:sync_ok")
async def cb_sync_apply(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    stars, premium = data.get("sync_stars"), data.get("sync_premium")
    if stars is None and premium is None:
        await call.answer("Sessiya eskirdi. Qayta sinxronlang.", show_alert=True)
        return
    if stars:
        await db.set_setting("stars_prices", json.dumps(
            [{"stars": s["stars"], "price": s["price"]} for s in stars], ensure_ascii=False))
    if premium:
        await db.set_setting("premium_prices", json.dumps(
            [{"months": p["months"], "price": p["price"]} for p in premium], ensure_ascii=False))
    await state.clear()
    await call.answer("Narxlar yangilandi")
    await show(call, *await cd_view(
        f"{em('done')} <b>Narxlar yangilandi:</b> {len(stars or [])} ta Stars, {len(premium or [])} ta Premium."))
