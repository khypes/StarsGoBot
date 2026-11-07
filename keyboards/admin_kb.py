from aiogram.types import ReplyKeyboardMarkup, InlineKeyboardMarkup

from emojis import rbtn, ibtn


def _reply(rows) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def admin_panel_kb() -> ReplyKeyboardMarkup:
    return _reply([
        [rbtn("stats"), rbtn("broadcast")],
        [rbtn("users"), rbtn("payment")],
        [rbtn("channels"), rbtn("settings")],
        [rbtn("emojis")],
        [rbtn("back")],
    ])


def system_settings_kb() -> ReplyKeyboardMarkup:
    return _reply([
        [rbtn("currency"), rbtn("ref_percent")],
        [rbtn("stars_prices"), rbtn("premium_prices")],
        [rbtn("ton"), rbtn("notify")],
        [rbtn("admins")],
        [rbtn("back")],
    ])


def order_action_kb(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        ibtn("done", "Bajarildi", style="success", callback_data=f"order_done:{order_id}"),
        ibtn("cancel", "Bekor qilish", style="danger", callback_data=f"order_cancel:{order_id}"),
    ]])


def topup_action_kb(tx_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        ibtn("done", "Tasdiqlash", style="success", callback_data=f"topup_ok:{tx_id}"),
        ibtn("cancel", "Rad etish", style="danger", callback_data=f"topup_no:{tx_id}"),
    ]])


def channels_kb(channels) -> InlineKeyboardMarkup:
    rows = [
        [ibtn("trash", f"{c['title']}", callback_data=f"ch:del:{c['id']}")]
        for c in channels
    ]
    rows.append([ibtn("plus", "Kanal qo'shish", style="primary", callback_data="ch:add")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
