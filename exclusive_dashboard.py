#!/usr/bin/env python3

import os
import sys
import time
import subprocess
from pathlib import Path

import pandas as pd
import streamlit as st

st.set_page_config(page_title="Exclusive Report with Aging — Dashboard", layout="wide")
st.title("📊 Exclusive Report with Aging — Dashboard")

# ---------- Paths ----------
BASE_DIR    = Path(__file__).parent.resolve()
SCRIPT_PATH = (BASE_DIR / "exclusive_report_with_aging_final.py").resolve()
REPORTS_DIR = (BASE_DIR / "reports").resolve()
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

uploaded = st.file_uploader("Upload Check .xlsx", type=["xlsx"])

def run_generator(input_path: Path, output_path: Path):
    """Run the ETL script with robust settings and show any errors."""
    cmd = [
        sys.executable,            # use SAME interpreter running Streamlit
        str(SCRIPT_PATH),          # absolute path to script
        str(input_path),           # input .xlsx
        "--out", str(output_path)  # explicit output path
    ]
    # Run from the app folder; capture output for debugging
    proc = subprocess.run(
        cmd,
        cwd=str(BASE_DIR),
        capture_output=True,
        text=True
    )
    return proc

if uploaded is not None:
    # 1) Save upload with a unique name so cache/locks can't trick us
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

    # 4) Clear any cached loaders before reading output
    try:
        st.cache_data.clear()
    except Exception:
        pass

    # 5) Load the workbook we just created
    try:
        xls    = pd.ExcelFile(out_path, engine="openpyxl")
        totals = pd.read_excel(xls, "Insurance_Totals")
        meta   = pd.read_excel(xls, "Meta")
    except Exception as e:
        st.error(f"Could not read output workbook: {e}")
        with st.expander("Debug info"):
            st.write("Output path:", str(out_path))
        st.stop()

    st.success(f"Report generated from uploaded {uploaded.name}.")
    st.caption(
        f"Input: **{meta.loc[0,'InputFile']}** · "
        f"SHA1: **{meta.loc[0,'InputSHA1']}** · "
        f"Generated: **{meta.loc[0,'GeneratedAt']}**"
    )

    # ---------- KPIs (from Grand Total) ----------
    if "Insurance" in totals.columns and (totals["Insurance"] == "Grand Total").any():
        gt = totals[totals["Insurance"] == "Grand Total"].iloc[0]
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Net Amount", f"{gt['Net Amount']:,.2f}")
        c2.metric("Paid",       f"{gt['Paid']:,.2f}")
        c3.metric("Balance",    f"{gt['Balance']:,.2f}")
        c4.metric("Rejected",   f"{gt['Rejected']:,.2f}")
        c5.metric("Accepted",   f"{gt['Accepted']:,.2f}")
    else:
        st.warning("Grand Total row not found in Insurance_Totals.")

    # ---------- Tabs / tables ----------
    tabs = st.tabs(["Insurance Totals", "Balance Aging Summary", "Balance Aging Detail", "Exclusive Report"])
    with tabs[0]:
        st.dataframe(totals, use_container_width=True)
    with tabs[1]:
        try:
            bal_summary = pd.read_excel(xls, "Balance_Aging_Summary")
            st.dataframe(bal_summary, use_container_width=True)
        except Exception as e:
            st.warning(f"Could not load Balance_Aging_Summary: {e}")
    with tabs[2]:
        try:
            bal_detail = pd.read_excel(xls, "Balance_Aging_Detail")
            st.dataframe(bal_detail, use_container_width=True)
        except Exception as e:
            st.warning(f"Could not load Balance_Aging_Detail: {e}")
    with tabs[3]:
        try:
            ex = pd.read_excel(xls, "Exclusive_Report")
            st.dataframe(ex, use_container_width=True)
        except Exception as e:
            st.warning(f"Could not load Exclusive_Report: {e}")

else:
    st.caption("Tip: After you upload, the app runs the generator with the **same Python** and reads the exact output file it wrote.")

