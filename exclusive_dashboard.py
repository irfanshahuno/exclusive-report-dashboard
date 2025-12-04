import os, time, subprocess
import pandas as pd
import streamlit as st

st.title("📊 Exclusive Report with Aging — Dashboard")

uploaded = st.file_uploader("Upload Check .xlsx", type=["xlsx"])
reports_dir = "reports"
os.makedirs(reports_dir, exist_ok=True)

if uploaded is not None:
    # 1) Save upload with a unique name so cache can’t trick us
    ts = int(time.time())
    in_path  = os.path.join(reports_dir, f"source_{ts}_{uploaded.name}")
    with open(in_path, "wb") as f:
        f.write(uploaded.getbuffer())

    # 2) Decide explicit output path that WE will read
    out_path = os.path.join(reports_dir, "Exclusive_Report_with_Aging.xlsx")

    # 3) Run the generator script with explicit in/out paths
    st.info("Source file saved. Generating report…")
    subprocess.run(
        ["python", "exclusive_report_with_aging_final.py", in_path, "--out", out_path],
        check=True
    )

    # 4) Clear any cached loaders and load THIS EXACT output
    try:
        st.cache_data.clear()  # if you used caching elsewhere
    except Exception:
        pass

    # 5) Read and display numbers from out_path
    xls = pd.ExcelFile(out_path, engine="openpyxl")
    totals = pd.read_excel(xls, "Insurance_Totals")
    meta   = pd.read_excel(xls, "Meta")

    st.success(f"Report generated from uploaded {uploaded.name}.")
    st.caption(f"Input SHA1: **{meta.loc[0,'InputSHA1']}** · GeneratedAt: **{meta.loc[0,'GeneratedAt']}**")

    # Example top-line KPIs from Grand Total
    gt = totals[totals["Insurance"]=="Grand Total"].iloc[0]
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Net Amount",   f"{gt['Net Amount']:,.2f}")
    col2.metric("Paid",         f"{gt['Paid']:,.2f}")
    col3.metric("Balance",      f"{gt['Balance']:,.2f}")
    col4.metric("Rejected",     f"{gt['Rejected']:,.2f}")
    col5.metric("Accepted",     f"{gt['Accepted']:,.2f}")

    # …then your existing charts/tabs reading from `xls`
