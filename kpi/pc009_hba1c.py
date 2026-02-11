#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PC009 - Diabetes: HbA1c Poor Control Rate (>9%) OR No test result (last 12 months)

This version is **robust**:
- It will NOT crash on minor column-name differences.
- It auto-detects common column aliases (CPT/LOINC/Result/Date/Patient).
- It gives a clear KeyError only if it truly can't find any usable columns.

Expected inputs:
- visits_df: outpatient visits (must contain a patient identifier + visit date + diagnosis info)
- labs_df: lab records (must contain a patient identifier + date + HbA1c identifier + result)
"""

from __future__ import annotations

import re
import pandas as pd
import numpy as np
from datetime import datetime, timedelta


# -----------------------------
# Helpers
# -----------------------------
def _normalize_cols(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    return df


def _pick_by_names(df: pd.DataFrame, names: list[str]) -> str | None:
    """Pick first matching column by exact name OR case-insensitive match."""
    if df is None or df.empty:
        return None

    cols = list(df.columns)
    lower_map = {c.lower(): c for c in cols}

    for n in names:
        if n in cols:
            return n
        if n.lower() in lower_map:
            return lower_map[n.lower()]
    return None


def _require_any(df: pd.DataFrame, label: str, options: list[str]) -> str:
    col = _pick_by_names(df, options)
    if not col:
        raise KeyError(
            f"{label} missing required column. Tried: {options}. Found: {list(df.columns)}"
        )
    return col


def _to_datetime_safe(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s, errors="coerce")


def _quarter_range(year: int, quarter: int):
    if quarter not in (1, 2, 3, 4):
        raise ValueError("quarter must be 1..4")
    start_month = (quarter - 1) * 3 + 1
    start = pd.Timestamp(year=year, month=start_month, day=1)
    end = (start + pd.offsets.QuarterEnd())  # end of quarter
    return start.normalize(), end.normalize()


def _numeric_result(series: pd.Series) -> pd.Series:
    # Extract first number from strings like "9.5", "HbA1c 10.2%", ">=9"
    def _parse(x):
        if pd.isna(x):
            return np.nan
        if isinstance(x, (int, float, np.number)):
            return float(x)
        m = re.search(r"(-?\d+(\.\d+)?)", str(x))
        return float(m.group(1)) if m else np.nan

    return series.map(_parse)


def _looks_like_diabetes(dx_text: str) -> bool:
    """Detect diabetes ICD-10 codes E10*, E11*, E13* etc or 'diab' text."""
    if not dx_text:
        return False
    t = str(dx_text).upper()
    if "DIAB" in t:
        return True
    # ICD-10 E10, E11, E13 (and E08, E09 sometimes)
    return bool(re.search(r"\bE(08|09|10|11|13)\d", t)) or bool(
        re.search(r"\bE(08|09|10|11|13)\b", t)
    )


# Common HbA1c identifiers
HBA1C_CPT = {"83036", "83037"}  # 83036 is most common; 83037 sometimes used
HBA1C_LOINC = {
    # Common HbA1c LOINC codes
    "4548-4",   # Hemoglobin A1c/Hemoglobin.total in Blood
    "17856-6",  # HbA1c/Hemoglobin.total in Blood by HPLC
    "41995-2",
    "59261-8",
    "62388-4",
}


def _is_hba1c_row(code: str | None, loinc: str | None, desc: str | None) -> bool:
    code_s = str(code).strip() if code is not None else ""
    loinc_s = str(loinc).strip() if loinc is not None else ""
    desc_s = str(desc).strip().lower() if desc is not None else ""

    if code_s in HBA1C_CPT:
        return True
    if loinc_s in HBA1C_LOINC:
        return True
    if "hba1c" in desc_s or "a1c" in desc_s or "glycosylated" in desc_s:
        return True
    return False


# -----------------------------
# Main KPI
# -----------------------------
def compute_pc009(visits_df: pd.DataFrame, labs_df: pd.DataFrame, year: int, quarter: int):
    """
    Returns:
      result_df: DataFrame with Metric/Value
      latest: dict with useful "latest" dates/info
    """
    v = _normalize_cols(visits_df)
    l = _normalize_cols(labs_df)

    q_start, q_end = _quarter_range(year, quarter)
    lookback_start = (q_end - pd.DateOffset(months=12)) + pd.DateOffset(days=1)  # last 12 months window start

    # ---- Visits: required columns (robust) ----
    v_patient = _require_any(
        v,
        "VISITS",
        ["Patient ID", "PatientID", "MRN", "EMR No", "Emr No", "EMR No.", "Medical Record Number", "Member ID"],
    )
    v_date = _require_any(
        v,
        "VISITS",
        ["Visit Date", "Date", "Encounter Date", "Service Date", "VisitDate"],
    )

    # Diagnosis columns (we try multiple; if none exist, we can't compute denominator)
    dx_cols_try = [
        "Principal DX", "Principal Diagnosis", "Primary DX", "Primary Diagnosis", "DX1", "Diagnosis",
        "Secondary DX", "Secondary Diagnosis", "DX2", "DX3", "All DX", "ICD", "ICD Code", "ICD10",
    ]
    dx_cols = [c for c in ([_pick_by_names(v, [n]) for n in dx_cols_try]) if c]
    dx_cols = list(dict.fromkeys(dx_cols))  # unique, preserve order

    if not dx_cols:
        raise KeyError(
            f"VISITS missing diagnosis columns (needed to identify diabetes patients). "
            f"Tried common names like {dx_cols_try}. Found: {list(v.columns)}"
        )

    # Age filter: best effort
    age_col = _pick_by_names(v, ["Age", "Patient Age", "Age (Years)", "Years"])
    dob_col = _pick_by_names(v, ["DOB", "Date of Birth", "Birth Date"])

    # Parse dates
    v[v_date] = _to_datetime_safe(v[v_date])

    # Keep only visits in the reporting quarter (denominator defined as diabetics with a visit in quarter)
    v_q = v[(v[v_date] >= q_start) & (v[v_date] <= q_end)].copy()

    # Identify diabetes visits/patients
    def _row_dx_text(row) -> str:
        parts = []
        for c in dx_cols:
            val = row.get(c, "")
            if pd.notna(val) and str(val).strip():
                parts.append(str(val))
        return " | ".join(parts)

    v_q["_dx_text"] = v_q.apply(_row_dx_text, axis=1)
    v_q["_is_diabetes"] = v_q["_dx_text"].map(_looks_like_diabetes)

    v_diab = v_q[v_q["_is_diabetes"]].copy()

    # Apply age filter if possible (18-75)
    if age_col:
        v_diab[age_col] = pd.to_numeric(v_diab[age_col], errors="coerce")
        v_diab = v_diab[(v_diab[age_col] >= 18) & (v_diab[age_col] <= 75)]
    elif dob_col:
        v_diab[dob_col] = _to_datetime_safe(v_diab[dob_col])
        # age at quarter end
        v_diab["_age"] = (q_end - v_diab[dob_col]).dt.days / 365.25
        v_diab = v_diab[(v_diab["_age"] >= 18) & (v_diab["_age"] <= 75)]
    # else: no age info → proceed without age filter (better than failing)

    denom_patients = v_diab[v_patient].dropna().astype(str).unique()
    denom = int(len(denom_patients))

    # ---- Labs: required columns (robust) ----
    l_patient = _require_any(
        l,
        "LAB",
        ["Patient ID", "PatientID", "MRN", "EMR No", "Emr No", "EMR No.", "Medical Record Number", "Member ID"],
    )
    l_date = _require_any(
        l,
        "LAB",
        ["Visit Date", "Order Date", "Service Date", "Result Date", "Lab Date", "Date", "Performed Date"],
    )

    # HbA1c identifier columns: at least one of CPT/LOINC/Description should exist
    l_cpt = _pick_by_names(l, ["Lab Code (Code/CPT Code)", "Lab Code", "CPT", "CPT Code", "Test Code", "Code"])
    l_loinc = _pick_by_names(l, ["Loinc Value", "LOINC", "LOINC Code", "Loinc", "LoincValue"])
    l_desc = _pick_by_names(l, ["Description", "Test Name", "Lab Test", "Lab Name", "Item Name"])

    if not any([l_cpt, l_loinc, l_desc]):
        raise KeyError(
            f"LAB file missing HbA1c identifier columns (need CPT or LOINC or Description). "
            f"Found: {list(l.columns)}"
        )

    l_result = _pick_by_names(l, ["Result", "Result Value", "Value", "Test Result", "Observation Value", "Numeric Result"])
    if not l_result:
        raise KeyError(f"LAB file missing Result column. Found: {list(l.columns)}")

    # Parse lab dates
    l[l_date] = _to_datetime_safe(l[l_date])

    # Only labs within last 12 months prior to quarter end
    l_window = l[(l[l_date] >= lookback_start) & (l[l_date] <= q_end)].copy()

    # Keep labs only for denominator patients
    l_window[l_patient] = l_window[l_patient].astype(str)
    denom_set = set(map(str, denom_patients))
    l_window = l_window[l_window[l_patient].isin(denom_set)].copy()

    # Flag HbA1c rows
    def _flag_hba1c(row):
        code = row.get(l_cpt) if l_cpt else None
        loinc = row.get(l_loinc) if l_loinc else None
        desc = row.get(l_desc) if l_desc else None
        return _is_hba1c_row(code, loinc, desc)

    if not l_window.empty:
        l_window["_is_hba1c"] = l_window.apply(_flag_hba1c, axis=1)
        l_hba1c = l_window[l_window["_is_hba1c"]].copy()
    else:
        l_hba1c = l_window.copy()
        l_hba1c["_is_hba1c"] = False

    # Convert result to numeric
    if not l_hba1c.empty:
        l_hba1c["_hba1c_val"] = _numeric_result(l_hba1c[l_result])
    else:
        l_hba1c["_hba1c_val"] = pd.Series(dtype=float)

    # For each patient: most recent HbA1c in window
    if not l_hba1c.empty:
        l_hba1c = l_hba1c.sort_values([l_patient, l_date])
        latest_per_patient = l_hba1c.groupby(l_patient, as_index=False).tail(1)
        latest_per_patient = latest_per_patient[[l_patient, l_date, "_hba1c_val"]].copy()
        latest_per_patient = latest_per_patient.rename(columns={l_patient: "Patient", l_date: "LabDate"})
    else:
        latest_per_patient = pd.DataFrame(columns=["Patient", "LabDate", "_hba1c_val"])

    # Determine numerator:
    # - patients with no HbA1c test in the last 12 months
    # - OR whose most recent HbA1c > 9
    tested_patients = set(latest_per_patient["Patient"].astype(str).tolist())
    no_test_patients = denom_set - tested_patients

    poor_control_patients = set(
        latest_per_patient.loc[latest_per_patient["_hba1c_val"] > 9, "Patient"].astype(str).tolist()
    )

    numerator_patients = no_test_patients.union(poor_control_patients)
    numer = int(len(numerator_patients))

    rate = (numer / denom) if denom > 0 else np.nan

    # Compose result
    result = pd.DataFrame(
        {
            "Metric": [
                "PC009 Denominator (Diabetics 18-75 with visit in quarter)",
                "PC009 Numerator (HbA1c > 9 OR No HbA1c in last 12 months)",
                "PC009 Rate",
                "HbA1c Tested Patients (last 12 months)",
                "HbA1c No-Test Patients (last 12 months)",
                "HbA1c Poor Control Patients (>9)",
            ],
            "Value": [
                denom,
                numer,
                (f"{rate:.2%}" if pd.notna(rate) else "N/A"),
                int(len(tested_patients)),
                int(len(no_test_patients)),
                int(len(poor_control_patients)),
            ],
        }
    )

    latest = {
        "quarter_start": str(q_start.date()),
        "quarter_end": str(q_end.date()),
        "lookback_start": str(lookback_start.date()),
        "latest_lab_date_in_window": (
            str(pd.to_datetime(l_hba1c[l_date]).max().date())
            if (not l_hba1c.empty and pd.to_datetime(l_hba1c[l_date]).notna().any())
            else None
        ),
    }

    return result, latest
