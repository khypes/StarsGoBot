from aiogram.types import InlineKeyboardMarkup

from emojis import ibtn, label
from keyboards.user_kb import grid


def _b(key: str, cb: str, **kw):
    return ibtn(key, label(key), callback_data=cb, **kw)


def admin_home_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_b("stats", "a:stats"), _b("broadcast", "a:bc")],
        [_b("users", "a:users"), _b("payment", "a:pay")],
        [_b("channels", "a:ch"), _b("settings", "a:set")],
        [_b("api", "a:cd", style="primary")],
        [_b("emojis", "em:home"), _b("palette", "col:home")],
        [ibtn("back", "Bosh menyu", callback_data="m:home")],
    ])


def back_admin_kb(to: str = "a:home", text: str = "Orqaga") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[ibtn("back", text, callback_data=to)]])


def settings_kb(notify_on: bool) -> InlineKeyboardMarkup:
    notify = "Bildirishnoma: yoqilgan" if notify_on else "Bildirishnoma: o'chirilgan"
    return InlineKeyboardMarkup(inline_keyboard=[
        [_b("currency", "s:cur"), _b("ref_percent", "s:ref")],
        [_b("stars_prices", "s:sp"), _b("premium_prices", "s:pp")],
        [ibtn("notify", notify, callback_data="s:notify")],
        [_b("admins", "s:adm")],
        [ibtn("back", "Orqaga", callback_data="a:home")],
    ])


def payment_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [ibtn("payment", "Karta raqami", callback_data="p:card"),
         ibtn("name", "Karta egasi", callback_data="p:holder")],
        [ibtn("back", "Orqaga", callback_data="a:home")],
    ])


def admins_kb(admin_ids: list[int], super_id: int) -> InlineKeyboardMarkup:
    rows = [
        [ibtn("trash", f"{uid}", callback_data=f"adm:del:{uid}")]
        for uid in admin_ids if uid != super_id
    ]
    rows.append([ibtn("plus", "Admin qo'shish", style="primary", callback_data="adm:add")])
    rows.append([ibtn("back", "Orqaga", callback_data="a:set")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def user_manage_kb(uid: int, banned: bool) -> InlineKeyboardMarkup:
    ban_btn = (ibtn("done", "Blokdan chiqarish", callback_data=f"u:unban:{uid}") if banned
               else ibtn("ban", "Bloklash", style="danger", callback_data=f"u:ban:{uid}"))
    return InlineKeyboardMarkup(inline_keyboard=[
        [ibtn("plus", "Balans qo'shish", style="success", callback_data=f"u:bal:{uid}:p"),
         ibtn("cancel", "Balans ayirish", callback_data=f"u:bal:{uid}:m")],
        [ban_btn],
        [ibtn("back", "Orqaga", callback_data="a:users")],
    ])


def order_action_kb(order_id: int, provider_status: str | None = None, locked: bool = False,
                    api_ready: bool = False) -> InlineKeyboardMarkup | None:
    """Buyurtma tugmalari.

    locked — API jarayonda: qo'lda bajarish/bekor qilish yopiq (ikki marta yetkazilmasligi uchun).
    """
    if locked:
        return None
    rows = []
    if api_ready and provider_status in (None, "error"):
        rows.append([ibtn("api", "API orqali yuborish", style="primary", callback_data=f"order_retry:{order_id}")])
    rows.append([
        ibtn("done", "Qo'lda bajarildi" if provider_status == "error" else "Bajarildi",
             style="success", callback_data=f"order_done:{order_id}"),
        ibtn("cancel", "Bekor qilish", style="danger", callback_data=f"order_cancel:{order_id}"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def topup_action_kb(tx_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        ibtn("done", "Tasdiqlash", style="success", callback_data=f"topup_ok:{tx_id}"),
        ibtn("cancel", "Rad etish", style="danger", callback_data=f"topup_no:{tx_id}"),
    ]])


def channels_kb(channels) -> InlineKeyboardMarkup:
    rows = [[ibtn("trash", f"{c['title']}", callback_data=f"ch:del:{c['id']}")] for c in channels]
    rows.append([ibtn("plus", "Kanal qo'shish", style="primary", callback_data="ch:add")])
    rows.append([ibtn("back", "Orqaga", callback_data="a:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def coindrop_kb(auto_on: bool, has_key: bool) -> InlineKeyboardMarkup:
    toggle = ibtn("cancel", "Avto-yetkazishni o'chirish", callback_data="cd:toggle") if auto_on \
        else ibtn("auto", "Avto-yetkazishni yoqish", style="success", callback_data="cd:toggle")
    rows = [
        [ibtn("apikey", "API kalitni o'zgartirish" if has_key else "API kalit kiritish",
              style=None if has_key else "primary", callback_data="cd:key")],
    ]
    if has_key:
        rows += [
            [toggle],
            [ibtn("refresh", "Balansni yangilash", callback_data="cd:refresh"),
             ibtn("sync", "Narxlarni sinxronlash", callback_data="cd:sync")],
            [ibtn("ref_percent", "Ustama foiz", callback_data="cd:markup"),
             ibtn("trash", "Kalitni o'chirish", style="danger", callback_data="cd:delkey")],
        ]
    rows.append([ibtn("back", "Orqaga", callback_data="a:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
