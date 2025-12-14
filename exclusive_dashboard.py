# exclusive_dashboard.py — CRASH-SAFE LITE
import sys
import subprocess
from pathlib import Path
from datetime import datetime
import pandas as pd
import streamlit as st

# =========================== Page & Folders ===========================
st.set_page_config(page_title="Exclusive Report with Aging — Dashboard", layout="wide")

BASE = Path(__file__).parent
DATA_DIR = BASE / "data"
(DATA_DIR / "easyhealth").mkdir(parents=True, exist_ok=True)
(DATA_DIR / "excellent").mkdir(parents=True, exist_ok=True)
(DATA_DIR / "excellent_pharmacy").mkdir(parents=True, exist_ok=True)

YEARS = [2024, 2025]

# =========================== External Doc Perf App ===========================
DOC_PERF_URL = "https://doctor-performance-app-tjwqgmptk8fbo57t4qrfqr.streamlit.app/"

# =========================== Helpers ===========================
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

def resolve_source_path(folder: Path, preferred="source.xlsx") -> Path:
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
        df_ins = pd.read_excel(path, sheet_name="Insurance_Totals", engine=engine)
        df_sum = pd.read_excel(path, sheet_name="Balance_Aging_Summary", engine=engine)
        return df_ins, df_sum
    except Exception as e:
        try:
            names = pd.ExcelFile(path, engine=engine).sheet_names
        except Exception:
            names = []
        raise RuntimeError(f"Sheets not found. Available: {', '.join(names)}\nError: {e}")

def trim_empty_rows(df):
    if df is None or df.empty:
        return df
    df2 = df.dropna(how="all")
    if df2.empty:
        return df2
    blank_rows = df2.fillna("").astype(str).apply(lambda r: "".join(r).strip() == "", axis=1)
    return df2.loc[~blank_rows]

def drop_empty_insurance(df, name_col="Insurance"):
    if df is None or df.empty or name_col not in df.columns:
        return df
    s = df[name_col].astype(str).fillna("").str.strip()
    bad = s.str.lower().isin(["", "none", "nan", "null", "na", "-", "--"])
    keep = s.str.contains("grand total", case=False, na=False)
    return df.loc[~bad | keep].copy()

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

def ksum(df, *cols):
    for c in cols:
        if c in df.columns:
            return float(pd.to_numeric(df[c], errors="coerce").sum())
    return 0.0

def is_admin_mode():
    secret = st.secrets.get("ADMIN_PASSWORD", "")
    if secret:
        if st.session_state.get("is_admin", False):
            return True
        with st.popover("🔒 Admin login"):
            pwd = st.text_input("Password", type="password")
            if st.button("Login"):
                if pwd == secret:
                    st.session_state.is_admin = True
                    st.rerun()
                else:
                    st.error("Wrong password")
        return False
    else:
        return st.toggle("Admin mode", value=st.session_state.get("is_admin", False))

# =========================== Dashboard ===========================
st.title("📊 Exclusive Report with Aging — Dashboard")
st.session_state.is_admin = is_admin_mode()

st.caption("Choose a center to view or rebuild reports.")

CENTERS = {
    "easyhealth": {
        "name": "Easy Health Medical Clinic (MF8031)",
        "folder": DATA_DIR / "easyhealth",
        "gen": BASE / "exclusive_report_with_aging_final.py",
        "out": "report.xlsx",
    },
    "excellent": {
        "name": "Excellent Medical Center (MF4777)",
        "folder": DATA_DIR / "excellent",
        "gen": BASE / "exclusive_report_with_aging_final.py",
        "out": "report.xlsx",
    },
    "pharmacy": {
        "name": "Excellent Pharmacy (PF3205)",
        "folder": DATA_DIR / "excellent_pharmacy",
        "gen": BASE / "pharmacy_exclusive_report_with_aging.py",
        "out": "Pharmacy_Exclusive_Report_with_Aging.xlsx",
    },
}

if "center_key" not in st.session_state:
    st.session_state.center_key = None

if st.session_state.center_key not in CENTERS:
    st.subheader("Choose a center")
    c1, c2, c3, c4 = st.columns(4)
    if c1.button(CENTERS["easyhealth"]["name"], use_container_width=True):
        st.session_state.center_key = "easyhealth"
        st.rerun()
    if c2.button(CENTERS["excellent"]["name"], use_container_width=True):
        st.session_state.center_key = "excellent"
        st.rerun()
    if c3.button(CENTERS["pharmacy"]["name"], use_container_width=True):
        st.session_state.center_key = "pharmacy"
        st.rerun()
    with c4:
        st.markdown(
            f"""
            <a href="{DOC_PERF_URL}" target="_blank" style="text-decoration:none;">
              <button style="
                  border:2px solid #e5e7eb;
                  border-radius:14px;
                  padding:18px 14px;
                  width:100%;
                  font-weight:600;
                  text-align:center;
                  background-color:white;
                  color:black;
                  cursor:pointer;
                  box-shadow:0 2px 6px rgba(0,0,0,0.05);
              "
              onmouseover="this.style.borderColor='#60a5fa'; this.style.boxShadow='0 6px 16px rgba(37,99,235,0.15)'"
              onmouseout="this.style.borderColor='#e5e7eb'; this.style.boxShadow='0 2px 6px rgba(0,0,0,0.05)'">
                Doc monthly performance
              </button>
            </a>
            """,
            unsafe_allow_html=True,
        )
    st.stop()

ck = st.session_state.center_key
cfg = CENTERS[ck]
st.subheader(cfg["name"])

folder = cfg["folder"] / str(YEARS[-1])
folder.mkdir(parents=True, exist_ok=True)
src_path = resolve_source_path(folder)
out_path = folder / cfg["out"]
gen_path = cfg["gen"]

if st.session_state.is_admin:
    st.success("Admin mode: upload or rebuild.")
    up = st.file_uploader("Upload Excel file", type=["xlsb", "xlsx", "xlsm"])
    if up:
        save_uploaded_source(folder, up)
        st.success("Uploaded.")
    if st.button("Rebuild report"):
        if gen_path.exists() and src_path.exists():
            msg = rebuild_report(gen_path, src_path, out_path)
            st.success("Report rebuilt successfully.")
            if msg.strip():
                st.code(msg)
        else:
            st.error("Missing generator or source file.")

token = mtime_token(out_path)
if token == 0.0:
    st.warning("Report not found.")
    st.stop()

try:
    totals, summary = load_core_sheets(str(out_path), token)
    totals = trim_empty_rows(drop_empty_insurance(ensure_grand_total(totals)))
    summary = trim_empty_rows(ensure_grand_total(summary))
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Net", f"{ksum(totals, 'Net Amount', 'NetAmount', 'Net'):,.2f}")
    c2.metric("Paid", f"{ksum(totals, 'Paid'):,.2f}")
    c3.metric("Balance", f"{ksum(totals, 'Balance'):,.2f}")
    c4.metric("Rejected", f"{ksum(totals, 'Rejected', 'Rejection'):,.2f}")
    st.dataframe(totals, use_container_width=True)
except Exception as e:
    st.error(str(e))
