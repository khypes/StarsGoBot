"""Admin panel: barcha emojilarni Telegram Premium (custom) emoji ID orqali boshqarish."""
import contextlib

from aiogram import Router, F, Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup

import database.db as db
import emojis
from emojis import SLOTS, GROUPS, em, ibtn
from keyboards.user_kb import grid
from nav import ask, invalid, finish, render_input
from states.states import AdminEmoji
from ui import IsAdmin, card, esc

router = Router()
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())

PAGE_SIZE = 8


# ==================== ko'rinishlar ====================

def _home_text() -> str:
    status = "yoqilgan" if emojis.is_enabled() else "o'chirilgan"
    return card(
        "emojis", "Premium emojilar",
        f"{em('done') if emojis.is_enabled() else em('cancel')} Holat: <b>{status}</b>",
        f"O'rnatilgan: <b>{emojis.count_set()}</b> / {len(SLOTS)}",
        "",
        "Har bir tugma va xabar emojisiga Telegram Premium emoji ID sini biriktiring. "
        "ID o'rnatilmagan joyda oddiy emoji ko'rinadi.",
        "",
        f"{em('warn')} Telegram qoidasi: custom emoji bot xabarlarida faqat <b>bot egasida Telegram Premium</b> "
        "bo'lsa ishlaydi. Ishlamasa, bot avtomatik oddiy emojiga qaytadi. «Sinash» tugmasi buni tekshiradi.",
    )


def _home_kb() -> InlineKeyboardMarkup:
    toggle_label = "O'chirish" if emojis.is_enabled() else "Yoqish"
    rows = [
        [ibtn("notify", toggle_label, callback_data="em:toggle"),
         ibtn("test", "Sinash", callback_data="em:test")],
    ]
    for gkey, gname in GROUPS.items():
        total = sum(1 for v in SLOTS.values() if v[1] == gkey)
        done = sum(1 for k, v in SLOTS.items() if v[1] == gkey and k in emojis.custom_ids())
        rows.append([ibtn("emojis", f"{gname} ({done}/{total})", callback_data=f"em:g:{gkey}:0")])
    rows.append([ibtn("pencil", "Ommaviy kiritish", callback_data="em:bulk"),
                 ibtn("trash", "Hammasini tozalash", style="danger", callback_data="em:rst")])
    rows.append([ibtn("back", "Orqaga", callback_data="a:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _group_keys(gkey: str) -> list[str]:
    return [k for k, v in SLOTS.items() if v[1] == gkey]


def _group_view(gkey: str, page: int):
    keys = _group_keys(gkey)
    pages = max((len(keys) + PAGE_SIZE - 1) // PAGE_SIZE, 1)
    page = min(max(page, 0), pages - 1)
    chunk = keys[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]
    ids = emojis.custom_ids()
    buttons = [
        ibtn(k, SLOTS[k][2] + (" ✓" if k in ids else ""), callback_data=f"em:s:{k}")
        for k in chunk
    ]
    rows = grid(buttons, 2)
    nav = []
    if page > 0:
        nav.append(ibtn("prev", "Oldingi", callback_data=f"em:g:{gkey}:{page - 1}"))
    if page < pages - 1:
        nav.append(ibtn("next", "Keyingi", callback_data=f"em:g:{gkey}:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([ibtn("back", "Orqaga", callback_data="em:home")])
    text = card(
        "emojis", f"{GROUPS[gkey]} — {page + 1}/{pages}",
        "Emojini tanlang (✓ — Premium emoji o'rnatilgan):",
    )
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


def _slot_view(key: str, flash: str | None = None):
    fb, gkey, desc = SLOTS[key]
    cid = emojis.custom_ids().get(key)
    lines = []
    if flash:
        lines += [flash, ""]
    lines += [
        f"Kalit: <code>{key}</code>",
        f"Oddiy emoji: {fb}",
        f"Premium ID: <code>{cid}</code>" if cid else "Premium ID: o'rnatilmagan",
        f"Ko'rinishi: {em(key)}",
        "",
        "Yangi Premium emojini <b>xabar qilib yuboring</b> (ID avtomatik olinadi) "
        "yoki raqamli ID ni kiriting.",
    ]
    rows = []
    if cid:
        rows.append([ibtn("trash", "Olib tashlash", style="danger", callback_data=f"em:del:{key}")])
    rows.append([ibtn("back", "Orqaga", callback_data=f"em:g:{gkey}:0")])
    return card(key, desc, *lines), InlineKeyboardMarkup(inline_keyboard=rows)


def extract_id(message: Message) -> str | None:
    """Xabardan custom emoji ID sini oladi: premium emoji, custom emoji stikeri yoki raqam."""
    for ent in message.entities or []:
        if ent.type == "custom_emoji" and ent.custom_emoji_id:
            return ent.custom_emoji_id
    if message.sticker and message.sticker.custom_emoji_id:
        return message.sticker.custom_emoji_id
    text = (message.text or "").strip()
    return text if emojis.valid_id(text) else None


async def _edit(call: CallbackQuery, text: str, markup: InlineKeyboardMarkup):
    with contextlib.suppress(TelegramBadRequest):
        await call.message.edit_text(text, reply_markup=markup)


# ==================== kirish ====================

@router.callback_query(F.data == "em:home")
async def cb_home(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.answer()
    await _edit(call, _home_text(), _home_kb())


@router.callback_query(F.data.startswith("em:g:"))
async def cb_group(call: CallbackQuery, state: FSMContext):
    _, _, gkey, page = call.data.split(":")
    if gkey not in GROUPS:
        await call.answer()
        return
    await state.clear()
    await call.answer()
    text, markup = _group_view(gkey, int(page))
    await _edit(call, text, markup)


@router.callback_query(F.data.startswith("em:s:"))
async def cb_slot(call: CallbackQuery, state: FSMContext):
    key = call.data.split(":", 2)[2]
    if key not in SLOTS:
        await call.answer()
        return
    await state.clear()
    await state.set_state(AdminEmoji.waiting_value)
    await state.update_data(slot=key, prompt_mid=call.message.message_id,
                            prompt_cid=call.message.chat.id, back=f"em:g:{SLOTS[key][1]}:0")
    await call.answer()
    text, markup = _slot_view(key)
    await state.update_data(prompt_text=text)
    await _edit(call, text, markup)


# ==================== qiymat qabul qilish ====================

@router.message(AdminEmoji.waiting_value)
async def slot_receive(message: Message, state: FSMContext):
    key = (await state.get_data()).get("slot")
    if key not in SLOTS:
        await state.clear()
        return
    value = extract_id(message)
    if not value:
        await invalid(message, state, "Premium emoji yuboring yoki 5–25 xonali ID kiriting.")
        return
    await db.set_emoji(key, value)
    await emojis.load()
    text, markup = _slot_view(key, flash=f"{em('done')} <b>Saqlandi!</b>")
    await render_input(message, state, text, markup)
    await state.update_data(prompt_text=text)


@router.callback_query(F.data.startswith("em:del:"))
async def cb_delete(call: CallbackQuery):
    key = call.data.split(":", 2)[2]
    if key not in SLOTS:
        await call.answer()
        return
    await db.delete_emoji(key)
    await emojis.load()
    await call.answer("Olib tashlandi")
    text, markup = _slot_view(key, flash=f"{em('done')} <b>Olib tashlandi.</b>")
    await _edit(call, text, markup)


# ==================== yoqish / sinash / tozalash ====================

@router.callback_query(F.data == "em:toggle")
async def cb_toggle(call: CallbackQuery):
    await db.set_setting("premium_emoji_enabled", "0" if emojis.is_enabled() else "1")
    await emojis.load()
    await call.answer("Holat o'zgartirildi")
    await _edit(call, _home_text(), _home_kb())


@router.callback_query(F.data == "em:test")
async def cb_test(call: CallbackQuery, bot: Bot):
    """Haqiqiy so'rovni fallback'siz yuboradi — Telegram rad etsa, sababini ko'rsatadi."""
    ids = emojis.custom_ids()
    if not ids:
        await call.answer("Avval kamida bitta Premium emoji ID o'rnating", show_alert=True)
        return
    if not emojis.is_enabled():
        await call.answer("Avval tizimni yoqing", show_alert=True)
        return
    key = next(iter(ids))
    token = emojis.NO_FALLBACK.set(True)
    try:
        await bot.send_message(
            call.message.chat.id,
            f"{em(key)} Matn ichidagi Premium emoji",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                ibtn(key, "Yopish", callback_data="em:close")
            ]]),
        )
        await call.answer("Sinov xabari yuborildi. Emoji animatsiyali ko'rinsa — hammasi ishlayapti.", show_alert=True)
    except TelegramBadRequest as exc:
        await call.answer()
        await call.message.answer(card(
            "warn", "Premium emoji ishlamadi",
            f"Telegram javobi: <code>{esc(exc.message)}</code>",
            "",
            "Odatda sabab: bot egasida Telegram Premium yo'q, ID noto'g'ri yoki yangi Bot API "
            "(9.4+) qo'llab-quvvatlanmaydi. Hozircha bot oddiy emoji bilan ishlaydi.",
        ))
    finally:
        emojis.NO_FALLBACK.reset(token)


@router.callback_query(F.data == "em:close")
async def cb_close(call: CallbackQuery):
    await call.answer()
    with contextlib.suppress(Exception):
        await call.message.delete()


@router.callback_query(F.data == "em:rst")
async def cb_reset_confirm(call: CallbackQuery):
    markup = InlineKeyboardMarkup(inline_keyboard=[[
        ibtn("done", "Ha, tozalash", style="danger", callback_data="em:rst_yes"),
        ibtn("cancel", "Yo'q", callback_data="em:home"),
    ]])
    await call.answer()
    await _edit(call, card("warn", "Tozalashni tasdiqlang",
                           f"{emojis.count_set()} ta Premium emoji ID o'chiriladi. Davom etasizmi?"), markup)


@router.callback_query(F.data == "em:rst_yes")
async def cb_reset(call: CallbackQuery):
    await db.clear_emojis()
    await emojis.load()
    await call.answer("Tozalandi")
    await _edit(call, _home_text(), _home_kb())


# ==================== ommaviy kiritish ====================

@router.callback_query(F.data == "em:bulk")
async def cb_bulk(call: CallbackQuery, state: FSMContext):
    await call.answer()
    keys = "\n".join(f"<code>{k}</code> — {SLOTS[k][2]}" for k in SLOTS)
    await ask(call, state, AdminEmoji.waiting_bulk, card(
        "pencil", "Ommaviy kiritish",
        "Har qatorga bittadan: <code>kalit=ID</code>",
        "ID o'rniga <code>0</code> yozsangiz — emoji olib tashlanadi.",
        "Masalan:\n<code>stars=5368324170671202286\npremium=5377336227997546019</code>",
        "",
        "<b>Kalitlar:</b>\n" + keys,
        expandable=True,
    ), back="em:home")


@router.message(AdminEmoji.waiting_bulk, F.text)
async def bulk_receive(message: Message, state: FSMContext):
    saved, removed, bad = 0, 0, []
    for raw in message.text.splitlines():
        line = raw.strip()
        if not line:
            continue
        key, sep, value = line.replace(" ", "").partition("=")
        if not sep:
            key, _, value = line.partition(" ")
        key, value = key.strip().lower(), value.strip()
        if key not in SLOTS:
            bad.append(raw.strip())
        elif value == "0":
            await db.delete_emoji(key)
            removed += 1
        elif emojis.valid_id(value):
            await db.set_emoji(key, value)
            saved += 1
        else:
            bad.append(raw.strip())
    await emojis.load()
    lines = [f"Saqlandi: <b>{saved}</b>", f"Olib tashlandi: <b>{removed}</b>"]
    if bad:
        lines += ["", "O'qilmagan qatorlar:"] + [f"<code>{esc(b)}</code>" for b in bad[:15]]
    flash = card("done" if not bad else "warn", "Natija", *lines)
    await finish(message, state, _home_text(), _home_kb(), flash=flash)


@router.message(AdminEmoji.waiting_bulk)
async def bulk_invalid(message: Message, state: FSMContext):
    await invalid(message, state, "Matn ko'rinishida kalit=ID yuboring.")
