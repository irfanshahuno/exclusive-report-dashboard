import io
import pandas as pd
import streamlit as st

from kpi.pc009_hba1c import compute_pc009

st.set_page_config(page_title="KPI Dashboard", layout="wide")
st.title("KPI Dashboard")

year = st.selectbox("Year", [2024, 2025, 2026], index=1)
quarter = st.selectbox("Quarter", ["Q1", "Q2", "Q3", "Q4"], index=3)

visit_file = st.file_uploader("Upload YEARLY VISIT file (.xlsx)", type=["xlsx"])
lab_file = st.file_uploader("Upload YEARLY LAB file (.xlsx)", type=["xlsx"])

process = st.button("Process KPI")

if process:
    if visit_file is None or lab_file is None:
        st.warning("Upload both files first.")
        st.stop()

    visits_df = pd.read_excel(visit_file)
    labs_df = pd.read_excel(lab_file)

    result, latest = compute_pc009(visits_df, labs_df, int(year), quarter)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Denominator", result["denominator"])
    c2.metric("Numerator", result["numerator"])
    c3.metric("Poor Control (>9)", result["poor_control"])
    c4.metric("No Test", result["no_test"])

    st.metric("PC009 %", f"{result['kpi_percent']}%")

    st.caption(
        f"Lab columns used → Code: {result['lab_code_col_used']} | "
        f"Value: {result['lab_value_col_used']} | "
        f"Date: {result['lab_date_col_used']}"
    )

    st.dataframe(latest.sort_values("HbA1c Date", ascending=False).head(100), use_container_width=True)

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        latest.to_excel(writer, index=False, sheet_name="PC009_Latest_HbA1c")
    buf.seek(0)

    st.download_button(
        "Download HbA1c Detail (Excel)",
        data=buf.getvalue(),
        file_name=f"PC009_detail_{year}_{quarter}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
