"""Admin panel: UC (PUBG Mobile) sotish tizimi — yoqish/o'chirish, narx sinxronlash (Coindrop API), paketlar, ustama, statistika."""
import time

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup

import database.db as db
import fulfillment
from coindrop import CoinDropError
from emojis import em, ibtn
from keyboards.user_kb import grid
from nav import show, ask, invalid, finish
from providers import CoindropProvider, sale_price
from states.states import AdminUC
from ui import IsAdmin, card, esc, fmt_num, currency

router = Router()
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())

MAX_PRICE = 1_000_000_000


def _ago(ts: int) -> str:
    if not ts:
        return "hali sinxronlanmagan"
    sec = max(int(time.time()) - ts, 0)
    if sec < 90:
        return "hozirgina"
    if sec < 3600:
        return f"{sec // 60} daqiqa oldin"
    if sec < 86400:
        return f"{sec // 3600} soat oldin"
    return f"{sec // 86400} kun oldin"


async def _coindrop():
    return await fulfillment.provider_by_name("coindrop")


# ==================== asosiy ekran ====================

async def uc_view(flash: str | None = None):
    prices = await db.get_uc_prices()
    on = (await db.get_setting("uc_enabled")) == "1"
    has_key = await fulfillment.has_key("coindrop")
    auto = await fulfillment.auto_ready("uc")
    cur = esc(await currency())
    done, total_uc, revenue, pending = await db.uc_stats()

    lines = [flash, ""] if flash else []
    lines += [
        f"{em('done' if on and prices else 'cancel')} Sotuv: <b>{'yoqilgan' if on else "o'chirilgan"}</b>"
        + ("" if prices else " (paketlar yo'q)"),
        f"{em('api')} Yetkazish: <b>{'avtomatik (Coindrop API)' if auto else "qo'lda (admin bajaradi)"}</b>",
        f"{em('ref_percent')} Narx ustamasi: <b>{esc(await db.get_setting('uc_markup'))}%</b>",
        f"{em('uc')} Paketlar: <b>{len(prices)}</b> ta · {_ago(int(await db.get_setting('uc_synced_at') or 0))}",
        "",
        f"{em('stats')} Bajarilgan: <b>{done}</b> ta · <b>{fmt_num(total_uc)}</b> UC · {fmt_num(revenue)} {cur}",
        f"{em('pending')} Kutilayotgan: <b>{pending}</b> ta",
    ]
    if not has_key:
        lines += ["", f"{em('warn')} Coindrop API kaliti kiritilmagan. «API» bo'limida Coindrop kalitini ulang — "
                      "UC avtomatik yetkaziladi va narxlarni sinxronlash mumkin bo'ladi."]
    elif not auto:
        lines += ["", f"{em('warn')} Avto-yetkazish o'chirilgan — UC buyurtmalar sizga qo'lda bajarish uchun keladi."]
    if prices:
        lines += ["", "<b>Paketlar:</b>"]
        lines += [f"{em('uc')} {fmt_num(p['uc'])} UC — <b>{fmt_num(p['price'])}</b> {cur}"
                  + (f" (tannarx {fmt_num(p['cost'])})" if p.get("cost") else "") for p in prices]
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [ibtn("cancel" if on else "auto", "Sotuvni o'chirish" if on else "Sotuvni yoqish",
              style=None if on else "success", callback_data="uc:toggle")],
        [ibtn("sync", "Narxlarni sinxronlash", callback_data="uc:sync"),
         ibtn("ref_percent", "Ustama foiz", callback_data="uc:markup")],
        *([[ibtn("uc", "Paketlarni boshqarish", callback_data="uc:list")]] if prices else []),
        [ibtn("api", "Coindrop API", callback_data="a:cd"), ibtn("back", "Orqaga", callback_data="a:home")],
    ])
    return card("uc_sell", "UC sotish (PUBG Mobile)", *lines, expandable=len(prices) > 6), kb


@router.callback_query(F.data == "a:uc")
async def cb_open(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.answer()
    await show(call, *await uc_view())


@router.callback_query(F.data == "uc:toggle")
async def cb_toggle(call: CallbackQuery):
    on = (await db.get_setting("uc_enabled")) == "1"
    if not on:
        if not await db.get_uc_prices():
            await call.answer("Avval narxlarni sinxronlang", show_alert=True)
            return
        if not await fulfillment.has_key("coindrop"):
            await call.answer("Avval Coindrop API kalitini ulang", show_alert=True)
            return
    await db.set_setting("uc_enabled", "0" if on else "1")
    await call.answer("O'chirildi" if on else "Yoqildi")
    await show(call, *await uc_view())


# ==================== narxlarni sinxronlash ====================

@router.callback_query(F.data == "uc:sync")
async def cb_sync(call: CallbackQuery, state: FSMContext):
    prov = await _coindrop()
    if prov is None:
        await call.answer("Avval Coindrop API kalitini ulang", show_alert=True)
        return
    await call.answer("Narxlar yuklanmoqda…")
    markup = int(await db.get_setting("uc_markup") or 0)
    try:
        items = await CoindropProvider(prov.api_key).uc_list(markup)
    except CoinDropError as exc:
        await show(call, *await uc_view(f"{em('warn')} <b>Narxlarni olib bo'lmadi:</b> {esc(exc.human())}"))
        return
    if not items:
        await show(call, *await uc_view(f"{em('warn')} Coindrop PUBG Mobile paketlarini qaytarmadi."))
        return
    await state.update_data(uc_sync=items)
    cur = esc(await currency())
    lines = [f"Ustama: <b>{markup}%</b> (Coindrop narxi → sizning narxingiz)", ""]
    lines += [f"{em('uc')} {fmt_num(i['uc'])} UC: {fmt_num(i['cost'])} → <b>{fmt_num(i['price'])}</b> {cur}" for i in items]
    lines += ["", f"{em('warn')} Qo'llasangiz, mavjud paketlar va qo'lda o'zgartirilgan narxlar almashtiriladi."]
    low = (await currency()).lower()
    if low not in ("so'm", "som", "uzs", "сум", "so`m", "soʻm"):
        lines += [f"{em('warn')} Valyuta «{esc(low)}» — narxlar so'mda yoziladi. Valyutani «so'm» ga o'zgartiring."]
    await show(call, card("sync", "UC narxlarini sinxronlash", *lines, expandable=True), InlineKeyboardMarkup(inline_keyboard=[
        [ibtn("done", "Narxlarni qo'llash", style="success", callback_data="uc:sync_ok")],
        [ibtn("cancel", "Bekor qilish", callback_data="a:uc")],
    ]))


@router.callback_query(F.data == "uc:sync_ok")
async def cb_sync_apply(call: CallbackQuery, state: FSMContext):
    items = (await state.get_data()).get("uc_sync")
    if not items:
        await call.answer("Sessiya eskirdi. Qayta sinxronlang.", show_alert=True)
        return
    await db.set_uc_prices(items)
    await db.set_setting("uc_synced_at", str(int(time.time())))
    await state.clear()
    await call.answer("Narxlar yangilandi")
    await show(call, *await uc_view(f"{em('done')} <b>{len(items)} ta UC paketi yangilandi.</b>"))


# ==================== ustama foiz ====================

@router.callback_query(F.data == "uc:markup")
async def cb_markup(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await ask(call, state, AdminUC.waiting_markup, card(
        "ref_percent", "UC narx ustamasi",
        f"Joriy: <b>{esc(await db.get_setting('uc_markup'))}%</b>",
        "Coindrop narxiga qo'shiladigan foizni yuboring (0–500).",
        "",
        f"{em('info')} Yangi foiz mavjud paketlar narxiga ham darhol qo'llanadi (tannarxi ma'lum paketlarga).",
    ), back="a:uc")


@router.message(AdminUC.waiting_markup, F.text)
async def markup_set(message: Message, state: FSMContext):
    raw = message.text.strip().rstrip("%")
    if not (raw.isascii() and raw.isdigit()) or not (0 <= int(raw) <= 500):
        await invalid(message, state, "0 dan 500 gacha butun son kiriting.")
        return
    markup = int(raw)
    await db.set_setting("uc_markup", str(markup))
    items = await db.get_uc_prices()
    for p in items:
        if p.get("cost"):
            p["price"] = sale_price(p["cost"], markup)
    if items:
        await db.set_uc_prices(items)
    await finish(message, state, *await uc_view(f"{em('done')} <b>Ustama foiz yangilandi:</b> {markup}%"))


@router.message(AdminUC.waiting_markup)
async def markup_invalid(message: Message, state: FSMContext):
    await invalid(message, state, "Iltimos, son yuboring.")


# ==================== paketlarni boshqarish ====================

@router.callback_query(F.data == "uc:list")
async def cb_list(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.answer()
    prices = await db.get_uc_prices()
    if not prices:
        await show(call, *await uc_view())
        return
    cur = await currency()
    buttons = [ibtn("uc", f"{fmt_num(p['uc'])} UC · {fmt_num(p['price'])}", callback_data=f"uc:p:{p['uc']}")
               for p in prices]
    await show(call, card("uc", "UC paketlari",
                          "Narxini o'zgartirish yoki o'chirish uchun paketni tanlang.",
                          f"Narxlar: {esc(cur)}"),
               InlineKeyboardMarkup(inline_keyboard=grid(buttons, 2) + [[ibtn("back", "Orqaga", callback_data="a:uc")]]))


async def _pkg(uc: int):
    return next((p for p in await db.get_uc_prices() if p["uc"] == uc), None)


async def _pkg_view(p: dict, flash: str | None = None):
    cur = esc(await currency())
    lines = [flash, ""] if flash else []
    lines += [
        f"{em('money')} Sotuv narxi: <b>{fmt_num(p['price'])}</b> {cur}",
        *([f"{em('api')} Tannarx: {fmt_num(p['cost'])} {cur} · foyda: <b>{fmt_num(p['price'] - p['cost'])}</b> {cur}"]
          if p.get("cost") else []),
        f"{em('id')} Provayder mahsulot ID: <code>{esc(str(p.get('product_id') or '—'))}</code>",
    ]
    return card("uc", f"{fmt_num(p['uc'])} UC", *lines), InlineKeyboardMarkup(inline_keyboard=[
        [ibtn("pencil", "Narxni o'zgartirish", callback_data=f"uc:price:{p['uc']}")],
        [ibtn("trash", "O'chirish", style="danger", callback_data=f"uc:del:{p['uc']}"),
         ibtn("back", "Orqaga", callback_data="uc:list")],
    ])


@router.callback_query(F.data.regexp(r"^uc:p:\d+$"))
async def cb_pkg(call: CallbackQuery, state: FSMContext):
    await state.clear()
    p = await _pkg(int(call.data.split(":")[2]))
    if not p:
        await call.answer("Paket topilmadi", show_alert=True)
        return
    await call.answer()
    await show(call, *await _pkg_view(p))


@router.callback_query(F.data.regexp(r"^uc:price:\d+$"))
async def cb_price(call: CallbackQuery, state: FSMContext):
    uc = int(call.data.split(":")[2])
    p = await _pkg(uc)
    if not p:
        await call.answer("Paket topilmadi", show_alert=True)
        return
    await call.answer()
    await ask(call, state, AdminUC.waiting_price, card(
        "pencil", f"{fmt_num(uc)} UC — yangi narx",
        f"Joriy narx: <b>{fmt_num(p['price'])}</b> {esc(await currency())}",
        "Yangi narxni faqat raqam bilan yuboring, masalan: <code>13500</code>",
        "",
        f"{em('info')} Keyingi sinxronlashda narx Coindrop narxi + ustama bo'yicha qayta hisoblanadi.",
    ), back=f"uc:p:{uc}", uc=uc)


@router.message(AdminUC.waiting_price, F.text)
async def price_set(message: Message, state: FSMContext):
    raw = message.text.replace(" ", "")
    if not (raw.isascii() and raw.isdigit()) or not (0 < int(raw) <= MAX_PRICE):
        await invalid(message, state, "Narxni musbat butun son bilan yozing. Masalan: 13500")
        return
    uc = (await state.get_data()).get("uc")
    items = await db.get_uc_prices()
    p = next((x for x in items if x["uc"] == uc), None)
    if not p:
        await finish(message, state, *await uc_view(f"{em('warn')} Paket topilmadi."))
        return
    p["price"] = int(raw)
    await db.set_uc_prices(items)
    await finish(message, state, *await _pkg_view(p, f"{em('done')} <b>Narx yangilandi.</b>"))


@router.message(AdminUC.waiting_price)
async def price_invalid(message: Message, state: FSMContext):
    await invalid(message, state, "Narxni raqam bilan yuboring. Masalan: 13500")


@router.callback_query(F.data.regexp(r"^uc:del:\d+$"))
async def cb_del(call: CallbackQuery):
    uc = int(call.data.split(":")[2])
    await call.answer()
    await show(call, card("warn", f"{fmt_num(uc)} UC paketini o'chirish",
                          "Paket foydalanuvchilarga ko'rinmay qoladi.",
                          "Keyingi sinxronlashda u qayta paydo bo'lishi mumkin."),
               InlineKeyboardMarkup(inline_keyboard=[[
                   ibtn("done", "Ha, o'chirish", style="danger", callback_data=f"uc:delyes:{uc}"),
                   ibtn("cancel", "Yo'q", callback_data=f"uc:p:{uc}"),
               ]]))


@router.callback_query(F.data.regexp(r"^uc:delyes:\d+$"))
async def cb_del_yes(call: CallbackQuery):
    uc = int(call.data.split(":")[2])
    items = [p for p in await db.get_uc_prices() if p["uc"] != uc]
    await db.set_uc_prices(items)
    await call.answer("O'chirildi")
    await show(call, *await uc_view(f"{em('done')} <b>{fmt_num(uc)} UC paketi o'chirildi.</b>"))
