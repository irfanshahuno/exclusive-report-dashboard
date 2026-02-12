import pandas as pd
from dateutil.relativedelta import relativedelta

PRIMARY_CARE_DEPTS = {"General Medicine", "Family Medicine"}

DIAB_PREFIXES = ("E10", "E11", "E13", "O24")

GESTATIONAL_EXACT = {
    "O24.410","O24.414","O24.415","O24.419","O24.420",
    "O24.424","O24.425","O24.429","O24.430","O24.434","O24.435","O24.439"
}

def quarter_dates(year: int, quarter: str):
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
    emr = df["EMR No"].astype(str).str.strip()
    eid = df["Emirates ID"].astype(str).str.strip()
    return emr.where(emr.notna() & (emr != "") & (emr.str.lower() != "nan"), eid)

def _norm(x) -> str:
    return "" if pd.isna(x) else str(x).upper()

def has_diabetes(principal, secondary) -> bool:
    text = _norm(principal) + " " + _norm(secondary)
    return any(p in text for p in DIAB_PREFIXES)

def has_exclusion(principal, secondary) -> bool:
    text = _norm(principal) + " " + _norm(secondary)
    if "E28.2" in text:  # PCOS
        return True
    if any(code in text for code in GESTATIONAL_EXACT):
        return True
    if "E09" in text:    # Steroid-induced prefix
        return True
    return False

def compute_denominator(visits_df: pd.DataFrame, year: int, quarter: str):
    """
    Returns:
      denom_patients_set, denom_detail_df
    """

    # ----- required columns -----
    required = ["Visit Date", "Birth Date", "Department", "Visit ID", "ICD (Principal)", "ICD (Secondary)", "EMR No", "Emirates ID"]
    missing = [c for c in required if c not in visits_df.columns]
    if missing:
        raise KeyError(f"VISIT file missing columns: {missing}")

    q_start, q_end = quarter_dates(year, quarter)
    prior_9m_start = q_start - relativedelta(months=9)

    v = visits_df.copy()
    v["Visit Date"] = pd.to_datetime(v["Visit Date"], errors="coerce")
    v["Birth Date"] = pd.to_datetime(v["Birth Date"], errors="coerce")
    v["Department"] = v["Department"].astype(str).str.strip()

    v["patient_key"] = make_patient_key(v)

    # Primary care only
    v = v[v["Department"].isin(PRIMARY_CARE_DEPTS)].copy()

    # Age at quarter start
    v["Age_at_qstart"] = (q_start - v["Birth Date"]).dt.days / 365.25

    # Flags
    v["is_diab"] = v.apply(lambda r: has_diabetes(r["ICD (Principal)"], r["ICD (Secondary)"]), axis=1)
    v["is_excl"] = v.apply(lambda r: has_exclusion(r["ICD (Principal)"], r["ICD (Secondary)"]), axis=1)

    # ----- Quarter candidates -----
    q_vis = v[
        (v["Visit Date"].between(q_start, q_end)) &
        (v["Age_at_qstart"].between(18, 75)) &
        (v["is_diab"])
    ].copy()

    candidate_patients = set(q_vis["patient_key"].dropna().astype(str))

    # ----- Prior 9 months eligibility: >=2 diabetes visits -----
    p9_vis = v[
        (v["Visit Date"].between(prior_9m_start, q_start)) &
        (v["is_diab"])
    ].copy()

    prior_counts = p9_vis.groupby("patient_key")["Visit ID"].nunique()
    eligible_patients = set(prior_counts[prior_counts >= 2].index.astype(str))

    # Denominator = quarter candidates who also have >=2 prior visits
    denom_patients = candidate_patients.intersection(eligible_patients)

    # ----- Exclusions anywhere in denominator timeframe (prior 9m + quarter) -----
    denom_window = v[v["Visit Date"].between(prior_9m_start, q_end)]
    excl_patients = set(denom_window.loc[denom_window["is_excl"], "patient_key"].dropna().astype(str))

    denom_patients = denom_patients - excl_patients

    # ----- Detail output -----
    base = q_vis.sort_values("Visit Date").drop_duplicates("patient_key")
    detail = base[["patient_key", "EMR No", "Emirates ID", "Name", "Age_at_qstart", "Department", "Doctor"]].copy()
    detail["prior_9m_diab_visits"] = detail["patient_key"].map(prior_counts).fillna(0).astype(int)
    detail["in_denominator"] = detail["patient_key"].astype(str).isin(denom_patients)

    detail = detail[detail["in_denominator"]].sort_values(["prior_9m_diab_visits", "Name"], ascending=[False, True])

    return denom_patients, detail

# --- Example run (local) ---
if __name__ == "__main__":
    VISIT_FILE = "yearly_visits.xlsx"  # change path
    year = 2025
    quarter = "Q4"

    df = pd.read_excel(VISIT_FILE)
    denom_set, denom_detail = compute_denominator(df, year, quarter)

    print("DENOMINATOR COUNT:", len(denom_set))
    denom_detail.to_excel(f"PC009_DENOM_{year}_{quarter}.xlsx", index=False)
    print(f"Saved: PC009_DENOM_{year}_{quarter}.xlsx")
