# -*- coding: utf-8 -*-
"""v4: extract + normalize names (dedup-aware) + aggregate + emit JS constant.
Builds on extract_v3 layout handling; adds customer-name normalization inside the dedup key
(fixes 2565-05 double dump with/without บริษัท prefix).

NOTE: output keeps customers exactly as invoiced. The NPP4 rule (ทรายคัดพิเศษ 0.5-1.4 มม.
ใช้จริงโดย NPP4 แต่ออกใบกำกับในนาม NPP3 — ข้อมูลจากผู้ใช้ 2 ส.ค. 2569) is applied at
render time in sand_dashboard.html (block HCP_NPP4_IDX, matched by product/customer name),
so regenerating this constant does not lose the reattribution."""
import io, sys, re, json, zipfile, datetime, unicodedata, xml.etree.ElementTree as ET
from collections import defaultdict
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

ROOT = r'g:/My Drive/ssincom/ssincom_dashboard_summary'
BASE = ROOT + '/Sales Report/Sales Report 60-68'
SCRATCH = r'C:/Users/supaw/AppData/Local/Temp/claude/g--My-Drive-ssincom-ssincom-dashboard-summary-Sales-Report-Sales-Report-60-68/2ae407d2-3919-44b3-885b-ecceeb42624f/scratchpad'
M = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
R = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'
TH_M = {f'{i:02d}': i for i in range(1, 13)}
EN_M = {'JAN':1,'FEB':2,'MAR':3,'APR':4,'MAY':5,'JUN':6,'JUL':7,'AUG':8,'SEP':9,'OCT':10,'NOV':11,'DEC':12}
PROD_RE = re.compile(r'ทราย|sand|big bag', re.I)

# ---------- customer normalization ----------
def cust_norm(s):
    s = unicodedata.normalize('NFC', str(s))
    s = s.replace('\u0e4d\u0e32', 'ำ')          # นิคหิต+สระอา -> ำ
    s = re.sub(r'\s+', ' ', s).strip()
    s = re.sub(r'^(บริษัท|บจก\.?|หจก\.?|ห้างหุ้นส่วนจำกัด)\s*', '', s)
    s = re.sub(r'\s*(จำกัด\s*\(มหาชน\)|จำกัด|\(มหาชน\))\s*$', '', s)
    return s.strip()

# map normalized-Thai -> short EN (same identities as HIST_CUSTOMERS / make_hist_summary.py)
# NOTE: exact match on the normalized string; NPP5 ("แพลนท์ 5") is a DIFFERENT company from
# NPP5A ("แพลนท์ 5 เอ") - exact keys keep them apart.
CUST_MAP = {
    'เนชั่นแนล เพาเวอร์ แพลนท์ 3': 'NPP3',
    'เนชั่นแนล เพาเวอร์ แพลนท์ 5 เอ': 'NPP5A',
    'เนชั่นแนล เพาเวอร์ แพลนท์ 5': 'บริษัท เนชั่นแนล เพาเวอร์ แพลนท์ 5 จำกัด',
    'เนชั่นแนล เพาเวอร์ ซัพพลาย': 'NPS',
    'เนชั่นแนลเพาเวอร์ซัพพลาย': 'NPS',
    'ฟิวเจอร์ กรีนเนอร์จี': 'FG9',
    'ฟิวเจอร์กรีนเนอร์จี': 'FG9',
    'ซิก้า (ประเทศไทย)': 'SIKA',
    'มากอตโต': 'Magotteaux',
    'อายิโนะโมะโต๊ะ (ประเทศไทย)': 'Ajinomoto',
    'วัฒนชัยรับเบอร์เมท': 'WA_Rubbermate',
    'ดับบลิว.เอ. รับเบอร์เมท (ประเทศไทย)': 'WA_Rubbermate',
    'ซีพี. คอนโปร': 'CP_conpro',
    'ซีพี.คอนโปร': 'CP_conpro',
    'ออมทรัพย์ แลนด์ แอนด์ เฮ้าส์ พร็อพเพอร์ตี้': 'Aomsub',
    'ที.เจ.ซี. เคมี': 'TJC',
    'ใจข้าว คอร์ปอเรชั่น': 'Jaikao',
    'เค.เอ.รุ่งเรืองกิจ มิเนอรัล': 'KA_mineral',
    'น้ำมันพืชปทุม': 'Pathum_oil',
    'วี.เอ็น.เคมีคัลซัพพลาย': 'VN',
    'วี.เอ็น.เคมีคัลซัพพลา': 'VN',
    'ยูช่าสยาม': 'Usha_Siam',
    'ยูช่า สยาม': 'Usha_Siam',
    'บลูเลเบิ้ล': 'Blue_label',
}
# คีย์ map แบบตัดช่องว่างทั้งหมด — ข้อมูลจริงมีทั้ง "เพาเวอร์ แพลนท์" และ "เพาเวอร์แพลนท์"
# NPP5 กับ NPP5A ยังแยกกันได้เพราะ "5" vs "5เอ" ต่างกันที่ท้ายคีย์
CUST_MAP_NS = {k.replace(' ', ''): v for k, v in CUST_MAP.items()}

def cust_final(s):
    n = cust_norm(s)
    return CUST_MAP_NS.get(n.replace(' ', ''), n)

# ---------- product normalization (same rules as make_hist_summary.py) ----------
def product_key(name):
    t = str(name).lower()
    t = t.replace('มิลลิเมตร', 'มม.')
    t = re.sub(r'\bmm\.?', 'มม', t)   # ชื่ออังกฤษในใบกำกับยุค PDF: "0.125 - 0.60 mm"
    t = re.sub(r'\s+', '', t)
    return t.replace('มม.', 'มม')

PRODUCT_GROUPS = [
    ["ทรายคัดขนาดพิเศษขนาด 0-0.66 มม. ,Silica > 85%", "ทรายขนาด 0-0.66 มม.", "ทรายขนาด 0.0-0.66 มม."],
    ["ทรายคัดขนาดพิเศษขนาด 0.125 - 0.60 มิลลิเมตร", "Sand Low Silica 0.125 - 0.60 มม."],
    ["ทรายคัดขนาดพิเศษขนาด 0.30 – 0.71 มม. (Sand #2)", "ทรายคัดขนาดพิเศษขนาด 0.30 – 0.71 มม."],
    ["ทรายคัดขนาดพิเศษขนาด 0.5 - 0.7 มิลลิเมตร", "ทรายคัดขนาดพิเศษขนาด 0.50-0.70 มม.",
     "ทรายคัดขนาดพิเศษขนาด 0.50 - 0.7 มิลลิเมตร"],
    ["ทรายคัดขนาดพิเศษขนาด 0.5-1.0 มิลลิเมตร", "ทรายขนาด 0.5-1.0 มม."],
    ["ทรายขนาด 0.5-1.4 มม.", "ทรายคัดขนาดพิเศษขนาด 0.50 - 1.40 มิลลิเมตร"],
    ["ทรายขนาด 0.7-1.4 มม.", "ทรายคัดขนาดพิเศษขนาด 0.70 - 1.40 มม.",
     "ทรายคัดขนาดพิเศษขนาด 0.7 - 1.4 มิลลิเมตร"],
    ["ทรายคัดขนาดพิเศษขนาด 1.0-2.0 มม.", "ทรายคัดขนาดพิเศษขนาด 1.0-2.0 มิลลิเมตร (RT12)"],
    ["ทรายคัดขนาดพิเศษขนาด 1.70 – 3.35 มม. (Sand #5)", "ทรายขนาด 1.7-3.35",
     "ทรายคัดขนาดพิเศษขนาด 1.70 – 3.35 มม."],
]
ALIAS_KEY = {}
for grp in PRODUCT_GROUPS:
    for nm in grp:
        ALIAS_KEY[product_key(nm)] = product_key(grp[0])

# ---------- xlsx helpers (same as v3) ----------
def sheets_of(p):
    z = zipfile.ZipFile(p)
    wb = ET.fromstring(z.read('xl/workbook.xml'))
    rels = {r.get('Id'): r.get('Target') for r in ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))}
    try:
        shared = [''.join(t.text or '' for t in si.iter(M + 't'))
                  for si in ET.fromstring(z.read('xl/sharedStrings.xml'))]
    except KeyError:
        shared = []
    out = []
    for s in wb.find(M + 'sheets'):
        t = rels[s.get(R + 'id')]
        out.append((s.get('name'), t if t.startswith('xl/') else 'xl/' + t))
    return z, out, shared

def load(z, path, shared):
    rows = []
    for row in ET.fromstring(z.read(path)).find(M + 'sheetData'):
        cells = {}
        for c in row:
            ref = re.match(r'([A-Z]+)', c.get('r') or 'A').group(1)
            ci = 0
            for ch in ref:
                ci = ci * 26 + (ord(ch) - 64)
            ci -= 1
            v = c.find(M + 'v')
            t = c.get('t')
            if t == 'inlineStr':
                cells[ci] = ''.join(x.text or '' for x in c.find(M + 'is').iter(M + 't'))
            elif v is None:
                continue
            else:
                cells[ci] = shared[int(v.text)] if t == 's' else v.text
        if cells:
            rows.append([str(cells.get(i, '')).strip() for i in range(max(cells) + 1)])
    return rows

def qp(s):
    s = str(s).strip().replace(',', '')
    if not s or not re.match(r'^\d[\d.]*$', s):
        return None
    p = s.split('.')
    return float(s) if len(p) == 1 else float(''.join(p[:-1]) + '.' + p[-1])

def fc(h, *names):
    low = [x.strip().lower() for x in h]
    for n in names:
        n = n.lower()
        if n in low:
            return low.index(n)
    return None

def serial_month(v):
    try:
        f = float(v)
        if 40000 < f < 50000:
            d = datetime.date(1899, 12, 30) + datetime.timedelta(days=int(f))
            return d.year + 543, d.month
    except (ValueError, TypeError):
        pass
    m = re.match(r'^(\d{1,2})/(\d{1,2})/(\d{4})$', str(v).strip())
    if m:
        return int(m.group(3)), int(m.group(2))
    return None, None

# ---------- pass 1: SYSITEMID map ----------
sys_name = {}
raw = []
for yy in range(60, 69):
    year = 2500 + yy
    z, shs, sh = sheets_of(f'{BASE}/{yy}/Sell {year}.xlsx')
    for name, path in shs:
        nm = name.strip()
        mn = TH_M.get(nm[:2]) if '_' in nm else EN_M.get(nm.upper())
        if mn is None:
            continue
        rows = load(z, path, sh)
        raw.append((year, mn, rows))
        for i, r in enumerate(rows[:5]):
            if 'SYSITEMID' in r and ('ITEMNAME' in r or 'CF_ITEMNAME' in r):
                cs, cn = fc(r, 'SYSITEMID'), fc(r, 'CF_ITEMNAME', 'ITEMNAME')
                for dr in rows[i + 1:]:
                    if len(dr) > max(cs, cn) and dr[cs].isdigit() and PROD_RE.search(dr[cn] or ''):
                        sys_name[dr[cs]] = dr[cn]
                break

# ---------- pass 2: extract ----------
recs, issues, seen = [], [], set()
for year, mn, rows in raw:
    if not rows:
        continue
    hidx = style = None
    for i, r in enumerate(rows[:6]):
        rl = [c.lower() for c in r]
        if 'customer' in rl:
            hidx, style = i, 'pdf'; break
        if any(c in ('BASEQUANTITY', 'CF_TDBASEQUANTITY') for c in r):
            hidx, style = i, 'erp'; break
        if any('รายการสินค้า' in c for c in r) and any('จำนวนตัน' in c.replace(' ', '') for c in r):
            hidx, style = i, 'inv68'; break
        if any('ชื่อผู้ขาย' in c for c in r) and any('จำนวนตัน' in c for c in r):
            hidx, style = i, 'invnp'; break
    if hidx is None:
        if {len(r) for r in rows[:12]} == {3} and all(qp(r[2]) is not None for r in rows[:12]):
            for r in rows:
                if len(r) == 3 and r[0] and PROD_RE.search(r[1] or '') and qp(r[2]) is not None:
                    recs.append((year, mn, cust_final(r[0]), r[1], qp(r[2])))
            continue
        issues.append((year, mn, 'no header'))
        continue
    header, data = rows[hidx], rows[hidx + 1:]

    if style == 'pdf':
        cc, cp, cq = fc(header, 'customer'), fc(header, 'product_name'), fc(header, 'จ่าย')
        cu, ct, cd = fc(header, 'unit'), fc(header, 'row_type'), fc(header, 'doc_no')
        if cq is None:
            issues.append((year, mn, 'no qty col — unrecoverable'))
            continue
        for r in data:
            if ct is not None and ct < len(r) and r[ct] not in ('data', ''):
                continue
            cust = r[cc] if cc < len(r) else ''
            prod = r[cp] if cp < len(r) else ''
            unit = r[cu] if cu is not None and cu < len(r) else ''
            q = qp(r[cq]) if cq < len(r) else None
            if not cust or not prod or q is None:
                continue
            t = q / 1000.0 if 'กิโล' in unit else q
            cn2 = cust_final(cust)
            key = (year, mn, r[cd] if cd is not None and cd < len(r) else '', product_key(prod), round(t, 3), cn2)
            if key in seen:
                continue
            seen.add(key)
            recs.append((year, mn, cn2, prod, t))

    elif style == 'erp':
        cq = fc(header, 'CF_TDBASEQUANTITY', 'BASEQUANTITY')
        cp = fc(header, 'CF_ITEMNAME', 'ITEMNAME')
        cc = fc(header, 'CF_PERSON_FNAME')
        cs = fc(header, 'SYSITEMID')
        cun = fc(header, 'CF_UNITNAME')
        ctr = fc(header, 'TRANNO', 'CF_TRANNO')
        cdt = fc(header, 'TRANDATE', 'CF_TRANDATE')
        hw = len(header)
        if {len(r) for r in data[:10]} == {3}:
            for r in data:
                if len(r) == 3 and r[0] and PROD_RE.search(r[1] or '') and qp(r[2]) is not None:
                    recs.append((year, mn, cust_final(r[0]), r[1], qp(r[2])))
            continue
        if cq is None or cc is None or (cp is None and cs is None):
            issues.append((year, mn, 'erp unusable'))
            continue
        ndrop = 0
        for r in data:
            if not any(r):
                continue
            def cell(i, sh=0):
                if i is None:
                    return ''
                j = i - sh if i >= 2 else i
                return r[j] if 0 <= j < len(r) else ''
            got = None
            for sh in ([0, 1] if len(r) == hw - 1 else [0]):
                prod = cell(cp, sh)
                if not prod and cs is not None:
                    prod = sys_name.get(cell(cs, sh), '')
                unit = cell(cun, sh)
                q = qp(cell(cq, sh))
                cust = cell(cc, sh)
                if q is not None and 'กิโล' in unit:
                    q = q / 1000.0
                if cust and prod and PROD_RE.search(prod) and q is not None and 0 < q < 2000:
                    got = (cust, prod, q, cell(ctr, sh), cell(cdt, sh))
                    break
            if not got:
                ndrop += 1
                continue
            cust, prod, q, tran, dt = got
            dy, dm = serial_month(dt)
            uy, um = (dy, dm) if dm and dy == year else (year, mn)
            cn2 = cust_final(cust)
            key = (uy, um, tran, product_key(prod), round(q, 3), cn2)
            if key in seen:
                continue
            seen.add(key)
            recs.append((uy, um, cn2, prod, q))
        if ndrop > 3:
            issues.append((year, mn, f'erp dropped {ndrop}'))

    elif style == 'inv68':
        def kc(*ks):
            for i, h in enumerate(header):
                hh = h.replace(' ', '')
                if any(k in hh for k in ks):
                    return i
            return None
        cc, cp, cq, cd = kc('ชื่อผู้ขาย'), kc('รายการสินค้า'), kc('จำนวนตัน'), kc('เลขที่ใบกำกับ', 'ใบกำกับ')
        for r in data:
            cust = r[cc] if cc < len(r) else ''
            prod = r[cp] if cp < len(r) else ''
            q = qp(r[cq]) if cq < len(r) else None
            if not cust or not prod or q is None or not PROD_RE.search(prod) or 'รวม' in cust:
                continue
            cn2 = cust_final(cust)
            key = (year, mn, r[cd] if cd is not None and cd < len(r) else '', product_key(prod), round(q, 3), cn2)
            if key in seen:
                continue
            seen.add(key)
            recs.append((year, mn, cn2, prod, q))
    else:
        issues.append((year, mn, 'invoice-level no product — unpairable'))

# ---------- canonical product names, preferring HV_PRODUCTS spellings ----------
html = open(ROOT + '/frontend/sand_dashboard.html', encoding='utf-8').read()
HVP = json.loads(re.search(r'const HV_PRODUCTS = (\[.*?\]);', html, re.S).group(1))
hv_by_key = {}
for nm in HVP:
    k = ALIAS_KEY.get(product_key(nm), product_key(nm))
    hv_by_key.setdefault(k, nm)

tons_by_name = defaultdict(float)
for y, m, c, p, t in recs:
    tons_by_name[p] += t
canon = {}
for p in tons_by_name:
    k = ALIAS_KEY.get(product_key(p), product_key(p))
    if k in hv_by_key:
        canon[p] = hv_by_key[k]
    else:
        best = max((n for n in tons_by_name if (ALIAS_KEY.get(product_key(n), product_key(n))) == k),
                   key=lambda n: tons_by_name[n])
        canon[p] = best

# ---------- aggregate (cust, prod, year) ----------
agg = defaultdict(float)
for y, m, c, p, t in recs:
    agg[(c, canon[p], y)] += t

custs = sorted({k[0] for k in agg}, key=lambda c: -sum(v for kk, v in agg.items() if kk[0] == c))
prods = sorted({k[1] for k in agg}, key=lambda p: -sum(v for kk, v in agg.items() if kk[1] == p))
ci = {c: i for i, c in enumerate(custs)}
pi = {p: i for i, p in enumerate(prods)}
triples = sorted([[pi[p], ci[c], y, round(t, 2)] for (c, p, y), t in agg.items() if t >= 0.005])

# ---------- coverage report ----------
HV = json.loads(re.search(r'const HISTORICAL_VOLUME = (\[.*?\]);', html, re.S).group(1))
off = defaultdict(float)
got = defaultdict(float)
for y, m, p, t in HV:
    if y <= 2568:
        off[y] += t
for y, m, c, p, t in recs:
    got[y] += t
print(f"{'year':<6}{'official':>11}{'paired':>11}{'cov%':>7}")
for y in range(2560, 2569):
    print(f"{y:<6}{off[y]:>11,.0f}{got[y]:>11,.0f}{got[y]/off[y]*100:>6.1f}%")
print(f"{'TOT':<6}{sum(off.values()):>11,.0f}{sum(got.values()):>11,.0f}{sum(got.values())/sum(off.values())*100:>6.1f}%")
print("\nissues:", issues)
print(f"\ncustomers: {len(custs)}, products: {len(prods)}, triples: {len(triples)}")
print("top customers by tons:")
for c in custs[:12]:
    print(f"  {sum(v for kk, v in agg.items() if kk[0] == c):>11,.1f}  {c}")
print("top products:")
for p in prods[:8]:
    print(f"  {sum(v for kk, v in agg.items() if kk[1] == p):>11,.1f}  {p[:60]}")

js = ('const HCP_CUSTOMERS = ' + json.dumps(custs, ensure_ascii=False, separators=(',', ':')) + ';\n'
      + 'const HCP_PRODUCTS = ' + json.dumps(prods, ensure_ascii=False, separators=(',', ':')) + ';\n'
      + 'const HIST_CUST_PROD = ' + json.dumps(triples, separators=(',', ':')) + ';\n')
open(f'{SCRATCH}/hist_cust_prod.js', 'w', encoding='utf-8').write(js)
print(f"\nconstant bytes: {len(js):,}")
