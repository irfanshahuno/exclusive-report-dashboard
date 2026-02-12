import io
import pandas as pd
import streamlit as st

# Import step version (make sure pc009_denominator_FIXED is deployed as kpi/pc009_denominator.py
# and it contains compute_denominator_with_steps)
from kpi.pc009_denominator import compute_denominator_with_steps

st.set_page_config(page_title="Denominator KPI", layout="wide")
st.title("PC009 Denominator Only")

year = st.selectbox("Year", [2024, 2025, 2026], index=1)
quarter = st.selectbox("Quarter", ["Q1", "Q2", "Q3", "Q4"], index=3)

visit_file = st.file_uploader("Upload YEARLY VISIT file (.xlsx)", type=["xlsx"])

col1, col2 = st.columns(2)
show_cols = col1.button("Show Columns")
process = col2.button("Process Denominator")

# Readable step labels
STEP_LABELS = {
    "0_total_rows": "0) Total rows in file",
    "1_rows_with_valid_visit_date": "1) Rows with valid Visit Date",
    "1_unique_patients_total": "1b) Unique patients overall",
    "2_after_department_rows": "2) After Department filter (rows)",
    "2_after_department_unique_patients": "2b) After Department filter (unique patients)",
    "3_rows_with_valid_birth_date": "3) Rows with valid Birth Date",
    "4_diabetes_rows_overall": "4) Diabetes coded rows overall",
    "4_diabetes_unique_patients_overall": "4b) Diabetes coded unique patients",
    "5_quarter_diab_rows": "5) Quarter diabetes rows (Age 18-75)",
    "5_quarter_diab_unique_patients": "5b) Quarter diabetes unique patients",
    "6_prior9m_diab_unique_patients_any": "6) Prior 9 months diabetes unique patients",
    "6_prior9m_eligible_patients_ge2visits": "6b) Prior 9 months eligible patients (>=2 visits)",
    "7_after_continuity_denominator_patients": "7) After continuity intersection",
    "8_exclusion_patients_found": "8) Exclusion patients found",
    "9_final_denominator_patients": "9) FINAL Denominator Patients",
}

if show_cols and visit_file is not None:
    df = pd.read_excel(visit_file)
    st.write("VISIT columns:", list(df.columns))

if process:
    if visit_file is None:
        st.warning("Please upload the yearly VISIT file first.")
        st.stop()

    visits_df = pd.read_excel(visit_file)

    # ✅ Step-by-step version
    denom_set, denom_detail, steps = compute_denominator_with_steps(visits_df, int(year), quarter)

    st.metric("Denominator Count", len(denom_set))

    st.subheader("Denominator Step-by-Step Breakdown")
    step_rows = [{"Step": STEP_LABELS.get(k, k), "Count": v} for k, v in steps.items()]
    steps_df = pd.DataFrame(step_rows)
    st.dataframe(steps_df, use_container_width=True)

    st.subheader("Denominator Patient Details")
    st.dataframe(denom_detail, use_container_width=True)

    # Download Excel with 2 sheets: Denominator + Steps
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        denom_detail.to_excel(writer, index=False, sheet_name="Denominator")
        steps_df.to_excel(writer, index=False, sheet_name="Steps")
    buf.seek(0)

    st.download_button(
        "Download Denominator List (Excel)",
        data=buf.getvalue(),
        file_name=f"PC009_DENOM_{year}_{quarter}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
