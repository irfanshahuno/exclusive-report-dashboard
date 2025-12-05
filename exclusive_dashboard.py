# dashboard.py
import shutil
import subprocess
from pathlib import Path
import pandas as pd
import streamlit as st

# -------------------------------------------------------------------
# Basic page setup
# -------------------------------------------------------------------
st.set_page_config(page_title="Exclusive Report with Aging — Dashboard", layout="wide")
BASE = Path(__file__).parent

# -------------------------------------------------------------------
# CONFIG — change file names here if yours are different
# -------------------------------------------------------------------
# One shared generator script for both centers:
GENERATOR = BASE / "exclusive_report_with_aging_final.py"

# If your generator supports: python script.py <source.xlsx> --out <report.xlsx>
GENERATOR_SUPPORTS_OUT_ARG = False  # set True if you add --out to your script

# The default Excel filename your generator writes (used when no --out)
DEFAULT_GENERATED_REPORT = BASE / "Exclusive_Report_with_Aging.xlsx"

# Centers (two buttons on the home page)
CENTERS = {
    "easyhealth": {
        "name": "Easy Health Medical Clinic (MF8031)",
        "source": BASE / "EH_Check3.xlsx",
        "report": BASE / "Exclusive_Report_with_Aging_EASYHEALTH.xlsx",
        "sheets": {
            "totals": "Insurance Totals",
            "summary": "Balance Aging Summary",
            "detail": "Balance Aging Detail",
        },
    },
    "excellent": {
        "name": "Excellent Medical Center (MF4777)",
        "source": BASE / "Check3.xlsx",
        "report": BASE / "Exclusive_Report_with_Aging_EXCELLENT.xlsx",
        "sheets": {
            "totals": "Insurance Totals",
            "summary": "Balance Aging Summary",
            "detail": "Balance Aging Detail",
        },
    },
}

# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------
def mtime_token(p: Path) -> float:
    try:
        return p.stat().st_mtime
    except FileNotFoundError:
        return 0.0

@st.cache_data(show_spinner=True)
def load_report(path: str, totals_sheet: str, summary_sheet: str, detail_sheet: str, _token: float):
    xls = pd.ExcelFile(path)
    totals  = xls.parse(totals_sheet)
    summary = xls.parse(summary_sheet)
    detail  = xls.parse(detail_sheet)
    return totals, summary, detail

def show_kpis(totals: pd.DataFrame):
    get = lambda col: float(totals[col].sum()) if col in totals else 0.0
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Net Amount", f"{get('Net Amount'):,.2f}")
    c2.metric("Paid", f"{get('Paid'):,.2f}")
    c3.metric("Balance", f"{get('Balance'):,.2f}")
    c4.metric("Rejected", f"{get('Rejected'):,.2f}")
    c5.metric("Accepted", f"{get('Accepted'):,.2f}")

def rebuild_report(cfg) -> str:
    """
    Run the generator to produce the report for the selected center.
    Uses --out if supported; otherwise copies the default output file.
    """
    src = str(cfg["source"])
    out = str(cfg["report"])
    if GENERATOR_SUPPORTS_OUT_ARG:
        cmd = ["python", str(GENERATOR), src, "--out", out]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            raise RuntimeError(res.stderr or "Generator failed")
        return res.stdout or "OK"
    else:
        res = subprocess.run(["python", str(GENERATOR), src], capture_output=True, text=True)
        if res.returncode != 0:
            raise RuntimeError(res.stderr or "Generator failed")
        if not DEFAULT_GENERATED_REPORT.exists():
            raise RuntimeError(f"Expected output not found: {DEFAULT_GENERATED_REPORT.name}")
        shutil.copyfile(DEFAULT_GENERATED_REPORT, out)
        return res.stdout or "OK"

# -------------------------------------------------------------------
# Routing (buttons → center, optional admin mode)
# -------------------------------------------------------------------
qp = st.query_params
mode = qp.get("mode", ["view"])[0].lower()
if mode not in ("view", "admin"):
    mode = "view"

center_key = qp.get("center", [None])[0]

# If no center chosen yet → show two big buttons and stop
if center_key not in CENTERS:
    st.title("📊 Exclusive Report with Aging — Dashboard")
    st.subheader("Choose a center")

    # Preserve mode when user clicks a button
    current_mode = st.query_params.get("mode", ["view"])[0].lower()

    c1, c2 = st.columns(2)
    with c1:
        if st.button(CENTERS["easyhealth"]["name"], use_container_width=True):
            st.query_params.update(center="easyhealth", mode=current_mode)
            st.rerun()
    with c2:
        if st.button(CENTERS["excellent"]["name"], use_container_width=True):
            st.query_params.update(center="excellent", mode=current_mode)
            st.rerun()

    st.stop()

# A center is selected
cfg = CENTERS[center_key]
st.title("📊 Exclusive Report with Aging — Dashboard")
st.caption(f"Center: **{cfg['name']}**  ·  Input: {cfg['source'].name}  ·  Report: {cfg['report'].name}")

# Little back button to go to center chooser (preserves mode)
if st.button("◀ Choose another center"):
    current_mode = st.query_params.get("mode", ["view"])[0].lower()
    st.query_params.clear()
    st.query_params.update(mode=current_mode)
    st.rerun()

# -------------------------------------------------------------------
# ADMIN (only when URL has ?mode=admin)
# -------------------------------------------------------------------
if mode == "admin":
    with st.expander("⬆️ Upload/replace source Excel", expanded=False):
        up = st.file_uploader("Upload .xlsx", type=["xlsx"])
        if up:
            cfg["source"].write_bytes(up.read())
            st.success(f"Saved to {cfg['source'].name}")

    colA, colB = st.columns(2)
    if colA.button("↻ Rebuild report", use_container_width=True):
        try:
            out = rebuild_report(cfg)
            st.success("Report rebuilt successfully.")
            if out.strip():
                st.code(out, language="bash")
            load_report.clear()
        except Exception as e:
            st.error(str(e))

    if colB.button("🗂 Show file locations", use_container_width=True):
        st.info(f"Source: {cfg['source']}\nReport: {cfg['report']}\nScript: {GENERATOR}")

# -------------------------------------------------------------------
# Viewer (KPIs + tables)
# -------------------------------------------------------------------
token = mtime_token(cfg["report"])
if token == 0.0:
    st.warning("Report not found. (Open with ?mode=admin to upload source and rebuild.)")
else:
    totals, summary, detail = load_report(
        str(cfg["report"]),
        cfg["sheets"]["totals"],
        cfg["sheets"]["summary"],
        cfg["sheets"]["detail"],
        token,
    )
    show_kpis(totals)
    t1, t2, t3 = st.tabs(["Insurance Totals", "Balance Aging Summary", "Balance Aging Detail"])
    with t1:
        st.dataframe(totals, use_container_width=True, hide_index=True)
    with t2:
        st.dataframe(summary, use_container_width=True, hide_index=True)
    with t3:
        st.dataframe(detail, use_container_width=True, hide_index=True)
