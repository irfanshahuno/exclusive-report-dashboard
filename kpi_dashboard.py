import io
import pandas as pd
import streamlit as st

from kpi.pc009_hba1c import compute_pc009

st.set_page_config(page_title="KPI Dashboard", layout="wide")
st.title("KPI Dashboard (JAWDA)")

year = st.selectbox("Year", [2024, 2025, 2026], index=1)
quarter = st.selectbox("Quarter", ["Q1", "Q2", "Q3", "Q4"], index=3)

visit_file = st.file_uploader("Upload YEARLY VISIT file (.xlsx)", type=["xlsx"])
lab_file = st.file_uploader("Upload YEARLY LAB file (.xlsx)", type=["xlsx"])

c1, c2 = st.columns(2)
show_cols = c1.button("Show Uploaded Columns")
process = c2.button("Process KPI")

if show_cols:
    if visit_file:
        v = pd.read_excel(visit_file)
        st.write("VISIT columns:", list(v.columns))
    if lab_file:
        l = pd.read_excel(lab_file)
        st.write("LAB columns:", list(l.columns))

if process:
    if visit_file is None or lab_file is None:
        st.warning("Upload both files first.")
        st.stop()

    visits_df = pd.read_excel(visit_file)
    labs_df = pd.read_excel(lab_file)

    result, latest = compute_pc009(visits_df, labs_df, int(year), quarter)

    st.subheader("PC009 — HbA1c Poor Control (>9%) or No Test")

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Denominator", result["denominator"])
    k2.metric("Numerator", result["numerator"])
    k3.metric("Poor Control (>9)", result["poor_control"])
    k4.metric("No Test", result["no_test"])

    st.metric("PC009 %", f"{result['kpi_percent']}%")

    st.write("Latest HbA1c per patient (top 100):")
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
