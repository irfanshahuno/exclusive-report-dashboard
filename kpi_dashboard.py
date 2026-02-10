import io
import pandas as pd
import streamlit as st

from kpi.pc009_hba1c import compute_pc009

st.set_page_config(page_title="KPI Dashboard", layout="wide")
st.title("KPI Dashboard (JAWDA)")

# ---- Controls ----
c1, c2 = st.columns(2)
with c1:
    year = st.selectbox("Year", [2024, 2025, 2026], index=1)
with c2:
    quarter = st.selectbox("Quarter", ["Q1", "Q2", "Q3", "Q4"], index=3)

st.divider()

st.subheader("PC009 — HbA1c Poor Control (>9%) or No Test")

visit_file = st.file_uploader("Upload YEARLY VISIT file (.xlsx)", type=["xlsx"])
lab_file = st.file_uploader("Upload YEARLY LAB billing file (.xlsx)", type=["xlsx"])

if visit_file and lab_file:
    visits_df = pd.read_excel(visit_file)
    labs_df = pd.read_excel(lab_file)

    result, latest_hba = compute_pc009(visits_df, labs_df, int(year), quarter)

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Denominator", result["denominator"])
    k2.metric("Numerator", result["numerator"])
    k3.metric("Poor control (>9)", result["poor_control"])
    k4.metric("No test", result["no_test"])

    st.metric("PC009 %", f"{result['kpi_percent']}%")

    st.write("Latest HbA1c tests (last record per patient):")
    st.dataframe(latest_hba.sort_values("Visit Date", ascending=False).head(50), use_container_width=True)

    # Download latest_hba as Excel
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        latest_hba.to_excel(writer, index=False, sheet_name="Latest_HbA1c")
    buf.seek(0)

    st.download_button(
        "Download Latest HbA1c List (Excel)",
        data=buf,
        file_name=f"PC009_latest_hba1c_{year}_{quarter}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
else:
    st.info("Upload both files to calculate KPI.")
