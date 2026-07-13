# app/models.py
# trim จาก ssincom_bill/app/models.py — เหลือเฉพาะที่ endpoint /api/dashboard/sales/rows ใช้
# (Invoice หัวใบกำกับ + InvoiceItem รายการ + Driver คนขับ) read-only ทั้งหมด
from sqlalchemy import Column, Integer, String, Float, Date, ForeignKey

from .database import Base


# ------------------ Invoices (schema: ss_invoices) ------------------

class Invoice(Base):
    __tablename__ = "invoices"
    __table_args__ = {"schema": "ss_invoices"}

    idx = Column(Integer, primary_key=True)          # PK (int)
    invoice_number = Column(String, index=True)      # เลขที่ใบกำกับ (varchar)
    invoice_date = Column(Date, index=True)          # วันที่ใบกำกับ (date, ค.ศ.)

    fname = Column(String)                            # ชื่อลูกค้า (snapshot)
    personid = Column(String, index=True)            # รหัสลูกค้า (snapshot)

    driver_id = Column(String(10), ForeignKey("products.drivers.driver_id"), index=True)


class InvoiceItem(Base):
    __tablename__ = "invoice_items"
    __table_args__ = {"schema": "ss_invoices"}

    idx = Column(Integer, primary_key=True)

    # ⚠ quirk: คอลัมน์นี้บางแถวเก็บ "เลขที่ใบกำกับ" บางแถวเก็บ inv.idx (varchar)
    # ต้อง join เผื่อสองแบบเสมอ (ดู sales_dashboard.py)
    invoice_number = Column(
        String,
        ForeignKey("ss_invoices.invoices.invoice_number"),
        index=True,
    )

    cf_itemid = Column(String(6))                    # รหัสสินค้า
    cf_itemname = Column(String(1000))               # ชื่อสินค้า
    cf_itempricelevel_price = Column(Float)          # ราคาต่อหน่วย
    quantity = Column(Float)                         # จำนวน (kg — >=1000 หาร 1000 = ตัน)
    amount = Column(Float)                           # จำนวนเงิน (null → คำนวณ qty*price)


# ------------------ Customers (schema: products) ------------------

class CustomerList(Base):
    __tablename__ = "customer_list"
    __table_args__ = {"schema": "products"}

    idx = Column(Integer, primary_key=True)
    personid = Column(String, index=True)     # รหัสลูกค้า — join กับ invoices.personid
    fname = Column(String)                     # ชื่อลูกค้า (master, สะอาดกว่า invoices.fname snapshot)
    cf_hq = Column(Integer)                     # 1 = สำนักงานใหญ่
    cf_branch = Column(String)                  # รหัสสาขา (ถ้าไม่ใช่สำนักงานใหญ่)


# ------------------ Drivers (schema: products) ------------------

class Driver(Base):
    __tablename__ = "drivers"
    __table_args__ = {"schema": "products"}

    driver_id = Column(String(10), primary_key=True)
    prefix = Column(String(16))
    first_name = Column(String(64))
    last_name = Column(String(64))
