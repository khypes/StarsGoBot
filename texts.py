"""Admin chatga yuboriladigan kartalar. Holat o'zgarganda matn bazadagi ma'lumotdan yangidan quriladi."""
import time

from emojis import em
from ui import card, esc, price

STALE_AFTER = 1800  # sekund: API jarayonida shundan ortiq tursa, qo'lda hal qilishga ruxsat


def _who(user, user_id: int) -> str:
    if user:
        name = esc(user["full_name"] or "—")
        uname = f"@{esc(user['username'])}" if user["username"] else "—"
    else:
        name, uname = "—", "—"
    return f"{em('account')} {name} (ID: <code>{user_id}</code>, {uname})"


def is_stale(order, now: float | None = None) -> bool:
    ps = order["provider_status"]
    if ps not in ("sending", "processing", "retry"):
        return False
    return (now or time.time()) - (order["provider_updated"] or 0) > STALE_AFTER


def provider_locked(order) -> bool:
    """API ishlayotgan buyurtmani qo'lda bajarish/bekor qilish mumkin emas (ikki marta yetkazilishi mumkin)."""
    return (
        order["status"] == "kutilmoqda"
        and order["provider_status"] in ("sending", "processing", "retry")
        and not is_stale(order)
    )


def status_line(order) -> str | None:
    st, ps = order["status"], order["provider_status"]
    if st == "bajarildi":
        return f"{em('done')} <b>BAJARILDI</b>" + (" (API orqali)" if ps == "delivered" else "")
    if st == "bekor qilindi":
        return f"{em('cancel')} <b>BEKOR QILINDI</b> (mablag' qaytarildi)"
    if ps in ("sending", "processing"):
        line = f"{em('api')} API: jarayonda…"
        if is_stale(order):
            line = f"{em('warn')} API javobi uzoq kechikdi — qo'lda hal qilishingiz mumkin"
        return line
    if ps == "retry":
        return f"{em('refresh')} API: qayta uriniladi ({order['provider_attempts'] or 0}) — {esc(order['provider_error'] or '')}"
    if ps == "error":
        return f"{em('warn')} <b>API xatosi:</b> {esc(order['provider_error'] or "noma'lum")}"
    return None


async def order_card(order, user) -> str:
    lines = [
        _who(user, order["user_id"]),
        f"{em('orders')} {esc(order['detail'])}",
    ]
    if order["recipient"]:
        lines.append(f"{em('link')} Qabul qiluvchi: <code>{esc(order['recipient'])}</code>")
    lines.append(f"{em('money')} {await price(order['price'])}")
    if order["provider_cost_usd"]:
        lines.append(f"{em('api')} API narxi: ${order['provider_cost_usd']:.2f}")
    status = status_line(order)
    if status:
        lines += ["", status]
    return card("new", f"Buyurtma #{order['id']}", *lines)


async def topup_card(tx, user, status: str | None = None) -> str:
    lines = [
        _who(user, tx["user_id"]),
        f"{em('money')} Summa: {await price(tx['amount'])}",
    ]
    if status:
        lines += ["", status]
    return card("topup", f"Hisob to'ldirish so'rovi #{tx['id']}", *lines)
