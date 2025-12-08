# exclusive_dashboard.py
import sys
import subprocess
import hashlib
import calendar
from pathlib import Path
from datetime import datetime, date
import pandas as pd
import streamlit as st

# =========================== Page & Folders ===========================
st.set_page_config(page_title="Exclusive Report with Aging — Dashboard", layout="wide")
BASE = Path(__file__).parent
DATA_DIR = BASE / "data"
(DATA_DIR / "easyhealth").mkdir(parents=True, exist_ok=True)
(DATA_DIR / "excellent").mkdir(parents=True, exist_ok=True)
(DATA_DIR / "excellent_pharmacy").mkdir(parents=True, exist_ok=True)

# =========================== Centers & Generators =====================
CENTERS = {
    "easyhealth": {
        "key": "easyhealth",
        "name": "Easy Health Medical Clinic (MF8031)",
        "folder_root": DATA_DIR / "easyhealth",
        "src_name": "source.xlsx",
        "out_name": "report.xlsx",
        "generator": BASE / "exclusive_report_with_aging_final.py",
    },
    "excellent": {
        "key": "excellent",
        "name": "Excellent Medical Center (MF4777)",
        "folder_root": DATA_DIR / "excellent",
        "src_name": "source.xlsx",
        "out_name": "report.xlsx",
        "generator": BASE / "exclusive_report_with_aging_final.py",
    },
    "pharmacy": {
        "key": "pharmacy",
        "name": "Excellent Pharmacy (PF3205)",
        "folder_root": DATA_DIR / "excellent_pharmacy",
        "src_name": "source.xlsx",
        "out_name": "Pharmacy_Exclusive_Report_with_Aging.xlsx",
        "generator": BASE / "pharmacy_exclusive_report_with_aging.py",
    },
}
YEARS = [2024, 2025]

# Canonical sheet names expected from generators
SHEET_INS_TOT = "Insurance_Totals"
SHEET_SUMMARY = "Balance_Aging_Summary"
SHEET_DETAIL  = "Balance_Aging_Detail"

# =============================== Helpers ==============================
def sha1_short(path: Path) -> str:
    try:
        h = hashlib.sha1()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()[:10]
    except Exception:
        return "—"

def mtime_token(p: Path) -> float:
    try:
        return p.stat().st_mtime
    except FileNotFoundError:
        return 0.0

def _run(cmd):
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(
            "Command failed:\n" + " ".join(cmd)
            + "\n\nSTDOUT:\n" + (res.stdout or "(empty)")
            + "\n\nSTDERR:\n" + (res.stderr or "(empty)")
        )
    return res

def rebuild_report(gen_path: Path, src_path: Path, out_path: Path) -> str:
    py = sys.executable
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [py, str(gen_path), str(src_path)]
    try:
        res = _run(cmd + ["--out", str(out_path)])
        return res.stdout or "OK"
    except Exception:
        res = _run([py, str(gen_path), "--out", str(out_path), str(src_path)])
        return res.stdout or "OK"

def _pick_sheet(sheet_names, wants_all=None, wants_any=None):
    lower = [s.lower() for s in sheet_names]
    if wants_all:
        for i, s in enumerate(lower):
            if all(w in s for w in wants_all):
                return sheet_names[i]
    if wants_any:
        for i, s in enumerate(lower):
            if any(w in s for w in wants_any):
                return sheet_names[i]
    return None

def autodetect(xls: pd.ExcelFile):
    names = xls.sheet_names
    ins_tot = SHEET_INS_TOT if SHEET_INS_TOT in names else None
    summary = SHEET_SUMMARY if SHEET_SUMMARY in names else None
    detail  = SHEET_DETAIL  if SHEET_DETAIL  in names else None
    if ins_tot is None:
        ins_tot = _pick_sheet(names, wants_any=["insurance", "total"]) or _pick_sheet(names, wants_any=["totals"])
    if summary is None:
        summary = _pick_sheet(names, wants_all=["aging","summary"]) or _pick_sheet(names, wants_any=["summary"])
    if detail is None:
        detail  = _pick_sheet(names, wants_all=["aging","detail"]) or _pick_sheet(names, wants_any=["detail"])
    return ins_tot, summary, detail, names

# ---------- caching ----------
@st.cache_resource(show_spinner=True)
def load_book(path: str, _token: float):
    return pd.ExcelFile(path, engine="openpyxl")

@st.cache_data(show_spinner=True)
def load_core_sheets(path: str, _token: float):
    xls = load_book(path, _token)
    ins_tot, summary, detail, names = autodetect(xls)
    if not ins_tot or not summary:
        raise RuntimeError(f"Required sheets not found. Available: {', '.join(names)}")
    df_ins  = xls.parse(ins_tot)
    df_sum  = xls.parse(summary)
    return df_ins, df_sum, ins_tot, summary, detail, names

@st.cache_data(show_spinner=True)
def load_detail(path: str, sheet_name: str, _token: float):
    xls = load_book(path, _token)
    return xls.parse(sheet_name)

# ---------- date-span helpers ----------
def _month_abbr(m: int) -> str:
    return calendar.month_abbr[m]

def _last_day_of_month(y: int, m: int) -> int:
    return calendar.monthrange(y, m)[1]

def _pretty_span(d1: pd.Timestamp, d2: pd.Timestamp) -> str:
    d1 = pd.to_datetime(d1).to_pydatetime().date()
    d2 = pd.to_datetime(d2).to_pydatetime().date()
    same_year = d1.year == d2.year
    full_start = d1.day == 1
    full_end = d2.day == _last_day_of_month(d2.year, d2.month)
    if same_year and full_start and full_end:
        if d1.month == d2.month:
            return f"{_month_abbr(d1.month)} {d1.year}"
        return f"{_month_abbr(d1.month)}–{_month_abbr(d2.month)} {d1.year}"
    else:
        if same_year:
            if d1.month == d2.month:
                return f"{_month_abbr(d1.month)} {d1.day}–{d2.day}, {d1.year}"
            return f"{_month_abbr(d1.month)} {d1.day}–{_month_abbr(d2.month)} {d2.day}, {d1.year}"
        return f"{_month_abbr(d1.month)} {d1.day}, {d1.year}–{_month_abbr(d2.month)} {d2.day}, {d2.year}"

@st.cache_data(show_spinner=False)
def find_date_span(path: str, preferred_detail_sheet: str | None, _token: float):
    """
    Detect min/max service dates and the most valid date column.
    Returns (min_date, max_date, sheet_used, date_col) or None.
    """
    try:
        xls = load_book(path, _token)
        names = xls.sheet_names

        candidates = []
        if preferred_detail_sheet and preferred_detail_sheet in names:
            candidates.append(preferred_detail_sheet)
        for guess in ["Balance_Aging_Detail", "Detail", "Claims", "Data"]:
            if guess in names and guess not in candidates:
                candidates.append(guess)
        if not candidates:
            candidates = names

        for sheet in candidates:
            df = xls.parse(sheet)
            if df is None or df.empty:
                continue
            poss = [c for c in df.columns
                    if any(k in str(c).lower() for k in
                           ["date", "dos", "service", "encounter", "txn", "transaction"])]
            if not poss:
                continue

            best_col, best_count, best_min, best_max = None, -1, None, None
            for c in poss:
                s = pd.to_datetime(df[c], errors="coerce")
                cnt = s.notna().sum()
                if cnt > best_count and cnt > 0:
                    best_col = c
                    best_count = cnt
                    best_min, best_max = s.min(), s.max()

            if best_col:
                return (best_min, best_max, sheet, best_col)

        return None
    except Exception:
        return None

# ---------- table & UI helpers ----------
def trim_empty_rows(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    df2 = df.dropna(how="all")
    if df2.empty:
        return df2
    blank_rows = df2.fillna("").astype(str).apply(lambda row: "".join(row).strip() == "", axis=1)
    return df2.loc[~blank_rows]

def drop_empty_insurance(df: pd.DataFrame, name_col: str = "Insurance") -> pd.DataFrame:
    """Remove rows where Insurance is blank/None-like, but keep 'Grand Total' rows."""
    if df is None or df.empty or name_col not in df.columns:
        return df
    series = df[name_col].astype(str).fillna("").str.strip()
    bad = series.str.lower().isin(["", "none", "nan", "null", "na", "-", "--"])
    keep_grand = series.str.contains("grand total", case=False, na=False)
    return df.loc[~bad | keep_grand].copy()

def ensure_grand_total(df: pd.DataFrame, name_col: str = "Insurance") -> pd.DataFrame:
    if df is None or df.empty or name_col not in df.columns:
        return df
    if df[name_col].astype(str).str.lower().str.contains("grand total").any():
        return df
    num_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    gt = {c: pd.to_numeric(df[c], errors="coerce").sum() for c in num_cols}
    row = {c: "" for c in df.columns}
    row.update(gt)
    row[name_col] = "Grand Total"
    return pd.concat([df, pd.DataFrame([row])], ignore_index=True)

def full_height(df, row_px: int = 45, header_px: int = 70, padding_px: int = 150) -> int:
    n = 0 if df is None else len(df)
    return header_px + (n * row_px) + padding_px

def style_grid(df: pd.DataFrame):
    if not isinstance(df, pd.DataFrame):
        return df
    if df.shape[1] == 0:
        return df.style
    df = df.copy()
    df.index = range(1, len(df) + 1)
    first_col = df.columns[0]
    num_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    fmt_map = {c: "{:,.2f}".format for c in num_cols}
    border = "#CBD5E1"; header_bg = "#2196F3"; header_font = "#FFFFFF"
    styler = (
        df.style
        .set_table_styles([
            {"selector": "table", "props": [("border-collapse", "collapse"), ("width", "100%")]},
            {"selector": "th.col_heading", "props": [("border", f"1px solid {border}"),
                                                    ("background-color", header_bg),
                                                    ("font-weight", "700"),
                                                    ("color", header_font)]},
            {"selector": "th.row_heading", "props": [("border", f"1px solid {border}"),
                                                     ("background-color", "#FFFFFF"),
                                                     ("color", "#000000"),
                                                     ("font-weight", "500")]},
            {"selector": "td", "props": [("border", f"1px solid {border}")]},
        ])
        .set_properties(subset=[first_col], **{"font-weight": "600"})
        .format(fmt_map)
    )
    try:
        mask_gt = df[first_col].astype(str).str.contains("grand total", case=False, na=False)
        if mask_gt.any():
            def highlight(row):
                return (["font-weight:700; color:black; background-color:#FFF7E0"] * len(row)
                        if mask_gt.iloc[row.name - 1] else [""] * len(row))
            styler = styler.apply(highlight, axis=1)
    except Exception:
        pass
    return styler

def ksum(df: pd.DataFrame, *cands):
    for col in cands:
        if col in df.columns:
            return float(pd.to_numeric(df[col], errors="coerce").sum())
    return 0.0

def recompute_totals_from_detail(df_detail: pd.DataFrame) -> pd.DataFrame:
    """Build an Insurance_Totals-like table from the detail rows."""
    if df_detail is None or df_detail.empty:
        return pd.DataFrame()
    name_col = None
    for c in df_detail.columns:
        if str(c).strip().lower() in {"insurance", "payer", "company"}:
            name_col = c; break
    if not name_col:
        row = {
            "Insurance": "All",
            "Net Amount": ksum(df_detail, "Net Amount", "NetAmount", "Net"),
            "Paid": ksum(df_detail, "Paid"),
            "Balance": ksum(df_detail, "Balance"),
            "Rejected": ksum(df_detail, "Rejected", "Rejection"),
            "Accepted": ksum(df_detail, "Accepted"),
        }
        return pd.DataFrame([row])

    out_cols = {
        "Net Amount": ["Net Amount", "NetAmount", "Net"],
        "Paid": ["Paid"],
        "Balance": ["Balance"],
        "Rejected": ["Rejected", "Rejection"],
        "Accepted": ["Accepted"],
    }
    agg = {}
    for friendly, cands in out_cols.items():
        chosen = next((c for c in cands if c in df_detail.columns), None)
        if chosen:
            agg[chosen] = "sum"
    if not agg:
        return pd.DataFrame()

    g = df_detail.groupby(name_col, dropna=False).agg(agg).reset_index()
    rename_map = {}
    for friendly, cands in out_cols.items():
        for c in cands:
            if c in g.columns:
                rename_map[c] = friendly
                break
    g = g.rename(columns=rename_map)
    g = g.rename(columns={name_col: "Insurance"})
    for friendly in ["Net Amount", "Paid", "Balance", "Rejected", "Accepted"]:
        if friendly not in g.columns:
            g[friendly] = 0.0
    return g

# ---------- admin ----------
def is_admin_mode() -> bool:
    secret_pwd = st.secrets.get("ADMIN_PASSWORD", "")
    if secret_pwd:
        if st.session_state.get("is_admin", False):
            return True
        with st.popover("🔒 Admin login"):
            pwd = st.text_input("Password", type="password", key="admin_pwd")
            if st.button("Login"):
                if pwd == secret_pwd:
                    st.session_state.is_admin = True
                    st.rerun()
                else:
                    st.error("Wrong password")
        return False
    else:
        return st.toggle("Admin mode", value=st.session_state.get("is_admin", False))

# ---------- state ----------
for key, default in [
    ("center_key", None),
    ("last_center_key", None),
    ("year", None),
    ("last_year", None),
    ("date_filter_active", False),
    ("date_filter_start", None),
    ("date_filter_end", None),
]:
    if key not in st.session_state:
        st.session_state[key] = default

# ---------- header ----------
top_left, top_right = st.columns([5, 2])
with top_left:
    st.title("📊 Exclusive Report with Aging — Dashboard")
with top_right:
    st.session_state.is_admin = is_admin_mode()

# URL preselect
qs = st.query_params
if st.session_state.center_key is None and qs.get("center"):
    ck_qs = qs.get("center")
    if ck_qs in CENTERS:
        st.session_state.center_key = ck_qs
if st.session_state.year is None and qs.get("year"):
    try:
        st.session_state.year = int(qs.get("year"))
    except Exception:
        pass

# Clear caches when selection changes
if (st.session_state.center_key != st.session_state.last_center_key) or (st.session_state.year != st.session_state.last_year):
    load_core_sheets.clear(); load_detail.clear(); load_book.clear(); find_date_span.clear()
    st.session_state.last_center_key = st.session_state.center_key
    st.session_state.last_year = st.session_state.year
    st.session_state.date_filter_active = False
    st.session_state.date_filter_start = None
    st.session_state.date_filter_end = None

st.caption(f"Mode: **{'admin' if st.session_state.is_admin else 'view'}** · Center: **{st.session_state.center_key or 'none'}** · Year: **{st.session_state.year or 'none'}**")

# ---------- center select ----------
ck = st.session_state.center_key
if ck not in CENTERS:
    st.subheader("Choose a center")
    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button(CENTERS["easyhealth"]["name"], use_container_width=True):
            st.session_state.center_key = "easyhealth"; st.session_state.year = None; st.rerun()
    with c2:
        if st.button(CENTERS["excellent"]["name"], use_container_width=True):
            st.session_state.center_key = "excellent"; st.session_state.year = None; st.rerun()
    with c3:
        if st.button(CENTERS["pharmacy"]["name"], use_container_width=True):
            st.session_state.center_key = "pharmacy"; st.session_state.year = None; st.rerun()
    st.stop()

# ---------- year select ----------
st.subheader("Select Year")
ycols = st.columns(len(YEARS))
for i, y in enumerate(YEARS):
    with ycols[i]:
        if st.session_state.year == y:
            st.markdown(
                f"""
                <div style="
                    background-color:#2196F3;
                    color:white;
                    text-align:center;
                    padding:0.8em;
                    border-radius:6px;
                    font-weight:700;
                    font-size:1.1em;
                    border:2px solid #1976D2;">
                    {y}
                </div>
                """,
                unsafe_allow_html=True,
            )
        else:
            if st.button(str(y), use_container_width=True, key=f"year_btn_{y}"):
                st.session_state.year = y
                st.rerun()

# Auto-pick latest year with a report else fallback
if st.session_state.year is None:
    cfg_tmp = CENTERS[ck]
    found = None
    for y in reversed(YEARS):
        folder_try = (cfg_tmp["folder_root"] / str(y))
        out_try = folder_try / cfg_tmp["out_name"]
        if out_try.exists():
            found = y; break
    st.session_state.year = found or YEARS[-1]
    st.rerun()

# ---------- resolve paths ----------
cfg = CENTERS[st.session_state.center_key]
folder = cfg["folder_root"] / str(st.session_state.year)
folder.mkdir(parents=True, exist_ok=True)
src_path = folder / cfg["src_name"]
out_path = folder / cfg["out_name"]
gen_path = cfg["generator"]

# Keep URL in sync
if (st.query_params.get("center") != st.session_state.center_key) or (st.query_params.get("year") != str(st.session_state.year)):
    st.query_params["center"] = st.session_state.center_key
    st.query_params["year"]   = str(st.session_state.year)

# Audit ribbon
mt = mtime_token(out_path)
built = "—" if not mt else datetime.fromtimestamp(mt).strftime("%Y-%m-%d %H:%M")
st.caption(f"Built: **{built}** · Source: `{src_path}` · Report: `{out_path.name}` · Hash: `{sha1_short(out_path) if mt else '—'}`")

# ---------- back to center picker ----------
if st.button("◀ Choose another center", key="btn_back_center"):
    st.session_state.center_key = None
    st.session_state.year = None
    try:
        if "center" in st.query_params:
            del st.query_params["center"]
        if "year" in st.query_params:
            del st.query_params["year"]
    except Exception:
        st.experimental_set_query_params()
    st.rerun()

# ---------- admin panel ----------
if st.session_state.is_admin:
    st.success("You are in **ADMIN** mode — upload/rebuild is enabled.")
    with st.expander("⬆️ Upload/replace source Excel for this year", expanded=False):
        up = st.file_uploader(
            f"Upload .xlsx for {st.session_state.year}",
            type=["xlsx"],
            key=f"uploader_{st.session_state.center_key}_{st.session_state.year}",
        )
        if up:
            folder.mkdir(parents=True, exist_ok=True)
            src_path.write_bytes(up.read())
            st.success(f"Saved to {src_path}")

    if st.button("↻ Rebuild report", use_container_width=True, key=f"rebuild_{ck}_{st.session_state.year}"):
        try:
            if not gen_path.exists():
                st.error(f"Generator not found: {gen_path}")
            elif not src_path.exists():
                st.error(f"No source file found for {st.session_state.year}. Please upload {src_path.name} first.")
            else:
                t0 = datetime.now()
                msg = rebuild_report(gen_path, src_path, out_path)
                t1 = datetime.now()
                st.success(f"Report rebuilt successfully in {(t1 - t0).total_seconds():.1f}s.")
                if msg.strip():
                    st.code(msg, language="bash")
            load_core_sheets.clear(); load_detail.clear(); load_book.clear(); find_date_span.clear()
        except Exception as e:
            st.error(str(e))

# ---------- render ----------
token = mtime_token(out_path)
if token == 0.0:
    msg = f"Report not found for {cfg['name']} ({st.session_state.year})."
    if st.session_state.is_admin:
        msg += " (Upload source and click Rebuild.)"
    st.warning(msg)
    st.stop()

try:
    # Load core sheets
    totals, summary, s_tot, s_sum, s_det, available = load_core_sheets(str(out_path), token)

    # ----- DATE RANGE BADGE + INTERACTIVE FILTER -----
    span = find_date_span(str(out_path), s_det, token)
    dmin = dmax = None
    detail_sheet = s_det if s_det in available else None
    date_col = None
    if span:
        dmin, dmax, detail_sheet, date_col = span

    # Helper: pretty print the currently selected filter range
    def _pretty_selected_range() -> str:
        s = st.session_state.get("date_filter_start")
        e = st.session_state.get("date_filter_end")
        if not s or not e:
            return ""
        s = pd.to_datetime(s).date()
        e = pd.to_datetime(e).date()
        if s.year == e.year:
            if s.month == e.month:
                return f"{s.strftime('%b %d')}–{e.strftime('%d, %Y')}"
            return f"{s.strftime('%b %d')}–{e.strftime('%b %d, %Y')}"
        return f"{s.strftime('%b %d, %Y')}–{e.strftime('%b %d, %Y')}"

    # clickable badge UI
    if span:
        label = _pretty_span(dmin, dmax)
        col_badge, col_actions = st.columns([6, 2])
        with col_badge:
            with st.popover(f"📅 Data range: {label}", use_container_width=True):
                st.markdown("**Quick months**")
                # month chips covering the span year(s)
                min_y, max_y = dmin.year, dmax.year
                chips = []
                for y in range(min_y, max_y + 1):
                    for m in range(1, 13):
                        m_start = date(y, m, 1)
                        m_end = date(y, m, _last_day_of_month(y, m))
                        if m_end < dmin.date() or m_start > dmax.date():
                            continue
                        chips.append((y, m))
                chcols = st.columns(6)
                for i, (y, m) in enumerate(chips):
                    lab = f"{_month_abbr(m)} {y}"
                    if chcols[i % 6].button(lab, key=f"chip_{y}_{m}"):
                        st.session_state.date_filter_active = True
                        st.session_state.date_filter_start = date(y, m, 1)
                        st.session_state.date_filter_end = date(y, m, _last_day_of_month(y, m))
                        st.rerun()

                st.divider()
                st.markdown("**Custom range**")
                d0 = st.session_state.date_filter_start or dmin.date()
                d1 = st.session_state.date_filter_end or dmax.date()
                d0 = st.date_input("Start", value=d0, min_value=dmin.date(), max_value=dmax.date(), key="custom_start")
                d1 = st.date_input("End", value=d1, min_value=dmin.date(), max_value=dmax.date(), key="custom_end")
                a1, a2 = st.columns(2)
                if a1.button("Apply"):
                    if d0 <= d1:
                        st.session_state.date_filter_active = True
                        st.session_state.date_filter_start = d0
                        st.session_state.date_filter_end = d1
                        st.rerun()
                    else:
                        st.warning("Start must be on/before End.")
                if a2.button("Clear filter"):
                    st.session_state.date_filter_active = False
                    st.session_state.date_filter_start = None
                    st.session_state.date_filter_end = None
                    st.rerun()
        with col_actions:
            if st.session_state.date_filter_active:
                st.markdown(
                    f"""
                    <div style="
                        padding:10px 14px;
                        border-radius:10px;
                        background:#E8F5E9;
                        border:1px solid #C8E6C9;
                        font-weight:700;
                        color:#1B5E20;">
                        ✅ Filter: ON
                        <div style="margin-top:6px; font-weight:600; color:#0B3D0B;">
                            Range: {_pretty_selected_range()}
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    """
                    <div style="
                        padding:10px 14px;
                        border-radius:10px;
                        background:#F1F5F9;
                        border:1px solid #CBD5E1;
                        font-weight:700;
                        color:#0F172A;">
                        ⛔ Filter: OFF
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

    # Normalize totals from workbook
    if "Insurance" not in totals.columns and len(totals.columns) > 0:
        totals = totals.rename(columns={totals.columns[0]: "Insurance"})
    for a, b in [("NetAmount","Net Amount"), ("Net amount","Net Amount"), ("Net","Net Amount")]:
        if a in totals.columns and "Net Amount" not in totals.columns:
            totals = totals.rename(columns={a: "Net Amount"})
    totals = trim_empty_rows(totals)
    totals = drop_empty_insurance(totals, "Insurance")
    totals = ensure_grand_total(totals, "Insurance")

    # Summary
    summary = trim_empty_rows(summary)
    if not summary.empty:
        summary = ensure_grand_total(summary, summary.columns[0])

    # ---------- Load Detail & apply date filter (for recompute) ----------
    filtered_totals = None
    net = paid = bal = rej = acc = 0.0
    use_filtered = False

    if st.session_state.date_filter_active and detail_sheet and date_col:
        try:
            df_detail = load_detail(str(out_path), detail_sheet, token)
            if not df_detail.empty and date_col in df_detail.columns:
                s_dates = pd.to_datetime(df_detail[date_col], errors="coerce")
                mask = (s_dates.dt.date >= st.session_state.date_filter_start) & (s_dates.dt.date <= st.session_state.date_filter_end)
                df_filt = df_detail.loc[mask].copy()
                if not df_filt.empty:
                    net = ksum(df_filt, "Net Amount", "NetAmount", "Net")
                    paid = ksum(df_filt, "Paid")
                    bal  = ksum(df_filt, "Balance")
                    rej  = ksum(df_filt, "Rejected", "Rejection")
                    acc  = ksum(df_filt, "Accepted")
                    filtered_totals = recompute_totals_from_detail(df_filt)
                    filtered_totals = trim_empty_rows(filtered_totals)
                    filtered_totals = drop_empty_insurance(filtered_totals, "Insurance")
                    filtered_totals = ensure_grand_total(filtered_totals, "Insurance")
                    use_filtered = True
        except Exception:
            use_filtered = False

    # >>> Caption above KPIs when filtered
    if st.session_state.date_filter_active:
        st.caption(
            f"Showing data for **{_pretty_selected_range()}** "
            + (f"(from `{detail_sheet}` → `{date_col}`)" if detail_sheet and date_col else "")
        )

    # ---------- KPIs ----------
    c0, c1, c2, c3, c4 = st.columns(5)
    if not use_filtered:
        def drop_grand_total(df: pd.DataFrame) -> pd.DataFrame:
            if df is None or df.empty:
                return df
            first_col = df.columns[0]
            return df.loc[~df[first_col].astype(str).str.contains("grand total", case=False, na=False)]
        totals_no_gt = drop_grand_total(totals)
        net = ksum(totals_no_gt, "Net Amount", "NetAmount", "Net")
        paid = ksum(totals_no_gt, "Paid")
        bal  = ksum(totals_no_gt, "Balance")
        rej  = ksum(totals_no_gt, "Rejected", "Rejection")
        acc  = ksum(totals_no_gt, "Accepted")

    c0.metric("Net Amount", f"{net:,.2f}")
    c1.metric("Paid",       f"{paid:,.2f}")
    c2.metric("Balance",    f"{bal:,.2f}")
    c3.metric("Rejected",   f"{rej:,.2f}")
    c4.metric("Accepted",   f"{acc:,.2f}")

    # ---------- Chart (styled) ----------
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FuncFormatter

    def human_aed_compact(x, _pos=None):
        ax = abs(x)
        if ax >= 1_000_000_000: return f"{x/1_000_000_000:.2f}B"
        if ax >= 1_000_000:     return f"{x/1_000_000:.2f}M"
        if ax >= 1_000:         return f"{x/1_000:.0f}.k"
        return f"{x:,.0f}"

    labels = ["Net Amount", "Paid", "Balance", "Rejected", "Accepted"]
    values = [net,          paid,   bal,       rej,        acc]
    colors = ["#1E3A5F", "#2E7D32", "#F2B444", "#C62828", "#1976D2"]  # navy, green, amber, red, blue

    st.subheader("")
    fig, ax = plt.subplots(figsize=(8.5, 4.8), dpi=160)
    bars = ax.bar(labels, values, color=colors, edgecolor="none")
    ax.set_title("Amounts", fontsize=28, fontweight="900", loc="left", pad=8)
    ax.yaxis.set_major_formatter(FuncFormatter(human_aed_compact))
    ax.grid(axis="y", linestyle="--", alpha=0.35)
    ax.set_axisbelow(True)
    for spine in ["top", "right"]:
        ax.spines[spine].set_visible(False)
    ax.spines["left"].set_linewidth(1.2)
    ax.spines["bottom"].set_linewidth(1.2)
    ax.tick_params(axis="x", labelsize=16, length=0)
    ax.tick_params(axis="y", labelsize=12)

    ymax = max(values) if values else 1.0
    for rect, v in zip(bars, values):
        x = rect.get_x() + rect.get_width() / 2
        label = f"{int(round(v)):,.0f}"
        if v >= 0.08 * ymax:
            ax.text(x, v * 0.96, label, ha="center", va="top",
                    fontsize=16, fontweight="900", color="white")
        else:
            ax.text(x, v + (0.02 * ymax), label, ha="center", va="bottom",
                    fontsize=14, fontweight="800", color="#1F2937")
    ax.set_ylim(0, ymax * 1.12 if ymax > 0 else 1)
    fig.tight_layout()
    st.pyplot(fig, use_container_width=True)

    # ---------- Tabs ----------
    t1, t2, t3 = st.tabs([SHEET_INS_TOT, SHEET_SUMMARY, SHEET_DETAIL])

    with t1:
        if use_filtered and filtered_totals is not None and not filtered_totals.empty:
            st.markdown(f"**Filtered Insurance Totals — {_pretty_selected_range()}**")
            st.dataframe(style_grid(filtered_totals), use_container_width=True,
                         height=full_height(filtered_totals))
            st.divider()
        st.dataframe(style_grid(totals), use_container_width=True, height=full_height(totals))
        dl1, dl2 = st.columns(2)
        with dl1:
            st.download_button(
                "⬇️ Download full report (.xlsx)",
                out_path.read_bytes(),
                file_name=out_path.name,
                use_container_width=True,
                key=f"dl_xlsx_totals_{ck}_{st.session_state.year}"
            )
        with dl2:
            st.download_button(
                "⬇️ Export this table (CSV)",
                totals.to_csv(index=False).encode("utf-8"),
                file_name=f"{cfg['key']}_{st.session_state.year}_totals.csv",
                use_container_width=True,
                key=f"dl_csv_totals_{ck}_{st.session_state.year}"
            )

    with t2:
        st.dataframe(style_grid(summary), use_container_width=True, height=full_height(summary))
        dl1, dl2 = st.columns(2)
        with dl1:
            st.download_button(
                "⬇️ Download full report (.xlsx)",
                out_path.read_bytes(),
                file_name=out_path.name,
                use_container_width=True,
                key=f"dl_xlsx_summary_{ck}_{st.session_state.year}"
            )
        with dl2:
            st.download_button(
                "⬇️ Export this table (CSV)",
                summary.to_csv(index=False).encode("utf-8"),
                file_name=f"{cfg['key']}_{st.session_state.year}_summary.csv",
                use_container_width=True,
                key=f"dl_csv_summary_{ck}_{st.session_state.year}"
            )

    with t3:
        st.caption("Loads only when you click, to keep things fast.")
        if st.button("Load Balance_Aging_Detail (no styling)"):
            try:
                detail_sheet2 = s_det or SHEET_DETAIL
                if not detail_sheet2 or detail_sheet2 not in available:
                    raise RuntimeError(f"Detail sheet not found. Available: {', '.join(available)}")
                df3 = load_detail(str(out_path), detail_sheet2, token)
                df3 = trim_empty_rows(df3)
                if st.session_state.date_filter_active and date_col and date_col in df3.columns:
                    s_dates3 = pd.to_datetime(df3[date_col], errors="coerce")
                    mask3 = (s_dates3.dt.date >= (st.session_state.date_filter_start or date.min)) & \
                            (s_dates3.dt.date <= (st.session_state.date_filter_end or date.max))
                    df3 = df3.loc[mask3].copy()

                total_rows = len(df3)
                st.info(f"Rows: {total_rows:,}")
                page_size = st.number_input("Rows per page", min_value=500, max_value=50000, step=500, value=5000)
                max_page = max(1, (total_rows + page_size - 1) // page_size)
                page = st.number_input("Page", min_value=1, max_value=max_page, step=1, value=1)
                start = (page - 1) * page_size
                end = min(start + page_size, total_rows)
                view = df3.iloc[start:end].copy()
                view.index = range(start + 1, end + 1)

                st.dataframe(view, use_container_width=True, height=full_height(view))
                dl1, dl2 = st.columns(2)
                with dl1:
                    st.download_button(
                        "⬇️ Download full report (.xlsx)",
                        out_path.read_bytes(),
                        file_name=out_path.name,
                        use_container_width=True,
                        key=f"dl_xlsx_detail_{ck}_{st.session_state.year}"
                    )
                with dl2:
                    st.download_button(
                        "⬇️ Export this page (CSV)",
                        view.to_csv(index=False).encode("utf-8"),
                        file_name=f"{cfg['key']}_{st.session_state.year}_detail_p{page}.csv",
                        use_container_width=True,
                        key=f"dl_csv_detail_{ck}_{st.session_state.year}_p{page}"
                    )
            except Exception as e:
                st.error(str(e))

except Exception as e:
    try:
        names = pd.ExcelFile(str(out_path), engine="openpyxl").sheet_names
    except Exception:
        names = []
    st.error(f"{e}\n\nAvailable sheets: {', '.join(names) if names else '(none)'}")

