from aiogram.types import ReplyKeyboardMarkup, InlineKeyboardMarkup

from emojis import rbtn, ibtn
from ui import fmt_num


def grid(buttons: list, cols: int) -> list[list]:
    """Tugmalarni `cols` ustunli qatorlarga joylaydi."""
    return [buttons[i:i + cols] for i in range(0, len(buttons), cols)]


def _reply(rows, placeholder: str | None = None) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=rows, resize_keyboard=True, input_field_placeholder=placeholder
    )


def main_menu(is_admin: bool = False) -> ReplyKeyboardMarkup:
    rows = [
        [rbtn("stars"), rbtn("premium")],
        [rbtn("account"), rbtn("topup")],
        [rbtn("orders"), rbtn("referral")],
        [rbtn("appeal"), rbtn("guide")],
    ]
    if is_admin:
        rows.append([rbtn("panel")])
    return _reply(rows, "Bo'limni tanlang…")


def back_menu() -> ReplyKeyboardMarkup:
    return _reply([[rbtn("back")]])


def stars_prices_kb(prices: list, currency: str) -> InlineKeyboardMarkup:
    buttons = [
        ibtn("stars", f"{fmt_num(p['stars'])} · {fmt_num(p['price'])} {currency}",
             callback_data=f"buy_stars:{p['stars']}")
        for p in sorted(prices, key=lambda p: p["stars"])
    ]
    return InlineKeyboardMarkup(inline_keyboard=grid(buttons, 2))


def premium_prices_kb(prices: list, currency: str) -> InlineKeyboardMarkup:
    buttons = [
        ibtn("calendar", f"{p['months']} oylik · {fmt_num(p['price'])} {currency}",
             callback_data=f"buy_premium:{p['months']}")
        for p in sorted(prices, key=lambda p: p["months"])
    ]
    return InlineKeyboardMarkup(inline_keyboard=grid(buttons, 1))


def channels_check_kb(channels) -> InlineKeyboardMarkup:
    rows = [[ibtn("megaphone", c["title"], url=c["url"])] for c in channels]
    rows.append([ibtn("done", "Tekshirish", style="success", callback_data="check_subs")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
