import pandas as pd
from dateutil.relativedelta import relativedelta

from kpi.kpi_utils import quarter_dates, make_patient_key, clean_numeric, PRIMARY_CARE_DEPTS

HBA1C_CODE = "83036"
DIAB_PREFIXES = ("E10", "E11", "E13", "O24")

def has_diabetes(principal, secondary):
    p = "" if pd.isna(principal) else str(principal).upper()
    s = "" if pd.isna(secondary) else str(secondary).upper()
    text = p + " " + s
    return any(pref in text for pref in DIAB_PREFIXES)

def compute_pc009(visits_df, labs_df, year, quarter):
    # ---------------- Date windows ----------------
    q_start, q_end = quarter_dates(year, quarter)
    prior_9m_start = q_start - relativedelta(months=9)
    lab_12m_start = q_end - relativedelta(months=12)

    # ---------------- VISITS ----------------
    v = visits_df.copy()

    needed_v = ["Visit Date", "Birth Date", "Department", "Visit ID", "ICD (Principal)", "ICD (Secondary)"]
    missing_v = [c for c in needed_v if c not in v.columns]
    if missing_v:
        raise KeyError(f"VISIT file missing columns: {missing_v}")

    v["Visit Date"] = pd.to_datetime(v["Visit Date"], errors="coerce")
    v["Birth Date"] = pd.to_datetime(v["Birth Date"], errors="coerce")
    v["Department"] = v["Department"].astype(str).str.strip()

    v["patient_key"] = make_patient_key(v)

    # Primary care only
    v = v[v["Department"].isin(PRIMARY_CARE_DEPTS)].copy()

    # Age at quarter start
    v["Age"] = (q_start - v["Birth Date"]).dt.days / 365.25

    # Diabetes flag
    v["is_diab"] = v.apply(lambda r: has_diabetes(r["ICD (Principal)"], r["ICD (Secondary)"]), axis=1)

    # Quarter diabetics
    q_vis = v[
        (v["Visit Date"].between(q_start, q_end)) &
        (v["Age"].between(18, 75)) &
        (v["is_diab"])
    ]
    candidate_patients = set(q_vis["patient_key"].dropna().astype(str))

    # Prior 9 months eligibility (>=2 diabetes visits)
    p9 = v[
        (v["Visit Date"].between(prior_9m_start, q_start)) &
        (v["is_diab"])
    ]
    counts = p9.groupby("patient_key")["Visit ID"].nunique()
    eligible_patients = set(counts[counts >= 2].index.astype(str))

    denominator_patients = candidate_patients.intersection(eligible_patients)

    # ---------------- LABS ----------------
    l = labs_df.copy()

    # HARD-MAPPED to your lab headers:
    # Code, Loinc Value, Visit Date
    needed_l = ["Code", "Loinc Value", "Visit Date"]
    missing_l = [c for c in needed_l if c not in l.columns]
    if missing_l:
        raise KeyError(f"LAB file missing columns: {missing_l}. Found: {list(l.columns)}")

    l["Visit Date"] = pd.to_datetime(l["Visit Date"], errors="coerce")
    l["patient_key"] = make_patient_key(l)

    l["Code"] = l["Code"].astype(str).str.strip()
    l["Loinc Value"] = clean_numeric(l["Loinc Value"])

    # HbA1c within last 12 months
    hba = l[
        (l["Code"] == HBA1C_CODE) &
        (l["Visit Date"].between(lab_12m_start, q_end)) &
        (l["patient_key"].astype(str).isin(denominator_patients))
    ].copy()

    # Latest HbA1c per patient
    latest = (
        hba.sort_values("Visit Date")
           .groupby("patient_key", as_index=False)
           .tail(1)
    )

    tested = set(latest["patient_key"].astype(str))
    poor = set(latest.loc[latest["Loinc Value"] > 9.0, "patient_key"].astype(str))
    no_test = set(denominator_patients) - tested
    numerator = poor.union(no_test)

    latest = latest.rename(columns={
        "Visit Date": "HbA1c Date",
        "Loinc Value": "HbA1c Value",
        "Code": "HbA1c Code"
    })

    result = {
        "denominator": len(denominator_patients),
        "numerator": len(numerator),
        "poor_control": len(poor),
        "no_test": len(no_test),
        "kpi_percent": round((len(numerator) / len(denominator_patients) * 100) if denominator_patients else 0, 2),
    }

    return result, latest
