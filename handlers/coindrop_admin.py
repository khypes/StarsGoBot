"""Admin panel: API provayderlar (Coindrop.uz, TgSuperstars) — tanlash, kalit, avto-yetkazish, kurs, narx sinxronlash."""
import json

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup

import database.db as db
import fulfillment
from coindrop import CoinDropError
from emojis import em, ibtn
from keyboards.admin_kb import coindrop_kb
from nav import show, ask, invalid, finish
from providers import REGISTRY, MAX_STARS_PACKAGES, title_of
from states.states import AdminCoinDrop
from ui import IsAdmin, card, esc, fmt_num, currency

router = Router()
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())


def mask(key: str) -> str:
    return f"{key[:5]}…{key[-4:]}" if len(key) > 10 else "•••"


async def _prov():
    """Faol provayder sinfi va uning kaliti."""
    name = await fulfillment.active_name()
    return REGISTRY[name], await fulfillment.api_key(name)


async def _rate() -> float:
    try:
        return float(await db.get_setting("usd_rate") or 0)
    except ValueError:
        return 0.0


# ==================== asosiy ekran ====================

async def cd_view(flash: str | None = None):
    cls, key = await _prov()
    enabled = await fulfillment.is_enabled()
    usd = cls.currency == "USD"
    lines = [flash, ""] if flash else []
    lines.append(f"{em('api')} Faol provayder: <b>{esc(cls.title)}</b> ({esc(cls.site)})")
    if not key:
        lines += [
            "",
            "API kalit hali kiritilmagan.",
            f"Kalitni olish: {cls.key_where} ({esc(cls.key_hint)}).",
            "Kalit kiritilgach Stars va Premium buyurtmalari avtomatik yetkaziladi.",
        ]
    else:
        lines += [
            f"{em('apikey')} Kalit: <code>{esc(mask(key))}</code>",
            f"{em('auto')} Avto-yetkazish: <b>{'yoqilgan' if enabled else "o'chirilgan"}</b>",
            f"{em('ref_percent')} Narx ustamasi: <b>{esc(await db.get_setting('coindrop_markup'))}%</b>",
        ]
        if usd:
            rate = await _rate()
            lines.append(f"{em('currency')} Kurs: " + (f"<b>1$ = {fmt_num(int(rate))} so'm</b>" if rate
                                                      else "<b>kiritilmagan</b> — narx sinxronlash uchun kerak"))
        try:
            acc = await cls(key).account()
            lines.append("")
            if acc.get("name"):
                lines.append(f"{em('account')} Akkaunt: {esc(str(acc['name']))}")
            lines += [f"{em('money')} {line}" if i == 0 else f"{em('currency')} {line}"
                      for i, line in enumerate(acc.get("lines") or [])]
            if acc.get("warn"):
                lines.append(f"{em('warn')} {esc(acc['warn'])}")
        except CoinDropError as exc:
            lines += ["", f"{em('warn')} <b>Ulanib bo'lmadi:</b> {esc(exc.human())}"]
    return card("api", f"{cls.title} API", *lines), coindrop_kb(enabled, bool(key), usd)


@router.callback_query(F.data.in_({"a:cd", "cd:refresh"}))
async def cb_open(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.answer()
    await show(call, *await cd_view())


# ==================== provayderni tanlash ====================

_ABOUT = {
    "coindrop": ("so'mda, O'zbekiston kartalari orqali to'ldiriladi, narxlar so'mda",
                 "Stars 50–10 000, Premium 3/6/12 oy"),
    "tgsuperstars": ("dollarda (USDT orqali to'ldiriladi), rasmiy hujjatlashtirilgan API, idempotency",
                     "Stars 50–50 000, Premium 3/6/12 oy"),
}


@router.callback_query(F.data == "cd:prov")
async def cb_providers(call: CallbackQuery):
    await call.answer()
    active = await fulfillment.active_name()
    lines = ["Qaysi API orqali buyurtmalar avtomatik yetkazilsin?", ""]
    rows = []
    for name, cls in REGISTRY.items():
        mark = "✅ " if name == active else ""
        keyed = "kalit bor" if await fulfillment.has_key(name) else "kalit yo'q"
        how, limits = _ABOUT.get(name, ("", ""))
        lines += [f"{em('api')} <b>{mark}{esc(cls.title)}</b> — {keyed}", f"      {esc(how)}", f"      {esc(limits)}", ""]
        rows.append([ibtn("api", f"{mark}{cls.title}", style="success" if name == active else "primary",
                          callback_data=f"cd:use:{name}")])
    lines.append(f"{em('info')} Yo'lda turgan buyurtmalar avvalgi provayder orqali yakunlanadi, yangilari tanlanganiga ketadi.")
    rows.append([ibtn("back", "Orqaga", callback_data="a:cd")])
    await show(call, card("api", "API provayderni tanlash", *lines), InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.regexp(r"^cd:use:[a-z]+$"))
async def cb_use(call: CallbackQuery):
    name = call.data.split(":")[2]
    if name not in REGISTRY:
        await call.answer("Noma'lum provayder", show_alert=True)
        return
    await db.set_setting("api_provider", name)
    await call.answer(f"{REGISTRY[name].title} tanlandi")
    await show(call, *await cd_view(f"{em('done')} <b>{esc(REGISTRY[name].title)}</b> faol provayder qilindi."))


# ==================== kalit ====================

@router.callback_query(F.data == "cd:key")
async def cb_key(call: CallbackQuery, state: FSMContext):
    await call.answer()
    cls, _ = await _prov()
    await ask(call, state, AdminCoinDrop.waiting_key, card(
        "apikey", f"{cls.title} — API kalit",
        f"{esc(cls.title)} kalitingizni yuboring ({esc(cls.key_hint)}).",
        f"Kalitni olish: {cls.key_where}",
        "",
        "Xavfsizlik uchun xabaringiz darhol o'chiriladi.",
    ), back="a:cd")


@router.message(AdminCoinDrop.waiting_key, F.text)
async def key_receive(message: Message, state: FSMContext):
    cls, _ = await _prov()
    key = message.text.strip()
    if not cls.key_re.match(key):
        await invalid(message, state, f"Kalit noto'g'ri ko'rinishda. U {cls.key_hint}.")
        return
    try:
        await cls(key).account()
    except CoinDropError as exc:
        await invalid(message, state, exc.human())
        return
    await db.set_setting(cls.key_setting, key)
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
    cls, _ = await _prov()
    await db.set_setting(cls.key_setting, "")
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
        "Narxlarni sinxronlashda provayder narxiga qo'shiladigan foizni yuboring (0–500).",
        "",
        f"{em('info')} Masalan, 10 yozsangiz: provayder narxi 100 000 bo'lsa, sizda 110 000 bo'ladi.",
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


# ==================== dollar kursi (USD bilan ishlaydigan provayderlar) ====================

@router.callback_query(F.data == "cd:rate")
async def cb_rate(call: CallbackQuery, state: FSMContext):
    await call.answer()
    rate = await _rate()
    await ask(call, state, AdminCoinDrop.waiting_rate, card(
        "currency", "Dollar kursi",
        "Joriy: " + (f"<b>1$ = {fmt_num(int(rate))} so'm</b>" if rate else "<b>kiritilmagan</b>"),
        "1 dollar necha so'm ekanini yuboring, masalan: <code>12800</code>",
        "",
        f"{em('info')} Provayder narxlari dollarda. Narxlarni so'mga o'tkazish uchun kurs kerak — "
        "uni kerak bo'lganda shu yerdan yangilab turing.",
    ), back="a:cd")


@router.message(AdminCoinDrop.waiting_rate, F.text)
async def rate_set(message: Message, state: FSMContext):
    raw = message.text.strip().replace(" ", "")
    if not (raw.isascii() and raw.isdigit()) or not (1000 <= int(raw) <= 100000):
        await invalid(message, state, "Kursni so'mda, 1000 dan 100000 gacha butun son bilan yozing. Masalan: 12800")
        return
    await db.set_setting("usd_rate", raw)
    await finish(message, state, *await cd_view(f"{em('done')} <b>Kurs yangilandi.</b>"))


@router.message(AdminCoinDrop.waiting_rate)
async def rate_invalid(message: Message, state: FSMContext):
    await invalid(message, state, "Kursni raqam bilan yuboring. Masalan: 12800")


# ==================== narxlarni sinxronlash ====================

async def build_sync(prov, markup: int, rate: float = 0.0, stars_qtys: list[int] | None = None):
    return await prov.price_list(markup, rate, stars_qtys or [])


@router.callback_query(F.data == "cd:sync")
async def cb_sync(call: CallbackQuery, state: FSMContext):
    cls, key = await _prov()
    if not key:
        await call.answer("Avval API kalitni kiriting", show_alert=True)
        return
    rate = await _rate()
    if cls.currency == "USD" and not rate:
        await call.answer("Avval dollar kursini kiriting", show_alert=True)
        return
    await call.answer("Narxlar yuklanmoqda…")
    markup = int(await db.get_setting("coindrop_markup") or 0)
    try:
        qtys = [p["stars"] for p in await db.get_stars_prices()]
        stars, premium, truncated = await build_sync(cls(key), markup, rate, qtys)
    except CoinDropError as exc:
        await show(call, *await cd_view(f"{em('warn')} <b>Narxlarni olib bo'lmadi:</b> {esc(exc.human())}"))
        return
    if not stars and not premium:
        await show(call, *await cd_view(f"{em('warn')} {esc(cls.title)} mahsulotlar ro'yxatini qaytarmadi."))
        return
    await state.update_data(sync_stars=stars, sync_premium=premium)

    lines = [f"Ustama: <b>{markup}%</b> ({esc(cls.title)} narxi → sizning narxingiz)", ""]
    lines += [f"{em('stars')} {fmt_num(s['stars'])} Stars: {fmt_num(s['cost'])} → <b>{fmt_num(s['price'])}</b>" for s in stars]
    if truncated:
        lines.append(f"(birinchi {MAX_STARS_PACKAGES} ta paket)")
    lines += [f"{em('premium')} {p['months']} oy: {fmt_num(p['cost'])} → <b>{fmt_num(p['price'])}</b>" for p in premium]
    if cls.currency == "USD":
        lines += ["", f"{em('info')} Stars paketlari hozirgi paket miqdorlaringiz bo'yicha hisoblandi (kurs: 1$ = {fmt_num(int(rate))} so'm)."]
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
