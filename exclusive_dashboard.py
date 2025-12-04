#!/usr/bin/env python3

import os
import sys
import time
import subprocess
from pathlib import Path

import pandas as pd
import streamlit as st

# ------------------------------------------
# Page / Layout
# ------------------------------------------
st.set_page_config(page_title="Exclusive Report with Aging — Dashboard", layout="wide")
st.title("📊 Exclusive Report with Aging — Dashboard")

# ------------------------------------------
# Paths
# ------------------------------------------
BASE_DIR    = Path(__file__).parent.resolve()
SCRIPT_PATH = (BASE_DIR / "exclusive_report_with_aging_final.py").resolve()   # generator script
REPORTS_DIR = (BASE_DIR / "reports").resolve()
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

# This is the ONE file everyone will view
DEFAULT_REPORT = REPORTS_DIR / "Exclusive_Report_with_Aging.xlsx"

# ------------------------------------------
# Mode: viewer (default) vs admin (?mode=admin)
# ------------------------------------------
try:
    params = st.query_params  # Streamlit ≥ 1.31
    mode = (params.get("mode") or "viewer").lower()
except Exception:
    # Fallback for older versions:
    mode = "viewer"
IS_ADMIN = (mode == "admin")

st.caption(
    f"Mode: **{'Admin' if IS_ADMIN else 'Viewer'}**  · "
    "Tip: add `?mode=admin` to the URL for upload/regenerate."
)

# ------------------------------------------
# Helpers
# ------------------------------------------
def run_generator(input_path: Path, output_path: Path):
    """
    Run the ETL script with robust settings and capture logs.
    Uses the same python interpreter as Streamlit.
    """
    cmd = [
        sys.executable,             # same interpreter
        str(SCRIPT_PATH),           # generator script
        str(input_path),            # input .xlsx
        "--out", str(output_path),  # output .xlsx
    ]
    proc = subprocess.run(
        cmd,
        cwd=str(BASE_DIR),
        capture_output=True,
        text=True,
    )
    return proc

def sheet_exists(xls: pd.ExcelFile, name: str) -> bool:
    try:
        return name in xls.sheet_names
    except Exception:
        return False

def open_current_report_or_fail() -> pd.ExcelFile:
    if not DEFAULT_REPORT.exists():
        st.error("No generated report found yet. Please upload in **admin mode** to create it.")
        st.stop()
    try:
        return pd.ExcelFile(DEFAULT_REPORT, engine="openpyxl")
    except Exception as e:
        st.error(f"Could not open the latest report: {e}")
        st.stop()

def render_report(xls: pd.ExcelFile, info_text: str = "Loaded latest report."):
    # Meta (optional but expected)
    try:
        meta = pd.read_excel(xls, "Meta")
        st.success(info_text)
        st.caption(
            f"Generated: **{meta.loc[0,'GeneratedAt']}** · "
            f"Input: **{meta.loc[0,'InputFile']}** · "
            f"Exclusive_Report sheet written: **{bool(meta.get('Exclusive_Report_Written', pd.Series([False])).iloc[0])}**"
        )
    except Exception:
        st.info(info_text)

    # KPIs from Insurance_Totals
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
        st.error("Sheet **Insurance_Totals** not found; cannot show KPIs.")

    # Build tabs dynamically
    labels = []
    if sheet_exists(xls, "Insurance_Totals"):       labels.append("Insurance Totals")
    if sheet_exists(xls, "Balance_Aging_Summary"):  labels.append("Balance Aging Summary")
    if sheet_exists(xls, "Balance_Aging_Detail"):   labels.append("Balance Aging Detail")
    if sheet_exists(xls, "Exclusive_Report"):       labels.append("Exclusive Report")  # optional

    if not labels:
        st.warning("No displayable sheets found in the workbook.")
        return

    tabs = st.tabs(labels)
    i = 0
    if sheet_exists(xls, "Insurance_Totals"):
        with tabs[i]:
            st.dataframe(pd.read_excel(xls, "Insurance_Totals"), use_container_width=True)
        i += 1
    if sheet_exists(xls, "Balance_Aging_Summary"):
        with tabs[i]:
            st.dataframe(pd.read_excel(xls, "Balance_Aging_Summary"), use_container_width=True)
        i += 1
    if sheet_exists(xls, "Balance_Aging_Detail"):
        with tabs[i]:
            st.dataframe(pd.read_excel(xls, "Balance_Aging_Detail"), use_container_width=True)
        i += 1
    if sheet_exists(xls, "Exclusive_Report"):
        with tabs[i]:
            st.dataframe(pd.read_excel(xls, "Exclusive_Report"), use_container_width=True)

# ------------------------------------------
# Viewer mode: just open & render the latest report
# ------------------------------------------
if not IS_ADMIN:
    xls = open_current_report_or_fail()
    render_report(xls, "Loaded latest report (viewer mode).")
    st.stop()

# ------------------------------------------
# Admin mode: upload -> generate -> overwrite DEFAULT_REPORT -> show
# ------------------------------------------
uploaded = st.file_uploader("Upload source Excel (.xlsx)", type=["xlsx"])
if uploaded is None:
    # Show whatever is currently the latest (if exists), so admin can see last state
    if DEFAULT_REPORT.exists():
        xls = open_current_report_or_fail()
        render_report(xls, "Showing current saved report. Upload to regenerate.")
    else:
        st.info("Upload an Excel file to generate the first report.")
    st.stop()

# Save upload with a unique name
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

# Clear any cached loaders (if you used them elsewhere)
try:
    st.cache_data.clear()
except Exception:
    pass

xls = open_current_report_or_fail()
render_report(xls, "Report updated successfully (admin mode). Share the **viewer link** without ?mode=admin.")
