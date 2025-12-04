import os
import sys
import io
import subprocess
from pathlib import Path
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Exclusive Report Dashboard", layout="wide")

# ---- Simple password gate (set DASH_PASS in Streamlit secrets) ----
PASS = os.environ.get("DASH_PASS", "")
if PASS:
    if "ok" not in st.session_state:
        st.session_state.ok = False
    if not st.session_state.ok:
        st.title("🔐 Exclusive Report — Login")
        pwd = st.text_input("Enter password", type="password")
        if st.button("Login"):
            if pwd == PASS:
                st.session_state.ok = True
            else:
                st.error("Incorrect password")
        st.stop()

# ---- Paths (all relative to this file in Streamlit Cloud) ----
BASE = Path(__file__).parent
DATA_FILE = BASE / "Exclusive_Report_with_Aging.xlsx"
SOURCE_XLSX = BASE / "Check3.xlsx"
GENERATOR = BASE / "exclusive_report_with_aging_final.py"

st.title("📊 Exclusive Report with Aging — Dashboard")

# ---- Upload (manual daily update) ----
st.subheader("📥 Upload your daily Excel")
uploaded = st.file_uploader("Upload Check3.xlsx (source) OR Exclusive_Report_with_Aging.xlsx (final)", type=["xlsx"])

colA, colB = st.columns([1,1])
with colA:
    if uploaded is not None:
        name = uploaded.name.lower()
        content = uploaded.read()

        if "check3" in name:
            with open(SOURCE_XLSX, "wb") as f:
                f.write(content)
            st.info("Source file saved. Generating report...")
            result = subprocess.run(
                [sys.executable, str(GENERATOR), str(SOURCE_XLSX)],
                capture_output=True, text=True, cwd=str(BASE)
            )
            if result.returncode == 0 and DATA_FILE.exists():
                st.success("✅ Report generated from uploaded Check3.xlsx.")
            else:
                st.error("❌ Report generation failed.")
                st.code(result.stderr or result.stdout)
        else:
            with open(DATA_FILE, "wb") as f:
                f.write(content)
            st.success("✅ Replaced Exclusive_Report_with_Aging.xlsx.")

with colB:
    if st.button("🔄 Refresh using current Check3.xlsx"):
        if SOURCE_XLSX.exists():
            result = subprocess.run(
                [sys.executable, str(GENERATOR), str(SOURCE_XLSX)],
                capture_output=True, text=True, cwd=str(BASE)
            )
            if result.returncode == 0 and DATA_FILE.exists():
                st.success("✅ Report refreshed.")
            else:
                st.error("❌ Refresh failed.")
                st.code(result.stderr or result.stdout)
        else:
            st.warning("No Check3.xlsx found yet. Please upload it first.")

st.divider()

# ---- Data viewer ----
@st.cache_data
def load_sheet(sheet):
    return pd.read_excel(DATA_FILE, sheet_name=sheet, engine="openpyxl")

tabs = st.tabs(["Insurance Totals", "Balance Aging Summary", "Balance Aging Detail", "Exclusive Report"])

if not DATA_FILE.exists():
    st.warning("No report file yet. Upload Check3.xlsx and click Refresh, or upload the final report.")
else:
    # Tab 1
    with tabs[0]:
        df = load_sheet("Insurance_Totals")
        st.subheader("Insurance Totals (Net Amount, Paid, Balance, Rejected, Accepted)")
        top = df[df["Insurance"].ne("Grand Total")]
        gt = df[df["Insurance"].eq("Grand Total")].tail(1)
        c1, c2, c3, c4, c5 = st.columns(5)
        if not gt.empty:
            c1.metric("Net Amount", f"{gt['Net Amount'].iloc[0]:,.2f}")
            c2.metric("Paid", f"{gt['Paid'].iloc[0]:,.2f}")
            c3.metric("Balance", f"{gt['Balance'].iloc[0]:,.2f}")
            c4.metric("Rejected", f"{gt['Rejected'].iloc[0]:,.2f}")
            c5.metric("Accepted", f"{gt['Accepted'].iloc[0]:,.2f}")
        st.bar_chart(top.set_index("Insurance")[["Net Amount","Paid","Balance"]])
        st.dataframe(df, use_container_width=True)

    # Tab 2
    with tabs[1]:
        df = load_sheet("Balance_Aging_Summary")
        st.subheader("Balance Aging Summary")
        st.dataframe(df, use_container_width=True)

    # Tab 3
    with tabs[2]:
        df = load_sheet("Balance_Aging_Detail")
        st.subheader("Balance Aging Detail")
        st.dataframe(df, use_container_width=True)

    # Tab 4
    with tabs[3]:
        df = load_sheet("Exclusive_Report")
        st.subheader("Exclusive Report (raw)")
        st.dataframe(df, use_container_width=True)
