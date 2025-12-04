#!/usr/bin/env python3

import os
import sys
import time
from pathlib import Path
import subprocess

import pandas as pd
import streamlit as st

st.set_page_config(page_title="Exclusive Report with Aging — Dashboard", layout="wide")
st.title("📊 Exclusive Report with Aging — Dashboard")

# ---------- Paths ----------
BASE_DIR    = Path(__file__).parent.resolve()
SCRIPT_PATH = (BASE_DIR / "exclusive_report_with_aging_final.py").resolve()
REPORTS_DIR = (BASE_DIR / "reports").resolve()
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

uploaded = st.file_uploader("Upload Check (.xlsx)", type=["xlsx"])

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

if uploaded is not None:
    # 1) Save upload with a unique name (avoids locking/caching issues)
    ts = int(time.time())
    in_path  = REPORTS_DIR / f"source_{ts}_{uploaded.name}"
    with open(in_path, "wb") as f:
        f.write(uploaded.getbuffer())

    # 2) Fixed output path we'll read from
    out_path = REPORTS_DIR / "Exclusive_Report_with_Aging.xlsx"

    st.info("Source file saved. Generating report…")

    # 3) Run generator
    proc = run_generator(in_path, out_path)
    if proc.returncode != 0:
        st.error("Report generation failed.")
        with st.expander("Show error details"):
            st.code(f"Command:\n{' '.join(proc.args)}", language="bash")
            st.code(f"STDOUT:\n{proc.stdout or '(empty)'}")
            st.code(f"STDERR:\n{proc.stderr or '(empty)'}")
        st.stop()

    # 4) Clear any cached loaders (if you used them elsewhere)
    try:
        st.cache_data.clear()
    except Exception:
        pass

    # 5) Open the workbook we just created
    try:
        xls = pd.ExcelFile(out_path, engine="openpyxl")
    except Exception as e:
        st.error(f"Could not open generated workbook: {e}")
        st.stop()

    # --- Read Meta (always present)
    try:
        meta = pd.read_excel(xls, "Meta")
        st.success(f"Report generated from uploaded {uploaded.name}.")
        st.caption(
            f"Input: **{meta.loc[0,'InputFile']}** · "
            f"SHA1: **{meta.loc[0,'InputSHA1']}** · "
            f"Generated: **{meta.loc[0,'GeneratedAt']}** · "
            f"Exclusive_Report sheet written: **{bool(meta.loc[0,'Exclusive_Report_Written'])}**"
        )
    except Exception:
        st.warning("Meta sheet missing; continuing…")

    # --- Load required sheets safely
    totals = None
    if sheet_exists(xls, "Insurance_Totals"):
        totals = pd.read_excel(xls, "Insurance_Totals")
    else:
        st.error("Sheet 'Insurance_Totals' not found. Cannot display KPIs.")

    # KPIs from Grand Total (if available)
    if totals is not None and "Insurance" in totals.columns and (totals["Insurance"] == "Grand Total").any():
        gt = totals[totals["Insurance"] == "Grand Total"].iloc[0]
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Net Amount", f"{gt['Net Amount']:,.2f}")
        c2.metric("Paid",       f"{gt['Paid']:,.2f}")
        c3.metric("Balance",    f"{gt['Balance']:,.2f}")
        c4.metric("Rejected",   f"{gt['Rejected']:,.2f}")
        c5.metric("Accepted",   f"{gt['Accepted']:,.2f}")

    # --- Build tabs dynamically based on which sheets exist
    tab_labels = []
    if totals is not None:
        tab_labels.append("Insurance Totals")
    if sheet_exists(xls, "Balance_Aging_Summary"):
        tab_labels.append("Balance Aging Summary")
    if sheet_exists(xls, "Balance_Aging_Detail"):
        tab_labels.append("Balance Aging Detail")
    # Exclusive_Report is optional — only show if present
    if sheet_exists(xls, "Exclusive_Report"):
        tab_labels.append("Exclusive Report")

    if not tab_labels:
        st.warning("No displayable sheets found.")
        st.stop()

    tabs = st.tabs(tab_labels)

    t = 0
    if totals is not None:
        with tabs[t]:
            st.dataframe(totals, use_container_width=True)
        t += 1

    if sheet_exists(xls, "Balance_Aging_Summary"):
        with tabs[t]:
            try:
                bal_summary = pd.read_excel(xls, "Balance_Aging_Summary")
                st.dataframe(bal_summary, use_container_width=True)
            except Exception as e:
                st.warning(f"Could not load Balance_Aging_Summary: {e}")
        t += 1

    if sheet_exists(xls, "Balance_Aging_Detail"):
        with tabs[t]:
            try:
                bal_detail = pd.read_excel(xls, "Balance_Aging_Detail")
                st.dataframe(bal_detail, use_container_width=True)
            except Exception as e:
                st.warning(f"Could not load Balance_Aging_Detail: {e}")
        t += 1

    if sheet_exists(xls, "Exclusive_Report"):
        with tabs[t]:
            try:
                ex = pd.read_excel(xls, "Exclusive_Report")
                st.dataframe(ex, use_container_width=True)
            except Exception as e:
                st.warning(f"Could not load Exclusive_Report: {e}")

else:
    st.caption("Upload your daily Excel to generate fresh KPIs and aging views. (The raw 'Exclusive_Report' tab is hidden when not written.)")
