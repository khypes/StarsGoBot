"""Buyurtmalarni Coindrop API orqali avtomatik yetkazish.

Xavfsizlik tamoyillari (pul bilan ishlagani uchun):
  * Buyurtma API ga yuborishdan oldin bazada atomik "band qilinadi" (claim) — ikki marta yuborilmaydi.
  * Aloqa uzilsa/5xx bo'lsa: avval `external_ref` bo'yicha buyurtma mavjudligi tekshiriladi.
    Qayta yuborish faqat buyurtma API da yo'qligi ishonchli bo'lganda amalga oshadi.
  * API ishlayotgan buyurtmani admin qo'lda bajara/bekor qila olmaydi (30 daqiqadan keyin — mumkin).
  * Provayder `failed` desa — mablag' foydalanuvchiga avtomatik qaytariladi.
  * Har qanday aniq xatoda (balans yetmaydi, kalit noto'g'ri, ...) buyurtma qo'lda rejimda qoladi
    va admin xabardor qilinadi.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import time

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest

import database.db as db
from coindrop import (
    CoinDrop, CoinDropError, STARS_GAME, PREMIUM_GAME, STARS_MIN, STARS_MAX, PREMIUM_MONTHS,
)
from config import ADMIN_CHAT_ID, COINDROP_API_KEY
from emojis import em
from keyboards.admin_kb import order_action_kb
from texts import order_card, provider_locked, is_stale, STALE_AFTER
from ui import card, esc, price

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 4
POLL_EVERY = 20       # sekund: bitta buyurtmani qayta so'rash oralig'i
TICK_EVERY = 15       # sekund: worker davri

_tasks: set[asyncio.Task] = set()
_last_poll: dict[int, float] = {}


def spawn(coro) -> None:
    task = asyncio.create_task(coro)
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


# ---------------- sozlamalar ----------------

async def api_key() -> str:
    return (await db.get_setting("coindrop_api_key")) or COINDROP_API_KEY


async def has_key() -> bool:
    return bool(await api_key())


async def is_enabled() -> bool:
    return (await db.get_setting("coindrop_enabled")) == "1"


async def get_client() -> CoinDrop | None:
    """Avto-yetkazish yoqilgan va kalit mavjud bo'lsagina mijoz qaytaradi."""
    if not await is_enabled():
        return None
    key = await api_key()
    return CoinDrop(key) if key else None


def build_request(order) -> dict | None:
    """Buyurtmani API so'roviga aylantiradi. Avtomatlashtirib bo'lmasa — None."""
    player = (order["recipient"] or "").strip().lstrip("@")
    qty = order["quantity"] or 0
    if not player or not qty:
        return None
    if order["order_type"] == "stars" and STARS_MIN <= qty <= STARS_MAX:
        return {"game_key": STARS_GAME, "player_id": player, "amount": qty}
    if order["order_type"] == "premium" and qty in PREMIUM_MONTHS:
        return {"game_key": PREMIUM_GAME, "player_id": player, "product_id": f"prem_{qty}m"}
    return None


# ---------------- admin xabarlari ----------------

async def order_view(order_id: int):
    """(matn, tugmalar) — admin kartasi. Buyurtma yo'q bo'lsa None."""
    order = await db.get_order(order_id)
    if order is None:
        return None
    user = await db.get_user(order["user_id"])
    kb = None
    if order["status"] == "kutilmoqda":
        kb = order_action_kb(
            order_id, order["provider_status"], locked=provider_locked(order),
            api_ready=await get_client() is not None,
        )
    return await order_card(order, user), kb


async def refresh_admin_card(bot: Bot, order_id: int) -> None:
    order = await db.get_order(order_id)
    view = await order_view(order_id)
    if not order or not view or not order["admin_msg_id"] or not ADMIN_CHAT_ID:
        return
    with contextlib.suppress(TelegramBadRequest):
        await bot.edit_message_text(
            view[0], chat_id=ADMIN_CHAT_ID, message_id=order["admin_msg_id"], reply_markup=view[1]
        )


async def notify_admin(bot: Bot, text: str) -> None:
    if not ADMIN_CHAT_ID:
        return
    with contextlib.suppress(Exception):
        await bot.send_message(ADMIN_CHAT_ID, text)


async def on_new_order(bot: Bot, order_id: int) -> None:
    """Yangi buyurtma: adminga karta yuboriladi, API yoqilgan bo'lsa — avtomatik yetkaziladi."""
    if ADMIN_CHAT_ID and (await db.get_setting("order_notify")) == "1":
        view = await order_view(order_id)
        if view:
            with contextlib.suppress(Exception):
                msg = await bot.send_message(ADMIN_CHAT_ID, view[0], reply_markup=view[1])
                await db.set_admin_msg(order_id, msg.message_id)
    if await get_client() is not None:
        spawn(fulfill(bot, order_id))


# ---------------- asosiy oqim ----------------

async def fulfill(bot: Bot, order_id: int) -> str:
    """Buyurtmani API ga yuboradi. Natija: disabled|closed|manual|busy|processing|delivered|failed|retry|error."""
    client = await get_client()
    if client is None:
        return "disabled"
    order = await db.get_order(order_id)
    if order is None or order["status"] != "kutilmoqda":
        return "closed"

    req = build_request(order)
    if req is None:
        await db.set_provider(order_id, "error", error="Avtomatik yuborib bo'lmaydi (miqdor/qabul qiluvchi mos emas) — qo'lda bajaring")
        await refresh_admin_card(bot, order_id)
        return "manual"

    ref = f"sg-{order_id}"

    # Oldingi urinish bo'lgan bo'lsa: avval API da buyurtma bor-yo'qligini tekshiramiz (ikki marta yuborilmasin)
    if (order["provider_attempts"] or 0) > 0:
        try:
            found = await client.find_by_ref(ref)
        except CoinDropError as exc:
            await _schedule_retry(bot, order_id, order, f"Tekshirib bo'lmadi: {exc.human()}")
            return "retry"
        if found:
            return await _apply(bot, order_id, found)

    if not await db.claim_for_provider(order_id):
        return "busy"

    try:
        resp = await client.create_order(external_ref=ref, **req)
    except CoinDropError as exc:
        return await _on_error(bot, client, order_id, ref, exc)
    except Exception as exc:  # kutilmagan xato — pulni himoya qilish uchun "noaniq" deb qaraymiz
        log.exception("Coindrop kutilmagan xato (buyurtma #%s)", order_id)
        return await _on_error(bot, client, order_id, ref, CoinDropError(0, str(exc), "network"))
    return await _apply(bot, order_id, resp)


async def _schedule_retry(bot: Bot, order_id: int, order, reason: str) -> None:
    attempts = (await db.get_order(order_id))["provider_attempts"] or 0
    if attempts >= MAX_ATTEMPTS:
        await db.set_provider(order_id, "error", error=f"{reason} ({attempts} urinishdan keyin to'xtatildi)")
        await notify_admin(bot, card(
            "warn", f"Buyurtma #{order_id}: API ishlamadi",
            esc(reason), "Qo'lda bajaring yoki keyinroq «API orqali yuborish» ni bosing.",
        ))
    else:
        await db.set_provider(order_id, "retry", error=reason)
    await refresh_admin_card(bot, order_id)


async def _on_error(bot: Bot, client: CoinDrop, order_id: int, ref: str, exc: CoinDropError) -> str:
    log.warning("Coindrop xatosi (buyurtma #%s): %s", order_id, exc)
    order = await db.get_order(order_id)
    if exc.uncertain:
        # So'rov yetib borgan bo'lishi mumkin — avval tekshiramiz
        with contextlib.suppress(CoinDropError):
            found = await client.find_by_ref(ref)
            if found:
                return await _apply(bot, order_id, found)
    if exc.retriable:
        await _schedule_retry(bot, order_id, order, exc.human())
        return "retry"
    await db.set_provider(order_id, "error", error=exc.human())
    await notify_admin(bot, card(
        "warn", f"Buyurtma #{order_id}: API xatosi", esc(exc.human()),
        "", "Buyurtma qo'lda rejimda qoldi.",
    ))
    await refresh_admin_card(bot, order_id)
    return "error"


async def _apply(bot: Bot, order_id: int, data: dict) -> str:
    """Provayder javobini (yaratish/so'rash/ro'yxat) bizning holatga o'tkazadi."""
    status = str(data.get("status") or "").lower()
    pid = str(data.get("order_id") or data.get("id") or "") or None
    try:
        cost = float(data.get("amount_usd")) if data.get("amount_usd") is not None else None
    except (TypeError, ValueError):
        cost = None

    if status == "delivered":
        await db.set_provider(order_id, "delivered", pid, None, cost)
        await _finalize_delivered(bot, order_id)
        return "delivered"
    if status == "failed":
        await db.set_provider(order_id, "failed", pid, "Provayder buyurtmani bajara olmadi", cost)
        await _finalize_failed(bot, order_id)
        return "failed"
    await db.set_provider(order_id, "processing", pid, None, cost)
    await refresh_admin_card(bot, order_id)
    return "processing"


async def _finalize_delivered(bot: Bot, order_id: int) -> None:
    res = await db.complete_order(order_id)
    if res:
        order, bonus = res
        with contextlib.suppress(Exception):
            await bot.send_message(order["user_id"], card(
                "done", f"Buyurtma #{order_id} bajarildi",
                f"{esc(order['detail'])} muvaffaqiyatli yetkazildi.",
                "",
                "Xaridingiz uchun rahmat! Yana kutib qolamiz.",
            ))
        if bonus:
            with contextlib.suppress(Exception):
                await bot.send_message(bonus[0], card(
                    "bonus", "Referal bonusi",
                    f"Taklif qilgan do'stingiz xarid qildi: <b>+{await price(bonus[1])}</b> balansingizga qo'shildi.",
                ))
    await refresh_admin_card(bot, order_id)


async def _finalize_failed(bot: Bot, order_id: int) -> None:
    order = await db.cancel_order(order_id)  # mablag' foydalanuvchiga qaytadi
    if order:
        with contextlib.suppress(Exception):
            await bot.send_message(order["user_id"], card(
                "cancel", f"Buyurtma #{order_id} bajarilmadi",
                f"{esc(order['detail'])}",
                "",
                "Texnik sabab bilan buyurtmani yetkazib bo'lmadi. Mablag' balansingizga to'liq qaytarildi.",
                "Username to'g'riligini tekshirib, qayta buyurtma bering.",
            ))
        await notify_admin(bot, card(
            "warn", f"Buyurtma #{order_id}: provayder bajara olmadi",
            "Mablag' foydalanuvchiga qaytarildi. Username to'g'riligini tekshiring.",
        ))
    await refresh_admin_card(bot, order_id)


# ---------------- fon worker ----------------

async def tick(bot: Bot) -> None:
    client = await get_client()
    if client is None:
        return
    now = time.time()
    polled = 0
    for o in await db.provider_work(int(now) - 120):
        oid, ps = o["id"], o["provider_status"]
        try:
            if ps == "retry":
                if now - (o["provider_updated"] or 0) >= 30 * max(o["provider_attempts"] or 1, 1):
                    await fulfill(bot, oid)
            elif ps == "sending":
                # javob yo'qolgan: external_ref bo'yicha aniqlaymiz
                found = await client.find_by_ref(f"sg-{oid}")
                if found:
                    await _apply(bot, oid, found)
                else:
                    await db.set_provider(oid, "retry", error="Javob olinmadi")
                    await refresh_admin_card(bot, oid)
            elif ps == "processing":
                if is_stale(o) and o["provider_error"] != "stale":
                    await db.mark_provider_note(oid, "stale")
                    await refresh_admin_card(bot, oid)
                    await notify_admin(bot, card(
                        "warn", f"Buyurtma #{oid}: API uzoq javob bermayapti",
                        f"{STALE_AFTER // 60} daqiqadan oshdi. Coindrop dashboardida tekshiring; "
                        "kerak bo'lsa qo'lda hal qiling.",
                    ))
                if polled >= 25 or now - _last_poll.get(oid, 0) < POLL_EVERY:
                    continue
                polled += 1
                _last_poll[oid] = now
                if o["provider_order_id"]:
                    data = await client.get_order(o["provider_order_id"])
                else:
                    data = await client.find_by_ref(f"sg-{oid}")
                if data and str(data.get("status") or "").lower() in ("delivered", "failed"):
                    await _apply(bot, oid, data)
        except CoinDropError as exc:
            log.warning("Worker: buyurtma #%s: %s", oid, exc)
            if exc.kind == "auth":
                return
        except Exception:
            log.exception("Worker xatosi (buyurtma #%s)", oid)


async def worker(bot: Bot) -> None:
    log.info("Coindrop worker ishga tushdi")
    while True:
        try:
            await tick(bot)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Worker tick xatosi")
        await asyncio.sleep(TICK_EVERY)
