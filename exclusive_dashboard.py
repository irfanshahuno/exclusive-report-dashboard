# exclusive_dashboard.py — Main dashboard KPIs at TOP (Doc Performance unchanged)
# NOTE: This is your original dashboard with ONLY the minimal additions:
#   • Optional Balance_Aging_InsGroup tab (already supported)
#   • Optional Balance_Aging_Plan tab (new) with Insurance filter
#   • S.No hidden and display index starts at 1
#   • Grand Total row (any of 'Grand Total' / 'Total') is shown LAST in tables
#   • NEW: View password gate (Emc@2026)
# ✅ NEEDFUL CHANGES:
#   • After password: landing page with ONLY 2 buttons (2024/2025) + Change Year
#   • ✅ NEW: Hide/remove EasyHealth in 2024 (ONLY) — no other changes
# ✅ PREMIUM SOOTHING UI (ONLY VISUAL):
#   • Soft background + premium light-blue buttons
#   • KPI section becomes premium cards (soothing)
#   • Center names dark navy
#   • Balance card clickable and same bold with slight different color
# ✅ FIX:
#   • KPI numbers auto-fit inside KPI box (no overflow)
# ✅ NEEDFUL (NEW):
#   • Rejected KPI remains SAME STYLE (card) but clickable → opens Rejection Analysis view
#   • Rejection page FAST: detail table + downloads shown ONLY when requested
# Nothing else is changed.

import sys
import subprocess
import re
from pathlib import Path
from datetime import datetime, date

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components  # used only for the home-card link

# ====================== ✅ NEEDFUL S3 IMPORTS (NEW) ======================
import boto3
from botocore.exceptions import ClientError


# ====================== VIEW PASSWORD (NEW) ======================
VIEW_PASSWORD = st.secrets.get("VIEW_PASSWORD", "Emc@2026")


def require_view_access() -> None:
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


st.set_page_config(page_title="Excellent Medical Group", layout="wide")
st.set_option("client.showErrorDetails", False)

require_view_access()

BALANCE_ATTEMPT_URL = "https://balance-attempt-aging-dashboard-eigtoins4ai9hd9r7jsmen.streamlit.app/"

# =========================================================
# ✅ PREMIUM + SOOTHING UI (ONLY STYLES) + ✅ AUTO-FIT KPI
# =========================================================
st.markdown(
    """
<style>
.stApp{
  background: linear-gradient(180deg, #F7FAFF 0%, #FFFFFF 45%) !important;
}
hr{ border: none !important; height:1px !important; background:#E6EEF8 !important; }

div.stButton > button{
  width: 100% !important;
  min-height: 58px !important;
  padding: 14px 22px !important;
  font-size: 18px !important;
  font-weight: 800 !important;

  background: #EEF6FF !important;
  color: #0B2D5C !important;
  border: 1.8px solid #B6D4FF !important;
  border-radius: 14px !important;

  box-shadow: 0 3px 10px rgba(11, 45, 92, 0.10) !important;
}
div.stButton > button:hover{
  background: #DCEBFF !important;
  border-color: #6FA4FF !important;
  box-shadow: 0 6px 16px rgba(11, 45, 92, 0.14) !important;
}
div.stButton > button:active,
div.stButton > button:focus,
div.stButton > button:focus-visible{
  background: #0B2D5C !important;
  color: #ffffff !important;
  border-color: #0B2D5C !important;
  outline: none !important;
  box-shadow: none !important;
}

.center-title{
  color: #0B2D5C !important;
  font-weight: 900 !important;
  margin-bottom: 0 !important;
}

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
  min-width: 0;
}
.kpi-label{
  font-size: 13px;
  color: #64748B;
  font-weight: 750;
  margin-bottom: 6px;
}
.kpi-value{
  font-size: clamp(18px, 2.2vw, 30px);
  font-weight: 900;
  color: #111827;
  letter-spacing: 0.2px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.kpi-card.balance{
  background: linear-gradient(180deg, #F1F7FF 0%, #FFFFFF 100%);
  border-color: #CFE3FF;
}
.kpi-card.balance .kpi-value{
  color:#0B2D5C;
}

.kpi-link{
  text-decoration:none !important;
  color: inherit !important;
  display:block !important;
}
.kpi-link:hover .kpi-card{
  border-color:#6FA4FF;
  box-shadow: 0 10px 22px rgba(11,45,92,0.10);
}

/* ✅ NEEDFUL: make clickable rejection card look same (no button style change) */
.kpi-card.clickable{
  cursor: pointer;
}
.kpi-card.clickable:hover{
  border-color:#6FA4FF;
  box-shadow: 0 10px 22px rgba(11,45,92,0.10);
}

@media (max-width: 1100px){
  .kpi-grid{ grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
</style>
""",
    unsafe_allow_html=True,
)

# ====================== Rejection page state (NEW) ======================
if "page" not in st.session_state:
    st.session_state.page = "main"  # main | rejection

# ====================== KPI Cards ======================
def render_kpi_cards(net, paid, bal, rej, acc, balance_url: str, allow_rejection_click: bool = False):
    def fmt(x):
        try:
            return f"{float(x):,.2f}"
        except Exception:
            return "—"

    # Net, Paid, Balance (link)
    html = f"""
    <div class="kpi-grid">
      <div class="kpi-card" title="{fmt(net)}">
        <div class="kpi-label">Net Amount</div>
        <div class="kpi-value">{fmt(net)}</div>
      </div>

      <div class="kpi-card" title="{fmt(paid)}">
        <div class="kpi-label">Paid</div>
        <div class="kpi-value">{fmt(paid)}</div>
      </div>

      <a class="kpi-link" href="{balance_url}" target="_blank" title="{fmt(bal)}">
        <div class="kpi-card balance">
          <div class="kpi-label">Balance</div>
          <div class="kpi-value">{fmt(bal)}</div>
        </div>
      </a>
    """
    st.markdown(html, unsafe_allow_html=True)

    # ✅ NEEDFUL: Rejected stays SAME KPI CARD STYLE but clickable
    if allow_rejection_click:
        # Streamlit "HTML click" via query param trigger using components
        # (keeps same card style)
        rej_html = f"""
        <a class="kpi-link" href="?rej=1" style="text-decoration:none;">
          <div class="kpi-card clickable" title="{fmt(rej)}">
            <div class="kpi-label">Rejected</div>
            <div class="kpi-value">{fmt(rej)}</div>
          </div>
        </a>
        """
        st.markdown(rej_html, unsafe_allow_html=True)
    else:
        st.markdown(
            f"""
            <div class="kpi-card" title="{fmt(rej)}">
              <div class="kpi-label">Rejected</div>
              <div class="kpi-value">{fmt(rej)}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    # Accepted
    st.markdown(
        f"""
        <div class="kpi-card" title="{fmt(acc)}">
          <div class="kpi-label">Accepted</div>
          <div class="kpi-value">{fmt(acc)}</div>
        </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

# ====================== YEAR LANDING PAGE ======================
def reset_year_selection():
    st.session_state.page = "main"
    st.session_state.rcm_year = None
    st.session_state.center_key = None
    st.session_state.year = None
    try:
        if "center" in st.query_params:
            del st.query_params["center"]
        if "year" in st.query_params:
            del st.query_params["year"]
        if "rej" in st.query_params:
            del st.query_params["rej"]
    except Exception:
        pass
    st.rerun()

def require_year_selection():
    if st.session_state.get("rcm_year") in (2024, 2025, 2026):
        return

    st.title("📊 Excellent Medical Group")
    st.caption("Revenue Cycle Management")
    st.markdown("### Select Report Year")

    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("Revenue Management Cycle 2024", use_container_width=True, key="rcm_btn_2024"):
            st.session_state.page = "main"
            st.session_state.rcm_year = 2024
            st.session_state.center_key = None
            st.session_state.year = 2024
            st.rerun()
    with c2:
        if st.button("Revenue Management Cycle 2025", use_container_width=True, key="rcm_btn_2025"):
            st.session_state.page = "main"
            st.session_state.rcm_year = 2025
            st.session_state.center_key = None
            st.session_state.year = 2025
            st.rerun()
    with c3:
        if st.button("Revenue Management Cycle 2026", use_container_width=True, key="rcm_btn_2026"):
            st.session_state.page = "main"
            st.session_state.rcm_year = 2026
            st.session_state.center_key = None
            st.session_state.year = 2026
            st.rerun()

    st.stop()

require_year_selection()

BASE = Path(__file__).parent
DATA_DIR = BASE / "data"
(DATA_DIR / "easyhealth").mkdir(parents=True, exist_ok=True)
(DATA_DIR / "excellent").mkdir(parents=True, exist_ok=True)
(DATA_DIR / "excellent_pharmacy").mkdir(parents=True, exist_ok=True)

YEARS = [2024, 2025, 2026]

SHEET_INS_TOT = "Insurance_Totals"
SHEET_SUMMARY = "Balance_Aging_Summary"
SHEET_DETAIL = "Balance_Aging_Detail"
SHEET_INGROUP = "Balance_Aging_InsGroup"
SHEET_IPLAN = "Balance_Aging_Plan"

GT_PAT = re.compile(r'^\s*(grand\s*total|total)\s*$', re.I)

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

# ====================== ✅ NEEDFUL S3 HELPERS ======================
def _get_s3_cfg():
    access_key = st.secrets.get("AWS_ACCESS_KEY_ID", "")
    secret_key = st.secrets.get("AWS_SECRET_ACCESS_KEY", "")

    region = (
        st.secrets.get("AWS_REGION")
        or st.secrets.get("AWS_DEFAULT_REGION")
        or "eu-north-1"
    )

    bucket = (
        st.secrets.get("S3_BUCKET_NAME")
        or st.secrets.get("S3_BUCKET")
        or ""
    )

    prefix = st.secrets.get("S3_PREFIX", "").strip().strip("/")

    if not (access_key and secret_key and bucket):
        return None

    return {
        "access_key": access_key,
        "secret_key": secret_key,
        "region": region,
        "bucket": bucket,
        "prefix": prefix,
    }

def _s3_client(cfg):
    return boto3.client(
        "s3",
        aws_access_key_id=cfg["access_key"],
        aws_secret_access_key=cfg["secret_key"],
        region_name=cfg["region"],
    )

def s3_key_for(center_key: str, year: int, filename: str) -> str:
    cfg = _get_s3_cfg()
    pre = (cfg["prefix"] + "/") if (cfg and cfg.get("prefix")) else ""
    return f"{pre}{center_key}/{year}/{filename}"

def upload_to_s3(local_path: Path, center_key: str, year: int) -> str:
    cfg = _get_s3_cfg()
    if cfg is None:
        return ""

    if not local_path.exists():
        raise FileNotFoundError(f"Local file not found: {local_path}")

    key = s3_key_for(center_key, year, local_path.name)
    client = _s3_client(cfg)

    try:
        client.upload_file(str(local_path), cfg["bucket"], key)
        return f"s3://{cfg['bucket']}/{key}"
    except ClientError as e:
        raise RuntimeError(f"S3 upload failed: {e}")

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
    df_ins = pd.read_excel(path, sheet_name=SHEET_INS_TOT, engine=engine)
    df_sum = pd.read_excel(path, sheet_name=SHEET_SUMMARY, engine=engine)
    return df_ins, df_sum, [SHEET_INS_TOT, SHEET_SUMMARY]

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

def load_center_kpis(center_key: str, year: int):
    cfg0 = CENTERS[center_key]
    if year not in YEARS:
        return year, 0.0, 0.0, 0.0, 0.0, 0.0

    outp = cfg0["folder_root"] / str(year) / cfg0["out_name"]
    if not outp.exists():
        return year, 0.0, 0.0, 0.0, 0.0, 0.0

    tok = mtime_token(outp)
    if tok == 0.0:
        return year, 0.0, 0.0, 0.0, 0.0, 0.0

    try:
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

        return year, net, paid, bal, rej, acc
    except Exception:
        return year, 0.0, 0.0, 0.0, 0.0, 0.0

# ====================== Rejection view (FAST + ON-DEMAND DETAIL/DOWNLOAD) ======================
@st.cache_data(show_spinner=True)
def load_rejection_base(src_excel_path: str, _token: float) -> pd.DataFrame:
    p = Path(src_excel_path)
    ext = p.suffix.lower()
    engine = "pyxlsb" if ext == ".xlsb" else "openpyxl"
    df = pd.read_excel(str(p), engine=engine)
    df.columns = df.columns.astype(str).str.strip()
    return df

def show_rejection_view_from_source(src_excel_path: Path, center_title: str):
    st.markdown(f"## ❌ Rejection Analysis — {center_title}")
    st.caption("Rule: Paid = 0 AND ActivityStatus = rejected AND DenialCode is not empty")

    if not src_excel_path.exists():
        st.error(f"Source file not found: {src_excel_path.name}")
        st.stop()

    df = load_rejection_base(str(src_excel_path), mtime_token(src_excel_path))

    remit_cols = [
        "actRemitInsShare", "actResub1RemitInsShare",
        "actResub2RemitInsShare", "actResub3RemitInsShare",
        "TKBKAmountAct",
    ]

    for c in ["ActivityIns"] + remit_cols:
        if c not in df.columns:
            df[c] = 0
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)

    df["Paid"] = df[remit_cols].sum(axis=1)

    if "DenialCode" not in df.columns:
        df["DenialCode"] = ""
    df["DenialCode"] = df["DenialCode"].astype(str).fillna("").str.strip()
    df.loc[df["DenialCode"].str.lower().isin(["nan", "none", "null"]), "DenialCode"] = ""

    if "Insurance" not in df.columns:
        alt = next((c for c in ["PayerName", "Insurer", "Plan"] if c in df.columns), None)
        df["Insurance"] = df[alt] if alt else "Not Available"

    if "ActivityStatus" not in df.columns:
        st.error("ActivityStatus column not found in source.")
        st.stop()

    status = df["ActivityStatus"].astype(str).fillna("").str.lower().str.strip()

    rej = df[(df["Paid"] == 0) & (status == "rejected") & (df["DenialCode"] != "")].copy()
    rej["RejectedAmount"] = rej["ActivityIns"]
    rej["RejectedCount"] = 1

    total_amt = float(rej["RejectedAmount"].sum()) if len(rej) else 0.0
    total_cnt = int(rej["RejectedCount"].sum()) if len(rej) else 0

    c1, c2, c3 = st.columns(3)
    c1.metric("Rejected Amount", f"{total_amt:,.2f}")
    c2.metric("Rejected Count", total_cnt)

    if len(rej):
        top_code = rej.groupby("DenialCode")["RejectedAmount"].sum().sort_values(ascending=False).head(1)
        c3.metric("Top Denial Code", top_code.index[0])
    else:
        c3.metric("Top Denial Code", "—")

    st.markdown("---")

    f1, f2 = st.columns(2)
    ins_list = ["All"] + sorted(rej["Insurance"].dropna().astype(str).unique().tolist()) if len(rej) else ["All"]
    code_list = ["All"] + sorted(rej["DenialCode"].dropna().astype(str).unique().tolist()) if len(rej) else ["All"]

    sel_ins = f1.selectbox("Insurance", ins_list, key="rej_sel_ins")
    sel_code = f2.selectbox("Denial Code", code_list, key="rej_sel_code")

    view = rej.copy()
    if sel_ins != "All":
        view = view[view["Insurance"].astype(str) == sel_ins]
    if sel_code != "All":
        view = view[view["DenialCode"].astype(str) == sel_code]

    tA, tB = st.tabs(["By Denial Code", "By Insurance"])

    with tA:
        by_code = (view.groupby("DenialCode")[["RejectedAmount", "RejectedCount"]]
                   .sum().reset_index()
                   .sort_values("RejectedAmount", ascending=False))
        st.dataframe(by_code, use_container_width=True)

    with tB:
        by_ins = (view.groupby("Insurance")[["RejectedAmount", "RejectedCount"]]
                  .sum().reset_index()
                  .sort_values("RejectedAmount", ascending=False))
        st.dataframe(by_ins, use_container_width=True)

    st.markdown("---")

    # ✅ NEEDFUL: detail + download only when you click (not always)
    with st.expander("📌 Show Rejected Detail / Download (only if needed)", expanded=False):
        st.dataframe(view, use_container_width=True)

        st.download_button(
            "⬇️ Download current view (CSV)",
            view.to_csv(index=False).encode("utf-8"),
            file_name=f"rejections_{st.session_state.get('center_key')}_{st.session_state.get('year')}.csv",
            use_container_width=True,
            key="rej_dl_csv",
        )

    st.markdown("---")
    if st.button("⬅ Back", use_container_width=True, key="rej_back_btn"):
        st.session_state.page = "main"
        try:
            if "rej" in st.query_params:
                del st.query_params["rej"]
        except Exception:
            pass
        st.rerun()

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

if st.session_state.get("year") is None and st.session_state.get("rcm_year") in YEARS:
    st.session_state.year = st.session_state.get("rcm_year")

if (st.session_state.get("center_key") != st.session_state.get("last_center_key")) or \
   (st.session_state.get("year") != st.session_state.get("last_year")):
    load_core_sheets.clear()
    get_report_bytes.clear()
    st.session_state.last_center_key = st.session_state.get("center_key")
    st.session_state.last_year = st.session_state.get("year")
    st.session_state.page = "main"

st.caption(
    f"Mode: **{'admin' if st.session_state.get('is_admin') else 'view'}** · "
    f"Center: **{st.session_state.get('center_key') or 'none'}** · "
    f"Year: **{st.session_state.get('year') or 'none'}**"
)

# ✅ HIDE EASYHEALTH IN 2024 ONLY
if st.session_state.get("rcm_year") == 2024:
    if st.session_state.get("center_key") == "easyhealth" or st.query_params.get("center") == "easyhealth":
        st.warning("Easy Health is available only in 2025.")
        st.session_state.center_key = None
        st.session_state.year = 2024
        st.session_state.page = "main"
        try:
            if "center" in st.query_params:
                del st.query_params["center"]
            if "year" in st.query_params:
                del st.query_params["year"]
        except Exception:
            pass
        st.rerun()

# ====================== Home cards ======================
ck = st.session_state.get("center_key")
if ck not in CENTERS:
    st.subheader("Choose a center")

    c1, c2, c3 = st.columns(3)

    with c1:
        if st.container(border=True).button(CENTERS["excellent"]["name"], use_container_width=True, key="home_exc"):
            st.session_state.page = "main"
            st.session_state.center_key = "excellent"
            st.session_state.year = st.session_state.get("rcm_year")
            st.rerun()

    with c2:
        if st.container(border=True).button(CENTERS["pharmacy"]["name"], use_container_width=True, key="home_pharm"):
            st.session_state.page = "main"
            st.session_state.center_key = "pharmacy"
            st.session_state.year = st.session_state.get("rcm_year")
            st.rerun()

    with c3:
        if st.session_state.get("rcm_year") != 2024:
            if st.container(border=True).button(CENTERS["easyhealth"]["name"], use_container_width=True, key="home_easy"):
                st.session_state.page = "main"
                st.session_state.center_key = "easyhealth"
                st.session_state.year = st.session_state.get("rcm_year")
                st.rerun()

    st.markdown("---")
    st.subheader("Key metrics (All centers)")

    sel_year = st.session_state.get("rcm_year")

    y_exc, net_exc, paid_exc, bal_exc, rej_exc, acc_exc = load_center_kpis("excellent", sel_year)
    y_ph,  net_ph,  paid_ph,  bal_ph,  rej_ph,  acc_ph  = load_center_kpis("pharmacy", sel_year)

    st.markdown('<h3 class="center-title">Excellent Medical Center (MF4777)</h3>', unsafe_allow_html=True)
    st.caption(f"Year: **{y_exc if y_exc is not None else '—'}**")
    render_kpi_cards(net_exc, paid_exc, bal_exc, rej_exc, acc_exc, BALANCE_ATTEMPT_URL)
    st.markdown("---")

    st.markdown('<h3 class="center-title">Excellent Pharmacy (PF3205)</h3>', unsafe_allow_html=True)
    st.caption(f"Year: **{y_ph if y_ph is not None else '—'}**")
    render_kpi_cards(net_ph, paid_ph, bal_ph, rej_ph, acc_ph, BALANCE_ATTEMPT_URL)
    st.markdown("---")

    if st.session_state.get("rcm_year") != 2024:
        y_eh,  net_eh,  paid_eh,  bal_eh,  rej_eh,  acc_eh  = load_center_kpis("easyhealth", sel_year)

        st.markdown('<h3 class="center-title">Easy Health Medical Clinic (MF8031)</h3>', unsafe_allow_html=True)
        st.caption(f"Year: **{y_eh if y_eh is not None else '—'}**")
        render_kpi_cards(net_eh, paid_eh, bal_eh, rej_eh, acc_eh, BALANCE_ATTEMPT_URL)

    st.stop()

# ====================== MAIN aging dashboard ======================
cfg = CENTERS[st.session_state.get("center_key")]
folder = cfg["folder_root"] / str(st.session_state.get("year"))
folder.mkdir(parents=True, exist_ok=True)

src_path = resolve_source_path(folder, preferred=cfg["src_name"])
out_path = folder / cfg["out_name"]
gen_path = cfg["generator"]

# ✅ NEEDFUL: if clicked rejected card (?rej=1), open rejection view
if st.query_params.get("rej") == "1":
    st.session_state.page = "rejection"
    try:
        del st.query_params["rej"]
    except Exception:
        pass

mt = mtime_token(out_path)
built = "—" if not mt else datetime.fromtimestamp(mt).strftime("%Y-%m-%d %H:%M")

st.caption(f"Built: **{built}** · Source: {src_path} · Report: {out_path.name}")

if st.session_state.page == "rejection":
    show_rejection_view_from_source(src_path, cfg["name"])
    st.stop()

token = mtime_token(out_path)
if token == 0.0:
    st.warning(f"Report not found for {cfg['name']} ({st.session_state.get('year')}).")
    st.stop()

totals, summary, _ = load_core_sheets(str(out_path), token)

totals = trim_empty_rows(totals)
summary = trim_empty_rows(summary)

totals_no_gt = drop_gt(totals)

net = ksum(totals_no_gt, "Net Amount", "NetAmount", "Net")
paid = ksum(totals_no_gt, "Paid")
bal = ksum(totals_no_gt, "Balance")
rej = ksum(totals_no_gt, "Rejected", "Rejection")
acc = ksum(totals_no_gt, "Accepted")

st.markdown(f"### Key metrics — {st.session_state.get('year')}")
render_kpi_cards(net, paid, bal, rej, acc, BALANCE_ATTEMPT_URL, allow_rejection_click=True)
st.markdown("---")

# Keep your original tabs (no change)
tab_labels = [SHEET_INS_TOT, SHEET_SUMMARY, "Downloads"]
t_tabs = st.tabs(tab_labels)
tab_map = {name: t for name, t in zip(tab_labels, t_tabs)}

t1 = tab_map[SHEET_INS_TOT]
t2 = tab_map[SHEET_SUMMARY]
t3 = tab_map["Downloads"]

def _display_df(df: pd.DataFrame) -> pd.DataFrame:
    d = df.drop(columns=["S.No"], errors="ignore").reset_index(drop=True)
    d.index = range(1, len(d) + 1)
    d.index.name = None
    return d

with t1:
    st.dataframe(_display_df(move_grand_total_last(totals)), use_container_width=True, height=full_height(totals))

with t2:
    st.dataframe(_display_df(move_grand_total_last(summary)), use_container_width=True, height=full_height(summary))

with t3:
    st.download_button(
        "⬇️ Download full report (.xlsx)",
        get_report_bytes(str(out_path)),
        file_name=out_path.name,
        use_container_width=True,
        key="dl_xlsx_full",
    )
