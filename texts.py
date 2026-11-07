"""Admin chatga yuboriladigan kartalar (qayta chizish mumkin: holat o'zgarganda matn bazadan yangidan quriladi)."""
from emojis import em
from ui import card, esc, price


def _who(user, user_id: int) -> str:
    if user:
        name = esc(user["full_name"] or "—")
        uname = f"@{esc(user['username'])}" if user["username"] else "—"
    else:
        name, uname = "—", "—"
    return f"{em('account')} {name} (ID: <code>{user_id}</code>, {uname})"


async def order_card(order, user, status: str | None = None) -> str:
    lines = [
        _who(user, order["user_id"]),
        f"{em('orders')} {esc(order['detail'])}",
        f"{em('money')} {await price(order['price'])}",
    ]
    if status:
        lines += ["", status]
    return card("new", f"Yangi buyurtma #{order['id']}", *lines)


async def topup_card(tx, user, status: str | None = None) -> str:
    lines = [
        _who(user, tx["user_id"]),
        f"{em('money')} Summa: {await price(tx['amount'])}",
    ]
    if status:
        lines += ["", status]
    return card("topup", f"Hisob to'ldirish so'rovi #{tx['id']}", *lines)
