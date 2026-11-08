import os

from dotenv import load_dotenv

load_dotenv()


def _int(name: str, default: int = 0) -> int:
    """Bo'sh yoki noto'g'ri qiymat bo'lsa ham yiqilmaydi."""
    raw = (os.getenv(name) or "").strip()
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


def _db_path() -> str:
    explicit = (os.getenv("DB_PATH") or "").strip()
    if explicit:
        return explicit
    # Railway Volume ulangan bo'lsa, baza avtomatik shu yerda saqlanadi
    volume = (os.getenv("RAILWAY_VOLUME_MOUNT_PATH") or "").strip()
    if volume:
        return os.path.join(volume, "starsgo.db")
    return "starsgo.db"


BOT_TOKEN = (os.getenv("BOT_TOKEN") or "").strip()
SUPER_ADMIN_ID = _int("SUPER_ADMIN_ID")
# Bildirishnomalar kelishi kerak bo'lgan chat. Berilmasa — bosh adminga yuboriladi.
ADMIN_CHAT_ID = _int("ADMIN_CHAT_ID") or SUPER_ADMIN_ID
DB_PATH = _db_path()
# Railway'da baza Volume ichida bo'lmasa, har deployda o'chib ketadi
_VOL = (os.getenv("RAILWAY_VOLUME_MOUNT_PATH") or "").strip()
ON_RAILWAY = bool(os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("RAILWAY_PROJECT_ID"))
DB_PERSISTENT = (not ON_RAILWAY) or bool(_VOL and os.path.abspath(DB_PATH).startswith(os.path.abspath(_VOL)))
# Ixtiyoriy: Coindrop kaliti env orqali ham berilishi mumkin (admin paneldagi qiymat ustun turadi)
COINDROP_API_KEY = (os.getenv("COINDROP_API_KEY") or "").strip()
# Deploy paytida to'plangan xabarlarni tashlab yuborish (standart: yo'q)
DROP_PENDING_UPDATES = (os.getenv("DROP_PENDING_UPDATES") or "0").strip() == "1"

MAX_TOPUP = 1_000_000_000

DEFAULT_STARS_PRICES = [
    {"stars": 50, "price": 10000},
    {"stars": 100, "price": 20000},
    {"stars": 150, "price": 30000},
    {"stars": 200, "price": 40000},
    {"stars": 250, "price": 50000},
    {"stars": 300, "price": 60000},
    {"stars": 500, "price": 100000},
]

DEFAULT_PREMIUM_PRICES = [
    {"months": 3, "price": 155000},
    {"months": 6, "price": 208000},
    {"months": 12, "price": 380000},
]
