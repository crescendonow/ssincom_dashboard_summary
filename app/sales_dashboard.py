# app/sales_dashboard.py
# endpoint /api/dashboard/sales/rows — คืน "line-item" สดจาก bill DB (ss_invoices)
# ให้ตรง shape ที่ frontend/sand_dashboard.html ใช้ (แทนที่ EMBEDDED_DATA จาก xlsx)
# logic คำนวณ (VAT 7%, qty→ตัน, join quirk idx::text, value=coalesce(amount,qty*price))
# ยืมจาก ssincom_bill/app/saletax_report.py — read-only + auth-gated
from collections import Counter

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
