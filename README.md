# ⭐ StarsGo — Telegram Stars & Premium sotuvchi bot

aiogram 3.31 + SQLite. Barcha xabarlar `<blockquote>` ichida, har bir emoji admin paneldan
**Telegram Premium emoji ID** orqali almashtiriladi.

## Imkoniyatlar

**Foydalanuvchi:** Stars / Premium xaridi (balansdan, atomik), buyurtmalar tarixi, hisob, referal
(do'st birinchi xarididan bonus), hisob to'ldirish (chek bilan), murojaat, qo'llanma, majburiy obuna.

Butun interfeys inline: bitta xabar ichida tahrirlanib navigatsiya qilinadi.

**Admin panel** («Boshqaruv»): statistika, xabar yuborish, foydalanuvchini boshqarish (balans, ban),
to'lov rekvizitlari, kanallar, sozlamalar (valyuta, referal %, narxlar, TON, adminlar) va
**✨ Premium emojilar**.

## ✨ Premium emojilarni sozlash

`Boshqaruv → ✨ Premium emojilar`

1. Guruhni tanlang (Asosiy menyu / Admin menyu / Xabarlar) → kerakli emojini tanlang.
2. Premium emojini **xabar qilib yuboring** (ID avtomatik olinadi) yoki raqamli ID ni yozing.
3. «Ommaviy kiritish» — `kalit=ID` qatorlari bilan hammasini birdaniga.
4. «Sinash» — Telegram custom emojini qabul qilishini tekshiradi.

Tugmalarda `icon_custom_emoji_id`, xabarlarda `<tg-emoji>` ishlatiladi (Bot API 9.4+).
**Telegram qoidasi:** custom emoji bot xabarlarida faqat bot egasida Telegram Premium bo'lsa ishlaydi.
Ishlamasa, bot avtomatik oddiy emojiga qaytadi — xato bermaydi.

## 🔌 Coindrop.uz API (avto-yetkazish)

`Boshqaruv → 🔌 Coindrop API → API kalit kiritish` (kalit: coindrop.uz → Profil → Security & API Key, `cd_...`).

- Kalit tekshiriladi, avto-yetkazish yoqiladi: Stars (50–10 000) va Premium (3/6/12 oy) buyurtmalari
  to'lovdan so'ng avtomatik `POST /orders` ga yuboriladi, holat fon workeri orqali kuzatiladi.
- `delivered` → buyurtma bajarildi + referal bonus; `failed` → mablag' foydalanuvchiga avtomatik qaytadi.
- Xatoda (Coindrop balansi yetmasa, kalit noto'g'ri, ...) buyurtma qo'lda rejimda qoladi, adminga xabar boradi,
  kartada «API orqali yuborish» tugmasi chiqadi.
- Ikki marta yuborishdan himoya: atomik band qilish, `external_ref` bo'yicha tekshiruv, API ishlayotganda
  qo'lda bajarish yopiq.
- «Narxlarni sinxronlash» — Coindrop narxi + ustama foiz bilan bot narxlarini yangilaydi.
- Kalit ixtiyoriy ravishda `COINDROP_API_KEY` env orqali ham berilishi mumkin.

## Lokal ishga tushirish

```bash
pip install -r requirements.txt
cp .env.example .env     # BOT_TOKEN va SUPER_ADMIN_ID ni to'ldiring
python main.py
```

## Railway'ga deploy

1. GitHub'ga yuklang (`.env` va `*.db` `.gitignore` da — yuklanmaydi).
2. Railway → **New Project → Deploy from GitHub repo** → shu repo. `Dockerfile` avtomatik topiladi.
3. **Variables:** `BOT_TOKEN`, `SUPER_ADMIN_ID` (ixtiyoriy: `ADMIN_CHAT_ID`).
4. **Volume qo'shing** (service → Settings → Volumes → mount path `/data`).
   Busiz SQLite bazasi har deployda o'chib ketadi! Bot yo'lni `RAILWAY_VOLUME_MOUNT_PATH` dan o'zi oladi.
5. Replicas — **1 ta** bo'lsin (polling bitta nusxada ishlaydi).

Bot HTTP port ochmaydi (worker), shuning uchun domain/healthcheck kerak emas.

## Tuzilma

```
main.py              ishga tushirish, middleware, routerlar
config.py            sozlamalar (.env / Railway Variables)
emojis.py            Premium emoji registri (barcha slotlar) va chiqarish
fallback.py          custom emoji rad etilsa oddiy emojiga qaytish
ui.py                blockquote yordamchilari, tugma filtrlari
texts.py             admin kartalari (buyurtma / to'ldirish)
middlewares.py       ban + majburiy obuna tekshiruvi
database/db.py       SQLite (atomik pul amallari)
keyboards/           reply va inline klaviaturalar
handlers/            user.py, admin.py, emoji_admin.py
```
