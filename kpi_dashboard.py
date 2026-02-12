import io
import pandas as pd
import streamlit as st

from kpi.pc009_denominator import compute_denominator

st.set_page_config(page_title="Denominator KPI", layout="wide")
st.title("PC009 Denominator Only")

year = st.selectbox("Year", [2024, 2025, 2026], index=1)
quarter = st.selectbox("Quarter", ["Q1", "Q2", "Q3", "Q4"], index=3)

visit_file = st.file_uploader("Upload YEARLY VISIT file (.xlsx)", type=["xlsx"])

col1, col2 = st.columns(2)
show_cols = col1.button("Show Columns")
process = col2.button("Process Denominator")

if show_cols and visit_file is not None:
    df = pd.read_excel(visit_file)
    st.write("VISIT columns:", list(df.columns))

if process:
    if visit_file is None:
        st.warning("Please upload the yearly VISIT file first.")
        st.stop()

    visits_df = pd.read_excel(visit_file)

    denom_set, denom_detail = compute_denominator(visits_df, int(year), quarter)

    st.metric("Denominator Count", len(denom_set))
    st.dataframe(denom_detail.head(200), use_container_width=True)

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        denom_detail.to_excel(writer, index=False, sheet_name="Denominator")
    buf.seek(0)

    st.download_button(
        "Download Denominator List (Excel)",
        data=buf.getvalue(),
        file_name=f"PC009_DENOM_{year}_{quarter}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
