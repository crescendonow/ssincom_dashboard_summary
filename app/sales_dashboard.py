# app/sales_dashboard.py
# endpoint /api/dashboard/sales/rows — คืน "line-item" สดจาก bill DB (ss_invoices)
# ให้ตรง shape ที่ frontend/sand_dashboard.html ใช้ (แทนที่ EMBEDDED_DATA จาก xlsx)
# logic คำนวณ (VAT 7%, qty→ตัน, join quirk idx::text, value=coalesce(amount,qty*price))
# ยืมจาก ssincom_bill/app/saletax_report.py — read-only + auth-gated
from collections import Counter
from datetime import date

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import String, cast, func, or_
from sqlalchemy.orm import Session

from . import models
from .customer_names import clean_customer_name
from .database import SessionLocal
from .product_groups import group_of, is_known

router = APIRouter()

VAT_RATE = 0.07

# ผู้ใช้ยืนยัน (16 ก.ค. 2569): ข้อมูลใน bill DB ก่อน 1 ม.ค. 2569 เป็น "ข้อมูลทดสอบระบบ" ตอน go-live
# ไม่ใช่ยอดขายจริง (เช่น ใบ 6808090003-6808090015 ส.ค. 2568 ที่ไม่มีในรายงาน XLS ทางการ) — ตัดทิ้ง
# จาก live query ทุกจุด. ปี 2568 บน dashboard ใช้ไฟล์รายงาน (closed month) อยู่แล้ว ไม่กระทบ.
LIVE_DATA_START = date(2026, 1, 1)  # = 1 ม.ค. 2569 (พ.ศ.)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/api/dashboard/sales/rows", include_in_schema=False)
def sales_rows(request: Request, db: Session = Depends(get_db)):
    # auth gate — เหมือน dashboard page (ไม่ login → 401)
    if not request.session.get("user"):
        return JSONResponse({"detail": "Not authenticated"}, status_code=401)

    inv = models.Invoice
    itm = models.InvoiceItem
    drv = models.Driver
    cust = models.CustomerList

    q = (
        db.query(
            inv.idx,
            inv.invoice_number,
            inv.invoice_date,
            inv.fname,
            itm.idx.label("item_idx"),
            itm.invoice_number.label("item_invoice_number"),
            itm.cf_itemid,
            itm.cf_itemname,
            itm.quantity,
            itm.cf_itempricelevel_price,
            itm.amount,
            drv.prefix,
            drv.first_name,
            drv.last_name,
            cust.fname.label("cust_fname"),
            cust.cf_hq,
            cust.cf_branch,
        )
        .join(
            itm,
            or_(
                itm.invoice_number == inv.invoice_number,
                itm.invoice_number == cast(inv.idx, String),  # ⚠ quirk: บางแถวเก็บ idx
            ),
        )
        .outerjoin(drv, inv.driver_id == drv.driver_id)
        .outerjoin(cust, inv.personid == cust.personid)
        .filter(inv.invoice_date >= LIVE_DATA_START)  # ตัดข้อมูลทดสอบก่อน 2569 ทิ้ง
        .order_by(inv.invoice_date.asc(), inv.idx.asc(), itm.idx.asc())
    )

    all_rows = q.all()

    # ป้องกัน item ถูกนับซ้ำจากบั๊ก join ข้างบน (⚠ quirk): ถ้า item_idx เดียวกันไป match
    # invoice 2 ใบพร้อมกัน (ใบหนึ่งตรงแบบตรงๆ อีกใบตรงจาก idx-fallback) จะได้แถวซ้ำ
    # กรณีปกติ (ไม่ซ้ำ) โค้ดนี้ไม่ทำอะไรเพิ่ม — คัดเฉพาะแถวที่ item_invoice_number ตรงกับ
    # invoice_number จริง (ไม่ใช่ fallback จาก idx) ไว้เป็นตัวที่ถูกต้อง
    item_idx_counts = Counter(r.item_idx for r in all_rows)
    keep_inv_idx: dict = {}
    for r in all_rows:
        if item_idx_counts[r.item_idx] <= 1:
            continue
        is_direct = r.item_invoice_number is not None and r.item_invoice_number == r.invoice_number
        chosen = keep_inv_idx.get(r.item_idx)
        if chosen is None or (is_direct and not chosen[1]):
            keep_inv_idx[r.item_idx] = (r.idx, is_direct)
    if keep_inv_idx:
        print(f"[sales_rows] resolved {len(keep_inv_idx)} OR-join duplicate item_idx: {sorted(keep_inv_idx)}")

    unmapped: dict = {}  # รหัสสินค้าที่ไม่อยู่ใน product_groups map (ตกกลุ่ม 16) — ไว้เตือน
    rows = []
    for (
        idx,
        _inv_no,
        inv_date,
        fname,
        item_idx,
        _item_inv_no,
        cf_itemid,
        cf_itemname,
        quantity,
        price,
        amount,
        dpre,
        dfirst,
        dlast,
        cust_fname,
        cf_hq,
        cf_branch,
    ) in all_rows:
        if item_idx in keep_inv_idx and idx != keep_inv_idx[item_idx][0]:
            continue  # OR-join fallback duplicate ของ item นี้ — ใช้แถวที่ match ตรงแทน
        qraw = float(quantity or 0.0)
        price = float(price or 0.0)
        value = float(amount) if amount is not None else qraw * price
        vat = value * VAT_RATE
        total = value + vat
        qty_ton = qraw / 1000.0 if qraw >= 1000 else qraw

        group_id, group_name = group_of(cf_itemid)
        if not is_known(cf_itemid):
            key = str(cf_itemid).strip() if cf_itemid else "(blank)"
            u = unmapped.setdefault(key, {"itemName": cf_itemname, "count": 0, "value": 0.0})
            u["count"] += 1
            u["value"] += value

        driver = " ".join(
            p for p in [(dpre or "").strip(), (dfirst or "").strip(), (dlast or "").strip()] if p
        ).strip() or "-"

        if inv_date:
            date_str = f"{inv_date.day:02d}/{inv_date.month:02d}/{inv_date.year + 543}"
            month = inv_date.month
        else:
            date_str = None
            month = None

        rows.append(
            {
                "no": str(len(rows) + 1),
                "date": date_str,
                "month": month,
                "customer": clean_customer_name(cust_fname or fname, cf_hq, cf_branch),
                "itemId": cf_itemid,
                "itemName": cf_itemname,
                "groupId": group_id,
                "groupName": group_name,
                "qty": round(qty_ton, 3),
                "value": round(value, 2),
                "vat": round(vat, 2),
                "total": round(total, 2),
                "driver": driver,
            }
        )

    if unmapped:
        top = sorted(unmapped.items(), key=lambda kv: -kv[1]["count"])
        print(
            f"[sales_rows] {len(unmapped)} unmapped item code(s) defaulted to group 16 "
            f"(needs classifying in product_groups.py): "
            + ", ".join(f"{k}({v['count']})" for k, v in top)
        )

    return JSONResponse(rows)


@router.get("/api/dashboard/unmapped-items", include_in_schema=False)
def unmapped_items(request: Request, db: Session = Depends(get_db)):
    """รายงานรหัสสินค้าที่ยังไม่ถูกจัดกลุ่มใน product_groups.ITEM_TO_GROUP (จึงตกกลุ่ม 16
    อัตโนมัติ) — ใช้แทนกลุ่ม "อื่นๆ" เดิมที่ยกเลิกไป เพื่อเตือนว่ามีรหัสใหม่ต้องเพิ่มลง map.
    คืน {count, items:[{itemId, itemName, count, value}]} เรียงตามจำนวนรายการมาก→น้อย."""
    if not request.session.get("user"):
        return JSONResponse({"detail": "Not authenticated"}, status_code=401)

    itm = models.InvoiceItem
    value_expr = func.coalesce(itm.amount, itm.quantity * itm.cf_itempricelevel_price)
    agg = (
        db.query(
            itm.cf_itemid,
            func.max(itm.cf_itemname).label("name"),
            func.count(itm.idx).label("cnt"),
            func.coalesce(func.sum(value_expr), 0).label("val"),
        )
        .group_by(itm.cf_itemid)
        .all()
    )
    items = [
        {
            "itemId": cf_itemid,
            "itemName": name,
            "count": int(cnt or 0),
            "value": round(float(val or 0), 2),
        }
        for cf_itemid, name, cnt, val in agg
        if not is_known(cf_itemid)
    ]
    items.sort(key=lambda x: (-x["count"], -x["value"]))
    return JSONResponse({"count": len(items), "items": items})


# กลุ่ม 17 = "ถุง Big Bag ขนาด 1 ตัน" ขายเป็นใบ ไม่ใช่ตัน — ตัดออกจากยอดตันให้ตรงกับ dashboard
BIGBAG_GROUP = 17


@router.get("/api/dashboard/customer-branches", include_in_schema=False)
def customer_branches(request: Request, db: Session = Depends(get_db)):
    """รายงานการจำแนก "สำนักงานใหญ่ / สาขา" ของลูกค้า พร้อมกลุ่มสินค้าที่แต่ละหน่วยซื้อ.

    ใช้ตรวจว่าการแยกสาขาทำงานถูกต้องบนข้อมูลจริง — dashboard แยกสาขาด้วย
    products.customer_list.cf_hq/cf_branch (join ด้วย personid) ผ่าน clean_customer_name()
    ซึ่งดูจากโค้ดอย่างเดียวไม่รู้ว่าข้อมูลจริงครบหรือเปล่า

    คืน:
      unmatched : ใบกำกับที่หา customer_list ไม่เจอ (cf_hq เป็น NULL) -> ไม่มี suffix สาขา
                  ทั้งที่อาจเป็นสาขาจริง = พังเงียบ ถ้า rows > 0 แปลว่าจำแนกยังไม่ครบ
      families  : ลูกค้าที่มีหลายหน่วย (สำนักงานใหญ่ + สาขา) จัดกลุ่มด้วยชื่อฐาน
      singles   : ลูกค้าที่มีหน่วยเดียว
    """
    if not request.session.get("user"):
        return JSONResponse({"detail": "Not authenticated"}, status_code=401)

    inv = models.Invoice
    itm = models.InvoiceItem
    cust = models.CustomerList

    value_expr = func.coalesce(itm.amount, itm.quantity * itm.cf_itempricelevel_price)
    rows = (
        db.query(
            inv.personid,
            inv.fname,
            cust.fname.label("cust_fname"),
            cust.cf_hq,
            cust.cf_branch,
            itm.cf_itemid,
            itm.quantity,
            value_expr.label("value"),
        )
        .join(
            itm,
            or_(
                itm.invoice_number == inv.invoice_number,
                itm.invoice_number == cast(inv.idx, String),  # ⚠ quirk เดียวกับ /sales/rows
            ),
        )
        .outerjoin(cust, inv.personid == cust.personid)
        .filter(inv.invoice_date >= LIVE_DATA_START)
        .all()
    )

    units: dict = {}
    unmatched_rows = 0
    unmatched_names: dict = {}

    for personid, fname, cust_fname, cf_hq, cf_branch, cf_itemid, quantity, value in rows:
        # ใช้ตัวเดียวกับ /sales/rows เสมอ — ถ้าเขียน logic ชื่อซ้ำ รายงานจะไม่ตรงกับที่ dashboard แสดง
        display = clean_customer_name(cust_fname or fname, cf_hq, cf_branch)

        if cf_hq is None:  # join ไม่ติด customer_list
            unmatched_rows += 1
            u = unmatched_names.setdefault(display, {"name": display, "personid": personid, "rows": 0})
            u["rows"] += 1

        qraw = float(quantity or 0.0)
        qty_ton = qraw / 1000.0 if qraw >= 1000 else qraw
        val = float(value or 0.0)
        gid, gname = group_of(cf_itemid)

        key = (personid, display)
        unit = units.setdefault(
            key,
            {
                "personid": personid,
                "displayName": display,
                "masterName": cust_fname,
                "invoiceName": fname,
                "isHQ": (cf_hq == 1) if cf_hq is not None else None,
                "branch": cf_branch or None,
                "matched": cf_hq is not None,
                "rows": 0,
                "tons": 0.0,
                "value": 0.0,
                "_groups": {},
            },
        )
        unit["rows"] += 1
        unit["value"] += val
        if gid != BIGBAG_GROUP:
            unit["tons"] += qty_ton
        g = unit["_groups"].setdefault(
            gid, {"groupId": gid, "groupName": gname, "rows": 0, "qty": 0.0, "value": 0.0}
        )
        g["rows"] += 1
        g["qty"] += qty_ton
        g["value"] += val

    def finish(u: dict) -> dict:
        groups = sorted(u.pop("_groups").values(), key=lambda x: -x["qty"])
        for g in groups:
            g["qty"] = round(g["qty"], 2)
            g["value"] = round(g["value"], 2)
            if g["groupId"] == BIGBAG_GROUP:
                g["note"] = "ขายเป็นใบ ไม่นับเป็นตัน"
        u["tons"] = round(u["tons"], 2)
        u["value"] = round(u["value"], 2)
        u["groups"] = groups
        return u

    all_units = [finish(u) for u in units.values()]

    # จัดกลุ่มด้วย "ชื่อฐาน" = displayName ที่ตัด suffix " (สาขา …)" ออก
    fams: dict = {}
    for u in all_units:
        base = u["displayName"].split(" (สาขา ")[0]
        fams.setdefault(base, []).append(u)

    families, singles = [], []
    for base, us in sorted(fams.items()):
        us.sort(key=lambda x: (x["isHQ"] is not True, x["branch"] or ""))
        if len(us) > 1:
            families.append(
                {
                    "base": base,
                    "unitCount": len(us),
                    "tons": round(sum(x["tons"] for x in us), 2),
                    "value": round(sum(x["value"] for x in us), 2),
                    "units": us,
                }
            )
        else:
            singles.append(us[0])

    families.sort(key=lambda f: -f["value"])
    singles.sort(key=lambda u: -u["value"])

    return JSONResponse(
        {
            "since": LIVE_DATA_START.isoformat(),
            "unmatched": {
                "rows": unmatched_rows,
                "customers": sorted(unmatched_names.values(), key=lambda x: -x["rows"]),
                "hint": "cf_hq เป็น NULL = ใบกำกับหา products.customer_list ไม่เจอ (join ด้วย personid) "
                        "จึงไม่ได้ต่อท้าย '(สาขา …)' ทั้งที่อาจเป็นสาขาจริง — ต้องเป็น 0",
            },
            "familyCount": len(families),
            "families": families,
            "singleCount": len(singles),
            "singles": singles,
        }
    )
