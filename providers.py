"""Stars/Premium yetkazib beruvchi API provayderlari uchun yagona qatlam.

Yangi provayder qo'shish: `Provider` dan meros oling va `REGISTRY` ga qo'shing — admin panel,
buyurtmani yetkazish va kuzatish (fulfillment.py) o'zgarishsiz ishlayveradi.
"""
from __future__ import annotations

import re
from decimal import Decimal, ROUND_CEILING

import coindrop
import tgsuperstars
from coindrop import CoinDrop, CoinDropError

MAX_STARS_PACKAGES = 20
MAX_UC_PACKAGES = 24
DEFAULT_STARS_QTYS = (50, 100, 250, 500, 1000)


def sale_price(cost_uzs: float, markup: int) -> int:
    """Tannarx + ustama, 100 so'mga yuqoriga yaxlitlanadi."""
    value = Decimal(str(cost_uzs)) * (100 + markup) / 100
    return int((value / 100).to_integral_value(rounding=ROUND_CEILING) * 100)


def _num(value) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


class Provider:
    name = ""
    title = ""
    site = ""
    key_setting = ""            # bazadagi sozlama nomi
    key_env = ""                # ixtiyoriy: env orqali kalit
    key_re = re.compile(r".+")
    key_hint = ""               # kalit qanday ko'rinishda
    key_where = ""              # kalitni qayerdan olish
    currency = "USD"            # provayder hisob-kitob valyutasi
    stars_min, stars_max = 50, 10_000
    months = (3, 6, 12)
    supports_uc = False

    def __init__(self, api_key: str):
        self.api_key = api_key.strip()

    def build_request(self, order) -> dict | None:
        """Buyurtmani API so'roviga aylantiradi. Avtomatlashtirib bo'lmasa — None."""
        player = (order["recipient"] or "").strip().lstrip("@")
        qty = order["quantity"] or 0
        if not player or not qty:
            return None
        if order["order_type"] == "stars" and self.stars_min <= qty <= self.stars_max:
            return {"kind": "stars", "player": player, "qty": qty}
        if order["order_type"] == "premium" and qty in self.months:
            return {"kind": "premium", "player": player, "qty": qty}
        return None

    # --- quyidagilarni provayderlar o'zi yozadi ---
    async def create(self, ref: str, req: dict) -> dict:
        raise NotImplementedError

    async def find(self, ref: str, order) -> dict | None:
        """Aloqa uzilganda: buyurtma yaratilganmi yoki yo'qmi — xavfsiz aniqlash."""
        raise NotImplementedError

    async def get(self, pid) -> dict:
        raise NotImplementedError

    def normalize(self, data: dict) -> tuple[str, str | None, float | None]:
        """(holat: delivered|failed|processing, provayder buyurtma ID, tannarx USD)."""
        raise NotImplementedError

    async def account(self) -> dict:
        """{"name": str|None, "lines": [str], "warn": str|None} — admin ekrani uchun."""
        raise NotImplementedError

    async def price_list(self, markup: int, rate: float, stars_qtys: list[int]):
        """(stars, premium, truncated): [{"stars"|"months", "price", "cost"}] — so'mda."""
        raise NotImplementedError


class CoindropProvider(Provider):
    name = "coindrop"
    title = "Coindrop.uz"
    site = "coindrop.uz"
    key_setting = "coindrop_api_key"
    key_env = "COINDROP_API_KEY"
    key_re = re.compile(r"^cd_[A-Za-z0-9_\-]{8,}$")
    key_hint = "cd_ bilan boshlanadi"
    key_where = "coindrop.uz → Profil → Security &amp; API Key"
    currency = "UZS"
    stars_min, stars_max = coindrop.STARS_MIN, coindrop.STARS_MAX
    months = coindrop.PREMIUM_MONTHS

    supports_uc = True

    def __init__(self, api_key: str):
        super().__init__(api_key)
        self.client = CoinDrop(self.api_key)

    async def uc_list(self, markup: int) -> list[dict]:
        """PUBG Mobile UC paketlari: [{"uc", "price", "cost", "product_id"}] (so'mda, arzonidan qimmatiga)."""
        best: dict[int, dict] = {}
        for p in await self.client.products(coindrop.UC_GAME):
            pid, cost = p.get("id"), _num(p.get("price_uzs"))
            amount = p.get("amount")
            if not amount:  # ba'zan miqdor faqat nomda: "60 UC"
                m = re.search(r"(\d[\d\s]*)\s*UC", str(p.get("name") or ""), re.I)
                amount = int(re.sub(r"\s", "", m.group(1))) if m else None
            if pid in (None, "") or not cost or not amount or int(amount) <= 0:
                continue
            uc = int(amount)
            item = {"uc": uc, "price": sale_price(cost, markup), "cost": int(cost), "product_id": str(pid)}
            if uc not in best or item["cost"] < best[uc]["cost"]:
                best[uc] = item
        return [best[k] for k in sorted(best)][:MAX_UC_PACKAGES]

    def build_request(self, order) -> dict | None:
        if order["order_type"] == "uc":
            player, product_id = (order["recipient"] or "").strip(), (order["product_id"] or "").strip()
            if not re.match(coindrop.UC_PLAYER_RE, player) or not product_id:
                return None
            return {"game_key": coindrop.UC_GAME, "player_id": player, "product_id": product_id}
        base = super().build_request(order)
        if base is None:
            return None
        if base["kind"] == "stars":
            return {"game_key": coindrop.STARS_GAME, "player_id": base["player"], "amount": base["qty"]}
        return {"game_key": coindrop.PREMIUM_GAME, "player_id": base["player"],
                "product_id": f"prem_{base['qty']}m"}

    async def create(self, ref, req):
        return await self.client.create_order(external_ref=ref, **req)

    async def find(self, ref, order):
        return await self.client.find_by_ref(ref)

    async def get(self, pid):
        return await self.client.get_order(pid)

    def normalize(self, data):
        status = str(data.get("status") or "").lower()
        pid = str(data.get("order_id") or data.get("id") or "") or None
        state = status if status in ("delivered", "failed") else "processing"
        return state, pid, _num(data.get("amount_usd"))

    async def account(self):
        data = await self.client.account()
        acc = data.get("account") or {}
        lines = [f"Balans: <b>${float(acc.get('balance_usd') or 0):.2f}</b> "
                 f"({int(float(acc.get('balance_uzs') or 0)):,} so'm)".replace(",", " ")]
        if data.get("usd_to_uzs"):
            lines.append(f"Kurs: 1$ = {int(float(data['usd_to_uzs'])):,} so'm".replace(",", " "))
        warn = None if acc.get("api_enabled", True) else "Akkauntda API o'chirilgan!"
        return {"name": acc.get("name"), "lines": lines, "warn": warn}

    async def price_list(self, markup, rate, stars_qtys):
        stars, premium = [], []
        for p in await self.client.products(coindrop.STARS_GAME):
            amount, cost = p.get("amount"), p.get("price_uzs")
            if str(p.get("id", "")).startswith("amt_") and amount and cost and int(amount) >= coindrop.STARS_MIN:
                stars.append({"stars": int(amount), "price": sale_price(float(cost), markup), "cost": int(float(cost))})
        for p in await self.client.products(coindrop.PREMIUM_GAME):
            m = re.fullmatch(r"prem_(\d+)m", str(p.get("id", "")))
            cost = p.get("price_uzs")
            if m and cost:
                premium.append({"months": int(m.group(1)), "price": sale_price(float(cost), markup),
                                "cost": int(float(cost))})
        stars.sort(key=lambda x: x["stars"])
        premium.sort(key=lambda x: x["months"])
        return stars[:MAX_STARS_PACKAGES], premium, len(stars) > MAX_STARS_PACKAGES


class TgSuperstarsProvider(Provider):
    name = "tgsuperstars"
    title = "TgSuperstars"
    site = "partner.tgsuperstars.com"
    key_setting = "tgss_api_key"
    key_env = "TGSUPERSTARS_API_KEY"
    key_re = re.compile(r"^pk_live_[A-Za-z0-9_\-]{8,}$")
    key_hint = "pk_live_ bilan boshlanadi"
    key_where = "partner.tgsuperstars.com → Dashboard → API keys (birinchi to'ldirishdan keyin)"
    currency = "USD"
    stars_min, stars_max = tgsuperstars.STARS_MIN, tgsuperstars.STARS_MAX
    months = tgsuperstars.PREMIUM_MONTHS

    def __init__(self, api_key: str):
        super().__init__(api_key)
        self.client = tgsuperstars.TgSuperstars(self.api_key)

    def build_request(self, order) -> dict | None:
        base = super().build_request(order)
        if base is None:
            return None
        recipient = "@" + base["player"]
        if base["kind"] == "stars":
            return {"type": "stars", "params": {"quantity": base["qty"], "recipient": recipient}}
        return {"type": "premium", "params": {"months": base["qty"], "recipient": recipient}}

    async def create(self, ref, req):
        return await self.client.create_order(req["type"], req["params"], ref)

    async def find(self, ref, order):
        # Bir xil idempotency_key bilan qayta yuborish — asl buyurtmani qaytaradi (pul ikki marta yechilmaydi).
        req = self.build_request(order)
        return await self.create(ref, req) if req else None

    async def get(self, pid):
        return await self.client.get_order(pid)

    def normalize(self, data):
        status = str(data.get("status") or "").lower()
        pid = str(data.get("order_id") or data.get("id") or "") or None
        state = {"completed": "delivered", "failed": "failed", "canceled": "failed"}.get(status, "processing")
        return state, pid, _num(data.get("partner_price"))

    async def account(self):
        data = await self.client.me()
        lines = [f"Balans: <b>${float(data.get('balance') or 0):.2f}</b> (USD)"]
        limits = data.get("limits") or {}
        if limits.get("stars_min_per_order") and limits.get("stars_max_per_order"):
            lines.append(f"Stars limiti: {limits['stars_min_per_order']}–{limits['stars_max_per_order']} / buyurtma")
        status = str(data.get("status") or "")
        warn = None if status in ("", "active") else f"Hisob holati: {status}"
        return {"name": data.get("partner_id"), "lines": lines, "warn": warn}

    async def price_list(self, markup, rate, stars_qtys):
        data = await self.client.products()
        if data.get("unavailable"):
            raise CoinDropError(503, f"Narxlar hozir mavjud emas ({data.get('reason') or '—'})", "upstream")
        stars, premium = [], []
        per_star = _num((data.get("stars") or {}).get("price_per_star"))
        if per_star:
            qtys = sorted({q for q in (stars_qtys or DEFAULT_STARS_QTYS)
                           if self.stars_min <= q <= self.stars_max})
            for q in qtys:
                cost = per_star * q * rate
                stars.append({"stars": q, "price": sale_price(cost, markup), "cost": int(round(cost))})
        for months, info in sorted((data.get("premium") or {}).items(), key=lambda kv: int(kv[0])):
            usd = _num((info or {}).get("partner_price"))
            if usd and int(months) in self.months:
                cost = usd * rate
                premium.append({"months": int(months), "price": sale_price(cost, markup), "cost": int(round(cost))})
        return stars[:MAX_STARS_PACKAGES], premium, len(stars) > MAX_STARS_PACKAGES


REGISTRY: dict[str, type[Provider]] = {
    CoindropProvider.name: CoindropProvider,
    TgSuperstarsProvider.name: TgSuperstarsProvider,
}
DEFAULT_PROVIDER = CoindropProvider.name


def title_of(name: str | None) -> str:
    cls = REGISTRY.get(name or DEFAULT_PROVIDER)
    return cls.title if cls else (name or "API")
