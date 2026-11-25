"""Buyurtmalarni provayder API (Coindrop.uz, TgSuperstars, ...) orqali avtomatik yetkazish.

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
import os
import time

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest

import database.db as db
from coindrop import CoinDropError
from config import ADMIN_CHAT_ID
from providers import REGISTRY, DEFAULT_PROVIDER, Provider, title_of
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

async def active_name() -> str:
    name = await db.get_setting("api_provider")
    return name if name in REGISTRY else DEFAULT_PROVIDER


async def api_key(name: str | None = None) -> str:
    cls = REGISTRY[name or await active_name()]
    return (await db.get_setting(cls.key_setting)) or (os.getenv(cls.key_env, "").strip() if cls.key_env else "")


async def has_key(name: str | None = None) -> bool:
    return bool(await api_key(name))


async def is_enabled() -> bool:
    return (await db.get_setting("coindrop_enabled")) == "1"


async def provider_by_name(name: str | None) -> Provider | None:
    """Kalit mavjud bo'lsa provayderni qaytaradi (yoqilgan-o'chirilganiga qaramasdan: kuzatish uchun)."""
    name = name if name in REGISTRY else DEFAULT_PROVIDER
    key = await api_key(name)
    return REGISTRY[name](key) if key else None


def provider_name_for(order) -> str | None:
    """UC faqat Coindrop orqali sotiladi; Stars/Premium — buyurtma yuborilgan yoki faol provayder."""
    if order["provider_name"]:
        return order["provider_name"]
    return "coindrop" if order["order_type"] == "uc" else None


async def auto_ready(kind: str) -> bool:
    """Shu turdagi buyurtma avtomatik yetkazilishi mumkinmi (kalit bor va avto-yetkazish yoqilgan)."""
    return await get_client("coindrop" if kind == "uc" else None) is not None


async def get_client(name: str | None = None) -> Provider | None:
    """Avto-yetkazish yoqilgan va kalit mavjud bo'lsagina provayderni qaytaradi (standart: faol provayder)."""
    if not await is_enabled():
        return None
    return await provider_by_name(name or await active_name())


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
            api_ready=await get_client(provider_name_for(order)) is not None,
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
    order = await db.get_order(order_id)
    if order and await get_client(provider_name_for(order)) is not None:
        spawn(fulfill(bot, order_id))


# ---------------- asosiy oqim ----------------

async def fulfill(bot: Bot, order_id: int) -> str:
    """Buyurtmani API ga yuboradi. Natija: disabled|closed|manual|busy|processing|delivered|failed|retry|error."""
    order = await db.get_order(order_id)
    if order is None or order["status"] != "kutilmoqda":
        return "closed"
    # Oldingi urinish bo'lgan buyurtma shu provayder bilan davom etadi (provayder almashsa ham)
    client = await get_client(provider_name_for(order))
    if client is None:
        return "disabled"

    req = client.build_request(order)
    if req is None:
        await db.set_provider(order_id, "error", error="Avtomatik yuborib bo'lmaydi (miqdor/qabul qiluvchi mos emas) — qo'lda bajaring")
        await refresh_admin_card(bot, order_id)
        return "manual"

    ref = f"sg-{order_id}"

    # Oldingi urinish bo'lgan bo'lsa: avval API da buyurtma bor-yo'qligini tekshiramiz (ikki marta yuborilmasin)
    if (order["provider_attempts"] or 0) > 0:
        try:
            found = await client.find(ref, order)
        except CoinDropError as exc:
            await _schedule_retry(bot, order_id, order, f"Tekshirib bo'lmadi: {exc.human()}")
            return "retry"
        if found:
            return await _apply(bot, order_id, found, client)

    if not await db.claim_for_provider(order_id, client.name):
        return "busy"

    try:
        resp = await client.create(ref, req)
    except CoinDropError as exc:
        return await _on_error(bot, client, order_id, ref, exc)
    except Exception as exc:  # kutilmagan xato — pulni himoya qilish uchun "noaniq" deb qaraymiz
        log.exception("%s kutilmagan xato (buyurtma #%s)", client.title, order_id)
        return await _on_error(bot, client, order_id, ref, CoinDropError(0, str(exc), "network"))
    return await _apply(bot, order_id, resp, client)


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


async def _on_error(bot: Bot, client: Provider, order_id: int, ref: str, exc: CoinDropError) -> str:
    log.warning("%s xatosi (buyurtma #%s): %s", client.title, order_id, exc)
    order = await db.get_order(order_id)
    if exc.uncertain:
        # So'rov yetib borgan bo'lishi mumkin — avval tekshiramiz
        with contextlib.suppress(CoinDropError):
            found = await client.find(ref, order)
            if found:
                return await _apply(bot, order_id, found, client)
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


async def _apply(bot: Bot, order_id: int, data: dict, client: Provider) -> str:
    """Provayder javobini (yaratish/so'rash/ro'yxat) bizning holatga o'tkazadi."""
    status, pid, cost = client.normalize(data)

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
    now = time.time()
    polled = 0
    for o in await db.provider_work(int(now) - 120):
        oid, ps = o["id"], o["provider_status"]
        # Har bir buyurtma o'zi yuborilgan provayder orqali kuzatiladi (kalit bo'lsa kifoya)
        client = await provider_by_name(provider_name_for(o))
        if client is None:
            continue
        try:
            if ps == "retry":
                if now - (o["provider_updated"] or 0) >= 30 * max(o["provider_attempts"] or 1, 1):
                    await fulfill(bot, oid)
            elif ps == "sending":
                # javob yo'qolgan: external_ref bo'yicha aniqlaymiz
                found = await client.find(f"sg-{oid}", o)
                if found:
                    await _apply(bot, oid, found, client)
                else:
                    await db.set_provider(oid, "retry", error="Javob olinmadi")
                    await refresh_admin_card(bot, oid)
            elif ps == "processing":
                if is_stale(o) and o["provider_error"] != "stale":
                    await db.mark_provider_note(oid, "stale")
                    await refresh_admin_card(bot, oid)
                    await notify_admin(bot, card(
                        "warn", f"Buyurtma #{oid}: API uzoq javob bermayapti",
                        f"{STALE_AFTER // 60} daqiqadan oshdi. {client.title} kabinetida tekshiring; "
                        "kerak bo'lsa qo'lda hal qiling.",
                    ))
                if polled >= 25 or now - _last_poll.get(oid, 0) < POLL_EVERY:
                    continue
                polled += 1
                _last_poll[oid] = now
                if o["provider_order_id"]:
                    data = await client.get(o["provider_order_id"])
                else:
                    data = await client.find(f"sg-{oid}", o)
                if data and client.normalize(data)[0] in ("delivered", "failed"):
                    await _apply(bot, oid, data, client)
        except CoinDropError as exc:
            log.warning("Worker: buyurtma #%s: %s", oid, exc)
            if exc.kind == "auth":
                return
        except Exception:
            log.exception("Worker xatosi (buyurtma #%s)", oid)


async def worker(bot: Bot) -> None:
    log.info("API worker ishga tushdi")
    while True:
        try:
            await tick(bot)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Worker tick xatosi")
        await asyncio.sleep(TICK_EVERY)
