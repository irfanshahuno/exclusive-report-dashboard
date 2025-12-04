#!/usr/bin/env python3

import os, sys, time, subprocess
from pathlib import Path
import pandas as pd
import streamlit as st

# -------------------- Page --------------------
st.set_page_config(page_title="Exclusive Report with Aging — Dashboard", layout="wide")
st.title("📊 Exclusive Report with Aging — Dashboard")

# -------------------- Paths --------------------
BASE_DIR     = Path(__file__).parent.resolve()
SCRIPT_PATH  = (BASE_DIR / "exclusive_report_with_aging_final.py").resolve()  # generator file
REPORTS_DIR  = (BASE_DIR / "reports").resolve()
REPORTS_DIR.mkdir(parents=True, exist_ok=True)
DEFAULT_REPORT = REPORTS_DIR / "Exclusive_Report_with_Aging.xlsx"             # viewer reads this

# -------------------- Mode (viewer default) --------------------
try:
    qp = st.query_params
except Exception:
    qp = {}
raw_mode = None
if isinstance(qp, dict):
    v = qp.get("mode")
    if isinstance(v, list) and v: raw_mode = v[0]
    elif isinstance(v, str):      raw_mode = v
MODE = (raw_mode or "viewer").strip().lower()
IS_ADMIN = (MODE == "admin")
st.caption(f"Mode: **{'Admin' if IS_ADMIN else 'Viewer'}** · Add `?mode=admin` to use the uploader.")

# -------------------- Helpers --------------------
def run_generator(input_path: Path, output_path: Path):
    cmd = [sys.executable, str(SCRIPT_PATH), str(input_path), "--out", str(output_path)]
    return subprocess.run(cmd, cwd=str(BASE_DIR), capture_output=True, text=True)

def sheet_exists(xls: pd.ExcelFile, name: str) -> bool:
    try: return name in xls.sheet_names
    except: return False

def render_report(xls: pd.ExcelFile, info_text: str):
    try:
        meta = pd.read_excel(xls, "Meta")
        st.success(info_text)
        st.caption(
            f"Generated: **{meta.loc[0,'GeneratedAt']}** · "
            f"Input: **{meta.loc[0,'InputFile']}** · "
            f"Exclusive_Report written: **{bool(meta.get('Exclusive_Report_Written', pd.Series([False])).iloc[0])}**"
        )
    except Exception:
        st.info(info_text)

    if sheet_exists(xls, "Insurance_Totals"):
        totals = pd.read_excel(xls, "Insurance_Totals")
        if "Insurance" in totals.columns and (totals["Insurance"] == "Grand Total").any():
            gt = totals[totals["Insurance"] == "Grand Total"].iloc[0]
            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("Net Amount", f"{gt['Net Amount']:,.2f}")
            c2.metric("Paid",       f"{gt['Paid']:,.2f}")
            c3.metric("Balance",    f"{gt['Balance']:,.2f}")
            c4.metric("Rejected",   f"{gt['Rejected']:,.2f}")
            c5.metric("Accepted",   f"{gt['Accepted']:,.2f}")
    else:
        st.error("Sheet 'Insurance_Totals' not found. Cannot show KPIs.")

    labels = []
    if sheet_exists(xls, "Insurance_Totals"):       labels.append("Insurance Totals")
    if sheet_exists(xls, "Balance_Aging_Summary"):  labels.append("Balance Aging Summary")
    if sheet_exists(xls, "Balance_Aging_Detail"):   labels.append("Balance Aging Detail")
    if sheet_exists(xls, "Exclusive_Report"):       labels.append("Exclusive Report")
    if not labels:
        st.warning("No displayable sheets found.")
        return

    tabs = st.tabs(labels)
    i = 0
    if sheet_exists(xls, "Insurance_Totals"):
        with tabs[i]: st.dataframe(pd.read_excel(xls, "Insurance_Totals"), use_container_width=True); i += 1
    if sheet_exists(xls, "Balance_Aging_Summary"):
        with tabs[i]: st.dataframe(pd.read_excel(xls, "Balance_Aging_Summary"), use_container_width=True); i += 1
    if sheet_exists(xls, "Balance_Aging_Detail"):
        with tabs[i]: st.dataframe(pd.read_excel(xls, "Balance_Aging_Detail"), use_container_width=True); i += 1
    if sheet_exists(xls, "Exclusive_Report"):
        with tabs[i]: st.dataframe(pd.read_excel(xls, "Exclusive_Report"), use_container_width=True)

# -------------------- VIEWER (no upload UI) --------------------
if not IS_ADMIN:
    if not DEFAULT_REPORT.exists():
        st.error("No generated report found yet. Ask admin to upload in **admin mode**.")
        st.stop()
    try:
        xls = pd.ExcelFile(DEFAULT_REPORT, engine="openpyxl")
    except Exception as e:
        st.error(f"Could not open report: {e}")
        st.stop()

    # (Optional) CSS safeguard to hide any accidental uploader widgets
    st.markdown("<style>[data-testid='stFileUploader']{display:none!important;}</style>", unsafe_allow_html=True)

    render_report(xls, "Loaded latest report (viewer mode).")
    st.stop()

# -------------------- ADMIN (upload & regenerate) --------------------
uploaded = st.file_uploader("Upload source Excel (.xlsx)", type=["xlsx"])
if uploaded is None:
    if DEFAULT_REPORT.exists():
        xls = pd.ExcelFile(DEFAULT_REPORT, engine="openpyxl")
        render_report(xls, "Showing current saved report. Upload to regenerate.")
    else:
        st.info("Upload an Excel file to generate the first report.")
    st.stop()

ts = int(time.time())
in_path = REPORTS_DIR / f"source_{ts}_{uploaded.name}"
with open(in_path, "wb") as f:
    f.write(uploaded.getbuffer())

st.info("Generating report…")
proc = run_generator(in_path, DEFAULT_REPORT)

if proc.returncode != 0:
    st.error("Report generation failed.")
    with st.expander("Show error details"):
        st.code(f"Command:\n{' '.join(proc.args)}", language="bash")
        st.code(f"STDOUT:\n{proc.stdout or '(empty)'}")
        st.code(f"STDERR:\n{proc.stderr or '(empty)'}")
    st.stop()

try:
    st.cache_data.clear()
except Exception:
    pass

xls = pd.ExcelFile(DEFAULT_REPORT, engine="openpyxl")
render_report(xls, "Report updated successfully (admin mode). Share the viewer link (no ?mode=admin).")


