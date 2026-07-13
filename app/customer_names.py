"""Customer/branch name cleanup (invoices.fname / products.customer_list.fname -> display name).

invoices.fname เป็น snapshot ดิบ ณ เวลาออกใบกำกับ ไม่ได้ผ่านการทำความสะอาด ทำให้ลูกค้ารายเดียวกัน
(เช่น NPP5A ที่มีทั้งสำนักงานใหญ่และสาขา) ปรากฏเป็นชื่อคนละแบบในแท็บ "ตามลูกค้า" ของ dashboard.

อ้างอิงกฎจาก ssincom_landingpage/.docs/3_sales_dashboard_db.md (ยืนยันโดยผู้ใช้ 10-12 ก.ค. 2569):
แยกสาขาด้วย personid -> products.customer_list.cf_hq/cf_branch เท่านั้น
ห้ามใช้ invoices.cf_branch (กรอกไม่ครบ) หรือเลขผู้เสียภาษี (สาขาใช้เลขเดียวกับสำนักงานใหญ่)
"""
from __future__ import annotations

import re

# ชื่อเดิม (substring หลังตัด prefix) -> ชื่อ canonical ปัจจุบัน
# ใช้เมื่อลูกค้าเปลี่ยนชื่อ/โครงสร้างบริษัท แต่ต้องการนับยอดขาย/ตันต่อเนื่องกันเป็นรายเดียว
CUSTOMER_ALIASES: dict[str, str] = {
    "วัฒนชัยรับเบอร์เมท": "ดับบลิว.เอ. รับเบอร์เมท (ประเทศไทย) จำกัด",
}

_PREFIX_RE = re.compile(r"^(บริษัท|บจก\.?|หจก\.?)\s*")
_SARA_AM_RE = re.compile("ํา")  # ◌ํ + า (สระอำ เขียนแยก 2 ตัว) -> ำ


def clean_customer_name(raw_name: str | None, cf_hq: int | None = None, cf_branch: str | None = None) -> str:
    """คืนชื่อลูกค้าที่ทำความสะอาดแล้ว พร้อมต่อท้ายสาขาถ้ามี (ไม่ใช่สำนักงานใหญ่)."""
    if not raw_name or not raw_name.strip():
        return "-"

    name = _SARA_AM_RE.sub("ำ", raw_name)
    name = _PREFIX_RE.sub("", name).strip()
    name = re.sub(r"\s+", " ", name)

    for old, new in CUSTOMER_ALIASES.items():
        if old in name:
            name = new
            break

    if cf_hq is not None and cf_hq != 1 and cf_branch:
        name = f"{name} (สาขา {cf_branch})"

    return name
