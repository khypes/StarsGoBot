"""SQLite qatlami.

Bitta umumiy ulanish + yozish uchun lock ishlatiladi. Pul bilan bog'liq barcha
amallar (xarid, bekor qilish, tasdiqlash) atomik: holat tekshiruvi va balans
o'zgarishi bir tranzaksiyada bajariladi — qo'sh bosish / poyga holatlari bo'lmaydi.
"""
import asyncio
import json
import os
import time

import aiosqlite

from config import DB_PATH, SUPER_ADMIN_ID, DEFAULT_STARS_PRICES, DEFAULT_PREMIUM_PRICES

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    full_name TEXT,
    balance INTEGER DEFAULT 0,
    referrer_id INTEGER,
    is_banned INTEGER DEFAULT 0,
    joined_at INTEGER
);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    order_type TEXT,          -- 'stars' | 'premium' | 'uc'
    detail TEXT,
    price INTEGER,
    status TEXT DEFAULT 'kutilmoqda',  -- kutilmoqda | bajarildi | bekor qilindi
    created_at INTEGER
);

CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    amount INTEGER,
    kind TEXT,                 -- 'topup' | 'referral_bonus' | 'admin_adjust'
    status TEXT DEFAULT 'kutilmoqda',  -- kutilmoqda | tasdiqlandi | rad etildi
    note TEXT,
    created_at INTEGER
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS admins (
    user_id INTEGER PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS channels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id TEXT,
    title TEXT,
    url TEXT
);

CREATE TABLE IF NOT EXISTS emojis (
    key TEXT PRIMARY KEY,
    custom_id TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS button_styles (
    key TEXT PRIMARY KEY,
    style TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id);
CREATE INDEX IF NOT EXISTS idx_users_ref ON users(referrer_id);
CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
"""

# orders jadvaliga keyin qo'shilgan ustunlar (eski bazalar ham avtomatik yangilanadi)
_ORDER_COLUMNS = {
    "recipient": "TEXT",
    "quantity": "INTEGER",
    "provider_status": "TEXT",      # NULL | sending | processing | retry | error | delivered | failed
    "provider_order_id": "TEXT",
    "provider_error": "TEXT",
    "provider_attempts": "INTEGER DEFAULT 0",
    "provider_updated": "INTEGER",
    "provider_cost_usd": "REAL",
    "product_id": "TEXT",           # provayder mahsulot ID si (UC paketlari uchun)
    "provider_name": "TEXT",        # buyurtma qaysi API orqali yuborilgan (NULL = coindrop)
    "admin_msg_id": "INTEGER",
}

_DEFAULT_SETTINGS = {
    "coindrop_api_key": "",
    "coindrop_enabled": "0",
    "coindrop_markup": "10",
    "uc_api_key": "",               # UC uchun alohida Coindrop kaliti (Stars/Premium dan mustaqil)
    "uc_auto": "0",                 # UC avto-yetkazish (Stars/Premium dan mustaqil)
    "uc_enabled": "0",              # UC (PUBG Mobile) sotuvi
    "uc_prices": "[]",              # [{"uc":60,"price":13000,"cost":10000,"product_id":"123"}]
    "uc_markup": "10",
    "uc_synced_at": "0",
    "uc_game_key": "",              # Coindrop PUBG o'yin kaliti (sinxronlashda aniqlanadi)
    "api_provider": "coindrop",     # faol provayder: coindrop | tgsuperstars
    "tgss_api_key": "",
    "usd_rate": "0",                # 1$ necha so'm (USD bilan ishlaydigan provayderlar uchun)
    "currency": "so'm",
    "referral_percent": "5",
    "card_number": "",
    "card_holder": "",
    "order_notify": "1",
    "premium_emoji_enabled": "1",
    "stars_prices": json.dumps(DEFAULT_STARS_PRICES, ensure_ascii=False),
    "premium_prices": json.dumps(DEFAULT_PREMIUM_PRICES, ensure_ascii=False),
}

_db: aiosqlite.Connection | None = None
_lock = asyncio.Lock()


async def init_db():
    global _db
    folder = os.path.dirname(os.path.abspath(DB_PATH))
    os.makedirs(folder, exist_ok=True)
    _db = await aiosqlite.connect(DB_PATH)
    _db.row_factory = aiosqlite.Row
    await _db.execute("PRAGMA journal_mode=WAL")
    await _db.execute("PRAGMA synchronous=NORMAL")
    await _db.execute("PRAGMA busy_timeout=5000")
    await _db.executescript(_SCHEMA)
    existing = {r["name"] for r in await _all("PRAGMA table_info(orders)")}
    for col, decl in _ORDER_COLUMNS.items():
        if col not in existing:
            await _db.execute(f"ALTER TABLE orders ADD COLUMN {col} {decl}")
    for k, v in _DEFAULT_SETTINGS.items():
        await _db.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))
    if SUPER_ADMIN_ID:
        await _db.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (SUPER_ADMIN_ID,))
    await _db.commit()


async def close_db():
    global _db
    if _db is not None:
        await _db.close()
        _db = None


async def _one(sql: str, params=()):
    cur = await _db.execute(sql, params)
    return await cur.fetchone()


async def _all(sql: str, params=()):
    cur = await _db.execute(sql, params)
    return await cur.fetchall()


async def _write(sql: str, params=()):
    """Bitta yozish amali. (rowcount, lastrowid) qaytaradi."""
    async with _lock:
        cur = await _db.execute(sql, params)
        await _db.commit()
        return cur.rowcount, cur.lastrowid


# ---------- users ----------

async def get_user(user_id: int):
    return await _one("SELECT * FROM users WHERE user_id=?", (user_id,))


async def get_user_by_username(username: str):
    return await _one("SELECT * FROM users WHERE lower(username)=lower(?)", (username.lstrip("@"),))


async def create_user_if_not_exists(user_id: int, username: str, full_name: str, referrer_id: int | None):
    """(user, is_new). Mavjud foydalanuvchining ism/username'i yangilanadi."""
    async with _lock:
        existing = await _one("SELECT * FROM users WHERE user_id=?", (user_id,))
        if existing:
            if existing["username"] != username or existing["full_name"] != full_name:
                await _db.execute(
                    "UPDATE users SET username=?, full_name=? WHERE user_id=?",
                    (username, full_name, user_id),
                )
                await _db.commit()
            return await _one("SELECT * FROM users WHERE user_id=?", (user_id,)), False
        if referrer_id == user_id:
            referrer_id = None
        if referrer_id is not None:
            ref = await _one("SELECT 1 FROM users WHERE user_id=?", (referrer_id,))
            if not ref:
                referrer_id = None
        await _db.execute(
            "INSERT INTO users (user_id, username, full_name, balance, referrer_id, joined_at) "
            "VALUES (?, ?, ?, 0, ?, ?)",
            (user_id, username, full_name, referrer_id, int(time.time())),
        )
        await _db.commit()
        return await _one("SELECT * FROM users WHERE user_id=?", (user_id,)), True


async def adjust_balance(user_id: int, delta: int) -> bool:
    """Admin tomonidan balansni o'zgartirish. Balans manfiy bo'lmaydi."""
    rc, _ = await _write(
        "UPDATE users SET balance = MAX(balance + ?, 0) WHERE user_id=?", (delta, user_id)
    )
    return rc == 1


async def set_ban(user_id: int, banned: bool):
    await _write("UPDATE users SET is_banned=? WHERE user_id=?", (1 if banned else 0, user_id))


async def all_user_ids():
    rows = await _all("SELECT user_id FROM users WHERE is_banned=0")
    return [r[0] for r in rows]


async def user_count():
    return (await _one("SELECT COUNT(*) FROM users"))[0]


async def referral_count(user_id: int):
    return (await _one("SELECT COUNT(*) FROM users WHERE referrer_id=?", (user_id,)))[0]


# ---------- orders ----------

async def purchase(user_id: int, order_type: str, detail: str, price: int,
                   recipient: str = "", quantity: int = 0, product_id: str | None = None) -> int | None:
    """Balansdan yechib, buyurtma yaratadi. Mablag' yetmasa None."""
    async with _lock:
        cur = await _db.execute(
            "UPDATE users SET balance = balance - ? WHERE user_id=? AND balance >= ?",
            (price, user_id, price),
        )
        if cur.rowcount != 1:
            await _db.commit()
            return None
        cur = await _db.execute(
            "INSERT INTO orders (user_id, order_type, detail, price, status, created_at, "
            "recipient, quantity, product_id) VALUES (?, ?, ?, ?, 'kutilmoqda', ?, ?, ?, ?)",
            (user_id, order_type, detail, price, int(time.time()), recipient, quantity, product_id),
        )
        await _db.commit()
        return cur.lastrowid


async def get_order(order_id: int):
    return await _one("SELECT * FROM orders WHERE id=?", (order_id,))


async def complete_order(order_id: int):
    """Kutilayotgan buyurtmani bajarilgan deb belgilaydi.

    Birinchi bajarilgan buyurtmada referrerga bonus beriladi.
    Qaytaradi: (order, bonus) yoki None (allaqachon ko'rib chiqilgan bo'lsa).
    bonus = (referrer_id, amount) yoki None.
    """
    async with _lock:
        cur = await _db.execute(
            "UPDATE orders SET status='bajarildi' WHERE id=? AND status='kutilmoqda'", (order_id,)
        )
        if cur.rowcount != 1:
            await _db.commit()
            return None
        order = await _one("SELECT * FROM orders WHERE id=?", (order_id,))
        bonus = None
        buyer = await _one("SELECT referrer_id FROM users WHERE user_id=?", (order["user_id"],))
        if buyer and buyer["referrer_id"]:
            done = (await _one(
                "SELECT COUNT(*) FROM orders WHERE user_id=? AND status='bajarildi'",
                (order["user_id"],),
            ))[0]
            if done == 1:
                row = await _one("SELECT value FROM settings WHERE key='referral_percent'")
                try:
                    percent = int(row[0]) if row else 0
                except ValueError:
                    percent = 0
                amount = order["price"] * percent // 100
                if amount > 0:
                    await _db.execute(
                        "UPDATE users SET balance = balance + ? WHERE user_id=?",
                        (amount, buyer["referrer_id"]),
                    )
                    await _db.execute(
                        "INSERT INTO transactions (user_id, amount, kind, status, note, created_at) "
                        "VALUES (?, ?, 'referral_bonus', 'tasdiqlandi', ?, ?)",
                        (buyer["referrer_id"], amount, f"buyurtma #{order_id}", int(time.time())),
                    )
                    bonus = (buyer["referrer_id"], amount)
        await _db.commit()
        return order, bonus


async def cancel_order(order_id: int):
    """Kutilayotgan buyurtmani bekor qilib, pulni qaytaradi. Aks holda None."""
    async with _lock:
        cur = await _db.execute(
            "UPDATE orders SET status='bekor qilindi' WHERE id=? AND status='kutilmoqda'", (order_id,)
        )
        if cur.rowcount != 1:
            await _db.commit()
            return None
        order = await _one("SELECT * FROM orders WHERE id=?", (order_id,))
        await _db.execute(
            "UPDATE users SET balance = balance + ? WHERE user_id=?", (order["price"], order["user_id"])
        )
        await _db.commit()
        return order


async def user_orders(user_id: int, limit: int = 15):
    return await _all("SELECT * FROM orders WHERE user_id=? ORDER BY id DESC LIMIT ?", (user_id, limit))


async def user_order_count(user_id: int) -> int:
    return (await _one("SELECT COUNT(*) FROM orders WHERE user_id=?", (user_id,)))[0]


async def order_stats():
    row = await _one("SELECT COUNT(*), COALESCE(SUM(price),0) FROM orders WHERE status='bajarildi'")
    pending = (await _one("SELECT COUNT(*) FROM orders WHERE status='kutilmoqda'"))[0]
    return row[0], row[1], pending


# ---------- provider (Coindrop, TgSuperstars, ...) ----------

async def claim_for_provider(order_id: int, provider_name: str | None = None) -> bool:
    """Buyurtmani API ga yuborish uchun atomik "band qilish" — ikki marta yuborilishining oldini oladi."""
    rc, _ = await _write(
        "UPDATE orders SET provider_status='sending', provider_error=NULL, "
        "provider_attempts=COALESCE(provider_attempts,0)+1, provider_updated=?, "
        "provider_name=COALESCE(provider_name, ?) "
        "WHERE id=? AND status='kutilmoqda' "
        "AND (provider_status IS NULL OR provider_status IN ('error','retry'))",
        (int(time.time()), provider_name, order_id),
    )
    return rc == 1


async def set_provider(order_id: int, status: str, provider_order_id: str | None = None,
                       error: str | None = None, cost: float | None = None):
    await _write(
        "UPDATE orders SET provider_status=?, "
        "provider_order_id=COALESCE(?, provider_order_id), provider_error=?, "
        "provider_cost_usd=COALESCE(?, provider_cost_usd), provider_updated=? WHERE id=?",
        (status, provider_order_id, error, cost, int(time.time()), order_id),
    )


async def mark_provider_note(order_id: int, error: str):
    """Holatni o'zgartirmasdan izohni yozadi (masalan, 'stale' belgisi)."""
    await _write("UPDATE orders SET provider_error=? WHERE id=?", (error, order_id))


async def provider_work(stale_before: int):
    """Worker ishlashi kerak bo'lgan buyurtmalar."""
    return await _all(
        "SELECT * FROM orders WHERE status='kutilmoqda' AND ("
        "provider_status IN ('processing','retry') "
        "OR (provider_status='sending' AND provider_updated < ?)) ORDER BY id LIMIT 40",
        (stale_before,),
    )


async def set_admin_msg(order_id: int, message_id: int):
    await _write("UPDATE orders SET admin_msg_id=? WHERE id=?", (message_id, order_id))


# ---------- transactions ----------

async def create_transaction(user_id: int, amount: int, kind: str, note: str = "",
                             status: str = "kutilmoqda") -> int:
    _, rid = await _write(
        "INSERT INTO transactions (user_id, amount, kind, status, note, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, amount, kind, status, note, int(time.time())),
    )
    return rid


async def get_transaction(tx_id: int):
    return await _one("SELECT * FROM transactions WHERE id=?", (tx_id,))


async def approve_topup(tx_id: int):
    """Kutilayotgan to'ldirishni tasdiqlaydi va balansga qo'shadi. Aks holda None."""
    async with _lock:
        cur = await _db.execute(
            "UPDATE transactions SET status='tasdiqlandi' "
            "WHERE id=? AND status='kutilmoqda' AND kind='topup'",
            (tx_id,),
        )
        if cur.rowcount != 1:
            await _db.commit()
            return None
        tx = await _one("SELECT * FROM transactions WHERE id=?", (tx_id,))
        await _db.execute(
            "UPDATE users SET balance = balance + ? WHERE user_id=?", (tx["amount"], tx["user_id"])
        )
        await _db.commit()
        return tx


async def reject_topup(tx_id: int):
    rc, _ = await _write(
        "UPDATE transactions SET status='rad etildi' "
        "WHERE id=? AND status='kutilmoqda' AND kind='topup'",
        (tx_id,),
    )
    return await get_transaction(tx_id) if rc == 1 else None


# ---------- settings ----------

async def get_setting(key: str) -> str:
    row = await _one("SELECT value FROM settings WHERE key=?", (key,))
    return row[0] if row else ""


async def set_setting(key: str, value: str):
    await _write(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )


async def get_stars_prices():
    return json.loads(await get_setting("stars_prices") or "[]")


async def get_premium_prices():
    return json.loads(await get_setting("premium_prices") or "[]")


async def get_uc_prices():
    try:
        return sorted(json.loads(await get_setting("uc_prices") or "[]"), key=lambda p: p["uc"])
    except (ValueError, KeyError, TypeError):
        return []


async def set_uc_prices(items: list):
    await set_setting("uc_prices", json.dumps(items, ensure_ascii=False))


async def uc_enabled() -> bool:
    return (await get_setting("uc_enabled")) == "1" and bool(await get_uc_prices())


async def uc_stats():
    """(bajarilgan soni, jami UC, tushum, kutilayotgan soni)"""
    row = await _one(
        "SELECT COUNT(*), COALESCE(SUM(quantity),0), COALESCE(SUM(price),0) FROM orders "
        "WHERE order_type='uc' AND status='bajarildi'")
    pending = (await _one("SELECT COUNT(*) FROM orders WHERE order_type='uc' AND status='kutilmoqda'"))[0]
    return row[0], row[1], row[2], pending


# ---------- admins ----------

async def is_admin(user_id: int) -> bool:
    if user_id == SUPER_ADMIN_ID:
        return True
    return (await _one("SELECT 1 FROM admins WHERE user_id=?", (user_id,))) is not None


async def add_admin(user_id: int):
    await _write("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (user_id,))


async def remove_admin(user_id: int) -> bool:
    if user_id == SUPER_ADMIN_ID:
        return False
    await _write("DELETE FROM admins WHERE user_id=?", (user_id,))
    return True


async def list_admins():
    return [r[0] for r in await _all("SELECT user_id FROM admins")]


# ---------- mandatory channels ----------

async def add_channel(chat_id: str, title: str, url: str):
    await _write("INSERT INTO channels (chat_id, title, url) VALUES (?, ?, ?)", (chat_id, title, url))


async def remove_channel(channel_id: int):
    await _write("DELETE FROM channels WHERE id=?", (channel_id,))


async def list_channels():
    return await _all("SELECT * FROM channels ORDER BY id")


# ---------- premium emojis ----------

async def get_emojis() -> dict[str, str]:
    return {r["key"]: r["custom_id"] for r in await _all("SELECT key, custom_id FROM emojis")}


async def set_emoji(key: str, custom_id: str):
    await _write(
        "INSERT INTO emojis (key, custom_id) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET custom_id=excluded.custom_id",
        (key, custom_id),
    )


async def delete_emoji(key: str):
    await _write("DELETE FROM emojis WHERE key=?", (key,))


async def get_styles() -> dict[str, str]:
    return {r["key"]: r["style"] for r in await _all("SELECT key, style FROM button_styles")}


async def set_style(key: str, style: str):
    await _write(
        "INSERT INTO button_styles (key, style) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET style=excluded.style",
        (key, style),
    )


async def delete_style(key: str):
    await _write("DELETE FROM button_styles WHERE key=?", (key,))


async def clear_styles():
    await _write("DELETE FROM button_styles")


async def clear_emojis():
    await _write("DELETE FROM emojis")
