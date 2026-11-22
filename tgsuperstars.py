"""TgSuperstars Partner API v1 mijozi.

Hujjat: https://partner.tgsuperstars.com/en/docs
  * Base URL: https://pay.tgsuperstars.com/api/partner/v1, autentifikatsiya: `Authorization: Bearer pk_live_...`
  * Buyurtma: POST /orders {type, idempotency_key, params}; holat: GET /orders/{id}
  * Holatlar: processing | completed | partial | canceled | failed
  * Pul birligi: USD (oldindan to'ldiriladigan balans, USDT orqali). Limit: 120 so'rov/min
  * `idempotency_key` bir xil bo'lsa, qayta yuborish asl buyurtmani qaytaradi va pul faqat bir marta yechiladi.
"""
from __future__ import annotations

import asyncio

import coindrop
from coindrop import CoinDropError

BASE_URL = "https://pay.tgsuperstars.com/api/partner/v1"

STARS_MIN, STARS_MAX = 50, 50_000
PREMIUM_MONTHS = (3, 6, 12)


def _error_parts(status: int, data: object) -> tuple[str, str]:
    """Xato javobdan (code, detail) ni oladi: {"code","detail"} yoki {"detail": {"code","detail"}}."""
    if not isinstance(data, dict):
        return "", str(data)[:300]
    inner = data.get("detail")
    if isinstance(inner, dict):
        return str(inner.get("code") or ""), str(inner.get("detail") or inner)[:300]
    return str(data.get("code") or ""), str(inner or data.get("message") or f"HTTP {status}")[:300]


def classify(status: int, code: str) -> str:
    if status == 0:
        return "network"
    if code == "insufficient_balance" or status == 402:
        return "balance"
    if code in ("unauthorized", "ip_not_allowed", "partner_inactive", "partner_program_unavailable") \
            or status in (401, 403):
        return "auth"
    if code == "rate_limited" or status == 429:
        return "rate"
    # buyurtma yaratilmagan yoki hozir yaratilmoqda: bir xil idempotency_key bilan qayta yuborish xavfsiz
    if code in ("order_in_progress", "ledger_unavailable", "product_unavailable", "rate_unavailable",
                "resolver_error") or status >= 500:
        return "upstream"
    return "invalid"


class TgSuperstars:
    def __init__(self, api_key: str):
        self.api_key = api_key.strip()

    async def _request(self, method: str, path: str, json: dict | None = None) -> dict:
        headers = {"Authorization": f"Bearer {self.api_key}", "Accept": "application/json"}
        try:
            status, data = await coindrop._send(method, BASE_URL + path, headers, json)
        except (asyncio.TimeoutError, OSError) as exc:
            raise CoinDropError(0, f"{type(exc).__name__}", "network") from exc
        except Exception as exc:  # aiohttp.ClientError va boshqalar
            raise CoinDropError(0, f"{type(exc).__name__}: {exc}", "network") from exc
        if not 200 <= status < 300:
            code, detail = _error_parts(status, data)
            raise CoinDropError(status, f"{code}: {detail}" if code else detail, classify(status, code))
        return data if isinstance(data, dict) else {}

    async def me(self) -> dict:
        return await self._request("GET", "/me")

    async def products(self) -> dict:
        return await self._request("GET", "/products")

    async def create_order(self, type_: str, params: dict, idempotency_key: str) -> dict:
        return await self._request("POST", "/orders", {
            "type": type_, "params": params, "idempotency_key": idempotency_key,
        })

    async def get_order(self, order_id: str | int) -> dict:
        return await self._request("GET", f"/orders/{order_id}")
