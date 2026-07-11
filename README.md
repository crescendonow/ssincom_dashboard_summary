# S&S Incom — Dashboard ยอดขายทราย

> Standalone FastAPI service ที่แสดงสรุปยอดขายทรายแบบ line-item จากฐานข้อมูลระบบ bill (PostgreSQL) — deploy บน Railway production ได้เอง.

---

## 1. ภาพรวม

โปรเจกต์นี้คือ **dashboard ยอดขายทราย** แบบ standalone web app ที่:

- **ดึงข้อมูลสด** จากฐานข้อมูลระบบ bill (`ss_invoices.invoices` + `invoice_items` + `products.drivers`) ผ่าน API `/api/dashboard/sales/rows`
- แสดงผลด้วย **Chart.js** + ตาราง HTML — 10 แท็บวิเคราะห์ (ภาพรวม, กราฟแยกประเภท, pivot รายเดือน, ลูกค้า, คนขับ, สินค้าขายดี, เทียบครึ่งปี/รายปี, แนวโน้มตันย้อนหลัง 2560–2568, รายละเอียด, อัปโหลด/Export)
- มี **login gate** (username/password เดียว, session cookie) ป้องกันการเข้าถึง dashboard โดยไม่ได้รับอนุญาต
- **read-only** — ไม่มี endpoint เขียนกลับฐานข้อมูล bill
- มี **offline fallback** — ถ้า API ไม่ตอบ จะใช้ข้อมูลฝังในไฟล์ HTML (`EMBEDDED_DATA`) หรือ localStorage cache

### ข้อมูลย้อนหลัง

| ประเภท | ช่วงปี | แหล่ง | มูลค่า/ลูกค้า/คนขับ |
|---|---|---|---|
| สดจาก DB | 2568–2569 (live) | `ss_invoices` ผ่าน `/api/dashboard/sales/rows` | ✅ ครบทุกฟิลด์ |
| ปริมาณตัน | 2560–2568 | `HISTORICAL_VOLUME` (static, ฝังใน HTML) | มีเฉพาะตัน |
| ยอดขายบาท | 2560–2568 | `HISTORICAL_SALES` (static, ฝังใน HTML) | มีเฉพาะบาท (รวม VAT) |

---

## 2. สถาปัตยกรรม

```
Browser
  │
  ├─ GET /login          → login.html (login form)
  ├─ POST /login         → ตรวจ user/pass → session cookie → redirect /frontend/
  ├─ GET /frontend/      → sand_dashboard.html (auth-gated)
  │     │
  │     └─ fetch /api/dashboard/sales/rows  (auth-gated, 401 ถ้าไม่ login)
  │           │
  │           └─ app/sales_dashboard.py
  │                ├─ SQLAlchemy query: ss_invoices.invoices
  │                │   JOIN ss_invoices.invoice_items
  │                │   LEFT JOIN products.drivers
  │                ├─ enrich: groupId/groupName จาก app/product_groups.py
  │                └─ คำนวณ: qty→ตัน, value=coalesce(amount,qty*price),
  │                          vat=value×0.07, total=value+vat, date=dd/mm/พ.ศ.
  │
  ├─ GET /logout         → เคลียร์ session → redirect /login
  ├─ GET /api/auth/me    → {authenticated, user} (สำหรับ frontend เช็คสถานะ)
  ├─ GET /healthz        → {ok: true} (สำหรับ Railway health check)
  │
  └─ static: /frontend/* (StaticFiles — เสิร์ฟ app.js, xlsx ฯลฯ)
```

### Request Flow

1. ผู้ใช้เข้า `/` → redirect → `/frontend/`
2. ถ้ายังไม่ login → redirect → `/login?next=/frontend/`
3. login สำเร็จ → session cookie (max-age 2 ชม.) → redirect → `/frontend/` → `sand_dashboard.html`
4. `sand_dashboard.html` โหลดเสร็จ → `init()` → `loadFromServer()` → `fetch('/api/dashboard/sales/rows')`
5. API ตรวจ session → query DB → คืน JSON array (line-item rows)
6. frontend เก็บใน `appData` + cache ใน `localStorage` → render ทุกแท็บ
7. ถ้า API ล้มเหลว → fallback: localStorage cache → `EMBEDDED_DATA` (ฝังใน HTML)

### Stack

| ชั้น | เทคโนโลยี | เวอร์ชัน |
|---|---|---|
| Backend | FastAPI | 0.115.6 |
| ASGI server | uvicorn[standard] | 0.34.0 |
| ORM | SQLAlchemy | 2.0.36 |
| DB driver | psycopg2-binary | 2.9.10 |
| Form parsing | python-multipart | 0.0.20 |
| Session | itsdangerous (SessionMiddleware) | 2.2.0 |
| Env | python-dotenv | 1.0.1 |
| Python | 3.11 | (runtime.txt) |
| Frontend chart | Chart.js | 4.4.1 (CDN) |
| Frontend XLSX export | SheetJS | 0.18.5 (CDN) |
| Deploy | Railway + Nixpacks | — |

---

## 3. โครงสร้างไฟล์

```
ssincom_dashboard_summary/
├── app/                          # Backend (FastAPI)
│   ├── __init__.py
│   ├── main.py                   # FastAPI app — login gate, serve frontend, auth routes
│   ├── database.py                # SQLAlchemy engine + SessionLocal (normalize DATABASE_URL)
│   ├── models.py                  # 3 ORM models: Invoice, InvoiceItem, Driver
│   ├── sales_dashboard.py         # GET /api/dashboard/sales/rows — query + enrich + calc
│   └── product_groups.py          # Static map itemId→(groupId, groupName) + group_of()
│
├── frontend/                     # Frontend (static HTML/JS)
│   ├── sand_dashboard.html        # Dashboard หลัก (sidebar layout, 10 แท็บ, Chart.js)
│   ├── login.html                # Login form (POST /login, next redirect)
│   ├── app.js                    # (ไม่ถูกใช้โดย dashboard — ปล่อยไว้)
│   └── รายงานยอดขายทราย_ม.ค.-พ.ค.2569.xlsx  # ต้นฉบับ EMBEDDED_DATA
│
├── requirements.txt              # Python dependencies (pinned)
├── Procfile                      # web: uvicorn app.main:app --host 0.0.0.0 --port $PORT
├── railway.json                  # Railway config (builder=NIXPACKS, startCommand)
├── nixpacks.toml                 # Nixpacks start cmd
├── runtime.txt                   # Python 3.11
├── .env.example                  # Template environment variables
├── .gitignore                    # .env, __pycache__, *.pyc, .docs
└── .docs/                        # เอกสารวิเคราะห์/แผน (gitignored)
```

---

## 4. รายละเอียด Backend

### 4.1 `app/main.py` — FastAPI app + auth

| Route | Method | Auth | ฟังก์ชัน |
|---|---|---|---|
| `/login` | GET | public | เสิร์ฟ `login.html` (ถ้า login แล้ว → redirect ต่อ) |
| `/login` | POST | public | ตรวจ `APP_USER`/`APP_PASS` → session → redirect `next` |
| `/logout` | GET | public | เคลียร์ session → redirect `/login` |
| `/api/auth/me` | GET | public | คืน `{authenticated, user}` |
| `/` | GET | public | redirect → `/frontend/` |
| `/frontend/` | GET | **gated** | เสิร์ฟ `sand_dashboard.html` (ไม่ login → redirect `/login`) |
| `/frontend/sand_dashboard.html` | GET | **gated** | เดียวกับ `/frontend/` |
| `/healthz` | GET | public | `{ok: true}` — health check |
| `/api/dashboard/sales/rows` | GET | **gated** | คืน line-item rows (ใน router) |
| `/frontend/*` | static | public | StaticFiles (app.js, xlsx ฯลฯ) |

**Session**: `SessionMiddleware` (itsdangerous) — `max_age=7200` (2 ชม.), secret = `SESSION_SECRET`.

**Login**: ใช้ `hmac.compare_digest` เปรียบเทียบ username/password (กัน timing attack). ถ้าผิด → redirect `/login?error=1`.

**Safe redirect**: `_safe_next()` ตรวจ `next` ว่าขึ้นต้นด้วย `/` และไม่ใช่ `//` (กัน open redirect).

### 4.2 `app/database.py` — DB connection

- `_normalize_db_url()`:
  - `postgres://` → `postgresql://` (SQLAlchemy ต้องการ)
  - ถ้า host ไม่ใช่ `.railway.internal` (public host) และยังไม่มี `sslmode` → เติม `sslmode=require`
- `engine` = `create_engine(DATABASE_URL, pool_pre_ping=True, future=True)` — `pool_pre_ping` กัน connection ตาย
- `SessionLocal` = `sessionmaker(autoflush=False, autocommit=False, future=True)`

### 4.3 `app/models.py` — ORM models (read-only)

| Model | Schema | Table | ใช้สำหรับ |
|---|---|---|---|
| `Invoice` | `ss_invoices` | `invoices` | หัวใบกำกับ: idx, invoice_number, invoice_date, fname (ลูกค้า), driver_id |
| `InvoiceItem` | `ss_invoices` | `invoice_items` | รายการสินค้า: cf_itemid, cf_itemname, quantity, price, amount |
| `Driver` | `products` | `drivers` | คนขับ: driver_id, prefix, first_name, last_name |

> **quirk**: `invoice_items.invoice_number` บางแถวเก็บเลขที่ใบกำกับ บางแถวเก็บ `invoices.idx` (varchar) → ต้อง JOIN เผื่อสองแบบทุกครั้ง (ดู `sales_dashboard.py:56-59`)

### 4.4 `app/sales_dashboard.py` — Endpoint `/api/dashboard/sales/rows`

```sql
SELECT inv.idx, inv.invoice_number, inv.invoice_date, inv.fname,
       itm.idx, itm.cf_itemid, itm.cf_itemname, itm.quantity,
       itm.cf_itempricelevel_price, itm.amount,
       drv.prefix, drv.first_name, drv.last_name
FROM ss_invoices.invoices inv
JOIN ss_invoices.invoice_items itm
  ON itm.invoice_number = inv.invoice_number
  OR itm.invoice_number = CAST(inv.idx AS text)   -- ⚠ quirk
LEFT JOIN products.drivers drv ON drv.driver_id = inv.driver_id
ORDER BY inv.invoice_date ASC, inv.idx ASC, itm.idx ASC
```

**การแปลงต่อแถว (Python):**

| ฟิลด์ | คำนวณจาก |
|---|---|
| `date` | `f"{day:02d}/{month:02d}/{year+543}"` (พ.ศ.) |
| `month` | `invoice_date.month` (1–12) |
| `qty` | `quantity/1000` ถ้า `>=1000` (kg→ตัน) ไม่งั้นใช้ค่าเดิม |
| `value` | `amount` ถ้าไม่ null ไม่งั้น `qty×price` (ก่อน VAT) |
| `vat` | `value × 0.07` |
| `total` | `value + vat` (รวม VAT) |
| `groupId`/`groupName` | `group_of(cf_itemid)` จาก static map |
| `driver` | `"prefix first_name last_name".strip()` หรือ `"-"` |

**Response shape** (JSON array):
```json
{
  "no": "1",
  "date": "05/01/2569",
  "month": 1,
  "customer": "ฟิวเจอร์ กรีนเนอร์จี จำกัด",
  "itemId": "1-2054",
  "itemName": "ทรายคัดขนาดพิเศษขนาด 0.3 มิลลิเมตร",
  "groupId": 3,
  "groupName": "ทรายคัดขนาดพิเศษขนาด 0.3 มิลลิเมตร",
  "qty": 26.38,
  "value": 29018.0,
  "vat": 2031.26,
  "total": 31049.26,
  "driver": "นาย สมศักดิ์ กุลสุวรรณ"
}
```

### 4.5 `app/product_groups.py` — Static group map

- `ITEM_TO_GROUP`: dict 31 รหัส → `(groupId, groupName)` — สกัดจาก xlsx ม.ค.–พ.ค. 2569
- `group_of(item_id)`: คืน `(groupId, groupName)` หรือ `(0, "อื่นๆ")` ถ้าไม่พบ
- **Coverage**: bill DB มี 93 รหัส — map ครอบ 31 รหัส (~75% มูลค่า), อีก 62 รหัส (~25%) ตกกลุ่ม "อื่นๆ"
- การตัดสินใจ (9 ก.ค. 2569): ยอมรับ "อื่นๆ" 25% ไปก่อน ค่อยขยาย map ทีหลัง

---

## 5. รายละเอียด Frontend (`frontend/sand_dashboard.html`)

### 5.1 Layout

- **Sidebar ซ้าย** (fixed, 260px) — แบ่งกลุ่มเมนู: เมนูหลัก, วิเคราะห์ตาม, เปรียบเทียบ, อื่นๆ
- **Topbar** — `page-title`/`page-subtitle` (เปลี่ยนตามแท็บ) + year-filter + data-status
- **User profile** — avatar "AD", "Admin", "ผู้ดูแลระบบ" + ลิงก์ `/logout`
- **มือถือ** (≤768px) — sidebar ซ่อน, ปุ่ม ☰ toggle, auto-close เมื่อคลิกนอก

### 5.2 แท็บ (10)

| # | แท็บ | แสดง |
|---|---|---|
| 1 | ภาพรวม | KPI cards, bar chart รายเดือน, line chart ตัน, **กราฟเปรียบเทียบรายปีย้อนหลัง** (bar=ตัน + line=บาท 2560→ปัจจุบัน) |
| 2 | กราฟแยกประเภท | bar/pie/doughnut แยกตามขนาดทราย |
| 3 | ยอดขายรายเดือน | pivot table ขนาดทราย × เดือน (เลือก metric: total/value/qty/count) |
| 4 | ตามลูกค้า | bar chart top 15 + pivot ลูกค้า × ประเภทสินค้า |
| 5 | ตามคนขับ | bar chart + pivot คนขับ × เดือน |
| 6 | สินค้าขายดี | bar chart + table top 10/20/50 |
| 7 | เทียบครึ่งปี/รายปี | bar chart H1/H2 + bar chart รายปี |
| 8 | แนวโน้มตัน 60-68 | KPI + bar chart ปี 2560–2568 + line chart เดือน + top 10 สินค้า + table (ตัน + บาท + บาท/ตัน) |
| 9 | รายละเอียด | table + filter (เดือน/ประเภท/ค้นหา) + pagination (50/หน้า) |
| 10 | อัปโหลด / Export | CSV upload (TIS-620) + export XLSX/CSV |

### 5.3 ข้อมูลฝังใน HTML (static)

| ตัวแปร | ความหมาย | ขนาด |
|---|---|---|
| `EMBEDDED_DATA` | line-item snapshot จาก xlsx ม.ค.–พ.ค. 2569 (692 แถว) | ~214 KB |
| `HISTORICAL_VOLUME` | ปริมาณตัน ปี 2560–2568 `[ปี,เดือน,productIdx,ตัน]` | ~21 KB |
| `HISTORICAL_SALES` | ยอดขายบาท ปี 2560–2568 `[ปี,เดือน,value,VAT,total]` | ~4 KB |

### 5.4 การโหลดข้อมูล (`loadFromServer()`)

```
fetch('/api/dashboard/sales/rows')
  ├─ สำเร็จ + rows.length > 0 → appData = rows + cache localStorage
  ├─ ล้มเหลว → อ่าน localStorage cache (ถ้ามี) → appData = cached
  └─ ไม่มี cache → appData = EMBEDDED_DATA (offline fallback)
```

### 5.5 Year filter

- `rowYear(r)` = parse ปี พ.ศ. จาก `r.date` (dd/mm/พ.ศ.)
- `yearData()` = กรองเฉพาะปีที่เลือกใน `#year-filter`
- แท็บเทียบครึ่งปี/รายปี + กราฟเปรียบเทียบรายปี ใช้ `appData` ทั้งหมด (ไม่กรองปี)

---

## 6. Environment Variables

| ตัวแปร | จำเป็น | ค่าตัวอย่าง | หมายเหตุ |
|---|---|---|---|
| `DATABASE_URL` | ✅ | `postgresql://user:pass@host:5432/db` | Railway PostgreSQL (bill DB). `sslmode=require` เติมอัตโนมัติถ้า public host |
| `APP_USER` | ✅ | `admin` | username สำหรับ login |
| `APP_PASS` | ✅ | (สุ่มยาว) | password สำหรับ login |
| `SESSION_SECRET` | ✅ | (สุ่มยาว 32+ chars) | secret สำหรับเซ็น session cookie |

ดู template ที่ `.env.example`

---

## 7. การรัน Local

### 7.1 สร้าง `.env`

```bash
cp .env.example .env
# แก้ค่าให้ตรงกับ production DB และ user/pass ที่ต้องการ
```

### 7.2 ติดตั้ง dependencies + รัน

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

### 7.3 ทดสอบ

1. เปิด `http://localhost:8000/` → redirect → `/login`
2. login ด้วย `APP_USER`/`APP_PASS` → redirect → `/frontend/`
3. ตรวจ data-status ขึ้น "📊 ข้อมูลจากฐานข้อมูล (N รายการ)"
4. ตรวจครบ 10 แท็บ ไม่มี error ใน console
5. ไม่ login → `/frontend/sand_dashboard.html` redirect `/login` + `/api/dashboard/sales/rows` = 401

---

## 8. การ Deploy บน Railway

### 8.1 สร้าง Railway project

1. ไปที่ [railway.app](https://railway.app) → New Project → Deploy from GitHub repo
2. เลือก repo `ssincom_dashboard_summary`
3. Railway จะใช้ `railway.json` (builder=NIXPACKS) อัตโนมัติ

### 8.2 ตั้ง Environment Variables

ใน Railway → Variables → เพิ่ม:

```
DATABASE_URL=postgresql://...   (Railway PostgreSQL หรือ external DB)
APP_USER=admin
APP_PASS=<สุ่มยาว>
SESSION_SECRET=<สุ่มยาว 32+ chars>
```

### 8.3 Deploy

- Railway จะ build ด้วย Nixpacks (Python 3.11 ตาม `runtime.txt`) + install `requirements.txt`
- Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT` (จาก `nixpacks.toml`)
- หลัง deploy: ตรวจ `/healthz` → `{ok: true}`

### 8.4 หลัง Deploy ตรวจสอบ

1. `https://<your-app>.up.railway.app/healthz` → `{ok: true}`
2. `/` → redirect → `/login`
3. login → `/frontend/` → data-status "📊 ข้อมูลจากฐานข้อมูล"
4. ตรวจครบ 10 แท็บ

---

## 9. การ Push ขึ้น GitHub

Repo: `https://github.com/crescendonow/ssincom_dashboard_summary.git`
Branch: `main`

### 9.1 Clone (ครั้งแรก)

```bash
git clone https://github.com/crescendonow/ssincom_dashboard_summary.git
cd ssincom_dashboard_summary
```

### 9.2 สร้าง `.env` (local only — ไม่ push)

```bash
cp .env.example .env
# แก้ค่า DATABASE_URL, APP_USER, APP_PASS, SESSION_SECRET
```

> `.env` อยู่ใน `.gitignore` — จะไม่ถูก push

### 9.3 แก้ไขโค้ด + ทดสอบ local

```bash
uvicorn app.main:app --reload
# ทดสอบทุกแท็บ + login/logout + 401
```

### 9.4 Commit + Push

```bash
# ดูสถานะ
git status

# เพิ่มไฟล์ที่แก้ (ยกเว้น .env ที่ถูก ignore อัตโนมัติ)
git add app/ frontend/ requirements.txt Procfile railway.json nixpacks.toml runtime.txt .env.example .gitignore

# commit
git commit -m "描述การเปลี่ยนแปลง"

# push ขึ้น GitHub
git push origin main
```

### 9.5 Railway auto-deploy

ถ้าเปิด auto-deploy ใน Railway → push ขึ้น `main` แล้ว Railway จะ build + deploy อัตโนมัติ

---

## 10. ความเสี่ยง / ข้อควรระวัง

1. **DB quirk `invoice_items.invoice_number`** — บางแถวเก็บเลขที่ใบกำกับ บางแถวเก็บ `idx`. JOIN ต้องเผื่อสองแบบ (`OR itm.invoice_number = CAST(inv.idx AS text)`) — มิฉะนั้นยอดตกหล่น
2. **Static map coverage** — `product_groups.py` ครอบ 31/93 รหัส (~75% มูลค่า). สินค้าใหม่ตกกลุ่ม "อื่นๆ" (groupId 0) — แท็บกลุ่มยังทำงาน แต่ "อื่นๆ" จะใหญ่. ต้องขยาย map ทีหลัง
3. **ปีที่ขาดยอดบาท** — `HISTORICAL_SALES` บางปี/เดือนไม่มีข้อมูลบาท → `missingBahtMonths()` ติดดาว `*` + ซ่อนค่า (ไม่ใส่ 0 เพราะจะทำให้ยอดรวมดูครบทั้งที่ขาด)
4. **read-only** — ไม่มี endpoint เขียนกลับ bill DB
5. **Session 2 ชม.** — `max_age=7200` ผู้ใช้ต้อง login ใหม่หลัง 2 ชม.
6. **`.docs/` ถูก ignore** — เอกสารวิเคราะห์/แผนไม่ถูก push ขึ้น GitHub (ตั้งใจ)

---

## 11. เอกสารอ้างอิง

เอกสารวิเคราะห์/แผนอยู่ใน `.docs/` (gitignored — local only):

| ไฟล์ | เนื้อหา |
|---|---|
| `1_plan_refactor_ssincom_landingpage.md` | แผน refactor landingpage |
| `2_add_dashboard_sand.md` | แผนเพิ่ม dashboard |
| `3_addlogin_fordata.md` | แผนเพิ่ม login สำหรับ data |
| `3_sales_dashboard_db.md` | สำรวจ DB schema สำหรับ dashboard |
| `4_connect_db_summary.md` | สรุปการเชื่อมต่อ DB |
| `5_prepare_for_deploy_railway_production.md` | แผนเตรียม deploy Railway |
| `6_prepare_merging_new_file_sand_dashboard.md` | แผน merge `sand_dashboard.html` เวอร์ชันใหม่ |

---

## 12. งานที่เหลือ (TODO)

- [ ] ขยาย `product_groups.py` map ให้ครอบ 62 รหัสที่เหลือ ลด "อื่นๆ"
- [ ] ตั้ง env บน Railway + deploy production
- [ ] หลัง deploy: ตรวจ `/healthz` + login + dashboard โหลดข้อมูลสด
- [ ] (ภายหลัง) ขยาย map ครบทุกรหัสสินค้า
