"""Umumiy ko'rinish yordamchilari: escape, <blockquote>, narx formati, tugma filtri."""
import html

from aiogram.filters import BaseFilter
from aiogram.types import Message

import database.db as db
from emojis import em


def esc(value) -> str:
    return html.escape(str(value if value is not None else ""), quote=False)


def q(*lines: str, expandable: bool = False) -> str:
    """Matnni <blockquote> ichiga o'raydi."""
    body = "\n".join(lines)
    tag = "<blockquote expandable>" if expandable else "<blockquote>"
    return f"{tag}{body}</blockquote>"


def card(emoji_key: str, title: str, *lines: str, expandable: bool = False) -> str:
    """Sarlavha (qalin) + blockquote tanasi. Botdagi deyarli barcha xabarlar shu shaklda."""
    head = f"<b>{em(emoji_key)} {esc(title)}</b>"
    if not lines:
        return head
    return head + "\n" + q(*lines, expandable=expandable)


def note(emoji_key: str, text: str) -> str:
    """Qisqa bir qatorli xabar: <blockquote>emoji matn</blockquote>."""
    return q(f"{em(emoji_key)} {text}")


def fmt_num(amount: int) -> str:
    return f"{amount:,}".replace(",", " ")


async def currency() -> str:
    return await db.get_setting("currency") or "so'm"


async def price(amount: int) -> str:
    return f"{fmt_num(amount)} {await currency()}"


class IsAdmin(BaseFilter):
    async def __call__(self, event) -> bool:
        user = getattr(event, "from_user", None)
        return bool(user) and await db.is_admin(user.id)
