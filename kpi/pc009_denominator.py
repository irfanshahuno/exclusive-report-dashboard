import io
import pandas as pd
import streamlit as st

from kpi.pc009_denominator import compute_denominator

st.set_page_config(page_title="PC009 Denominator Only", layout="wide")
st.title("PC009 Denominator Only (Step-by-step counts)")

year = st.selectbox("Year", [2024, 2025, 2026], index=1)
quarter = st.selectbox("Quarter", ["Q1", "Q2", "Q3", "Q4"], index=3)

visit_file = st.file_uploader("Upload YEARLY VISIT file (.xlsx)", type=["xlsx"])

c1, c2, c3 = st.columns([1, 1, 2])
show_cols = c1.button("Show Columns")
process = c2.button("Process Denominator")
download_steps = c3.checkbox("Show step-by-step counts", value=True)

if show_cols:
    if visit_file is None:
        st.warning("Upload the VISIT file first.")
    else:
        df = pd.read_excel(visit_file)
        st.write("VISIT columns:", list(df.columns))
        if "Department" in df.columns:
            st.write("Top Department values (Top 20):")
            st.dataframe(
                df["Department"].astype(str).str.strip().value_counts().head(20).reset_index()
                .rename(columns={"index": "Department", "Department": "Count"}),
                use_container_width=True
            )

if process:
    if visit_file is None:
        st.warning("Upload the VISIT file first.")
        st.stop()

    visits_df = pd.read_excel(visit_file)

    denom_set, denom_detail, steps = compute_denominator(visits_df, int(year), quarter)

    st.metric("Denominator Count", len(denom_set))

    # Show step-by-step
    if download_steps:
        st.subheader("Processing Steps (Counts)")
        steps_df = pd.DataFrame(
            [{"Step": k, "Value": v} for k, v in steps.items()]
        )
        st.dataframe(steps_df, use_container_width=True)

    st.subheader("Denominator Patient List (Top 200)")
    st.dataframe(denom_detail.head(200), use_container_width=True)

    # Download denominator list
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        denom_detail.to_excel(writer, index=False, sheet_name="Denominator")
        if download_steps:
            steps_df.to_excel(writer, index=False, sheet_name="Steps")
    buf.seek(0)

    st.download_button(
        "Download Denominator + Steps (Excel)",
        data=buf.getvalue(),
        file_name=f"PC009_DENOM_{year}_{quarter}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
