"""Admin panel: inline tugmalarning rangini sozlash (ko'k / yashil / qizil / rangsiz).

Rang tugma "kalit"i bo'yicha beriladi: masalan «done» kaliti — barcha «Tasdiqlash/Bajarildi» tugmalari.
Tugmalar ro'yxatida har bir tugma o'zining haqiqiy rangida ko'rinadi.
"""
from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

import database.db as db
import emojis
from emojis import SLOTS, STYLE_GROUPS, STYLE_NAMES, DEFAULT_STYLES, em, ibtn
from keyboards.user_kb import grid
from nav import show
from ui import IsAdmin, card

router = Router()
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())

PAGE_SIZE = 8


def _home():
    overrides = emojis.style_overrides()
    colored = sum(1 for g in STYLE_GROUPS.values() for k in g[1] if emojis.style_of(k) != "none")
    total = sum(len(g[1]) for g in STYLE_GROUPS.values())
    text = card(
        "palette", "Tugma ranglari",
        "Inline tugmalarni rangli qilish mumkin: ko'k, yashil yoki qizil.",
        "Rang tugma turi bo'yicha beriladi — masalan «Tasdiqlash» tugmasini yashil qilsangiz, botdagi barcha shunday tugmalar yashil bo'ladi.",
        "",
        f"Rangli tugmalar: <b>{colored}</b> / {total}",
        f"O'zgartirilgan: <b>{len(overrides)}</b> ta",
        "",
        f"{em('info')} Ranglar Telegramning yangi versiyalarida ko'rinadi; eski ilovalarda tugma oddiy bo'ladi.",
    )
    rows = [[ibtn("palette", f"{name} ({len(keys)})", callback_data=f"col:g:{gk}:0")]
            for gk, (name, keys) in STYLE_GROUPS.items()]
    rows.append([ibtn("refresh", "Hammasini standartga qaytarish", style="danger", callback_data="col:rst")])
    rows.append([ibtn("back", "Orqaga", callback_data="a:home")])
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


def _group(gk: str, page: int):
    name, keys = STYLE_GROUPS[gk]
    pages = max((len(keys) + PAGE_SIZE - 1) // PAGE_SIZE, 1)
    page = min(max(page, 0), pages - 1)
    chunk = keys[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]
    # tugma o'zining haqiqiy rangida ko'rinadi (ibtn ranglarni o'zi qo'llaydi)
    buttons = [ibtn(k, SLOTS[k][2], callback_data=f"col:s:{k}") for k in chunk]
    rows = grid(buttons, 2)
    nav = []
    if page > 0:
        nav.append(ibtn("prev", "Oldingi", callback_data=f"col:g:{gk}:{page - 1}"))
    if page < pages - 1:
        nav.append(ibtn("next", "Keyingi", callback_data=f"col:g:{gk}:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([ibtn("back", "Orqaga", callback_data="col:home")])
    text = card("palette", f"{name} — {page + 1}/{pages}", "Rangini o'zgartirmoqchi bo'lgan tugmani tanlang:")
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


def _slot(key: str, flash: str | None = None):
    cur = emojis.style_of(key)
    icon, cname = STYLE_NAMES[cur]
    default_icon, default_name = STYLE_NAMES[DEFAULT_STYLES.get(key, "none")]
    lines = [flash, ""] if flash else []
    lines += [
        f"Joriy rang: {icon} <b>{cname}</b>",
        f"Standart rang: {default_icon} {default_name}",
        "",
        "Yangi rangni tanlang:",
    ]
    # rang tanlash tugmalari — ibtn emas, to'g'ridan-to'g'ri (har biri o'z rangida ko'rinadi)
    choose = [
        InlineKeyboardButton(text=f"{STYLE_NAMES[s][0]} {STYLE_NAMES[s][1]}",
                             style=None if s == "none" else s, callback_data=f"col:set:{key}:{s}")
        for s in ("primary", "success", "danger", "none")
    ]
    rows = grid(choose, 2)
    if key in emojis.style_overrides():
        rows.append([ibtn("refresh", "Standartga qaytarish", callback_data=f"col:def:{key}")])
    gk = next(g for g, (_, keys) in STYLE_GROUPS.items() if key in keys)
    rows.append([ibtn("back", "Orqaga", callback_data=f"col:g:{gk}:0")])
    return card(key, SLOTS[key][2], *lines), InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data.in_({"col:home"}))
async def cb_home(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.answer()
    await show(call, *_home())


@router.callback_query(F.data.regexp(r"^col:g:[a-z]+:\d+$"))
async def cb_group(call: CallbackQuery):
    _, _, gk, page = call.data.split(":")
    if gk not in STYLE_GROUPS:
        await call.answer()
        return
    await call.answer()
    await show(call, *_group(gk, int(page)))


def _valid_key(key: str) -> bool:
    return any(key in keys for _, keys in STYLE_GROUPS.values()) and key in SLOTS


@router.callback_query(F.data.regexp(r"^col:s:[a-z_]+$"))
async def cb_slot(call: CallbackQuery):
    key = call.data.split(":")[2]
    if not _valid_key(key):
        await call.answer()
        return
    await call.answer()
    await show(call, *_slot(key))


@router.callback_query(F.data.regexp(r"^col:set:[a-z_]+:(primary|success|danger|none)$"))
async def cb_set(call: CallbackQuery):
    _, _, key, style = call.data.split(":")
    if not _valid_key(key):
        await call.answer()
        return
    await db.set_style(key, style)
    await emojis.load()
    await call.answer("Saqlandi")
    await show(call, *_slot(key, flash=f"{em('done')} <b>Rang saqlandi.</b>"))


@router.callback_query(F.data.regexp(r"^col:def:[a-z_]+$"))
async def cb_default(call: CallbackQuery):
    key = call.data.split(":")[2]
    if not _valid_key(key):
        await call.answer()
        return
    await db.delete_style(key)
    await emojis.load()
    await call.answer("Standart rang tiklandi")
    await show(call, *_slot(key, flash=f"{em('done')} <b>Standart rang tiklandi.</b>"))


@router.callback_query(F.data == "col:rst")
async def cb_reset_confirm(call: CallbackQuery):
    await call.answer()
    await show(call, card(
        "warn", "Ranglarni tiklashni tasdiqlang",
        f"Barcha {len(emojis.style_overrides())} ta o'zgartirilgan rang standartga qaytariladi.",
    ), InlineKeyboardMarkup(inline_keyboard=[[
        ibtn("done", "Ha, tiklash", callback_data="col:rst_yes"),
        ibtn("cancel", "Yo'q", callback_data="col:home"),
    ]]))


@router.callback_query(F.data == "col:rst_yes")
async def cb_reset(call: CallbackQuery):
    await db.clear_styles()
    await emojis.load()
    await call.answer("Tiklandi")
    await show(call, *_home())
