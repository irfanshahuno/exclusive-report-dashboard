"""EMC Marketing Report - Streamlit page (separate from the Revenue Scorecard).

Upload the HIS Registration List (and optionally the ProcedureDetails report for revenue).
Shows which companies and camps the patients come from: today, month so far, growing / dropping / lost companies.
Marketing team sees patient counts only; management also sees revenue per company.
"""
import difflib
import html as _h
import io
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import streamlit as st

for _p in (Path(__file__).resolve().parent, Path(__file__).resolve().parents[1]):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

st.set_page_config(page_title="EMC Marketing Report", page_icon="📣", layout="wide")
UAE = timezone(timedelta(hours=4))
E = lambda s: _h.escape(str(s))                                        # noqa: E731


def fmt(n):
    try:
        return f"{float(n):,.0f}"
    except Exception:  # noqa: BLE001
        return str(n)


def _secret(name, default=""):
    try:
        if name in st.secrets:
            return str(st.secrets[name])
    except Exception:  # noqa: BLE001
        pass
    return os.environ.get(name, default)


# ---------------------------------------------------------------- style
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Barlow+Semi+Condensed:wght@500;600;700&family=IBM+Plex+Sans:wght@400;500;600&display=swap');
:root{--ink:#18211C; --muted:#5D6A62; --line:#E1E6E0; --soft:#F2F5F1; --card:#fff; --brand:#1F4E8C; --brand-soft:#E8EEF8;
      --ok:#1E7A45; --ok-bg:#E2F3E8; --bad:#B3261E; --bad-bg:#FBE4E1; --warn:#9A6200; --warn-bg:#FBF0D9;}
html, body, [class*="css"], .stMarkdown, p, li, label, input, button, textarea {font-family:'IBM Plex Sans', system-ui, sans-serif;}
.block-container{padding-top:3.8rem; max-width:1280px;}
h1,h2,h3{font-family:'Barlow Semi Condensed','Arial Narrow',sans-serif !important;}
.hero{background:linear-gradient(135deg,#16335C 0%,#1F4E8C 70%,#2C66B0 100%); color:#fff; border-radius:16px; padding:24px 28px;
      display:flex; justify-content:space-between; align-items:flex-end; flex-wrap:wrap; gap:14px; margin-bottom:16px;}
.hero h1{color:#fff !important; font-size:36px; margin:0; line-height:1.05; padding:0;}
.hero p{color:#D6E2F3; margin:6px 0 0; font-size:14px;}
.chip{background:rgba(255,255,255,.14); border:1px solid rgba(255,255,255,.25); color:#fff; padding:5px 12px; border-radius:999px; font-size:12.5px;}
.kpis{display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr)); gap:14px; margin:4px 0 16px;}
.kpi{background:var(--card); border:1px solid var(--line); border-radius:14px; padding:15px 18px;}
.kpi.m{border:1.5px solid var(--brand); background:#FAFCFF;}
.kpi .lbl{font-size:11px; text-transform:uppercase; letter-spacing:.09em; color:var(--muted); font-weight:600;}
.kpi .val{font-family:'Barlow Semi Condensed',sans-serif; font-size:34px; font-weight:700; color:var(--ink); line-height:1.1; margin-top:4px;}
.kpi .val small{font-size:16px; color:var(--muted); font-weight:500;}
.kpi .sub{font-size:12.5px; color:var(--muted); margin-top:3px;}
.warnline{color:var(--warn); font-weight:600; font-size:12.5px; margin-top:6px;}
.sec{font-family:'Barlow Semi Condensed',sans-serif; font-size:21px; font-weight:700; color:var(--ink); margin:18px 0 8px;}
.note{font-size:12.5px; color:var(--muted); margin:4px 0 10px;}
.tbl{width:100%; border-collapse:separate; border-spacing:0; background:var(--card); border:1px solid var(--line); border-radius:12px; overflow:hidden; font-size:13.5px;}
.tbl th{background:var(--soft); color:var(--muted); font-size:11px; text-transform:uppercase; letter-spacing:.06em; text-align:right; padding:9px 12px; border-bottom:1px solid var(--line);}
.tbl td{padding:8px 12px; border-bottom:1px solid var(--line); text-align:right; font-variant-numeric:tabular-nums;}
.tbl th:first-child,.tbl td:first-child{text-align:left;} .tbl tr:last-child td{border-bottom:0;}
.tbl td.nm{font-weight:600; color:var(--ink); text-align:left;} .tbl th.l{text-align:left;}
.dwrap{overflow-x:auto; border-radius:12px;} .dd td,.dd th{padding:7px 8px; white-space:nowrap;} .dd td.nm{position:sticky; left:0; background:#fff; z-index:1; min-width:220px; white-space:normal;}
.dd th:first-child{position:sticky; left:0; z-index:2;} .dd tr.tot td{background:var(--brand-soft); font-weight:700;} .dd td.z{color:#C9D2CB;} .dd td.hi{background:#E8EEF8; font-weight:700;} .tbl .rank{color:var(--muted); width:28px;}
.up{color:var(--ok); font-weight:700;} .down{color:var(--bad); font-weight:700;} .flat{color:var(--muted);}
.barc{display:inline-block; height:8px; background:var(--brand); border-radius:4px; vertical-align:middle; margin-right:6px;}
.empty{background:var(--soft); border:1px dashed #C9D2CB; border-radius:12px; padding:14px 16px; color:var(--muted); font-size:13.5px;}
.tag{display:inline-block; padding:2px 8px; border-radius:999px; font-size:11px; font-weight:700;}
.t-new{background:#E8EEF8; color:#1F4E8C;} .t-lost{background:var(--bad-bg); color:var(--bad);}
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------- storage (own folder, separate from the revenue scorecard)
PREFIX = (_secret("S3_BASE_PREFIX").strip("/") + "/" if _secret("S3_BASE_PREFIX") else "") + "emc_marketing/"
LOCAL = Path(__file__).resolve().parent / ".emc_marketing"


def _s3():
    bucket = _secret("S3_BUCKET_NAME")
    if not bucket:
        return None, None
    try:
        import boto3
        kw = {"region_name": _secret("AWS_REGION") or None}
        if _secret("AWS_ACCESS_KEY_ID"):
            kw.update(aws_access_key_id=_secret("AWS_ACCESS_KEY_ID"), aws_secret_access_key=_secret("AWS_SECRET_ACCESS_KEY"))
        return boto3.client("s3", **kw), bucket
    except Exception:  # noqa: BLE001
        return None, None


def put(key, data: bytes):
    s3, b = _s3()
    if s3:
        try:
            s3.put_object(Bucket=b, Key=PREFIX + key, Body=data)
            return "cloud"
        except Exception:  # noqa: BLE001
            pass
    f = LOCAL / key
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(data)
    return "local"


def get(key):
    s3, b = _s3()
    if s3:
        try:
            return s3.get_object(Bucket=b, Key=PREFIX + key)["Body"].read()
        except Exception:  # noqa: BLE001
            pass
    f = LOCAL / key
    return f.read_bytes() if f.exists() else None


def get_json(key, default):
    raw = get(key)
    try:
        return json.loads(raw) if raw else default
    except Exception:  # noqa: BLE001
        return default


# ---------------------------------------------------------------- reading the reports
def _clean(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    return re.sub(r"\s+", " ", str(v).replace("\t", " ")).strip()


def read_registration(data, name=""):
    engine = "xlrd" if name.lower().endswith(".xls") else None
    raw = pd.read_excel(io.BytesIO(data), header=None, engine=engine, dtype=object)
    hdr = None
    for i in range(min(len(raw), 30)):
        vals = [_clean(v).upper() for v in raw.iloc[i].tolist()]
        if "EMR NO" in vals and "EMPLOYER NAME" in vals:
            hdr = i
            break
    if hdr is None:
        raise ValueError('This is not the Registration List: no "EMR No" and "Employer Name" columns.')
    col = {}
    for j, v in enumerate(raw.iloc[hdr].tolist()):
        v = _clean(v).upper()
        if v and v not in col:
            col[v] = j
    g = lambda r, n: _clean(r[col[n]]) if n in col else ""          # noqa: E731
    rows = []
    for _, r in raw.iloc[hdr + 1:].iterrows():
        r = r.tolist()
        emr = g(r, "EMR NO")
        if not emr:
            continue
        dt = g(r, "REG:DATE")[:10]
        try:
            datetime.strptime(dt, "%d-%m-%Y")
        except ValueError:
            continue
        rows.append({"emr": emr, "date": dt, "employer": g(r, "EMPLOYER NAME"),
                     "camp": g(r, "ADDRESS 1") or g(r, "ADDRESS 2"), "nat": g(r, "NATIONALITY").title() or "Unknown",
                     "new": g(r, "PATIENT TYPE").upper().startswith("NEW"), "fu": "FOLLOW" in g(r, "VISIT TYPE").upper(),
                     "user": g(r, "REG:USER").upper() or "–"})
    if not rows:
        raise ValueError("No visits found in the Registration List.")
    return rows


def revenue_map(data, name):
    """(EMR, date) -> insurance share after the scorecard's price corrections."""
    import emc_logic as L
    visits, _, _ = L.correct(L.read_report(data, name))
    out = {}
    for v in visits:
        k = (str(v.get("emr", "")).strip(), v["date"])
        out[k] = out.get(k, 0.0) + v["runs"]
    return out


# ---------------------------------------------------------------- name clean-up (companies spelled many ways)
LEGAL = r"\b(L ?L ?C|S ?P ?C|W ?L ?L|P ?J ?S ?C|PJSC|LTD|LIMITED|EST|ESTABLISHMENT|CO|COMPANY|SOLE|PROPRIETORSHIP|PROPRITERSHIP|BRANCH|BR|LSB|AUH|ABU DHABI|DUBAI)\b"


def company_key(s):
    s = _clean(s).upper()
    if not s or s in ("N/A", "NA", "-", "NIL", "NONE", "0"):
        return ""
    s = re.sub(r"OWNED BY.*", "", s)
    s = s.replace("&", " AND ")
    s = re.sub(r"\bCONT\b", "CONTRACTING", s)
    s = re.sub(r"\bGEN\b", "GENERAL", s)
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    s = re.sub(LEGAL, " ", s)
    s = re.sub(r"\s+", "", s)
    return s


CAMP_STOP = r"\b(AL|EL|CAMP|CHAMAP|VILLAGE|LABOUR|LABOR|ACCOMMODATION|AREA)\b"


CAMPS = [(r"NA+S+[AEI]+R|NASSR", "Al Nasser Camp"), (r"RA+H+A?|RAAH", "Al Raha"), (r"LAB+OT+[AE]?L", "Labotel"),
         (r"JA+B+[AE]R", "Al Jaber"), (r"MOU?N?A?T[AI]*N|MOUTIN|MOUNTAIN", "Mountain Gate"), (r"SAWA+E*D", "Al Sawaeed"),
         (r"ESH?OUSE", "Eshouse"), (r"RAZEEM", "Razeem"), (r"RAYAN", "Al Rayan"), (r"GEEMI", "Al Geemi")]


def camp_canon(s):
    k = camp_key(s)
    for pat, name in CAMPS:
        if re.search(pat, k):
            return name
    return ""


def camp_key(s):
    s = re.sub(r"[^A-Z0-9 ]", " ", _clean(s).upper())
    s = re.sub(CAMP_STOP, " ", s)
    return re.sub(r"\s+", "", s)


def build_names(raws, keyfn, aliases, threshold=0.84):
    """raw text -> one display name. Similar spellings are merged; the most common spelling is shown.
    'aliases' (raw or display -> chosen name) always wins."""
    count = {}
    for r, n in raws.items():
        count[r] = count.get(r, 0) + n
    clusters = []                                   # [key, {raw: n}]
    for r in sorted(count, key=lambda x: -count[x]):
        k = keyfn(r)
        if keyfn is camp_key and camp_canon(r):
            k = "CANON:" + camp_canon(r)
            hit = next((c for c in clusters if c[0] == k), None)
            if hit:
                hit[1][r] = count[r]
            else:
                clusters.append([k, {r: count[r]}])
            continue
        if not k:
            continue
        best = None
        for c in clusters:
            ck = c[0]
            if ck.startswith("CANON:"):
                continue
            ratio = difflib.SequenceMatcher(None, k, ck).ratio()
            if ratio >= threshold or (min(len(k), len(ck)) >= 8 and (k.startswith(ck) or ck.startswith(k))):
                best = c
                break
        if best:
            best[1][r] = count[r]
        else:
            clusters.append([k, {r: count[r]}])
    out = {}
    up = {k.upper(): v for k, v in aliases.items()}
    for _, members in clusters:
        disp = max(members, key=lambda x: members[x])
        if keyfn is camp_key and camp_canon(disp):
            disp = camp_canon(disp)
        else:
            disp = re.sub(r"OWNED BY.*", "", disp, flags=re.I)
            disp = re.sub(r"[-,]?\s*\bSOLE\b.*$", " ", disp, flags=re.I)
            disp = re.sub(r"\bL\.?\s?L\.?\s?C\.?\b|\bS\s?P\s?C\b|\bW\.?\s?L\.?\s?L\b|\bP\.?J\.?S\.?C\.?", " ", disp, flags=re.I)
            disp = re.sub(r"\s*-\s*(DUBAI|ABU DHABI|AUH|LSB)?\s*(BRANCH)?\s*$", "", disp, flags=re.I)
            disp = re.sub(r"\s+", " ", disp).strip(" -,.&").title()
            disp = re.sub(r"\bAnd\b", "and", disp)
        for r in members:
            out[r] = up.get(r.upper(), up.get(disp.upper(), disp))
    return out


# ---------------------------------------------------------------- daily ledger (per day, per company: counts and revenue)
def day_totals(rows, rev):
    days = {}
    for r in rows:
        d = days.setdefault(r["date"], {"co": {}, "camp": {}, "nat": {}, "users": {}, "n": 0, "new": 0, "fu": 0,
                                        "blank": 0, "rev": 0.0, "has_rev": rev is not None})
        runs = (rev or {}).pop((r["emr"], r["date"]), 0.0)      # each bill counted once, even if registered twice
        d["n"] += 1; d["new"] += r["new"]; d["fu"] += r["fu"]; d["rev"] += runs
        emp = r["employer"] if company_key(r["employer"]) else ""
        if not emp:
            d["blank"] += 1
        c = d["co"].setdefault(emp or "(not filled)", [0, 0, 0, 0.0])
        c[0] += 1; c[1] += r["new"]; c[2] += r["fu"]; c[3] += runs
        cp = r["camp"] if camp_key(r["camp"]) else "(not filled)"
        d["camp"][cp] = d["camp"].get(cp, 0) + 1
        d["nat"][r["nat"]] = d["nat"].get(r["nat"], 0) + 1
        u = d["users"].setdefault(r["user"], [0, 0])
        u[0] += bool(emp); u[1] += 1
    for (emr, dt), runs in (rev or {}).items():      # bills with no matching registration: keep the day total right
        if dt in days and runs:
            days[dt]["rev"] += runs
            days[dt]["co"].setdefault("(not filled)", [0, 0, 0, 0.0])[3] += runs
    return days


def update_ledger(days):
    by_month = {}
    for dt, val in days.items():
        k = datetime.strptime(dt, "%d-%m-%Y")
        by_month.setdefault(f"{k:%Y-%m}", {})[f"{k:%Y-%m-%d}"] = val
    for ym, vals in by_month.items():
        led = get_json(f"ledger/{ym}.json", {})
        for k, v in vals.items():
            if not v["has_rev"] and k in led and led[k].get("has_rev") and led[k]["n"] == v["n"]:
                # keep revenue already stored for the same day when this upload has no ProcedureDetails
                for name, c in v["co"].items():
                    c[3] = led[k]["co"].get(name, [0, 0, 0, 0.0])[3]
                v["rev"], v["has_rev"] = led[k]["rev"], True
            led[k] = v
        put(f"ledger/{ym}.json", json.dumps(led).encode())


def sum_days(led, keys):
    tot = {"co": {}, "camp": {}, "nat": {}, "users": {}, "n": 0, "new": 0, "fu": 0, "blank": 0, "rev": 0.0, "days": 0, "rev_days": 0}
    for k in keys:
        d = led.get(k)
        if not d:
            continue
        tot["days"] += 1; tot["rev_days"] += bool(d.get("has_rev"))
        for f in ("n", "new", "fu", "blank", "rev"):
            tot[f] += d[f]
        for name, c in d["co"].items():
            t = tot["co"].setdefault(name, [0, 0, 0, 0.0])
            for i in range(4):
                t[i] += c[i]
        for f in ("camp", "nat"):
            for name, n in d[f].items():
                tot[f][name] = tot[f].get(name, 0) + n
        for u, (a, b) in d["users"].items():
            t = tot["users"].setdefault(u, [0, 0]); t[0] += a; t[1] += b
    return tot


# ---------------------------------------------------------------- upload
if "mk" not in st.session_state:
    st.session_state["mk"] = (get("latest/registration.xlsx"), get_json("latest/meta.json", {}), get("latest/procedure.xlsx"))
reg_bytes, meta, proc_bytes = st.session_state["mk"]

with st.expander("Upload new reports", expanded=reg_bytes is None):
    with st.form("mk_up", clear_on_submit=True):
        f_reg = st.file_uploader("1 · Registration List (required)", type=["xlsx", "xls"])
        f_proc = st.file_uploader("2 · ProcedureDetails (optional – adds revenue for the management view)", type=["xlsx", "xls"])
        go = st.form_submit_button("Process reports", type="primary")
    if go:
        if not f_reg and reg_bytes is None:
            st.error("Add the Registration List first.")
        elif not (f_reg or f_proc):
            st.info("No new file added. The saved reports are already showing.")
        else:
            try:
                if f_reg:
                    read_registration(f_reg.getvalue(), f_reg.name)
                if f_proc:
                    revenue_map(f_proc.getvalue(), f_proc.name)
            except Exception as e:  # noqa: BLE001
                st.error(f"Could not read the files. {e}")
            else:
                now = datetime.now(UAE)
                new_meta = dict(meta)
                if f_reg:
                    put("latest/registration.xlsx", f_reg.getvalue())
                    new_meta.update(reg=f_reg.name, uploaded_at=now.strftime("%d-%m-%Y %I:%M %p"))
                    if not f_proc:
                        new_meta["proc"] = ""
                if f_proc:
                    put("latest/procedure.xlsx", f_proc.getvalue())
                    new_meta["proc"] = f_proc.name
                put("latest/meta.json", json.dumps(new_meta).encode())
                st.session_state["mk"] = (f_reg.getvalue() if f_reg else reg_bytes, new_meta,
                                          f_proc.getvalue() if f_proc else (None if f_reg else proc_bytes))
                st.rerun()
    if reg_bytes is not None:
        st.caption(f"Saved now: Registration List {meta.get('reg', '')}"
                   + (f" · ProcedureDetails {meta['proc']}" if meta.get("proc") else " · no ProcedureDetails (revenue not shown)")
                   + ". A new Registration List starts a new day; add the ProcedureDetails of the same day for revenue.")

if reg_bytes is None:
    st.markdown('<div class="empty"><b>No report yet.</b> Upload the HIS Registration List above and press Process reports.</div>',
                unsafe_allow_html=True)
    st.stop()

try:
    rows = read_registration(reg_bytes, meta.get("reg", "x.xlsx"))
    rev = revenue_map(proc_bytes, meta.get("proc", "x.xlsx")) if proc_bytes else None
except Exception as e:  # noqa: BLE001
    st.error(f"Could not read the saved reports. {e}")
    st.stop()

days = day_totals(rows, dict(rev) if rev else None)
try:
    update_ledger(days)
except Exception:  # noqa: BLE001
    pass
dates = sorted(days, key=lambda s: datetime.strptime(s, "%d-%m-%Y"))
last = datetime.strptime(dates[-1], "%d-%m-%Y")
ym = f"{last:%Y-%m}"
led = get_json(f"ledger/{ym}.json", {})
for k, v in days.items():                         # make sure today is in, even if saving failed
    led.setdefault(f"{datetime.strptime(k, '%d-%m-%Y'):%Y-%m-%d}", v)
prev_last = last.replace(day=1) - timedelta(days=1)
led_prev = get_json(f"ledger/{prev_last:%Y-%m}.json", {})

span = [f"{last.replace(day=i):%Y-%m-%d}" for i in range(1, last.day + 1)]
DAY_OPTS = ["ALL"] + [k for k in reversed(span) if k in led]
_pick = st.session_state.get("mk_day", DAY_OPTS[1] if len(DAY_OPTS) > 1 else "ALL")
if _pick not in DAY_OPTS:
    _pick = DAY_OPTS[1] if len(DAY_OPTS) > 1 else "ALL"
st.session_state["mk_day"] = _pick
if _pick == "ALL":
    today = sum_days(led, span)
    LBL, SEL = "All days", None
else:
    today = sum_days(led, [_pick])
    SEL = datetime.strptime(_pick, "%Y-%m-%d")
    LBL = "Today" if SEL.date() == last.date() else f"{SEL:%a %d %b}"
month = sum_days(led, span)
missing = [datetime.strptime(k, "%Y-%m-%d") for k in span if k not in led]
same_prev = [f"{prev_last.replace(day=i):%Y-%m-%d}" for i in range(1, min(last.day, prev_last.day) + 1)]
prev_part = sum_days(led_prev, same_prev)
prev_full = sum_days(led_prev, list(led_prev))
has_prev = prev_part["days"] > 0

aliases = get_json("aliases.json", {})
all_co = {}
for src in (month, prev_full):
    for name, c in src["co"].items():
        all_co[name] = all_co.get(name, 0) + c[0]
all_co.pop("(not filled)", None)
CO = build_names(all_co, company_key, aliases)
all_camp = {}
for src in (month, prev_full):
    for name, n in src["camp"].items():
        all_camp[name] = all_camp.get(name, 0) + n
all_camp.pop("(not filled)", None)
CAMP = build_names(all_camp, camp_key, {}, threshold=0.72)


def group(src, mapping, field="co"):
    out = {}
    for name, val in src[field].items():
        disp = mapping.get(name, name)
        if field == "co":
            t = out.setdefault(disp, [0, 0, 0, 0.0])
            for i in range(4):
                t[i] += val[i]
        else:
            out[disp] = out.get(disp, 0) + val
    return out


co_today, co_month = group(today, CO), group(month, CO)
co_prev, co_prevfull = group(prev_part, CO), group(prev_full, CO)
camp_today, camp_month = group(today, CAMP, "camp"), group(month, CAMP, "camp")
camp_prev = group(prev_part, CAMP, "camp")
REV_OK = month["rev_days"] > 0
PERIOD = f"1–{last:%d %b %Y}"
DAY = f"All days 1–{last:%d %b %Y}" if SEL is None else f"{SEL:%a %d %b %Y}"


def trend(now, before):
    if not has_prev:
        return ""
    if before == 0 and now > 0:
        return '<span class="tag t-new">NEW</span>'
    d = now - before
    if d > 0:
        return f'<span class="up">▲ {d}</span>'
    if d < 0:
        return f'<span class="down">▼ {-d}</span>'
    return '<span class="flat">→</span>'


lost = sorted(((n, c[0]) for n, c in co_prevfull.items() if n != "(not filled)" and c[0] >= 2 and co_month.get(n, [0])[0] == 0),
              key=lambda x: -x[1])

# ---------------------------------------------------------------- page
st.markdown(f"""
<div class="hero"><div><h1>EMC Marketing Report</h1>
<p>{E(DAY)} &nbsp;·&nbsp; month so far {E(PERIOD)} &nbsp;·&nbsp; where our patients come from</p></div>
<div style="display:flex;gap:8px;flex-wrap:wrap"><span class="chip">{E(meta.get('reg', ''))}</span>
<span class="chip">Uploaded {E(meta.get('uploaded_at', ''))}</span></div></div>""", unsafe_allow_html=True)

_c1, _c2 = st.columns([3, 2])
with _c1:
    view = st.segmented_control("View", ["Marketing (patient counts)", "Management (with revenue)"],
                                default="Marketing (patient counts)", key="mk_view") or "Marketing (patient counts)"
with _c2:
    st.selectbox("Day", DAY_OPTS, key="mk_day",
                 format_func=lambda k: f"All days · 1–{last:%d %b}" if k == "ALL" else
                 f"{datetime.strptime(k, '%Y-%m-%d'):%a %d %b}" + (f" · {led[k]['n']} patients"))
MGMT = view.startswith("Management")
if MGMT and not REV_OK:
    st.info("Revenue needs the ProcedureDetails report for the same day. Upload it as file 2 to see revenue here.")


def pct(a, b):
    return f"{a / b:.0%}" if b else "–"


miss_txt = ""
if missing:
    miss_txt = (f"data for {month['days']} of {len(span)} days · missing: "
                + ", ".join(f"{d:%a %d}" for d in missing[:6]) + (f" +{len(missing) - 6} more" if len(missing) > 6 else ""))
named_today = len([n for n in co_today if n != "(not filled)"])
named_month = len([n for n in co_month if n != "(not filled)"])
st.markdown(f"""
<div class="kpis">
 <div class="kpi"><div class="lbl">Patients · {E(LBL)}</div><div class="val">{today['n']}</div>
  <div class="sub">{today['new']} new · {today['n'] - today['new']} returning · {today['fu']} follow-ups</div></div>
 <div class="kpi"><div class="lbl">Companies · {E(LBL)}</div><div class="val">{named_today}</div>
  <div class="sub">employer filled for {pct(today['n'] - today['blank'], today['n'])} of patients</div></div>
 <div class="kpi m"><div class="lbl">Month so far · {E(PERIOD)}</div><div class="val">{month['n']:,}</div>
  <div class="sub">{month['new']} new · {named_month} companies{f" · last month same days {prev_part['n']:,}" if has_prev else ""}</div>
  {f'<div class="warnline">⚠ {E(miss_txt)}</div>' if miss_txt else ""}</div>
 {f'<div class="kpi m"><div class="lbl">Revenue · month so far</div><div class="val">{fmt(month["rev"])} <small>AED</small></div><div class="sub">{E(LBL.lower())} {fmt(today["rev"])} · {fmt(month["rev"] / max(month["n"], 1))} per patient</div></div>' if MGMT and REV_OK else ""}
 {f'<div class="kpi"><div class="lbl">Companies lost</div><div class="val" style="color:#B3261E">{len(lost)}</div><div class="sub">came last month (2+ patients), none this month</div></div>' if has_prev else ""}
</div>""", unsafe_allow_html=True)


def company_table(n=None):
    items = sorted(((k, v) for k, v in co_month.items()), key=lambda x: (x[0] == "(not filled)", -x[1][0]))
    if n:
        items = items[:n]
    top = max([v[0] for k, v in items if k != "(not filled)"] or [1])
    head = (f"<tr><th>#</th><th class='l'>Company</th><th>{E(LBL)}</th><th>Month</th><th>New</th><th>Follow-ups</th>"
            + ("<th>vs last month</th>" if has_prev else "")
            + ("<th>Revenue today</th><th>Revenue month</th><th>Per patient</th>" if MGMT and REV_OK else "") + "</tr>")
    body = ""
    for i, (name, v) in enumerate(items, 1):
        t = co_today.get(name, [0, 0, 0, 0.0])
        bar = f'<span class="barc" style="width:{int(60 * v[0] / top)}px"></span>' if name != "(not filled)" else ""
        body += (f'<tr><td class="rank">{i}</td><td class="nm">{E(name)}</td><td>{t[0] or "–"}</td><td>{bar}<b>{v[0]}</b></td>'
                 f'<td>{v[1] or "–"}</td><td>{v[2] or "–"}</td>'
                 + (f'<td>{trend(v[0], co_prev.get(name, [0])[0])}</td>' if has_prev else "")
                 + (f'<td>{fmt(t[3]) if t[0] else "–"}</td><td><b>{fmt(v[3])}</b></td><td>{fmt(v[3] / max(v[0], 1))}</td>' if MGMT and REV_OK else "")
                 + "</tr>")
    return f'<table class="tbl">{head}{body}</table>'


def camp_table():
    items = sorted(camp_month.items(), key=lambda x: (x[0] == "(not filled)", -x[1]))
    top = max([v for k, v in items if k != "(not filled)"] or [1])
    body = "".join(f'<tr><td class="nm">{E(k)}</td><td>{camp_today.get(k, 0) or "–"}</td>'
                   f'<td><span class="barc" style="width:{int(80 * v / top) if k != "(not filled)" else 0}px"></span><b>{v}</b></td>'
                   + (f'<td>{trend(v, camp_prev.get(k, 0))}</td>' if has_prev else "") + "</tr>" for k, v in items)
    return (f'<table class="tbl"><tr><th class="l">Camp / area</th><th>{E(LBL)}</th><th>Month</th>{"<th>vs last month</th>" if has_prev else ""}</tr>'
            f'{body}</table>')


t1, t7, t2, t3, t4, t5, t6 = st.tabs(["Companies", "Day by day", "Camps and areas", "Growing · dropping · lost", "Nationality", "Data quality", "Email"])
with t1:
    st.markdown(f'<div class="note">Month so far {E(PERIOD)}, biggest first. "New" = new patients registered. '
                + ("Trend compares with the same days of last month. " if has_prev else "Trend starts once last month's data is saved. ")
                + 'Different spellings of the same company are merged (fix any in Data quality).</div>' + company_table(),
                unsafe_allow_html=True)
with t7:
    dkeys = [k for k in span if k in led]
    what = st.radio("Show", ["Companies", "Camps and areas"], horizontal=True, key="mk_dd")
    top_n = st.select_slider("Rows", options=[10, 25, 50, 100, "All"], value=25, key="mk_ddn")
    per = {}
    for k in dkeys:
        one = sum_days(led, [k])
        g = group(one, CO) if what == "Companies" else group(one, CAMP, "camp")
        for name, v in g.items():
            per.setdefault(name, {})[k] = v[0] if what == "Companies" else v
    tot = {n: sum(d.values()) for n, d in per.items()}
    names = sorted(tot, key=lambda n: (n == "(not filled)", -tot[n]))
    if top_n != "All":
        names = names[:top_n]
    day_n = {k: led[k]["n"] for k in dkeys}
    day_new = {k: led[k]["new"] for k in dkeys}
    cols = "".join(f'<th>{datetime.strptime(k, "%Y-%m-%d"):%a}<br>{datetime.strptime(k, "%Y-%m-%d").day}</th>' for k in span)
    head = f'<tr><th class="l">{"Company" if what == "Companies" else "Camp / area"}</th>{cols}<th>Total</th><th>Avg / day</th></tr>'

    def cells(d):
        out = ""
        for k in span:
            if k not in led:
                out += '<td class="z" title="no data">·</td>'
            else:
                v = d.get(k, 0)
                out += f'<td class="{"z" if not v else ""}">{v or "–"}</td>'
        return out

    nd = max(len(dkeys), 1)
    body = (f'<tr class="tot"><td class="nm">All patients</td>{cells(day_n)}<td>{sum(day_n.values()):,}</td><td>{sum(day_n.values()) / nd:.0f}</td></tr>'
            f'<tr class="tot"><td class="nm">New patients</td>{cells(day_new)}<td>{sum(day_new.values()):,}</td><td>{sum(day_new.values()) / nd:.0f}</td></tr>')
    for n in names:
        d = per[n]
        best = max(d.values()) if d else 0
        row = ""
        for k in span:
            if k not in led:
                row += '<td class="z">·</td>'
            else:
                v = d.get(k, 0)
                row += f'<td class="{"z" if not v else "hi" if v == best and best >= 3 else ""}">{v or "–"}</td>'
        body += f'<tr><td class="nm">{E(n)}</td>{row}<td><b>{tot[n]}</b></td><td>{tot[n] / nd:.1f}</td></tr>'
    st.markdown(f'<div class="note">Every day of {E(PERIOD)}. · = no report for that day. Shaded = that row\'s best day. '
                f'Sorted by month total.</div><div class="dwrap"><table class="tbl dd">{head}{body}</table></div>',
                unsafe_allow_html=True)
with t2:
    st.markdown('<div class="note">From the patient address (Address 1). Spellings like "Al Naser / Al Nasser / Alnasir" are merged.</div>'
                + camp_table(), unsafe_allow_html=True)
with t3:
    if not has_prev:
        st.markdown('<div class="empty">Trends start next month, once last month\'s days are saved here. '
                    'To start now, upload last month\'s Registration List (one file for the whole month) once.</div>',
                    unsafe_allow_html=True)
    else:
        moves = [(n, v[0], co_prev.get(n, [0])[0]) for n, v in co_month.items() if n != "(not filled)"]
        grow = sorted([m for m in moves if m[1] > m[2]], key=lambda m: -(m[1] - m[2]))[:10]
        drop = sorted([(n, co_month.get(n, [0])[0], p[0]) for n, p in co_prev.items()
                       if n != "(not filled)" and p[0] > co_month.get(n, [0])[0]], key=lambda m: -(m[2] - m[1]))[:10]
        rowsf = lambda L_, cls: "".join(f'<tr><td class="nm">{E(n)}</td><td>{b}</td><td>{a}</td><td class="{cls}">{"+" if a >= b else ""}{a - b}</td></tr>'
                                        for n, a, b in L_) or '<tr><td colspan="4">–</td></tr>'           # noqa: E731
        h = f"<tr><th>Company</th><th>Last month 1–{min(last.day, prev_last.day)}</th><th>This month</th><th>Change</th></tr>"
        st.markdown('<div class="sec">Growing ▲</div><table class="tbl">' + h + rowsf(grow, "up") + '</table>'
                    '<div class="sec">Dropping ▼</div><table class="tbl">' + h + rowsf(drop, "down") + '</table>',
                    unsafe_allow_html=True)
        lost_rows = "".join(f'<tr><td class="nm">{E(n)}</td><td>{c}</td></tr>' for n, c in lost) or '<tr><td colspan="2">None</td></tr>'
        st.markdown(f'<div class="sec">Lost companies – follow up</div><div class="note">Came last month with 2 or more patients, '
                    f'no patient yet this month.</div><table class="tbl"><tr><th>Company</th><th>Patients last month</th></tr>{lost_rows}</table>',
                    unsafe_allow_html=True)
with t4:
    nat = sorted(month["nat"].items(), key=lambda x: -x[1])
    top = max([v for _, v in nat] or [1])
    st.markdown('<div class="note">Useful for the language of flyers and WhatsApp messages.</div><table class="tbl">'
                f'<tr><th>Nationality</th><th>{E(LBL)}</th><th>Month</th><th>Share</th></tr>'
                + "".join(f'<tr><td class="nm">{E(k)}</td><td>{today["nat"].get(k, 0) or "–"}</td>'
                          f'<td><span class="barc" style="width:{int(80 * v / top)}px"></span><b>{v}</b></td><td>{pct(v, month["n"])}</td></tr>'
                          for k, v in nat) + '</table>', unsafe_allow_html=True)
with t5:
    users = sorted(month["users"].items(), key=lambda x: -x[1][1])
    st.markdown(f'<div class="note">Employer filled for <b>{pct(month["n"] - month["blank"], month["n"])}</b> of patients this month. '
                'Reception should fill Employer Name and Address for every patient.</div><table class="tbl">'
                '<tr><th>Registered by</th><th>Patients</th><th>Employer filled</th><th>%</th></tr>'
                + "".join(f'<tr><td class="nm">{E(u)}</td><td>{b}</td><td>{a}</td>'
                          f'<td class="{"up" if b and a / b >= 0.95 else "down"}">{pct(a, b)}</td></tr>' for u, (a, b) in users)
                + '</table>', unsafe_allow_html=True)
    st.markdown('<div class="sec">Company name fixes</div><div class="note">Similar spellings are merged automatically. '
                'If two companies are merged wrongly, or one company still shows twice, write one line per fix: '
                '<b>spelling as it shows = name to use</b>.</div>', unsafe_allow_html=True)
    groups = {}
    for raw, disp in CO.items():
        groups.setdefault(disp, []).append(raw)
    with st.expander("See which spellings were merged"):
        st.markdown("".join(f"<div style='font-size:13px;margin-bottom:6px'><b>{E(d)}</b> ← {E(' | '.join(r))}</div>"
                            for d, r in sorted(groups.items()) if len(r) > 1) or "Nothing merged.", unsafe_allow_html=True)
    txt = st.text_area("Fixes", value="\n".join(f"{k} = {v}" for k, v in aliases.items()), height=120,
                       placeholder="ARCO GENERAL CONTRACTNG = Arco General Contracting LLC")
    if st.button("Save fixes"):
        new = {}
        for line in txt.splitlines():
            if "=" in line:
                a, b = line.split("=", 1)
                if a.strip() and b.strip():
                    new[a.strip()] = b.strip()
        put("aliases.json", json.dumps(new).encode())
        st.success(f"Saved {len(new)} fixes.")
        st.rerun()


# ---------------------------------------------------------------- email (Outlook-safe tables)
def email_html(mgmt):
    F = "font-family:Segoe UI,Arial,Helvetica,sans-serif;"
    INK, MUT, LINE, SOFT, EDGE, BR = "#18211C", "#5D6A62", "#E1E6E0", "#F2F5F1", "#C9D2CB", "#1F4E8C"
    T = 'role="presentation" cellpadding="0" cellspacing="0" border="0"'
    show_rev = mgmt and REV_OK
    th = f'bgcolor="{SOFT}" style="background:{SOFT};color:{MUT};font-size:10.5px;letter-spacing:1px;text-transform:uppercase;padding:8px 10px;text-align:right;border-bottom:2px solid {EDGE};"'
    thl = th.replace("text-align:right", "text-align:left")
    td = f'style="padding:7px 10px;border-bottom:1px solid {LINE};text-align:right;font-size:13px;"'
    tdl = td.replace("text-align:right", "text-align:left")

    def box(lbl, val, sub, w="25%", strong=False):
        return (f'<td width="{w}" valign="top" bgcolor="#ffffff" style="background:#ffffff;border:{"2px" if strong else "1px"} solid {BR if strong else EDGE};'
                f'border-radius:12px;padding:12px 14px;"><div style="font-size:10.5px;letter-spacing:1px;text-transform:uppercase;'
                f'color:{BR if strong else MUT};font-weight:bold;">{lbl}</div><div style="font:bold 26px Arial,sans-serif;color:{INK};padding-top:4px;">{val}</div>'
                f'<div style="font-size:12px;color:{MUT};padding-top:3px;">{sub}</div></td>')

    def section(t):
        return (f'<tr><td style="padding:22px 0 8px;"><table {T} width="100%"><tr><td style="font:bold 18px Arial,sans-serif;color:{INK};'
                f'border-bottom:3px solid {BR};padding-bottom:6px;">{t}</td></tr></table></td></tr>')

    def trend_e(now, before):
        if not has_prev:
            return ""
        if before == 0 and now > 0:
            return f'<b style="color:{BR}">NEW</b>'
        d = now - before
        return (f'<b style="color:#1E7A45">&#9650; {d}</b>' if d > 0 else f'<b style="color:#B3261E">&#9660; {-d}</b>' if d < 0
                else f'<span style="color:{MUT}">&#8594;</span>')

    out = [f'<table {T} width="100%" bgcolor="#EEF1F5" style="background:#EEF1F5;{F}"><tr><td align="center" style="padding:18px 10px;">'
           f'<table {T} width="760" style="width:760px;max-width:100%;{F}color:{INK};">'
           f'<tr><td bgcolor="{BR}" style="background:{BR};border-radius:16px;padding:22px 26px;">'
           f'<div style="font:bold 26px Arial,sans-serif;color:#ffffff;">EMC Marketing Report{" · Management" if mgmt else ""}</div>'
           f'<div style="font-size:14px;color:#D6E2F3;padding-top:6px;">{E(DAY)} &nbsp;·&nbsp; month so far {E(PERIOD)}</div></td></tr>'
           f'<tr><td style="padding-top:12px;"><table {T.replace("cellspacing=\"0\"", "cellspacing=\"8\"")} width="100%" style="margin:0 -8px;"><tr>'
           + box(f"Patients · {LBL}", today["n"], f'{today["new"]} new · {today["fu"]} follow-ups')
           + box(f"Companies · {LBL}", named_today, f'employer filled {pct(today["n"] - today["blank"], today["n"])}')
           + box(f"Month so far · {PERIOD}", f'{month["n"]:,}',
                 f'{month["new"]} new · {named_month} companies' + (f' · last month same days {prev_part["n"]:,}' if has_prev else "")
                 + (f'<br><b style="color:#9A6200">&#9888; {E(miss_txt)}</b>' if miss_txt else ""), "30%", True)
           + (box("Revenue · month so far", f'{fmt(month["rev"])} <span style="font-size:13px;color:{MUT}">AED</span>',
                  f'today {fmt(today["rev"])} · {fmt(month["rev"] / max(month["n"], 1))} per patient', "20%", True) if show_rev else
              (box("Companies lost", len(lost), "came last month, none yet this month", "20%") if has_prev else ""))
           + '</tr></table></td></tr>']
    # companies
    out.append(section("Top companies"))
    items = sorted(((k, v) for k, v in co_month.items() if k != "(not filled)"), key=lambda x: -x[1][0])[:25]
    head = (f'<tr><th {thl}>Company</th><th {th}>{E(LBL)}</th><th {th}>Month</th><th {th}>New</th>'
            + (f'<th {th}>vs last month</th>' if has_prev else "")
            + (f'<th {th}>Revenue month</th><th {th}>Per patient</th>' if show_rev else "") + '</tr>')
    body = ""
    for name, v in items:
        t = co_today.get(name, [0])
        body += (f'<tr><td {tdl}><b>{E(name)}</b></td><td {td}>{t[0] or "–"}</td><td {td}><b>{v[0]}</b></td><td {td}>{v[1] or "–"}</td>'
                 + (f'<td {td}>{trend_e(v[0], co_prev.get(name, [0])[0])}</td>' if has_prev else "")
                 + (f'<td {td}><b>{fmt(v[3])}</b></td><td {td}>{fmt(v[3] / max(v[0], 1))}</td>' if show_rev else "") + '</tr>')
    nf = co_month.get("(not filled)", [0])[0]
    out.append(f'<tr><td><table {T} width="100%" bgcolor="#ffffff" style="background:#ffffff;border:1px solid {EDGE};border-collapse:collapse;">'
               f'{head}{body}</table>'
               + (f'<div style="font-size:12px;color:{MUT};padding-top:6px;">{nf} patients this month with no employer filled. '
                  f'Full list in the attached Excel.</div>' if nf else "") + '</td></tr>')
    # camps
    out.append(section("Camps and areas"))
    citems = sorted(((k, v) for k, v in camp_month.items() if k != "(not filled)"), key=lambda x: -x[1])[:12]
    out.append(f'<tr><td><table {T} width="100%" bgcolor="#ffffff" style="background:#ffffff;border:1px solid {EDGE};border-collapse:collapse;">'
               f'<tr><th {thl}>Camp / area</th><th {th}>{E(LBL)}</th><th {th}>Month</th>{f"<th {th}>vs last month</th>" if has_prev else ""}</tr>'
               + "".join(f'<tr><td {tdl}><b>{E(k)}</b></td><td {td}>{camp_today.get(k, 0) or "–"}</td><td {td}><b>{v}</b></td>'
                         + (f'<td {td}>{trend_e(v, camp_prev.get(k, 0))}</td>' if has_prev else "") + '</tr>' for k, v in citems)
               + '</table></td></tr>')
    # lost
    if has_prev and lost:
        out.append(section("Lost companies – follow up"))
        out.append(f'<tr><td><table {T} width="100%" bgcolor="#ffffff" style="background:#ffffff;border:1px solid {EDGE};border-collapse:collapse;">'
                   f'<tr><th {thl}>Company</th><th {th}>Patients last month</th><th {th}>This month</th></tr>'
                   + "".join(f'<tr><td {tdl}><b>{E(n)}</b></td><td {td}>{c}</td><td {td}><b style="color:#B3261E">0</b></td></tr>' for n, c in lost[:15])
                   + '</table></td></tr>')
    # nationality
    nat = sorted(month["nat"].items(), key=lambda x: -x[1])[:8]
    out.append(section("Nationality"))
    out.append(f'<tr><td style="font-size:13.5px;color:{INK};">' + " &nbsp;·&nbsp; ".join(f'<b>{E(k)}</b> {v} ({pct(v, month["n"])})' for k, v in nat) + '</td></tr>')
    out.append(f'<tr><td style="font-size:12px;color:{MUT};padding:20px 0 0;">From the HIS Registration List. Company spellings are merged; '
               f'patient names and contact details are not included. Sent {datetime.now(UAE):%d-%m-%Y %I:%M %p}.</td></tr>')
    out.append('</table></td></tr></table>')
    return "".join(out)


def build_excel(mgmt):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter
    show_rev = mgmt and REV_OK
    wb = Workbook()
    thin = Side(style="thin", color="D5DCD6")
    box = Border(left=thin, right=thin, top=thin, bottom=thin)
    fill = lambda c: PatternFill("solid", start_color=c, end_color=c)      # noqa: E731

    def sheet(ws, title, headers, rows, widths):
        ws.sheet_view.showGridLines = False
        ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(headers))
        c = ws.cell(1, 1, title); c.font = Font(bold=True, size=14, color="FFFFFF"); c.fill = fill("1F4E8C")
        for j in range(2, len(headers) + 1):
            ws.cell(1, j).fill = fill("1F4E8C")
        ws.row_dimensions[1].height = 26
        for j, h in enumerate(headers, 1):
            c = ws.cell(3, j, h); c.font = Font(bold=True, color="FFFFFF"); c.fill = fill("1F4E8C"); c.border = box
            c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        for i, r in enumerate(rows, 4):
            for j, v in enumerate(r, 1):
                c = ws.cell(i, j, v); c.border = box
                if i % 2:
                    c.fill = fill("F2F5F1")
                if isinstance(v, float):
                    c.number_format = "#,##0"
        for j, w in enumerate(widths, 1):
            ws.column_dimensions[get_column_letter(j)].width = w
        ws.freeze_panes = "A4"

    ws = wb.active; ws.title = "Companies"
    hdr = ["Company", LBL, f"Month {PERIOD}", "New", "Follow-ups"] + (["Last month same days"] if has_prev else []) \
        + (["Revenue today", "Revenue month", "Per patient"] if show_rev else [])
    rows_ = []
    for name, v in sorted(co_month.items(), key=lambda x: (x[0] == "(not filled)", -x[1][0])):
        t = co_today.get(name, [0, 0, 0, 0.0])
        r = [name, t[0], v[0], v[1], v[2]] + ([co_prev.get(name, [0])[0]] if has_prev else [])
        if show_rev:
            r += [float(round(t[3])), float(round(v[3])), float(round(v[3] / max(v[0], 1)))]
        rows_.append(r)
    sheet(ws, f"Companies · {PERIOD}", hdr, rows_, [48, 9, 14, 8, 11] + ([16] if has_prev else []) + ([14, 15, 12] if show_rev else []))
    ws2 = wb.create_sheet("Camps and areas")
    sheet(ws2, f"Camps and areas · {PERIOD}", ["Camp / area", LBL, "Month"] + (["Last month same days"] if has_prev else []),
          [[k, camp_today.get(k, 0), v] + ([camp_prev.get(k, 0)] if has_prev else [])
           for k, v in sorted(camp_month.items(), key=lambda x: -x[1])], [34, 9, 10, 18])
    if has_prev:
        ws3 = wb.create_sheet("Lost companies")
        sheet(ws3, "Lost companies – follow up", ["Company", "Patients last month", "This month"], [[n, c, 0] for n, c in lost], [48, 18, 12])
    dk = [k for k in span if k in led]
    per = {}
    for k in dk:
        for name, v in group(sum_days(led, [k]), CO).items():
            per.setdefault(name, {})[k] = v[0]
    ws5 = wb.create_sheet("Day by day")
    hdr5 = ["Company"] + [f"{datetime.strptime(k, '%Y-%m-%d'):%d %b}" for k in dk] + ["Total"]
    rows5 = [["All patients"] + [led[k]["n"] for k in dk] + [sum(led[k]["n"] for k in dk)]]
    for n in sorted(per, key=lambda n: (n == "(not filled)", -sum(per[n].values()))):
        rows5.append([n] + [per[n].get(k, 0) for k in dk] + [sum(per[n].values())])
    sheet(ws5, f"Day by day · {PERIOD}", hdr5, rows5, [44] + [8] * len(dk) + [9])
    ws4 = wb.create_sheet("Nationality")
    sheet(ws4, f"Nationality · {PERIOD}", ["Nationality", LBL, "Month"],
          [[k, today["nat"].get(k, 0), v] for k, v in sorted(month["nat"].items(), key=lambda x: -x[1])], [24, 9, 10])
    buf = io.BytesIO(); wb.save(buf)
    return buf.getvalue()


with t6:
    smtp = {"host": _secret("SMTP_HOST"), "port": _secret("SMTP_PORT", "465"), "user": _secret("SMTP_USER"), "password": _secret("SMTP_PASS")}
    if not (smtp["host"] and smtp["user"] and smtp["password"]):
        smtp = {}
    who = st.selectbox("Send", ["Marketing team – patient counts only", "Management – with revenue"])
    mgmt_mail = who.startswith("Management")
    c1, c2 = st.columns(2)
    to = c1.text_input("Send to (comma separated)", key=f"mk_to_{who}",
                       value=_secret("EMAIL_TO") if mgmt_mail else _secret("MARKETING_EMAIL_TO"))
    cc = c2.text_input("CC (comma separated)", key=f"mk_cc_{who}", value=_secret("EMAIL_CC") if mgmt_mail else "")
    subject = st.text_input("Subject", key=f"mk_sub_{who}",
                            value=f"EMC Marketing Report{' (management)' if mgmt_mail else ''} - {last:%d-%m-%Y}")
    html = email_html(mgmt_mail)
    xbytes = build_excel(mgmt_mail)
    xname = f"EMC_Marketing_{'Management_' if mgmt_mail else ''}{last:%d-%m-%Y}.xlsx"
    with st.expander("Preview email"):
        st.html(html)
    b1, b2 = st.columns([1, 3])
    b2.download_button("Download Excel", xbytes, file_name=xname,
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    if mgmt_mail and not REV_OK:
        st.caption("No ProcedureDetails uploaded, so the management email has no revenue yet.")
    if not smtp:
        st.warning("Email is not set up. It uses the same SMTP secrets as the Revenue Scorecard; add MARKETING_EMAIL_TO for the marketing team.")
    elif b1.button("Send", type="primary"):
        rcp = [x.strip() for x in to.split(",") if x.strip()]
        if not rcp:
            st.error("Add at least one email address.")
        else:
            try:
                import emc_logic as L
                L.send_email(smtp, rcp, subject, html, xbytes, xname, [x.strip() for x in cc.split(",") if x.strip()])
                st.success(f"Sent to {', '.join(rcp)}.")
            except Exception as e:  # noqa: BLE001
                st.error(f"Email not sent: {e}")
