import pandas as pd

PRIMARY_CARE_DEPTS = {"General Medicine", "Family Medicine"}

def quarter_dates(year, quarter):
    if quarter == "Q1":
        return pd.Timestamp(year, 1, 1), pd.Timestamp(year, 3, 31)
    if quarter == "Q2":
        return pd.Timestamp(year, 4, 1), pd.Timestamp(year, 6, 30)
    if quarter == "Q3":
        return pd.Timestamp(year, 7, 1), pd.Timestamp(year, 9, 30)
    if quarter == "Q4":
        return pd.Timestamp(year, 10, 1), pd.Timestamp(year, 12, 31)
    raise ValueError("Invalid quarter")

def make_patient_key(df):
    # Prefer EMR No, fallback to Emirates ID
    emr = df.get("EMR No", "").astype(str).str.strip()
    eid = df.get("Emirates ID", "").astype(str).str.strip()
    return emr.where(emr.notna() & (emr != "") & (emr.str.lower() != "nan"), eid)

def clean_numeric(series):
    s = series.astype(str).str.replace("%", "", regex=False).str.strip()
    return pd.to_numeric(s, errors="coerce")
