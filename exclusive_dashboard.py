import streamlit as st
import pandas as pd
import subprocess
import sys
from pathlib import Path

st.set_page_config(page_title="Exclusive Report Dashboard", layout="wide")

BASE_DIR = Path(__file__).parent
DATA_FILE = BASE_DIR / "Exclusive_Report_with_Aging.xlsx"
SOURCE_XLSX = BASE_DIR / "Check3.xlsx"
REPORT_SCRIPT = BASE_DIR / "exclusive_report_with_aging_final.py"

st.title("📊 Exclusive Report with Aging — Dashboard")

left, mid, right = st.columns([1, 1, 2], gap="large")
with left:
    st.write("**Data file:**", DATA_FILE.name)
    st.write("**Source:**", SOURCE_XLSX.name)

with mid:
    if st.button("🔄 Refresh Report (Run Python)"):
        try:
            result = subprocess.run(
                [sys.executable, str(REPORT_SCRIPT), str(SOURCE_XLSX)],
                capture_output=True, text=True, cwd=str(BASE_DIR)
            )
            if result.returncode == 0:
                st.success("Report refreshed successfully.")
            else:
                st.error("Report refresh failed.")
                st.code(result.stderr or result.stdout)
        except Exception as e:
            st.error(f"Error: {e}")

with right:
    st.caption("Tip: Use Windows Task Scheduler to refresh automatically every morning.")

st.divider()

@st.cache_data
def load_sheet(sheet):
    return pd.read_excel(DATA_FILE, sheet_name=sheet, engine="openpyxl")

sheets = ["Insurance_Totals", "Balance_Aging_Summary", "Balance_Aging_Detail", "Exclusive_Report"]
sheet_choice = st.selectbox("Select a sheet to view", sheets, index=0)

if not DATA_FILE.exists():
    st.warning(f"Data file not found: {DATA_FILE.name}. Click **Refresh Report** or run your script.")
else:
    df = load_sheet(sheet_choice)

    if sheet_choice == "Insurance_Totals":
        top = df[df["Insurance"].ne("Grand Total")]
        gt = df[df["Insurance"].eq("Grand Total")].tail(1)

        c1, c2, c3, c4, c5 = st.columns(5)
        if not gt.empty:
            c1.metric("Net Amount", f"{gt['Net Amount'].iloc[0]:,.2f}")
            c2.metric("Paid", f"{gt['Paid'].iloc[0]:,.2f}")
            c3.metric("Balance", f"{gt['Balance'].iloc[0]:,.2f}")
            c4.metric("Rejected", f"{gt['Rejected'].iloc[0]:,.2f}")
            c5.metric("Accepted", f"{gt['Accepted'].iloc[0]:,.2f}")

        st.bar_chart(top.set_index("Insurance")[["Net Amount", "Paid", "Balance"]])

    st.write(f"### 📄 {sheet_choice}")
    st.dataframe(df, use_container_width=True)
