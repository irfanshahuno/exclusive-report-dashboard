# exclusive_dashboard.py (with top-level Doc monthly performance)
import sys
import subprocess
from pathlib import Path
from datetime import datetime
import pandas as pd
import streamlit as st
from io import BytesIO

# ==================== page setup ====================
st.set_page_config(page_title="Exclusive Report with Aging — Dashboard", layout="wide")
st.set_option("client.showErrorDetails", False)

BASE = Path(__file__).parent
DATA_DIR = BASE / "data"
(DATA_DIR / "easyhealth").mkdir(parents=True, exist_ok=True)
(DATA_DIR / "excellent").mkdir(parents=True, exist_ok=True)
(DATA_DIR / "excellent_pharmacy").mkdir(parents=True, exist_ok=True)

CENTERS = {
    "easyhealth": {
        "name": "Easy Health Medical Clinic (MF8031)",
        "folder_root": DATA_DIR / "easyhealth",
        "src_name": "source.xlsx",
        "out_name": "report.xlsx",
        "generator": BASE / "exclusive_report_with_aging_final.py",
    },
    "excellent": {
        "name": "Excellent Medical Center (MF4777)",
        "folder_root": DATA_DIR / "excellent",
        "src_name": "source.xlsx",
        "out_name": "report.xlsx",
        "generator": BASE / "exclusive_report_with_aging_final.py",
    },
    "pharmacy": {
        "name": "Excellent Pharmacy (PF3205)",
        "folder_root": DATA_DIR / "excellent_pharmacy",
        "src_name": "source.xlsx",
        "out_name": "Pharmacy_Exclusive_Report_with_Aging.xlsx",
        "generator": BASE / "pharmacy_exclusive_report_with_aging.py",
    },
}
YEARS = [2024, 2025]
SHEET_INS_TOT = "Insurance_Totals"
SHEET_SUMMARY = "Balance_Aging_Summary"

# ========== helper functions ==========
def mtime_token(p: Path) -> float:
    try: return p.stat().st_mtime
    except FileNotFoundError: return 0.0

def _run(cmd):
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(cmd)}\n\n{res.stderr}")
    return res

def rebuild_report(gen_path: Path, src_path: Path, out_path: Path):
    py = sys.executable
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [py, str(gen_path), str(src_path), "--out", str(out_path)]
    return _run(cmd).stdout or "OK"

def resolve_source_path(folder: Path, preferred="source.xlsx"):
    for ext in [".xlsb", ".xlsx", ".xlsm"]:
        p = folder / f"source{ext}"
        if p.exists():
            return p
    return folder / preferred

def save_uploaded_source(folder: Path, upload):
    ext = Path(upload.name).suffix.lower()
    if ext not in {".xlsb",".xlsx",".xlsm"}:
        raise ValueError("Please upload .xlsb/.xlsx/.xlsm only")
    dst = folder / f"source{ext}"
    folder.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(upload.read())
    return dst

@st.cache_data(max_entries=5, show_spinner=False)
def get_report_bytes(path): return Path(path).read_bytes()

@st.cache_data(show_spinner=False)
def load_core_sheets(path, token):
    ext = Path(path).suffix.lower()
    engine = "pyxlsb" if ext == ".xlsb" else "openpyxl"
    df1 = pd.read_excel(path, sheet_name=SHEET_INS_TOT, engine=engine)
    df2 = pd.read_excel(path, sheet_name=SHEET_SUMMARY, engine=engine)
    return df1, df2

# ========== admin/password ==========
def is_admin_mode():
    secret = st.secrets.get("ADMIN_PASSWORD","")
    if secret:
        if st.session_state.get("is_admin"): return True
        with st.popover("🔒 Admin login"):
            pwd = st.text_input("Password", type="password")
            if st.button("Login"):
                if pwd==secret: st.session_state.is_admin=True; st.rerun()
                else: st.error("Wrong password")
        return False
    return st.toggle("Admin mode", value=st.session_state.get("is_admin",False))

# ========== header ==========
st.title("📊 Exclusive Report with Aging — Dashboard")
st.session_state.is_admin = is_admin_mode()
if "center" not in st.session_state: st.session_state.center=None
if "year" not in st.session_state: st.session_state.year=None

# ---------- center selection ----------
if not st.session_state.center:
    st.subheader("Choose a center")
    c1,c2,c3 = st.columns(3)
    if c1.button(CENTERS["easyhealth"]["name"], use_container_width=True):
        st.session_state.center="easyhealth"; st.session_state.year=None; st.rerun()
    if c2.button(CENTERS["excellent"]["name"], use_container_width=True):
        st.session_state.center="excellent"; st.session_state.year=None; st.rerun()
    if c3.button(CENTERS["pharmacy"]["name"], use_container_width=True):
        st.session_state.center="pharmacy"; st.session_state.year=None; st.rerun()
    st.stop()

ck = st.session_state.center
cfg = CENTERS[ck]
st.caption(f"Mode: **{'admin' if st.session_state.is_admin else 'view'}** · Center: **{ck}** · Year: **{st.session_state.year or 'none'}**")

# ---------- year selection ----------
st.subheader("Select Year")
cols = st.columns(len(YEARS))
for i,y in enumerate(YEARS):
    with cols[i]:
        if st.session_state.year==y:
            st.markdown(f"<div style='background:#2196F3;color:white;text-align:center;padding:.8em;border-radius:6px;font-weight:700'>{y}</div>", unsafe_allow_html=True)
        else:
            if st.button(str(y), use_container_width=True): st.session_state.year=y; st.rerun()

if not st.session_state.year: st.session_state.year=YEARS[-1]

folder = cfg["folder_root"]/str(st.session_state.year)
folder.mkdir(parents=True, exist_ok=True)
src_path = resolve_source_path(folder)
out_path = folder/cfg["out_name"]

st.caption(f"Built: — · Source: `{src_path}` · Report: `{out_path.name}`")

# === Doc monthly performance right under year ===
if ck in ("easyhealth","excellent"):
    st.markdown("### 👨‍⚕️ Doc monthly performance (independent tool)")
    st.caption("Upload a .xlsx containing VisitNo, VisitDate, DocName, Item Group, ActivityIns columns (Month/Year optional).")

    try:
        from doctor_month_performance import load_minimal, build_report
        helper_ok=True
    except Exception as e:
        helper_ok=False
        st.warning("Missing helper script: **doctor_month_performance.py** not found in repo root.")
        st.code(str(e))

    up_perf = st.file_uploader("Upload Excel (.xlsx)", type=["xlsx"], key=f"docperf_upload_{ck}_{st.session_state.year}")
    run_perf = st.button("▶ Run Doc monthly performance", disabled=(not helper_ok or up_perf is None), use_container_width=True)

    if helper_ok and up_perf and run_perf:
        try:
            df_src = load_minimal(up_perf)
            result = build_report(df_src)
            st.success("Doctor monthly performance generated.")
            st.dataframe(result, use_container_width=True, height=min(850,120+35*max(1,len(result))))
            bio = BytesIO()
            with pd.ExcelWriter(bio, engine="openpyxl") as w:
                result.to_excel(w, sheet_name="Doctor_Performance", index=False)
            bio.seek(0)
            st.download_button("⬇️ Download Doc_Performance_By_Month.xlsx", data=bio.getvalue(),
                file_name=f"{ck}_{st.session_state.year}_Doc_Performance_By_Month.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
        except Exception as ex:
            st.error(str(ex))

# ---------- continue to main dashboard ----------
st.divider()
st.markdown("### 📑 Main Report (Exclusive Report with Aging)")

if st.session_state.is_admin:
    st.success("You are in **ADMIN** mode — upload/rebuild is enabled.")
    with st.expander("⬆️ Upload/replace source Excel for this year", expanded=False):
        up = st.file_uploader("Upload source Excel (.xlsb/.xlsx/.xlsm)", type=["xlsb","xlsx","xlsm"])
        if up:
            try: saved = save_uploaded_source(folder,up); st.success(f"Saved to {saved.name}")
            except Exception as e: st.error(str(e))
    if st.button("↻ Rebuild report", use_container_width=True):
        try:
            if not src_path.exists(): st.error("No source found."); st.stop()
            msg=rebuild_report(cfg["generator"], src_path, out_path)
            st.success("Report rebuilt successfully."); st.code(msg)
        except Exception as e: st.error(str(e))

# ---------- if report exists, show data ----------
if out_path.exists():
    token = mtime_token(out_path)
    try:
        totals, summary = load_core_sheets(str(out_path), token)
        st.write("✅ Report loaded successfully.")
        st.tabs([SHEET_INS_TOT, SHEET_SUMMARY])
    except Exception as e:
        st.error(str(e))
else:
    st.info("No report file found yet. Upload and rebuild to view aging details.")

