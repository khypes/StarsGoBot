"""Premium (custom) emoji tizimi.

Botdagi HAR BIR emoji — bu yerda ro'yxatga olingan "slot". Admin panel orqali har bir slotga
Telegram Premium emoji ID sini biriktirish mumkin:

  * xabarlarda   -> <tg-emoji emoji-id="ID">⭐</tg-emoji>
  * tugmalarda   -> InlineKeyboardButton(icon_custom_emoji_id=ID)  (Bot API 9.4+)

ID o'rnatilmagan yoki tizim o'chirilgan bo'lsa — oddiy (fallback) emoji ko'rsatiladi.

Eslatma (Telegram qoidasi): custom emoji bot xabarlarida faqat bot egasida Telegram Premium
bo'lsa ishlaydi. Ishlamasa, bot avtomatik oddiy emojiga qaytadi (fallback.py).
"""
from __future__ import annotations

import contextvars
import re

from aiogram.types import InlineKeyboardButton

GROUPS: dict[str, str] = {
    "menu": "Asosiy menyu",
    "admin": "Admin menyu",
    "msg": "Xabarlar va holatlar",
}

# key: (oddiy emoji, guruh, tavsif)
SLOTS: dict[str, tuple[str, str, str]] = {
    # --- asosiy menyu tugmalari ---
    "stars": ("⭐", "menu", "Stars olish"),
    "premium": ("🎁", "menu", "Premium olish"),
    "uc": ("🎮", "menu", "UC olish"),
    "orders": ("📦", "menu", "Buyurtmalarim"),
    "account": ("👤", "menu", "Mening hisobim"),
    "topup": ("💰", "menu", "Hisob to'ldirish"),
    "referral": ("🗣", "menu", "Referal"),
    "appeal": ("🏛", "menu", "Murojaat"),
    "guide": ("📗", "menu", "Qo'llanma"),
    "panel": ("🗄", "menu", "Boshqaruv"),
    "back": ("◀️", "menu", "Orqaga"),
    # --- admin menyu tugmalari ---
    "stats": ("📊", "admin", "Statistika"),
    "broadcast": ("📨", "admin", "Xabar yuborish"),
    "users": ("🔎", "admin", "Foydalanuvchilar"),
    "payment": ("💳", "admin", "To'lov tizimi"),
    "channels": ("📣", "admin", "Kanallar"),
    "settings": ("⚙️", "admin", "Sozlamalar"),
    "emojis": ("✨", "admin", "Premium emojilar"),
    "currency": ("💱", "admin", "Valyuta"),
    "ref_percent": ("👥", "admin", "Referal foizi"),
    "stars_prices": ("🌟", "admin", "Stars narxlari"),
    "premium_prices": ("💎", "admin", "Premium narxlari"),
    "notify": ("🔔", "admin", "Bildirishnoma"),
    "admins": ("🛡", "admin", "Adminlar"),
    "api": ("🔌", "admin", "API provayder"),
    "apikey": ("🗝", "admin", "API kalit"),
    "auto": ("⚡", "admin", "Avto-yetkazish"),
    "refresh": ("🔄", "admin", "Yangilash"),
    "sync": ("🔁", "admin", "Narxlarni sinxronlash"),
    "palette": ("🎨", "admin", "Tugma ranglari"),
    "uc_sell": ("🪙", "admin", "UC sotish"),
    "uc_player": ("🕹", "msg", "PUBG Player ID"),
    # --- xabarlar va holatlar ---
    "wave": ("👋", "msg", "Salomlashish"),
    "rocket": ("🚀", "msg", "Raketa"),
    "down": ("👇", "msg", "Pastga ko'rsatkich"),
    "link": ("🔗", "msg", "Havola"),
    "calendar": ("📅", "msg", "Kalendar (oylik tarif)"),
    "pending": ("⏳", "msg", "Kutilmoqda"),
    "done": ("✅", "msg", "Bajarildi / tasdiqlandi"),
    "cancel": ("❌", "msg", "Bekor / rad etildi"),
    "warn": ("❗️", "msg", "Ogohlantirish"),
    "megaphone": ("📢", "msg", "Kanal / e'lon"),
    "money": ("💵", "msg", "Pul / narx"),
    "pencil": ("✍️", "msg", "Yozish"),
    "home": ("🏠", "msg", "Bosh menyu"),
    "inbox": ("📭", "msg", "Bo'sh ro'yxat"),
    "new": ("🆕", "msg", "Yangi"),
    "ban": ("🚫", "msg", "Bloklash"),
    "id": ("🆔", "msg", "ID"),
    "people": ("👥", "msg", "Odamlar"),
    "bonus": ("🎉", "msg", "Bonus"),
    "plus": ("➕", "msg", "Qo'shish"),
    "trash": ("🗑", "msg", "O'chirish"),
    "test": ("🧪", "msg", "Sinash"),
    "prev": ("⬅️", "msg", "Oldingi"),
    "next": ("➡️", "msg", "Keyingi"),
    "info": ("ℹ️", "msg", "Izoh / maslahat"),
    "name": ("🪪", "msg", "Ism / egasi"),
}

# ---- tugma ranglari (Bot API 9.4: primary=ko'k, success=yashil, danger=qizil) ----
STYLE_NAMES: dict[str, tuple[str, str]] = {
    "primary": ("🔵", "Ko'k"),
    "success": ("🟢", "Yashil"),
    "danger": ("🔴", "Qizil"),
    "none": ("⚪", "Rangsiz"),
}

# Tugma "kalit"lari (emoji slotlari bilan bir xil), ranglar shu kalit bo'yicha belgilanadi
DEFAULT_STYLES: dict[str, str] = {
    "stars": "primary", "premium": "primary", "uc": "primary", "uc_sell": "primary", "topup": "success", "panel": "danger",
    "stats": "primary", "broadcast": "primary", "payment": "success", "api": "primary",
    "apikey": "primary", "auto": "success", "sync": "primary", "emojis": "primary", "palette": "primary",
    "done": "success", "cancel": "danger", "ban": "danger", "trash": "danger", "plus": "success",
    "calendar": "primary",
}

# Rang berish mumkin bo'lgan tugmalar guruhlari
STYLE_GROUPS: dict[str, tuple[str, list[str]]] = {
    "menu": ("Asosiy menyu", ["stars", "premium", "uc", "account", "topup", "orders", "referral", "appeal", "guide", "panel"]),
    "admin": ("Admin menyu", ["stats", "broadcast", "users", "payment", "channels", "settings", "api", "emojis",
                              "palette", "uc_sell", "currency", "ref_percent", "stars_prices", "premium_prices", "notify",
                              "admins", "apikey", "auto", "refresh", "sync"]),
    "actions": ("Amal tugmalari", ["done", "cancel", "back", "plus", "trash", "ban", "calendar", "megaphone",
                                   "prev", "next"]),
}

_styles: dict[str, str] = {}
_custom: dict[str, str] = {}
_enabled: bool = True

# Sinash paytida avtomatik fallback'ni o'chirish uchun (admin xatoni ko'rsin)
NO_FALLBACK: contextvars.ContextVar[bool] = contextvars.ContextVar("no_emoji_fallback", default=False)

_ID_RE = re.compile(r"^\d{5,25}$")
_TG_EMOJI_RE = re.compile(r'<tg-emoji emoji-id="\d+">(.*?)</tg-emoji>', re.DOTALL)


# ---------- holat ----------

async def load() -> None:
    """Bazadan emoji ID lar va yoqilgan/o'chirilgan holatni keshga yuklaydi."""
    global _custom, _enabled
    from database import db

    stored = await db.get_emojis()
    _custom = {k: v for k, v in stored.items() if k in SLOTS}
    _enabled = (await db.get_setting("premium_emoji_enabled")) != "0"
    global _styles
    _styles = {k: v for k, v in (await db.get_styles()).items() if v in STYLE_NAMES}


def is_enabled() -> bool:
    return _enabled


def custom_ids() -> dict[str, str]:
    return dict(_custom)


def style_of(key: str) -> str:
    """Tugmaning joriy rangi (primary|success|danger|none)."""
    return _styles.get(key) or DEFAULT_STYLES.get(key) or "none"


def style_overrides() -> dict[str, str]:
    return dict(_styles)


def count_set() -> int:
    return len(_custom)


def valid_id(value: str) -> bool:
    return bool(_ID_RE.match(value or ""))


def fallback_for_id(custom_id: str) -> str:
    for key, cid in _custom.items():
        if cid == custom_id:
            return SLOTS[key][0]
    return ""


def _active_id(key: str) -> str | None:
    return _custom.get(key) if _enabled else None


# ---------- chiqarish ----------

def plain(key: str) -> str:
    """Oddiy (fallback) emoji."""
    return SLOTS[key][0]


def em(key: str) -> str:
    """Xabar matni (HTML) uchun emoji."""
    cid = _active_id(key)
    if cid:
        return f'<tg-emoji emoji-id="{cid}">{SLOTS[key][0]}</tg-emoji>'
    return SLOTS[key][0]


def label(key: str) -> str:
    """Slotning tugma matni (emojisiz)."""
    return SLOTS[key][2]


def ibtn(key: str, label: str, style: str | None = None, **kwargs) -> InlineKeyboardButton:
    """Inline tugma (callback_data=... yoki url=...)."""
    effective = _styles.get(key) or style or DEFAULT_STYLES.get(key)
    extra = {"style": effective} if effective and effective != "none" else {}
    cid = _active_id(key)
    if cid:
        return InlineKeyboardButton(text=label, icon_custom_emoji_id=cid, **extra, **kwargs)
    return InlineKeyboardButton(text=f"{SLOTS[key][0]} {label}", **extra, **kwargs)


# ---------- fallback uchun yordamchilar ----------

def strip_text(text: str | None) -> str | None:
    if not text or "<tg-emoji" not in text:
        return text
    return _TG_EMOJI_RE.sub(lambda m: m.group(1), text)


def strip_markup(markup):
    """Tugmalardagi icon_custom_emoji_id ni olib tashlab, oddiy emojini matnga qo'shadi."""
    from aiogram.types import InlineKeyboardMarkup

    if not isinstance(markup, InlineKeyboardMarkup):
        return markup, False
    field, rows = "inline_keyboard", markup.inline_keyboard

    changed = False
    new_rows = []
    for row in rows:
        new_row = []
        for button in row:
            icon = getattr(button, "icon_custom_emoji_id", None)
            if icon:
                fb = fallback_for_id(icon)
                text = f"{fb} {button.text}".strip()
                button = button.model_copy(update={"icon_custom_emoji_id": None, "text": text})
                changed = True
            new_row.append(button)
        new_rows.append(new_row)
    if not changed:
        return markup, False
    return markup.model_copy(update={field: new_rows}), True
