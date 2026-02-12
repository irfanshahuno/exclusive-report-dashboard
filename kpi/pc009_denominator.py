import pandas as pd
from dateutil.relativedelta import relativedelta

# Diabetes prefixes (matches guideline: E10/E11/E13 and O24 series)
DIAB_PREFIXES = ("E10", "E11", "E13", "O24")

# Denominator exclusions (from your guideline text)
GESTATIONAL_EXACT = {
    "O24.410","O24.414","O24.415","O24.419","O24.420",
    "O24.424","O24.425","O24.429","O24.430","O24.434","O24.435","O24.439"
}

def quarter_dates(year: int, quarter: str):
    quarter = str(quarter).upper().strip()
    if quarter == "Q1":
        return pd.Timestamp(year, 1, 1), pd.Timestamp(year, 3, 31)
    if quarter == "Q2":
        return pd.Timestamp(year, 4, 1), pd.Timestamp(year, 6, 30)
    if quarter == "Q3":
        return pd.Timestamp(year, 7, 1), pd.Timestamp(year, 9, 30)
    if quarter == "Q4":
        return pd.Timestamp(year, 10, 1), pd.Timestamp(year, 12, 31)
    raise ValueError("Quarter must be Q1/Q2/Q3/Q4")

def make_patient_key(df: pd.DataFrame) -> pd.Series:
    # Prefer EMR No. fallback Emirates ID.
    emr = df["EMR No"].astype(str).str.strip()
    eid = df["Emirates ID"].astype(str).str.strip()
    emr_ok = emr.notna() & (emr != "") & (emr.str.lower() != "nan")
    return emr.where(emr_ok, eid)

def _norm(x) -> str:
    return "" if pd.isna(x) else str(x).upper()

def has_diabetes(principal, secondary) -> bool:
    text = _norm(principal) + " " + _norm(secondary)
    return any(pref in text for pref in DIAB_PREFIXES)

def has_exclusion(principal, secondary) -> bool:
    text = _norm(principal) + " " + _norm(secondary)
    # PCOS
    if "E28.2" in text:
        return True
    # Gestational DM exact list
    if any(code in text for code in GESTATIONAL_EXACT):
        return True
    # Steroid induced diabetes prefix
    if "E09" in text:
        return True
    return False

def compute_denominator(visits_df: pd.DataFrame, year: int, quarter: str):
    """
    Returns:
      denom_patients_set (set[str]),
      denom_detail_df (DataFrame) - one row per patient in denominator,
      steps (dict) - step-by-step counts
    """

    steps = {}

    required = [
        "Visit Date", "Birth Date", "Department", "Visit ID",
        "ICD (Principal)", "ICD (Secondary)",
        "EMR No", "Emirates ID"
    ]
    missing = [c for c in required if c not in visits_df.columns]
    if missing:
        raise KeyError(f"VISIT file missing columns: {missing}. Found: {list(visits_df.columns)}")

    v = visits_df.copy()
    steps["0_total_rows"] = len(v)

    # Your dates are day-first (01-01-2025)
    v["Visit Date"] = pd.to_datetime(v["Visit Date"], errors="coerce", dayfirst=True)
    v["Birth Date"] = pd.to_datetime(v["Birth Date"], errors="coerce", dayfirst=True)
    v["Department"] = v["Department"].astype(str).str.strip()
    v["patient_key"] = make_patient_key(v)

    steps["1_rows_with_valid_visit_date"] = int(v["Visit Date"].notna().sum())
    steps["1_unique_patients_total"] = int(v["patient_key"].nunique())

    # ✅ Department filter fixed for your data:
    # Your data shows "GENERAL PRACTICE DEPARTMENT"
    dept = v["Department"].astype(str).str.upper().str.strip()
    v = v[
        dept.str.contains("GENERAL", na=False) |
        dept.str.contains("FAMILY", na=False) |
        dept.str.contains("PRACTICE", na=False)
    ].copy()

    steps["2_after_department_rows"] = len(v)
    steps["2_after_department_unique_patients"] = int(v["patient_key"].nunique())

    # Quarter windows
    q_start, q_end = quarter_dates(year, quarter)
    prior_9m_start = q_start - relativedelta(months=9)

    # Age at quarter start
    v["Age_at_qstart"] = (q_start - v["Birth Date"]).dt.days / 365.25
    steps["3_rows_with_valid_birth_date"] = int(v["Birth Date"].notna().sum())

    # Flags
    v["is_diab"] = v.apply(lambda r: has_diabetes(r["ICD (Principal)"], r["ICD (Secondary)"]), axis=1)
    v["is_excl"] = v.apply(lambda r: has_exclusion(r["ICD (Principal)"], r["ICD (Secondary)"]), axis=1)

    steps["4_diabetes_rows_overall"] = int(v["is_diab"].sum())
    steps["4_diabetes_unique_patients_overall"] = int(v.loc[v["is_diab"], "patient_key"].nunique())

    # Quarter diabetic candidates (18-75)
    q_vis = v[
        (v["Visit Date"].between(q_start, q_end)) &
        (v["Age_at_qstart"].between(18, 75)) &
        (v["is_diab"])
    ].copy()

    steps["5_quarter_diab_rows"] = len(q_vis)
    steps["5_quarter_diab_unique_patients"] = int(q_vis["patient_key"].nunique())

    candidate_patients = set(q_vis["patient_key"].dropna().astype(str))

    # Prior 9 months: at least 2 outpatient visits with diabetes
    p9_vis = v[
        (v["Visit Date"].between(prior_9m_start, q_start)) &
        (v["is_diab"])
    ].copy()

    prior_counts = p9_vis.groupby("patient_key")["Visit ID"].nunique()
    eligible_patients = set(prior_counts[prior_counts >= 2].index.astype(str))

    steps["6_prior9m_diab_unique_patients_any"] = int(p9_vis["patient_key"].nunique())
    steps["6_prior9m_eligible_patients_ge2visits"] = len(eligible_patients)

    denom_patients = candidate_patients.intersection(eligible_patients)
    steps["7_after_continuity_denominator_patients"] = len(denom_patients)

    # Exclusions anywhere in (prior 9 months + quarter)
    denom_window = v[v["Visit Date"].between(prior_9m_start, q_end)]
    excl_patients = set(denom_window.loc[denom_window["is_excl"], "patient_key"].dropna().astype(str))

    steps["8_exclusion_patients_found"] = len(excl_patients)

    denom_patients = denom_patients - excl_patients
    steps["9_final_denominator_patients"] = len(denom_patients)

    # Detail: pick first quarter record per patient
    detail = q_vis.sort_values("Visit Date").drop_duplicates("patient_key").copy()

    for col in ["Name", "Doctor"]:
        if col not in detail.columns:
            detail[col] = ""

    detail["prior_9m_diab_visits"] = detail["patient_key"].map(prior_counts).fillna(0).astype(int)
    detail = detail[detail["patient_key"].astype(str).isin(denom_patients)]

    keep_cols = [
        "patient_key", "EMR No", "Emirates ID", "Name", "Doctor",
        "Department", "Age_at_qstart", "prior_9m_diab_visits"
    ]
    detail = detail[keep_cols].sort_values(["prior_9m_diab_visits", "Name"], ascending=[False, True])

    return denom_patients, detail, steps
