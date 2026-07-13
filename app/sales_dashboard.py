# app/sales_dashboard.py
# endpoint /api/dashboard/sales/rows — คืน "line-item" สดจาก bill DB (ss_invoices)
# ให้ตรง shape ที่ frontend/sand_dashboard.html ใช้ (แทนที่ EMBEDDED_DATA จาก xlsx)
# logic คำนวณ (VAT 7%, qty→ตัน, join quirk idx::text, value=coalesce(amount,qty*price))
# ยืมจาก ssincom_bill/app/saletax_report.py — read-only + auth-gated
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import String, cast, or_
from sqlalchemy.orm import Session

from . import models
from .customer_names import clean_customer_name
from .database import SessionLocal
from .product_groups import group_of

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

    rows = []
    for (
        _idx,
        _inv_no,
        inv_date,
        fname,
        _item_idx,
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
    ) in q.all():
        qraw = float(quantity or 0.0)
        price = float(price or 0.0)
        value = float(amount) if amount is not None else qraw * price
        vat = value * VAT_RATE
        total = value + vat
        qty_ton = qraw / 1000.0 if qraw >= 1000 else qraw

        group_id, group_name = group_of(cf_itemid)

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

    return JSONResponse(rows)
