import pandas as pd
from dateutil.relativedelta import relativedelta

from kpi.kpi_utils import quarter_dates, make_patient_key, PRIMARY_CARE_DEPTS

DIAB_PREFIXES = ("E10", "E11", "E13", "O24")
HBA1C_CODE = "83036"

# -------- helpers --------
def _pick_first_existing(df, candidates):
    for c in candidates:
        if c in df.columns:
            return c
    return None

def _require_col(df, col, label):
    if col is None:
        raise KeyError(f"Missing required {label} column. Available columns: {list(df.columns)}")

def _has_diabetes(principal, secondary):
    p = "" if pd.isna(principal) else str(principal).upper()
    s = "" if pd.isna(secondary) else str(secondary).upper()
    text = p + " " + s
    return any(code in text for code in DIAB_PREFIXES)

def _clean_numeric(series):
    s = series.astype(str).str.replace("%", "", regex=False).str.strip()
    return pd.to_numeric(s, errors="coerce")

def compute_pc009(visits_df, labs_df, year, quarter):
    # ---------- Date windows ----------
    q_start, q_end = quarter_dates(year, quarter)
    prior_9m_start = q_start - relativedelta(months=9)
    lab_12m_start = q_end - relativedelta(months=12)

    # ================= VISITS =================
    v = visits_df.copy()

    # Required visit cols (your visit files have these)
    _require_col(v, _pick_first_existing(v, ["Visit Date"]), "Visit Date")
    _require_col(v, _pick_first_existing(v, ["Birth Date"]), "Birth Date")
    _require_col(v, _pick_first_existing(v, ["Department"]), "Department")
    _require_col(v, _pick_first_existing(v, ["Visit ID"]), "Visit ID")
    _require_col(v, _pick_first_existing(v, ["ICD (Principal)"]), "ICD (Principal)")
    _require_col(v, _pick_first_existing(v, ["ICD (Secondary)"]), "ICD (Secondary)")

    v["Visit Date"] = pd.to_datetime(v["Visit Date"], errors="coerce")
    v["Birth Date"] = pd.to_datetime(v["Birth Date"], errors="coerce")
    v["Department"] = v["Department"].astype(str).str.strip()

    v["patient_key"] = make_patient_key(v)

    # Primary care only
    v = v[v["Department"].isin(PRIMARY_CARE_DEPTS)].copy()

    # Age at quarter start
    v["Age"] = (q_start - v["Birth Date"]).dt.days / 365.25

    # diabetes flag
    v["is_diab"] = v.apply(lambda r: _has_diabetes(r["ICD (Principal)"], r["ICD (Secondary)"]), axis=1)

    # Quarter candidates
    q_vis = v[
        (v["Visit Date"].between(q_start, q_end)) &
        (v["Age"].between(18, 75)) &
        (v["is_diab"])
    ]
    candidate_patients = set(q_vis["patient_key"].dropna())

    # Prior 9 months (>=2 diabetic visits)
    p9 = v[
        (v["Visit Date"].between(prior_9m_start, q_start)) &
        (v["is_diab"])
    ]
    counts = p9.groupby("patient_key")["Visit ID"].nunique()
    eligible_patients = set(counts[counts >= 2].index)

    denominator_patients = candidate_patients.intersection(eligible_patients)

    # ================= LABS =================
    l = labs_df.copy()

    # Auto-detect lab columns based on your screenshots
    code_col = _pick_first_existing(l, ["Code", "CPT Code", "Service Code"])
    value_col = _pick_first_existing(l, ["Loinc Value", "Result Value", "Value", "Result"])
    date_col = _pick_first_existing(l, ["Visit Date", "Result Date", "Invoice Date", "Service Date"])

    _require_col(l, code_col, "Lab Code (Code/CPT Code)")
    _require_col(l, value_col, "HbA1c Value (Loinc Value/Result Value)")
    _require_col(l, date_col, "Lab Date (Visit Date/Result Date/Invoice Date)")

    l[date_col] = pd.to_datetime(l[date_col], errors="coerce")
    l["patient_key"] = make_patient_key(l)

    l[code_col] = l[code_col].astype(str).str.strip()
    l[value_col] = _clean_numeric(l[value_col])

    # Filter HbA1c records within 12 months
    hba = l[
        (l[code_col] == HBA1C_CODE) &
        (l[date_col].between(lab_12m_start, q_end)) &
        (l["patient_key"].isin(denominator_patients))
    ].copy()

    # Latest HbA1c per patient
    latest = (
        hba.sort_values(date_col)
           .groupby("patient_key", as_index=False)
           .tail(1)
    )

    tested_patients = set(latest["patient_key"])
    poor_control_patients = set(latest.loc[latest[value_col] > 9.0, "patient_key"])

    no_test_patients = denominator_patients - tested_patients
    numerator_patients = poor_control_patients.union(no_test_patients)

    # Add friendly columns for download
    latest = latest.rename(columns={date_col: "HbA1c Date", value_col: "HbA1c Value", code_col: "HbA1c Code"})

    result = {
        "denominator": len(denominator_patients),
        "numerator": len(numerator_patients),
        "poor_control": len(poor_control_patients),
        "no_test": len(no_test_patients),
        "kpi_percent": round((len(numerator_patients) / len(denominator_patients) * 100) if denominator_patients else 0, 2),
        "lab_code_col_used": code_col,
        "lab_value_col_used": value_col,
        "lab_date_col_used": date_col,
    }

    return result, latest
