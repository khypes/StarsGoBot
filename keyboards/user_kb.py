from aiogram.types import InlineKeyboardMarkup

from emojis import ibtn, label
from ui import fmt_num


def grid(buttons: list, cols: int) -> list[list]:
    """Tugmalarni `cols` ustunli qatorlarga joylaydi."""
    return [buttons[i:i + cols] for i in range(0, len(buttons), cols)]


def main_menu(is_admin: bool = False, uc: bool = False) -> InlineKeyboardMarkup:
    """Bitta katta inline klaviatura: yuqorida mahsulotlar (to'liq kenglikdagi katta tugmalar), pastda bo'limlar."""
    def b(key: str, cb: str):
        return ibtn(key, label(key), callback_data=cb)

    rows = [[b("stars", "m:stars")], [b("premium", "m:premium")]]
    if uc:
        rows.append([b("uc", "m:uc")])
    rows += [
        [b("account", "m:account"), b("topup", "m:topup")],
        [b("orders", "m:orders"), b("referral", "m:ref")],
        [b("appeal", "m:appeal"), b("guide", "m:guide")],
    ]
    if is_admin:
        rows.append([b("panel", "a:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def back_kb(to: str = "m:home", text: str = "Orqaga") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[ibtn("back", text, callback_data=to)]])


def stars_prices_kb(prices: list, currency: str) -> InlineKeyboardMarkup:
    buttons = [
        ibtn("stars", f"{fmt_num(p['stars'])} · {fmt_num(p['price'])} {currency}",
             callback_data=f"b:s:{p['stars']}")
        for p in sorted(prices, key=lambda p: p["stars"])
    ]
    rows = grid(buttons, 2) + [[ibtn("back", "Orqaga", callback_data="m:home")]]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def premium_prices_kb(prices: list, currency: str) -> InlineKeyboardMarkup:
    buttons = [
        ibtn("calendar", f"{p['months']} oylik · {fmt_num(p['price'])} {currency}",
             callback_data=f"b:p:{p['months']}")
        for p in sorted(prices, key=lambda p: p["months"])
    ]
    rows = grid(buttons, 1) + [[ibtn("back", "Orqaga", callback_data="m:home")]]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def uc_prices_kb(prices: list, currency: str) -> InlineKeyboardMarkup:
    buttons = [
        ibtn("uc", f"{fmt_num(p['uc'])} UC · {fmt_num(p['price'])} {currency}", callback_data=f"b:u:{p['uc']}")
        for p in sorted(prices, key=lambda p: p["uc"])
    ]
    rows = grid(buttons, 2) + [[ibtn("back", "Orqaga", callback_data="m:home")]]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def recipient_kb(own_username: str | None, back: str) -> InlineKeyboardMarkup:
    rows = []
    if own_username:
        rows.append([ibtn("account", f"O'zimga (@{own_username})", style="primary", callback_data="b:self")])
    rows.append([ibtn("back", "Orqaga", callback_data=back)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def confirm_kb(price_text: str, back: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [ibtn("done", f"Tasdiqlash · {price_text}", style="success", callback_data="b:ok")],
        [ibtn("cancel", "Bekor qilish", callback_data=back)],
    ])


def channels_check_kb(channels) -> InlineKeyboardMarkup:
    rows = [[ibtn("megaphone", c["title"], url=c["url"])] for c in channels]
    rows.append([ibtn("done", "Tekshirish", style="success", callback_data="check_subs")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
