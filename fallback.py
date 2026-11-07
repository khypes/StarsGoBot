"""Custom emoji ishlamasa (masalan, bot egasida Premium yo'q) — oddiy emojiga avtomatik qaytish."""
import logging

from aiogram.client.session.middlewares.base import BaseRequestMiddleware
from aiogram.exceptions import TelegramBadRequest

import emojis

log = logging.getLogger(__name__)


class EmojiFallbackMiddleware(BaseRequestMiddleware):
    async def __call__(self, make_request, bot, method):
        try:
            return await make_request(bot, method)
        except TelegramBadRequest as exc:
            if emojis.NO_FALLBACK.get():
                raise
            update = {}
            for field in ("text", "caption"):
                value = getattr(method, field, None)
                stripped = emojis.strip_text(value)
                if stripped != value:
                    update[field] = stripped
            markup = getattr(method, "reply_markup", None)
            if markup is not None:
                new_markup, changed = emojis.strip_markup(markup)
                if changed:
                    update["reply_markup"] = new_markup
            if not update:
                raise
            log.warning("Premium emoji yuborilmadi (%s) — oddiy emoji bilan qayta yuborilmoqda", exc.message)
            return await make_request(bot, method.model_copy(update=update))
