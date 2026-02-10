import pandas as pd
from dateutil.relativedelta import relativedelta

from kpi.kpi_utils import (
    quarter_dates,
    make_patient_key,
    clean_result_value,
    PRIMARY_CARE_DEPTS
)

HBA1C_CPT = "83036"
DIAB_PREFIXES = ("E10", "E11", "E13", "O24")

def has_diabetes(principal, secondary):
    p = "" if pd.isna(principal) else str(principal).upper()
    s = "" if pd.isna(secondary) else str(secondary).upper()
    text = p + " " + s
    return any(code in text for code in DIAB_PREFIXES)

def compute_pc009(visits_df, labs_df, year, quarter):
    # ----------------- Dates -----------------
    q_start, q_end = quarter_dates(year, quarter)
    prior_9m_start = q_start - relativedelta(months=9)
    lab_12m_start = q_end - relativedelta(months=12)

    # ----------------- VISITS -----------------
    visits_df = visits_df.copy()
    visits_df["Visit Date"] = pd.to_datetime(visits_df["Visit Date"], errors="coerce")
    visits_df["Birth Date"] = pd.to_datetime(visits_df["Birth Date"], errors="coerce")

    visits_df["patient_key"] = make_patient_key(visits_df)
    visits_df["Department"] = visits_df["Department"].astype(str).str.strip()

    # Primary care only
    visits_df = visits_df[visits_df["Department"].isin(PRIMARY_CARE_DEPTS)]

    # Age at quarter start
    visits_df["Age"] = (q_start - visits_df["Birth Date"]).dt.days / 365.25

    # Diabetes flag
    visits_df["is_diab"] = visits_df.apply(
        lambda r: has_diabetes(r["ICD (Principal)"], r["ICD (Secondary)"]),
        axis=1
    )

    # -------- Quarter diabetics (candidate) --------
    q_vis = visits_df[
        (visits_df["Visit Date"].between(q_start, q_end)) &
        (visits_df["Age"].between(18, 75)) &
        (visits_df["is_diab"])
    ]

    candidate_patients = set(q_vis["patient_key"].dropna())

    # -------- Prior 9 months eligibility --------
    p9_vis = visits_df[
        (visits_df["Visit Date"].between(prior_9m_start, q_start)) &
        (visits_df["is_diab"])
    ]

    visit_counts = p9_vis.groupby("patient_key")["Visit ID"].nunique()
    eligible_patients = set(visit_counts[visit_counts >= 2].index)

    denominator_patients = candidate_patients.intersection(eligible_patients)

    # ----------------- LABS -----------------
    labs_df = labs_df.copy()
    labs_df["Visit Date"] = pd.to_datetime(labs_df["Visit Date"], errors="coerce")
    labs_df["patient_key"] = make_patient_key(labs_df)
    labs_df["CPT Code"] = labs_df["CPT Code"].astype(str).str.strip()

    labs_df["Result Value"] = clean_result_value(labs_df["Result Value"])

    hba = labs_df[
        (labs_df["CPT Code"] == HBA1C_CPT) &
        (labs_df["Visit Date"].between(lab_12m_start, q_end)) &
        (labs_df["patient_key"].isin(denominator_patients))
    ]

    # Most recent HbA1c
    latest = (
        hba.sort_values("Visit Date")
           .groupby("patient_key", as_index=False)
           .tail(1)
    )

    tested_patients = set(latest["patient_key"])
    poor_control_patients = set(
        latest.loc[latest["Result Value"] > 9, "patient_key"]
    )

    no_test_patients = denominator_patients - tested_patients
    numerator_patients = poor_control_patients.union(no_test_patients)

    # ----------------- Result -----------------
    result = {
        "denominator": len(denominator_patients),
        "numerator": len(numerator_patients),
        "poor_control": len(poor_control_patients),
        "no_test": len(no_test_patients),
        "kpi_percent": round(
            (len(numerator_patients) / len(denominator_patients) * 100)
            if denominator_patients else 0, 2
        )
    }

    return result, latest

