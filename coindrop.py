"""Coindrop.uz Reseller API v1 mijozi.

Hujjat: https://coindrop.uz/api-docs
  * Base URL: https://coindrop.uz/api/v1, autentifikatsiya: `X-API-Key: cd_...`
  * Stars: game_key=telegram-stars (amount 50..10000), Premium: telegram-premium (prem_3m/6m/12m)
  * Buyurtma holatlari: processing | delivered | failed
  * Limit: 120 so'rov/min, buyurtma POST 30/min
"""
from __future__ import annotations

import asyncio
import logging

log = logging.getLogger(__name__)

BASE_URL = "https://coindrop.uz/api/v1"
TIMEOUT = 25

STARS_GAME = "telegram-stars"
PREMIUM_GAME = "telegram-premium"
STARS_MIN, STARS_MAX = 50, 10_000
PREMIUM_MONTHS = (3, 6, 12)


class CoinDropError(Exception):
    """API xatosi. `kind` — xatoning turi (qaror qabul qilish uchun)."""

    def __init__(self, status: int, detail: str, kind: str):
        super().__init__(f"[{status}] {detail}")
        self.status = status
        self.detail = detail
        self.kind = kind

    @property
    def uncertain(self) -> bool:
        """So'rov serverga yetib, bajarilgan bo'lishi mumkinmi (tarmoq uzilishi, 5xx)."""
        return self.kind in ("network", "upstream")

    @property
    def retriable(self) -> bool:
        return self.kind in ("network", "upstream", "rate")

    def human(self) -> str:
        return {
            "auth": "API kalit noto'g'ri yoki API o'chirilgan (401/403)",
            "balance": "Coindrop balansi yetarli emas — hisobni to'ldiring",
            "stock": "Mahsulot hozir mavjud emas (stock)",
            "invalid": f"So'rov rad etildi: {self.detail}",
            "rate": "So'rovlar limiti oshdi (429)",
            "upstream": "Coindrop provayderi vaqtincha ishlamayapti (503)",
            "network": "Coindrop bilan aloqa o'rnatib bo'lmadi",
        }.get(self.kind, self.detail)


def classify(status: int, detail: str) -> str:
    d = (detail or "").lower()
    if status == 0:
        return "network"
    if status in (401, 403):
        return "auth"
    if status == 429:
        return "rate"
    if status >= 500:
        return "upstream"
    if any(w in d for w in ("balance", "insufficient", "balans", "mablag")):
        return "balance"
    if any(w in d for w in ("stock", "sold out", "out of")):
        return "stock"
    if status in (404, 422, 400, 200):
        return "invalid"
    return "other"


_session = None


async def _send(method: str, url: str, headers: dict, json: dict | None) -> tuple[int, object]:
    """Yagona tarmoq nuqtasi (testlarda almashtiriladi)."""
    global _session
    import aiohttp

    if _session is None or _session.closed:
        _session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=TIMEOUT))
    async with _session.request(method, url, headers=headers, json=json) as resp:
        try:
            data = await resp.json(content_type=None)
        except Exception:
            data = {"detail": (await resp.text())[:300]}
        return resp.status, data


async def close_session() -> None:
    global _session
    if _session is not None and not _session.closed:
        await _session.close()
    _session = None


class CoinDrop:
    def __init__(self, api_key: str):
        self.api_key = api_key.strip()

    async def _request(self, method: str, path: str, json: dict | None = None) -> dict:
        headers = {"X-API-Key": self.api_key, "Accept": "application/json"}
        try:
            status, data = await _send(method, BASE_URL + path, headers, json)
        except (asyncio.TimeoutError, OSError) as exc:
            raise CoinDropError(0, f"{type(exc).__name__}", "network") from exc
        except Exception as exc:  # aiohttp.ClientError va boshqalar
            raise CoinDropError(0, f"{type(exc).__name__}: {exc}", "network") from exc

        if not isinstance(data, dict):
            data = {"detail": str(data)[:300]}
        if status != 200 or data.get("success") is False:
            detail = str(data.get("detail") or data.get("message") or f"HTTP {status}")
            if isinstance(data.get("detail"), (list, dict)):
                detail = str(data["detail"])[:300]
            raise CoinDropError(status, detail, classify(status, detail))
        return data

    # ---- akkaunt ----
    async def account(self) -> dict:
        return await self._request("GET", "/account")

    async def balance(self) -> dict:
        return await self._request("GET", "/balance")

    # ---- mahsulotlar ----
    async def products(self, game_key: str) -> list[dict]:
        data = await self._request("GET", f"/games/{game_key}/products")
        return data.get("products") or []

    # ---- buyurtmalar ----
    async def create_order(self, game_key: str, player_id: str, *, product_id: str | None = None,
                           amount: int | None = None, external_ref: str | None = None) -> dict:
        body: dict = {"game_key": game_key, "player_id": player_id.lstrip("@")}
        if product_id:
            body["product_id"] = product_id
        if amount is not None:
            body["amount"] = amount
        if external_ref:
            body["external_ref"] = external_ref
        return await self._request("POST", "/orders", body)

    async def get_order(self, order_id: str | int) -> dict:
        data = await self._request("GET", f"/orders/{order_id}")
        return data.get("order") or data

    async def find_by_ref(self, external_ref: str) -> dict | None:
        """Aloqa uzilganda: buyurtma haqiqatan yaratilganmi — external_ref bo'yicha qidiradi."""
        data = await self._request("GET", "/orders?page=1&per_page=100")
        for order in data.get("orders") or []:
            if order.get("external_ref") == external_ref:
                return order
        return None
