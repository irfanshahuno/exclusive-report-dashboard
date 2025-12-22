# exclusive_dashboard.py — Main dashboard KPIs at TOP (Doc Performance unchanged)
# NOTE: This is your original dashboard with ONLY the minimal additions:
#   • Optional Balance_Aging_InsGroup tab (already supported)
#   • Optional Balance_Aging_Plan tab (new) with Insurance filter
#   • S.No hidden and display index starts at 1
#   • Grand Total row (any of 'Grand Total' / 'Total') is shown LAST in tables
#   • NEW: View password gate (Emc@2026)
# ✅ NEEDFUL CHANGES (as per your request earlier):
#   1) Home page: "Choose a center" moved to TOP (above KPIs)
#   2) Home page: Balance value is clickable (opens BALANCE_ATTEMPT_URL) for each center
# ✅ NEEDFUL CHANGES (as per your latest request):
#   3) After password: show landing page with ONLY 2 buttons (2024/2025)
#   4) Add "⬅ Change Year" button so management can go back anytime
# ✅ PREMIUM SOOTHING UI (ONLY VISUAL):
#   5) Soft background + premium light-blue buttons
#   6) KPI section becomes premium cards (soothing + easier for eyes)
#   7) Center names dark navy
#   8) Balance card same bold + slight different color + clickable
# Nothing else is changed.

import sys
import subprocess
import re
from pathlib import Path
from datetime import datetime, date

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components  # used only for the home-card link


# ====================== VIEW PASSWORD (NEW) ======================
VIEW_PASSWORD = "Emc@2026"


def require_view_access() -> None:
    """
    View-only password gate.
    - Blocks everything unless correct view password is entered.
    - Does NOT affect Admin password logic (admin is separate).
    """
    if st.session_state.get("is_view_auth", False):
        return

    st.set_page_config(page_title="Excellent Medical Group", layout="wide")
    st.set_option("client.showErrorDetails", False)

    st.title("🔒 Dashboard Access")
    st.info("Enter the view password to open the dashboard.")

    pwd = st.text_input("View Password", type="password", key="view_pwd")
    c1, c2 = st.columns([1, 1])
    with c1:
        if st.button("Enter Dashboard", use_container_width=True):
            if pwd == VIEW_PASSWORD:
                st.session_state.is_view_auth = True
                st.rerun()
            else:
                st.error("Incorrect password.")
    with c2:
        st.caption("")

    st.stop()


# ====================== Page & base folders ======================
st.set_page_config(page_title="Excellent Medical Group", layout="wide")
st.set_option("client.showErrorDetails", False)

# NEW: enforce view login first
require_view_access()

# ✅ Balance Attempt Aging app URL (opens on Balance click)
BALANCE_ATTEMPT_URL = "https://balance-attempt-aging-dashboard-eigtoins4ai9hd9r7jsmen.streamlit.app/"

# =========================================================
# ✅ PREMIUM + SOOTHING UI (ONLY STYLES)
# =========================================================
st.markdown(
    """
<style>
/* ---------- Page background (soothing) ---------- */
.stApp{
  background: linear-gradient(180deg, #F7FAFF 0%, #FFFFFF 45%) !important;
}

/* Reduce harsh separators */
hr{ border: none !important; height:1px !important; background:#E6EEF8 !important; }

/* ---------- Premium Buttons (Light-blue) ---------- */
div.stButton > button{
  width: 100% !important;
  min-height: 58px !important;
  padding: 14px 22px !important;
  font-size: 18px !important;
  font-weight: 800 !important;

  background: #EEF6FF !important;              /* premium light blue */
  color: #0B2D5C !important;                   /* navy text */
  border: 1.8px solid #B6D4FF !important;      /* soft border */
  border-radius: 14px !important;

  box-shadow: 0 3px 10px rgba(11, 45, 92, 0.10) !important;
}

/* Hover */
div.stButton > button:hover{
  background: #DCEBFF !important;
  border-color: #6FA4FF !important;
  box-shadow: 0 6px 16px rgba(11, 45, 92, 0.14) !important;
}

/* Active/Selected feel */
div.stButton > button:active,
div.stButton > button:focus,
div.stButton > button:focus-visible{
  background: #0B2D5C !important;              /* navy active */
  color: #ffffff !important;
  border-color: #0B2D5C !important;
  outline: none !important;
  box-shadow: none !important;
}

/* Center titles */
.center-title{
  color: #0B2D5C !important;
  font-weight: 900 !important;
  margin-bottom: 0 !important;
}

/* ---------- KPI Cards (premium + soothing) ---------- */
.kpi-grid{
  display:grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 14px;
  margin-top: 10px;
  margin-bottom: 10px;
}
.kpi-card{
  background: rgba(255,255,255,0.92);
  border: 1.4px solid #E3ECFA;
  border-radius: 16px;
  padding: 14px 16px;
  box-shadow: 0 8px 18px rgba(11,45,92,0.06);
}
.kpi-label{
  font-size: 13px;
  color: #64748B;
  font-weight: 750;
  margin-bottom: 6px;
}
.kpi-value{
  font-size: 30px;
  font-weight: 900;
  color: #111827;
  letter-spacing: 0.2px;
}

/* Balance featured: same bold, slight different color */
.kpi-card.balance{
  background: linear-gradient(180deg, #F1F7FF 0%, #FFFFFF 100%);
  border-color: #CFE3FF;
}
.kpi-card.balance .kpi-value{
  color:#0B2D5C; /* slight different premium navy */
}

/* Links inside cards look clean */
.kpi-link{
  text-decoration:none !important;
  color: inherit !important;
  display:block !important;
}
.kpi-link:hover .kpi-card{
  border-color:#6FA4FF;
  box-shadow: 0 10px 22px rgba(11,45,92,0.10);
}

/* Mobile */
@media (max-width: 1100px){
  .kpi-grid{ grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
</style>
""",
    unsafe_allow_html=True,
)


def render_kpi_cards(net, paid, bal, rej, acc, balance_url: str):
    """Premium KPI cards (Balance card clickable)."""
    def fmt(x):
        try:
            return f"{float(x):,.2f}"
        except Exception:
            return "—"

    html = f"""
    <div class="kpi-grid">
      <div class="kpi-card">
        <div class="kpi-label">Net Amount</div>
        <div class="kpi-value">{fmt(net)}</div>
      </div>

      <div class="kpi-card">
        <div class="kpi-label">Paid</div>
        <div class="kpi-value">{fmt(paid)}</div>
      </div>

      <a class="kpi-link" href="{balance_url}" target="_blank">
        <div class="kpi-card balance">
          <div class="kpi-label">Balance</div>
          <div class="kpi-value">{fmt(bal)}</div>
        </div>
      </a>

      <div class="kpi-card">
        <div class="kpi-label">Rejected</div>
        <div class="kpi-value">{fmt(rej)}</div>
      </div>

      <div class="kpi-card">
        <div class="kpi-label">Accepted</div>
        <div class="kpi-value">{fmt(acc)}</div>
      </div>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)


# ====================== NEW: YEAR LANDING PAGE (NEEDFUL) ======================
def reset_year_selection():
    # back to landing page
    st.session_state.rcm_year = None
    st.session_state.center_key = None
    st.session_state.year = None
    try:
        if "center" in st.query_params:
            del st.query_params["center"]
        if "year" in st.query_params:
            del st.query_params["year"]
    except Exception:
        pass
    st.rerun()


def require_year_selection():
    """
    After view password:
    Show ONLY two buttons:
      - Revenue Management Cycle 2024
      - Revenue Management Cycle 2025
    """
    if st.session_state.get("rcm_year") in (2024, 2025):
        return

    st.title("📊 Excellent Medical Group")
    st.caption("Revenue Cycle Management")
    st.markdown("### Select Report Year")

    c1, c2 = st.columns(2)
    with c1:
        if st.button("Revenue Management Cycle 2024", use_container_width=True, key="rcm_btn_2024"):
            st.session_state.rcm_year = 2024
            st.session_state.center_key = None
            st.session_state.year = 2024
            st.rerun()
    with c2:
        if st.button("Revenue Management Cycle 2025", use_container_width=True, key="rcm_btn_2025"):
            st.session_state.rcm_year = 2025
            st.session_state.center_key = None
            st.session_state.year = 2025
            st.rerun()

    st.stop()


require_year_selection()
# =================================================================

BASE = Path(__file__).parent
DATA_DIR = BASE / "data"
(DATA_DIR / "easyhealth").mkdir(parents=True, exist_ok=True)
(DATA_DIR / "excellent").mkdir(parents=True, exist_ok=True)
(DATA_DIR / "excellent_pharmacy").mkdir(parents=True, exist_ok=True)

YEARS = [2024, 2025]

# Canonical sheet names for main Aging report
SHEET_INS_TOT = "Insurance_Totals"
SHEET_SUMMARY = "Balance_Aging_Summary"
SHEET_DETAIL = "Balance_Aging_Detail"
SHEET_INGROUP = "Balance_Aging_InsGroup"  # optional tab if present
SHEET_IPLAN = "Balance_Aging_Plan"        # optional tab if present (PHARMACY uses Plan)

# Robust Grand Total match (handles 'Grand Total', 'total', spacing, case)
GT_PAT = re.compile(r'^\s*(grand\s*total|total)\s*$', re.I)


# ====================== Centers config ======================
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


# ====================== Small helpers ======================
def mtime_token(p: Path) -> float:
    try:
        return p.stat().st_mtime
    except FileNotFoundError:
        return 0.0


def _run(cmd):
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(
            "Command failed:\n"
            + " ".join(cmd)
            + "\n\nSTDOUT:\n"
            + (res.stdout or "(empty)")
            + "\n\nSTDERR:\n"
            + (res.stderr or "(empty)")
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


def resolve_source_path(folder: Path, preferred: str = "source.xlsx") -> Path:
    for p in [folder / "source.xlsb", folder / "source.xlsx", folder / "source.xlsm"]:
        if p.exists():
            return p
    return folder / preferred


def save_uploaded_source(folder: Path, upload) -> Path:
    ext = Path(upload.name).suffix.lower()
    if ext not in {".xlsb", ".xlsx", ".xlsm"}:
        raise ValueError("Please upload an .xlsb, .xlsx, or .xlsm file.")
    dst = folder / f"source{ext}"
    folder.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(upload.read())
    return dst


@st.cache_data(max_entries=6, show_spinner=False)
def get_report_bytes(path: str) -> bytes:
    return Path(path).read_bytes()


@st.cache_data(show_spinner=True)
def load_core_sheets(path: str, _token: float):
    ext = Path(path).suffix.lower()
    engine = "pyxlsb" if ext == ".xlsb" else "openpyxl"
    try:
        df_ins = pd.read_excel(path, sheet_name=SHEET_INS_TOT, engine=engine)
        df_sum = pd.read_excel(path, sheet_name=SHEET_SUMMARY, engine=engine)
        return df_ins, df_sum, [SHEET_INS_TOT, SHEET_SUMMARY]
    except Exception as e:
        try:
            names = pd.ExcelFile(path, engine=engine).sheet_names
        except Exception:
            names = []
        raise RuntimeError(
            f"Required sheets not found or failed to load. "
            f"Available: {', '.join(names) if names else '(none)'}\nOriginal error: {e}"
        )


def trim_empty_rows(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    df2 = df.dropna(how="all")
    if df2.empty:
        return df2
    blank_rows = df2.fillna("").astype(str).apply(lambda r: "".join(r).strip() == "", axis=1)
    return df2.loc[~blank_rows]


def drop_empty_insurance(df: pd.DataFrame, name_col: str = "Insurance") -> pd.DataFrame:
    if df is None or df.empty or name_col not in df.columns:
        return df
    series = df[name_col].astype(str).fillna("").str.strip()
    bad = series.str.lower().isin(["", "none", "nan", "null", "na", "-", "--"])
    keep_grand = series.str.contains("grand total", case=False, na=False)
    return df.loc[~bad | keep_grand].copy()


def ensure_grand_total(df: pd.DataFrame, name_col: str = "Insurance") -> pd.DataFrame:
    """Ensure a Grand Total/Total row exists; if not, append one computed from numeric cols."""
    if df is None or df.empty or name_col not in df.columns:
        return df
    if df[name_col].astype(str).str.match(GT_PAT).any():
        return df
    num_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    gt_vals = {c: pd.to_numeric(df[c], errors="coerce").sum() for c in num_cols}
    row = {c: "" for c in df.columns}
    row.update(gt_vals)
    row[name_col] = "Grand Total"
    return pd.concat([df, pd.DataFrame([row])], ignore_index=True)


def move_grand_total_last(df: pd.DataFrame) -> pd.DataFrame:
    """Put the (Grand) Total row at the bottom; if missing, create it first."""
    if df is None or df.empty:
        return df
    first = df.columns[0]
    if not df[first].astype(str).str.match(GT_PAT).any():
        df = ensure_grand_total(df, first)
    mask = df[first].astype(str).str.match(GT_PAT)
    body = df.loc[~mask]
    gt = df.loc[mask]
    return pd.concat([body, gt], ignore_index=True)


def drop_gt(df: pd.DataFrame) -> pd.DataFrame:
    """Drop GT/Total rows (for KPI sums only)."""
    if df is None or df.empty:
        return df
    first = df.columns[0]
    return df.loc[~df[first].astype(str).str.match(GT_PAT)]


def full_height(df, row_px: int = 45, header_px: int = 70, padding_px: int = 150) -> int:
    n = 0 if df is None else len(df)
    return header_px + (n * row_px) + padding_px


def ksum(df: pd.DataFrame, *cands):
    for col in cands:
        if col in df.columns:
            return float(pd.to_numeric(df[col], errors="coerce").sum())
    return 0.0


def is_admin_mode() -> bool:
    secret_pwd = st.secrets.get("ADMIN_PASSWORD", "")
    if secret_pwd:
        if st.session_state.get("is_admin", False):
            return True
        with st.popover("🔒 Admin login"):
            pwd = st.text_input("Password", type="password", key="admin_pwd")
            if st.button("Login", key="admin_login_btn"):
                if pwd == secret_pwd:
                    st.session_state.is_admin = True
                    st.rerun()
                else:
                    st.error("Wrong password")
        return False
    else:
        return st.toggle("Admin mode", value=st.session_state.get("is_admin", False))


# ====================== (Home KPIs helper) ======================
def pick_latest_year_with_report(cfg0: dict):
    # prefer landing-selected year first
    forced = st.session_state.get("rcm_year")
    if forced in YEARS:
        p_forced = cfg0["folder_root"] / str(forced) / cfg0["out_name"]
        if p_forced.exists():
            return forced
    # fallback to latest available
    for y in reversed(YEARS):
        p = cfg0["folder_root"] / str(y) / cfg0["out_name"]
        if p.exists():
            return y
    return None


def load_center_kpis(center_key: str):
    """
    Returns: (year, net, paid, bal, rej, acc) or (None, 0,0,0,0,0) if not found.
    Minimal: reuses existing sheet logic.
    """
    cfg0 = CENTERS[center_key]
    y = pick_latest_year_with_report(cfg0)
    if y is None:
        return None, 0.0, 0.0, 0.0, 0.0, 0.0

    outp = cfg0["folder_root"] / str(y) / cfg0["out_name"]
    tok = mtime_token(outp)
    if tok == 0.0:
        return None, 0.0, 0.0, 0.0, 0.0, 0.0

    totals, _, _ = load_core_sheets(str(outp), tok)
    totals = totals.copy()

    if "Insurance" not in totals.columns and len(totals.columns) > 0:
        totals = totals.rename(columns={totals.columns[0]: "Insurance"})

    for a in ["NetAmount", "Net amount", "Net"]:
        if a in totals.columns and "Net Amount" not in totals.columns:
            totals = totals.rename(columns={a: "Net Amount"})

    totals = trim_empty_rows(totals)
    totals = drop_empty_insurance(totals, "Insurance")
    totals = ensure_grand_total(totals, "Insurance")

    totals_no_gt = drop_gt(totals)

    net = ksum(totals_no_gt, "Net Amount", "NetAmount", "Net")
    paid = ksum(totals_no_gt, "Paid")
    bal = ksum(totals_no_gt, "Balance")
    rej = ksum(totals_no_gt, "Rejected", "Rejection")
    acc = ksum(totals_no_gt, "Accepted")
    return y, net, paid, bal, rej, acc


# ====================== Header & routing ======================
t1, t2 = st.columns([6, 2])
with t1:
    st.title("📊 Excellent Medical Group")
with t2:
    if st.button("⬅ Change Year", use_container_width=True, key="btn_change_year"):
        reset_year_selection()

st.session_state.is_admin = is_admin_mode()

qs = st.query_params
if st.session_state.get("center_key") is None and qs.get("center"):
    ck_qs = qs.get("center")
    if ck_qs in CENTERS:
        st.session_state.center_key = ck_qs

if st.session_state.get("year") is None and qs.get("year"):
    try:
        st.session_state.year = int(qs.get("year"))
    except Exception:
        pass

# default year from landing
if st.session_state.get("year") is None and st.session_state.get("rcm_year") in YEARS:
    st.session_state.year = st.session_state.get("rcm_year")

if (st.session_state.get("center_key") != st.session_state.get("last_center_key")) or \
   (st.session_state.get("year") != st.session_state.get("last_year")):
    load_core_sheets.clear()
    get_report_bytes.clear()
    st.session_state.last_center_key = st.session_state.get("center_key")
    st.session_state.last_year = st.session_state.get("year")

st.caption(
    f"Mode: **{'admin' if st.session_state.get('is_admin') else 'view'}** · "
    f"Center: **{st.session_state.get('center_key') or 'none'}** · "
    f"Year: **{st.session_state.get('year') or 'none'}**"
)

# ====================== Home cards ======================
ck = st.session_state.get("center_key")
if ck not in CENTERS:
    st.subheader("Choose a center")

    # Order: Excellent, Pharmacy, EasyHealth
    c1, c2, c3 = st.columns(3)

    with c1:
        if st.container(border=True).button(CENTERS["excellent"]["name"], use_container_width=True, key="home_exc"):
            st.session_state.center_key = "excellent"
            st.session_state.year = st.session_state.get("rcm_year")
            st.rerun()

    with c2:
        if st.container(border=True).button(CENTERS["pharmacy"]["name"], use_container_width=True, key="home_pharm"):
            st.session_state.center_key = "pharmacy"
            st.session_state.year = st.session_state.get("rcm_year")
            st.rerun()

    with c3:
        if st.container(border=True).button(CENTERS["easyhealth"]["name"], use_container_width=True, key="home_easy"):
            st.session_state.center_key = "easyhealth"
            st.session_state.year = st.session_state.get("rcm_year")
            st.rerun()

    st.markdown("---")

    st.subheader("Key metrics (All centers)")

    y_exc, net_exc, paid_exc, bal_exc, rej_exc, acc_exc = load_center_kpis("excellent")
    y_ph,  net_ph,  paid_ph,  bal_ph,  rej_ph,  acc_ph  = load_center_kpis("pharmacy")
    y_eh,  net_eh,  paid_eh,  bal_eh,  rej_eh,  acc_eh  = load_center_kpis("easyhealth")

    # 1) Excellent Medical Center
    st.markdown('<h3 class="center-title">Excellent Medical Center (MF4777)</h3>', unsafe_allow_html=True)
    st.caption(f"Year: **{y_exc if y_exc is not None else '—'}**")
    render_kpi_cards(net_exc, paid_exc, bal_exc, rej_exc, acc_exc, BALANCE_ATTEMPT_URL)
    st.markdown("---")

    # 2) Excellent Pharmacy
    st.markdown('<h3 class="center-title">Excellent Pharmacy (PF3205)</h3>', unsafe_allow_html=True)
    st.caption(f"Year: **{y_ph if y_ph is not None else '—'}**")
    render_kpi_cards(net_ph, paid_ph, bal_ph, rej_ph, acc_ph, BALANCE_ATTEMPT_URL)
    st.markdown("---")

    # 3) Easy Health
    st.markdown('<h3 class="center-title">Easy Health Medical Clinic (MF8031)</h3>', unsafe_allow_html=True)
    st.caption(f"Year: **{y_eh if y_eh is not None else '—'}**")
    render_kpi_cards(net_eh, paid_eh, bal_eh, rej_eh, acc_eh, BALANCE_ATTEMPT_URL)

    st.stop()

# ====================== MAIN aging dashboard ======================
# Show Select Year ONLY if not coming from landing
if st.session_state.get("rcm_year") is None:
    st.subheader("Select Year")
    ycols = st.columns(len(YEARS))
    for i, y in enumerate(YEARS):
        with ycols[i]:
            if st.session_state.get("year") == y:
                st.markdown(
                    f"""
                    <div style="
                      background-color:#0B2D5C;color:white;text-align:center;
                      padding:0.85em;border-radius:14px;font-weight:900;font-size:1.1em;
                      border:2px solid #0B2D5C;
                      box-shadow: 0 6px 16px rgba(11,45,92,0.18);
                    ">
                      {y}
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
            else:
                if st.button(str(y), use_container_width=True, key=f"year_btn_{y}"):
                    st.session_state.year = y
                    st.rerun()

# Pick a year automatically if none
if st.session_state.get("year") is None:
    if st.session_state.get("rcm_year") in YEARS:
        st.session_state.year = st.session_state.get("rcm_year")
        st.rerun()

    cfg_tmp = CENTERS[st.session_state.get("center_key")]
    found = None
    for y in reversed(YEARS):
        out_try = (cfg_tmp["folder_root"] / str(y) / cfg_tmp["out_name"])
        if out_try.exists():
            found = y
            break
    st.session_state.year = found or YEARS[-1]
    st.rerun()

cfg = CENTERS[st.session_state.get("center_key")]
folder = cfg["folder_root"] / str(st.session_state.get("year"))
folder.mkdir(parents=True, exist_ok=True)

src_path = resolve_source_path(folder, preferred=cfg["src_name"])
out_path = folder / cfg["out_name"]
gen_path = cfg["generator"]

# Keep URL query in sync
if (st.query_params.get("center") != st.session_state.get("center_key")) or \
   (st.query_params.get("year") != str(st.session_state.get("year"))):
    st.query_params["center"] = st.session_state.get("center_key")
    st.query_params["year"] = str(st.session_state.get("year"))

mt = mtime_token(out_path)
built = "—" if not mt else datetime.fromtimestamp(mt).strftime("%Y-%m-%d %H:%M")

# Premium center header card (soothing)
st.markdown(
    f"""
    <div style="
        background: #F5FAFF;
        border: 1.5px solid #CFE3FF;
        padding: 14px 18px;
        border-radius: 16px;
        margin-bottom: 8px;
        box-shadow: 0 6px 18px rgba(11, 45, 92, 0.08);
    ">
        <div style="font-size:26px;font-weight:900;color:#0B2D5C;">
            {cfg["name"]}
        </div>
        <div style="font-size:14px;color:#334155;margin-top:2px;font-weight:750;">
            Year: {st.session_state.get("year")}
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

st.caption(f"Built: **{built}** · Source: {src_path} · Report: {out_path.name}")

if st.button("◀ Choose another center", key="btn_back_center"):
    st.session_state.center_key = None
    st.session_state.year = st.session_state.get("rcm_year")
    try:
        if "center" in st.query_params:
            del st.query_params["center"]
        if "year" in st.query_params:
            del st.query_params["year"]
    except Exception:
        st.experimental_set_query_params()
    st.rerun()

# ===== Admin controls (unchanged) =====
if st.session_state.get("is_admin"):
    st.success("You are in **ADMIN** mode — upload/rebuild is enabled.")

    with st.expander("⬆️ Upload/replace source Excel for this year", expanded=False):
        up = st.file_uploader(
            f"Upload source Excel for {st.session_state.get('year')} (.xlsb/.xlsx/.xlsm)",
            type=["xlsb", "xlsx", "xlsm"],
            key=f"uploader_{st.session_state.get('center_key')}_{st.session_state.get('year')}",
        )
        if up:
            try:
                st.success(f"Saved to {save_uploaded_source(folder, up).name}")
            except Exception as e:
                st.error(str(e))

    if st.button("↻ Rebuild report", use_container_width=True, key=f"rebuild_{st.session_state.get('center_key')}_{st.session_state.get('year')}"):
        try:
            if not gen_path.exists():
                st.error(f"Generator not found: {gen_path}")
            elif not src_path.exists():
                st.error("No source file found. Please upload source.xlsb/.xlsx first.")
            else:
                t0 = datetime.now()
                msg = rebuild_report(gen_path, src_path, out_path)
                t1 = datetime.now()
                st.success(f"Report rebuilt successfully in {(t1 - t0).total_seconds():.1f}s.")
                if msg.strip():
                    st.code(msg, language="bash")
                load_core_sheets.clear()
                get_report_bytes.clear()
        except Exception as e:
            st.error(str(e))

# ===== Load report and render =====
token = mtime_token(out_path)
if token == 0.0:
    msg = f"Report not found for {cfg['name']} ({st.session_state.get('year')})."
    if st.session_state.get("is_admin"):
        msg += " (Upload source and click Rebuild.)"
    st.warning(msg)
    st.stop()

try:
    totals, summary, _ = load_core_sheets(str(out_path), token)
    totals = totals.copy()

    if "Insurance" not in totals.columns and len(totals.columns) > 0:
        totals = totals.rename(columns={totals.columns[0]: "Insurance"})

    for a in ["NetAmount", "Net amount", "Net"]:
        if a in totals.columns and "Net Amount" not in totals.columns:
            totals = totals.rename(columns={a: "Net Amount"})

    totals = trim_empty_rows(totals)
    totals = drop_empty_insurance(totals, "Insurance")
    totals = ensure_grand_total(totals, "Insurance")

    summary = trim_empty_rows(summary)
    if not summary.empty:
        summary = ensure_grand_total(summary, summary.columns[0])

    # Optionally load the InsGroup and Plan sheets (no errors if missing)
    ext = Path(str(out_path)).suffix.lower()
    engine = "pyxlsb" if ext == ".xlsb" else "openpyxl"

    try:
        insgroup_df = pd.read_excel(str(out_path), sheet_name=SHEET_INGROUP, engine=engine)
        insgroup_df = trim_empty_rows(insgroup_df)
    except Exception:
        insgroup_df = None

    try:
        plan_df = pd.read_excel(str(out_path), sheet_name=SHEET_IPLAN, engine=engine)
        plan_df = trim_empty_rows(plan_df)
    except Exception:
        plan_df = None

    # KPI sums should not double-count the GT row
    totals_no_gt = drop_gt(totals)

    # ===== KPI sums =====
    net = ksum(totals_no_gt, "Net Amount", "NetAmount", "Net")
    paid = ksum(totals_no_gt, "Paid")
    bal = ksum(totals_no_gt, "Balance")
    rej = ksum(totals_no_gt, "Rejected", "Rejection")
    acc = ksum(totals_no_gt, "Accepted")

    # ===== TOP KPIs (PREMIUM CARDS) =====
    st.markdown(f"### Key metrics — {st.session_state.get('year')}")
    render_kpi_cards(net, paid, bal, rej, acc, BALANCE_ATTEMPT_URL)
    st.markdown("---")

    # ===== Tabs (optional InsGroup / Plan) =====
    tab_labels = [SHEET_INS_TOT, SHEET_SUMMARY]
    if insgroup_df is not None:
        tab_labels.append(SHEET_INGROUP)
    if plan_df is not None:
        tab_labels.append(SHEET_IPLAN)
    tab_labels.append("Downloads")

    if insgroup_df is not None and st.session_state.pop("_stay_on_ig", False):
        tab_labels = [SHEET_INGROUP] + [x for x in tab_labels if x != SHEET_INGROUP]

    t_tabs = st.tabs(tab_labels)
    tab_map = {name: t for name, t in zip(tab_labels, t_tabs)}

    t1 = tab_map[SHEET_INS_TOT]
    t2 = tab_map[SHEET_SUMMARY]
    t3 = tab_map["Downloads"]
    tIG = tab_map.get(SHEET_INGROUP)
    tPL = tab_map.get(SHEET_IPLAN)

    def _display_df(df: pd.DataFrame) -> pd.DataFrame:
        d = df.drop(columns=["S.No"], errors="ignore").reset_index(drop=True)
        d.index = range(1, len(d) + 1)
        d.index.name = None
        return d

    with t1:
        st.dataframe(
            _display_df(move_grand_total_last(totals)),
            use_container_width=True,
            height=full_height(totals),
        )
        st.download_button(
            "⬇️ Export Insurance Totals (CSV)",
            totals.to_csv(index=False).encode("utf-8"),
            file_name=f"{cfg['key']}_{st.session_state.get('year')}_insurance_totals.csv",
            use_container_width=True,
            key=f"dl_csv_totals_{st.session_state.get('center_key')}_{st.session_state.get('year')}",
        )

    with t2:
        st.dataframe(
            _display_df(move_grand_total_last(summary)),
            use_container_width=True,
            height=full_height(summary),
        )
        st.download_button(
            "⬇️ Export Summary (CSV)",
            summary.to_csv(index=False).encode("utf-8"),
            file_name=f"{cfg['key']}_{st.session_state.get('year')}_summary.csv",
            use_container_width=True,
            key=f"dl_csv_summary_{st.session_state.get('center_key')}_{st.session_state.get('year')}",
        )

    if tIG is not None and insgroup_df is not None:
        with tIG:
            insurers = (
                insgroup_df["Insurance"]
                .dropna()
                .astype(str)
                .loc[lambda s: ~s.str.match(GT_PAT)]
                .sort_values()
                .unique()
                .tolist()
            )
            ig_key = f"insgroup_select_{st.session_state.get('center_key')}_{st.session_state.get('year')}"

            with st.form(key=f"ig_form_{st.session_state.get('center_key')}_{st.session_state.get('year')}"):
                choice = st.selectbox(
                    "Filter by Insurance",
                    ["All"] + insurers,
                    index=(["All"] + insurers).index(st.session_state.get(ig_key, "All")),
                )
                apply_btn = st.form_submit_button("Apply")

            if apply_btn:
                st.session_state[ig_key] = choice
                st.session_state["_stay_on_ig"] = True
                st.rerun()

            choice = st.session_state.get(ig_key, "All")
            view_df = insgroup_df.copy()
            if choice != "All":
                view_df = (
                    view_df.loc[view_df["Insurance"].astype(str) == choice]
                    .drop(columns=["Insurance"], errors="ignore")
                )

            st.caption(f"Showing InsGroup aging for **{choice}**")
            st.dataframe(
                _display_df(move_grand_total_last(view_df)),
                use_container_width=True,
                height=full_height(view_df),
            )
            st.download_button(
                "⬇️ Export InsGroup (CSV) — current view",
                view_df.to_csv(index=False).encode("utf-8"),
                file_name=f"{cfg['key']}_{st.session_state.get('year')}_insgroup{'_' + choice if choice != 'All' else ''}.csv",
                use_container_width=True,
                key=f"dl_csv_insgroup_view_{st.session_state.get('center_key')}_{st.session_state.get('year')}",
            )

    if tPL is not None and plan_df is not None:
        with tPL:
            insurers_pl = (
                plan_df["Insurance"]
                .dropna()
                .astype(str)
                .loc[lambda s: ~s.str.match(GT_PAT)]
                .sort_values()
                .unique()
                .tolist()
            )
            pl_key = f"plan_select_{st.session_state.get('center_key')}_{st.session_state.get('year')}"

            with st.form(key=f"pl_form_{st.session_state.get('center_key')}_{st.session_state.get('year')}"):
                choice_pl = st.selectbox(
                    "Filter by Insurance",
                    ["All"] + insurers_pl,
                    index=(["All"] + insurers_pl).index(st.session_state.get(pl_key, "All")),
                )
                apply_btn_pl = st.form_submit_button("Apply")

            if apply_btn_pl:
                st.session_state[pl_key] = choice_pl
                st.rerun()

            choice_pl = st.session_state.get(pl_key, "All")
            view_pl = plan_df.copy()
            if choice_pl != "All":
                view_pl = (
                    view_pl.loc[view_pl["Insurance"].astype(str) == choice_pl]
                    .drop(columns=["Insurance"], errors="ignore")
                )

            st.caption(f"Showing Plan aging for **{choice_pl}**")
            st.dataframe(
                _display_df(move_grand_total_last(view_pl)),
                use_container_width=True,
                height=full_height(view_pl),
            )
            st.download_button(
                "⬇️ Export Plan (CSV) — current view",
                view_pl.to_csv(index=False).encode("utf-8"),
                file_name=f"{cfg['key']}_{st.session_state.get('year')}_plan{'_' + choice_pl if choice_pl != 'All' else ''}.csv",
                use_container_width=True,
                key=f"dl_csv_plan_view_{st.session_state.get('center_key')}_{st.session_state.get('year')}",
            )

    with t3:
        st.markdown("### Report Download")
        st.write("Open the XLSX locally to inspect **Balance_Aging_Detail** if needed.")
        st.download_button(
            "⬇️ Download full report (.xlsx)",
            get_report_bytes(str(out_path)),
            file_name=out_path.name,
            use_container_width=True,
            key=f"dl_xlsx_full_{st.session_state.get('center_key')}_{st.session_state.get('year')}",
        )

except Exception as e:
    try:
        ext = Path(str(out_path)).suffix.lower()
        eng = "pyxlsb" if ext == ".xlsb" else "openpyxl"
        names = pd.ExcelFile(str(out_path), engine=eng).sheet_names
    except Exception:
        names = []
    st.error(f"{e}\n\nAvailable sheets: {', '.join(names) if names else '(none)'}")
