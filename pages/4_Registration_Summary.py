#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Streamlit Page: Registration Summary (Registration + CashOut + Pending)

Key features:
- Step-by-step upload (1 Registration, 2 CashOut, 3 Pending) with delete buttons.
- Minimal requirements:
  * Registration: must contain EMRNo and VisitNo (case-insensitive).
  * CashOut: only EMRNo required.
  * Pending: only EMRNo required.
- Day detection:
  * Prefers a date column in Registration (RegDate / RegistrationDate / Date).
  * Falls back to a manual date picker.
- Process & Save:
  * Saves raw uploads + processed summary (pickle) + history.csv to S3 if configured.
  * Supports old/new secret keys:
      S3_BUCKET_NAME or S3_BUCKET
      AWS_REGION or AWS_DEFAULT_REGION
      S3_BASE_PREFIX or S3_PREFIX
- Display:
  * CURRENT DAY summary first.
  * ACCUMULATED section shown below CURRENT DAY.
  * Accumulated table does NOT show internal columns.

If your main app already sets st.session_state["center_key"], this page will use it.
Otherwise it provides a center selector.
"""

import io
import os
import re
import pickle
from datetime import datetime, date
from typing import Dict, Tuple, Optional, List

import pandas as pd
import streamlit as st

# Optional S3
try:
    import boto3
    from botocore.exceptions import ClientError
except Exception:
    boto3 = None
    ClientError = Exception


st.set_page_config(page_title="Registration Summary", layout="wide", initial_sidebar_state="collapsed")
st.title("Registration Summary (Registration + CashOut + Pending)")

# ---------------------------
# Admin mode (admin-only page)
# ---------------------------
# Viewer mode removed: this page always shows upload + processing controls.
admin_mode = True



# ---------------------------
# Employer alias dictionary (RCM-safe dedupe)
# ---------------------------
# Add/adjust aliases here (left side = raw cleaned key, right side = canonical display name)
# Keys must be LOWERCASE and already cleaned by `employer_clean_key()`.
EMPLOYER_ALIAS = {
    # QAMRA variations
    "qamra": "QAMRA",
    "qamara": "QAMRA",
    "qumra": "QAMRA",
    # EXCEED variations
    "exceed": "EXCEED",
    "excee": "EXCEED",
    "exeed": "EXCEED",
    # Others (examples you mentioned)
    "alryum": "ALRYUM",
    "noor al sahara": "NOOR AL SAHARA",
    "noor al sahra": "NOOR AL SAHARA",
}

# Prefix-based aliases (optional). If the cleaned employer starts with the prefix -> canonical.
# Useful for cases like ARCO where you want to keep ONLY the initial keyword.
EMPLOYER_PREFIX_ALIAS = [
    ("arco", "ARCO"),

    # QAMRA / QUMRA / QAMARA variations
    ("qamra", "QAMRA"),
    ("qamara", "QAMRA"),
    ("qumra", "QAMRA"),

    # EXCEED / EXEED variations
    ("exceed", "EXCEED"),
    ("exeed", "EXCEED"),
    ("excee", "EXCEED"),

    # Strong merge for the specific company name
    ("exceed precast", "EXCEED PRECAST"),
    ("exeed precast", "EXCEED PRECAST"),
]
def _norm_col(c: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(c).strip().lower())


def _find_col(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    norm_map = {_norm_col(c): c for c in df.columns}
    for cand in candidates:
        key = _norm_col(cand)
        if key in norm_map:
            return norm_map[key]
    # fuzzy: contains
    for cand in candidates:
        key = _norm_col(cand)
        for k, orig in norm_map.items():
            if key and key in k:
                return orig
    return None


# -------------------- Income Analysis (Doctor Revenue) helpers --------------------
def _detect_header_row(df_raw: pd.DataFrame, must_have: List[str]) -> Optional[int]:
    for i in range(min(50, len(df_raw))):
        row = df_raw.iloc[i].astype(str).str.strip().str.lower().tolist()
        if all(any(k.lower() in cell for cell in row) for k in must_have):
            return i
    return None


def load_income_details(uploaded_file) -> Optional[pd.DataFrame]:
    if uploaded_file is None:
        return None
    try:
        df_raw = pd.read_excel(uploaded_file, sheet_name="Daily Collection Details", header=None)
    except Exception:
        df_raw = pd.read_excel(uploaded_file, sheet_name=0, header=None)

    hdr = _detect_header_row(df_raw, must_have=["doctor", "department", "insurance name", "visit no"])
    if hdr is None:
        return None

    header = df_raw.iloc[hdr].astype(str).str.strip()
    df = df_raw.iloc[hdr + 1:].copy()
    df.columns = header

    df = df.dropna(how="all").reset_index(drop=True)
    df.columns = [str(c).strip() for c in df.columns]
    return df


def income_tables(df: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    if df is None or df.empty:
        return {}

    col_dept = _find_col(df, ["Department"])
    col_doc  = _find_col(df, ["Doctor"])
    col_ins  = _find_col(df, ["Insurance Name", "Insurance"])
    col_visit= _find_col(df, ["Visit No", "VisitNo"])
    col_cons = _find_col(df, ["Consultation"])
    col_lab  = _find_col(df, ["Lab"])
    col_proc = _find_col(df, ["Procedure"])

    needed = [col_doc, col_ins, col_visit, col_cons, col_lab, col_proc]
    if any(c is None for c in needed):
        return {}

    tmp = df.copy()
    # Clean blanks/None so they don't appear as a separate 'None' row and don't affect GRAND TOTAL
    # Doctor is mandatory for any revenue attribution
    tmp[col_doc] = tmp[col_doc].astype(str).str.strip()
    tmp = tmp[~tmp[col_doc].str.lower().isin(['', 'none', 'nan'])].copy()
    # Optional Department: if present, drop blank departments as well (prevents 'None' department grouping)
    if col_dept:
        tmp[col_dept] = tmp[col_dept].astype(str).str.strip()
        tmp = tmp[~tmp[col_dept].str.lower().isin(['', 'none', 'nan'])].copy()
    # Insurance: blanks treated as CASH
    tmp[col_ins] = tmp[col_ins].fillna('CASH').astype(str).str.strip().replace('', 'CASH')
    tmp[col_visit] = tmp[col_visit].astype(str).str.strip()
    tmp = tmp[tmp[col_visit] != ''].copy()

    for c in [col_cons, col_lab, col_proc]:
        tmp[c] = pd.to_numeric(tmp[c], errors="coerce").fillna(0.0)

    tmp[col_visit] = tmp[col_visit].astype(str).str.strip()
    tmp["_total_amt"] = tmp[col_cons] + tmp[col_lab] + tmp[col_proc]

    def _agg(group_cols: List[str]) -> pd.DataFrame:
        g = tmp.groupby(group_cols, dropna=False).agg(
            Consultation=(col_cons, "sum"),
            Lab=(col_lab, "sum"),
            Procedure=(col_proc, "sum"),
            Total_Visit=(col_visit, pd.Series.nunique),
            Total_Amount=("_total_amt", "sum"),
        ).reset_index()
        g["Avg_Amount"] = g["Total_Amount"] / g["Total_Visit"].replace(0, pd.NA)
        g["Lab_%"] = (g["Lab"] / g["Total_Amount"].replace(0, pd.NA)) * 100
        return g

    if col_dept:
        doctor_wise = _agg([col_dept, col_doc]).rename(columns={col_dept: "Department", col_doc: "Doctor"})
    else:
        doctor_wise = _agg([col_doc]).rename(columns={col_doc: "Doctor"})

    insurance_wise = _agg([col_ins]).rename(columns={col_ins: "Insurance"})
    doctor_ins_wise = _agg([col_doc, col_ins]).rename(columns={col_doc: "Doctor", col_ins: "Insurance"})

    def _add_grand_total(d: pd.DataFrame, label_cols: List[str]) -> pd.DataFrame:
        if d.empty:
            return d
        total_visit = int(d["Total_Visit"].sum())
        total_amount = float(d["Total_Amount"].sum())
        lab_sum = float(d["Lab"].sum())

        row = {c: "" for c in d.columns}
        for lc in label_cols:
            if lc in row:
                row[lc] = "GRAND TOTAL"
                break
        row["Consultation"] = float(d["Consultation"].sum())
        row["Lab"] = lab_sum
        row["Procedure"] = float(d["Procedure"].sum())
        row["Total_Visit"] = total_visit
        row["Total_Amount"] = total_amount
        row["Avg_Amount"] = (total_amount / total_visit) if total_visit else 0.0
        row["Lab_%"] = (lab_sum / total_amount * 100) if total_amount else 0.0
        return pd.concat([d, pd.DataFrame([row])], ignore_index=True)

    doctor_wise = _add_grand_total(doctor_wise, ["Department", "Doctor"])
    insurance_wise = _add_grand_total(insurance_wise, ["Insurance"])
    doctor_ins_wise = _add_grand_total(doctor_ins_wise, ["Doctor"])

    return {
        "Doctor Wise Revenue": doctor_wise,
        "Insurance Wise Revenue": insurance_wise,
        "Doctor x Insurance Revenue": doctor_ins_wise,
    }


# -------------------- CPT / ICD Analysis (Step 5) helpers --------------------
def load_cpticd_details(uploaded_file) -> Optional[pd.DataFrame]:
    """Load the RegistrationDetailswithICDandCPTList report (single sheet)."""
    if uploaded_file is None:
        return None
    try:
        df = pd.read_excel(uploaded_file)
    except Exception:
        return None
    if df is None or df.empty:
        return None
    # normalize columns (strip)
    df.columns = [str(c).strip() for c in df.columns]
    return df


def _split_multi_codes(s: pd.Series) -> pd.Series:
    """Split codes like 'A01,B02 / C03' -> list items; returns exploded series-friendly lists."""
    s = s.fillna("").astype(str)
    # replace common separators with comma
    s = s.str.replace("\n", ",", regex=False)
    s = s.str.replace("|", ",", regex=False)
    s = s.str.replace(";", ",", regex=False)
    s = s.str.replace("/", ",", regex=False)
    # split
    return s.apply(lambda x: [p.strip() for p in x.split(",") if str(p).strip() not in ["", "None", "nan"]])


def _top_code_per_group(df_exp: pd.DataFrame, group_cols: List[str], code_col: str, desc_col: Optional[str] = None) -> pd.DataFrame:
    """Return Top-1 code per group with count (+ most common description if provided)."""
    if df_exp.empty:
        cols = group_cols + ["Code", "Description", "Count"]
        return pd.DataFrame(columns=cols)
    g = df_exp.groupby(group_cols + [code_col]).size().reset_index(name="Count")
    # attach description mode
    if desc_col and desc_col in df_exp.columns:
        # map (group, code) -> mode description
        tmp = df_exp[group_cols + [code_col, desc_col]].copy()
        tmp[desc_col] = tmp[desc_col].fillna("").astype(str).str.strip()
        def _mode_desc(x):
            x = x[x != ""]
            if x.empty:
                return ""
            m = x.mode()
            return m.iat[0] if not m.empty else x.iloc[0]
        dmap = tmp.groupby(group_cols + [code_col])[desc_col].apply(_mode_desc).reset_index(name="Description")
        g = g.merge(dmap, on=group_cols + [code_col], how="left")
    else:
        g["Description"] = ""
    # rank within group
    g["_rank"] = g.groupby(group_cols)["Count"].rank(method="first", ascending=False)
    top = g[g["_rank"] == 1].drop(columns=["_rank"]).rename(columns={code_col: "Code"})
    # order columns
    top = top[group_cols + ["Code", "Description", "Count"]]
    return top.sort_values(group_cols + ["Count"], ascending=[True]*len(group_cols) + [False])


def _top_n_codes(df_exp: pd.DataFrame, group_cols: List[str], code_col: str, desc_col: Optional[str] = None, n: int = 10) -> pd.DataFrame:
    """Return Top-N codes per group."""
    if df_exp.empty:
        cols = group_cols + ["Code", "Description", "Count"]
        return pd.DataFrame(columns=cols)
    g = df_exp.groupby(group_cols + [code_col]).size().reset_index(name="Count")
    if desc_col and desc_col in df_exp.columns:
        tmp = df_exp[group_cols + [code_col, desc_col]].copy()
        tmp[desc_col] = tmp[desc_col].fillna("").astype(str).str.strip()
        def _mode_desc(x):
            x = x[x != ""]
            if x.empty:
                return ""
            m = x.mode()
            return m.iat[0] if not m.empty else x.iloc[0]
        dmap = tmp.groupby(group_cols + [code_col])[desc_col].apply(_mode_desc).reset_index(name="Description")
        g = g.merge(dmap, on=group_cols + [code_col], how="left")
    else:
        g["Description"] = ""

    g["_rank"] = g.groupby(group_cols)["Count"].rank(method="first", ascending=False)
    g = g[g["_rank"] <= n].drop(columns=["_rank"]).rename(columns={code_col: "Code"})
    g = g[group_cols + ["Code", "Description", "Count"]]
    return g.sort_values(group_cols + ["Count"], ascending=[True]*len(group_cols) + [False])


def cpticd_tables(df: pd.DataFrame, reg_df: Optional[pd.DataFrame] = None) -> Dict[str, pd.DataFrame]:
    """Build CPT/ICD analytics tables. Uses Company as Employer."""
    if df is None or df.empty:
        return {}

    # required columns (as provided by you)
    col_emr = _find_col(df, ["EMR No", "EMRNo", "EMR"])
    col_visit = _find_col(df, ["Visit ID", "VisitNo", "Visit No"])
    col_doc = _find_col(df, ["Doctor"])
    col_company = _find_col(df, ["Company"])
    col_exp = _find_col(df, ["Expiry Date", "Expiry"])
    col_pri = _find_col(df, ["ICD (Principal)"])
    col_pri_desc = _find_col(df, ["ICD Principal Description"])
    col_sec = _find_col(df, ["ICD (Secondary)"])
    col_sec_desc = _find_col(df, ["ICD Secondary Description"])
    col_cpt = _find_col(df, ["CPT Codes", "CPT Code", "CPT"])
    col_cpt_desc = _find_col(df, ["Procedure Description"])

    must = [col_doc, col_company, col_pri, col_sec, col_cpt, col_exp]
    if any(c is None for c in must):
        return {}

    base = df.copy()
    # normalize core fields
    base[col_doc] = base[col_doc].fillna("UNKNOWN").astype(str).str.strip().replace("", "UNKNOWN")
    base[col_company] = base[col_company].fillna("UNKNOWN").astype(str).str.strip().replace("", "UNKNOWN")

    # optional merge with registration to enrich (Visit Type, Insurance etc.)
    if reg_df is not None and isinstance(reg_df, pd.DataFrame) and not reg_df.empty:
        try:
            rmap = ensure_required(reg_df, ["EMRNo", "VisitNo"], "Registration")
            r_emr, r_visit = rmap["EMRNo"], rmap["VisitNo"]
            reg_small = reg_df.copy()
            reg_small[r_emr] = reg_small[r_emr].astype(str).str.strip()
            reg_small[r_visit] = reg_small[r_visit].astype(str).str.strip()
            # pick useful columns
            r_visit_type = _find_col(reg_small, ["VisitType", "Visit Type", "VisitCategory"])
            r_ins = _find_col(reg_small, ["Insurance", "InsuranceName", "Payer", "PayerName"])

            r_emp = _find_col(reg_small, ["Employer Name"])  # STRICT Employer Name only

            keep_cols = [r_emr, r_visit]
            if r_visit_type:
                keep_cols.append(r_visit_type)
            if r_ins:
                keep_cols.append(r_ins)
            if r_emp:
                keep_cols.append(r_emp)

            reg_small = reg_small[keep_cols].drop_duplicates()

            base[col_emr] = base[col_emr].astype(str).str.strip() if col_emr else ""
            base[col_visit] = base[col_visit].astype(str).str.strip() if col_visit else ""
            # --- IMPORTANT: restrict CPT/ICD rows to ONLY the visits present in the provided reg_df (day/week/month) ---
            # This ensures CPT/ICD counts match the selected period (e.g., Daily 06 Feb 2026).
            if col_emr and col_visit and r_emr and r_visit:
                reg_keys = (reg_small[[r_emr, r_visit]]
                            .dropna()
                            .astype(str)
                            .apply(lambda x: x.str.strip()))
                reg_key_series = (reg_keys[r_emr] + "||" + reg_keys[r_visit]).unique()

                base_key_series = base[col_emr].astype(str).str.strip() + "||" + base[col_visit].astype(str).str.strip()
                base = base.loc[base_key_series.isin(reg_key_series)].copy()
            base = base.merge(
                reg_small,
                left_on=[col_emr, col_visit] if col_emr and col_visit else [col_emr],
                right_on=[r_emr, r_visit] if col_emr and col_visit else [r_emr],
                how="left",
                suffixes=("", "_reg"),
            )
        except Exception:
            pass

    # explode ICD and CPT
    pri = base[[col_doc, col_company, col_pri, col_pri_desc]].copy()
    pri[col_pri] = _split_multi_codes(pri[col_pri])
    pri = pri.explode(col_pri)
    pri[col_pri] = pri[col_pri].fillna("").astype(str).str.strip()
    pri = pri[pri[col_pri] != ""].copy()

    sec = base[[col_doc, col_company, col_sec, col_sec_desc]].copy()
    sec[col_sec] = _split_multi_codes(sec[col_sec])
    sec = sec.explode(col_sec)
    sec[col_sec] = sec[col_sec].fillna("").astype(str).str.strip()
    sec = sec[sec[col_sec] != ""].copy()

    cpt = base[[col_doc, col_company, col_cpt, col_cpt_desc]].copy()
    cpt[col_cpt] = _split_multi_codes(cpt[col_cpt])
    cpt = cpt.explode(col_cpt)
    cpt[col_cpt] = cpt[col_cpt].fillna("").astype(str).str.strip()
    cpt = cpt[cpt[col_cpt] != ""].copy()

    # Top-1 per Doctor x Company
    docco_pri_top = _top_code_per_group(pri, [col_doc, col_company], col_pri, col_pri_desc).rename(columns={col_doc:"Doctor", col_company:"Company"})
    docco_sec_top = _top_code_per_group(sec, [col_doc, col_company], col_sec, col_sec_desc).rename(columns={col_doc:"Doctor", col_company:"Company"})
    doc_pri_top = _top_code_per_group(pri, [col_doc], col_pri, col_pri_desc).rename(columns={col_doc:"Doctor"})
    doc_sec_top = _top_code_per_group(sec, [col_doc], col_sec, col_sec_desc).rename(columns={col_doc:"Doctor"})
    co_pri_top = _top_code_per_group(pri, [col_company], col_pri, col_pri_desc).rename(columns={col_company:"Company"})
    co_sec_top = _top_code_per_group(sec, [col_company], col_sec, col_sec_desc).rename(columns={col_company:"Company"})

    # CPT -> Top principal ICD
    # link by original rows: explode CPT + principal then count pairs
    pair = base[[col_cpt, col_pri, col_pri_desc]].copy()
    pair[col_cpt] = _split_multi_codes(pair[col_cpt])
    pair[col_pri] = _split_multi_codes(pair[col_pri])
    pair = pair.explode(col_cpt).explode(col_pri)
    pair[col_cpt] = pair[col_cpt].fillna("").astype(str).str.strip()
    pair[col_pri] = pair[col_pri].fillna("").astype(str).str.strip()
    pair = pair[(pair[col_cpt]!="") & (pair[col_pri]!="")].copy()
    pair_top = _top_code_per_group(pair, [col_cpt], col_pri, col_pri_desc).rename(columns={col_cpt:"CPT", "Code":"ICD"})
    # optional add CPT description mode
    if col_cpt_desc in base.columns:
        tmpd = base[[col_cpt, col_cpt_desc]].copy()
        tmpd[col_cpt] = _split_multi_codes(tmpd[col_cpt])
        tmpd = tmpd.explode(col_cpt)
        tmpd[col_cpt] = tmpd[col_cpt].fillna("").astype(str).str.strip()
        tmpd = tmpd[tmpd[col_cpt]!=""]
        def _mode_desc(x):
            x = x.dropna().astype(str).str.strip()
            x = x[x!=""]
            if x.empty: return ""
            m=x.mode()
            return m.iat[0] if not m.empty else x.iloc[0]
        cptdesc = tmpd.groupby(col_cpt)[col_cpt_desc].apply(_mode_desc).reset_index(name="CPT Description")
        pair_top = pair_top.merge(cptdesc, left_on="CPT", right_on=col_cpt, how="left").drop(columns=[col_cpt], errors="ignore")
    else:
        pair_top["CPT Description"] = ""

    pair_top = pair_top[["CPT","CPT Description","ICD","Description","Count"]].rename(columns={"Description":"ICD Description"})

    # Expiry tracker (Employer + Expiry)
    # Expiry tracker (Employer + Expiry)
    employer_col_use = r_emp if (reg_df is not None and 'r_emp' in locals() and r_emp and r_emp in base.columns) else col_company
    exp = base[[employer_col_use, col_emr, col_visit, ("Name" if "Name" in base.columns else None), col_doc, col_exp]].copy()
    exp = exp.loc[:, [c for c in exp.columns if c is not None]]

    exp = exp.rename(columns={employer_col_use:"Employer", col_doc:"Doctor", col_emr:"EMR No", col_visit:"Visit ID", col_exp:"Expiry Date"})
    # Clean expiry date
    exp["Expiry Date"] = pd.to_datetime(exp["Expiry Date"], errors="coerce", dayfirst=True)
    exp = exp.dropna(subset=["Expiry Date"])
    # compute days to expiry
    today = pd.to_datetime(date.today())
    exp["Days To Expiry"] = (exp["Expiry Date"].dt.normalize() - today.normalize()).dt.days
    # if Name column missing, create empty
    if "Name" not in exp.columns:
        exp["Name"] = ""
    # de-dup per EMR/company expiry
    exp = exp.drop_duplicates(subset=["Employer","EMR No","Expiry Date"])
    exp = exp.sort_values(["Days To Expiry","Employer","Name"], ascending=[True, True, True]).reset_index(drop=True)

    return {
        "Doctor x Company | Principal DX (Top1)": docco_pri_top.rename(columns={"Code":"ICD", "Description":"ICD Description"}),
        "Doctor x Company | Secondary DX (Top1)": docco_sec_top.rename(columns={"Code":"ICD", "Description":"ICD Description"}),
        "Doctor | Principal DX (Top1)": doc_pri_top.rename(columns={"Code":"ICD", "Description":"ICD Description"}),
        "Doctor | Secondary DX (Top1)": doc_sec_top.rename(columns={"Code":"ICD", "Description":"ICD Description"}),
        "Company | Principal DX (Top1)": co_pri_top.rename(columns={"Code":"ICD", "Description":"ICD Description"}),
        "Company | Secondary DX (Top1)": co_sec_top.rename(columns={"Code":"ICD", "Description":"ICD Description"}),
        "CPT -> Top Principal ICD": pair_top,
        "Employer Expiry Tracker": exp[["Employer","Name","EMR No","Visit ID","Doctor","Expiry Date","Days To Expiry"]],
    }


def read_excel_any(uploaded_file, required_hint: Optional[List[str]] = None) -> pd.DataFrame:
    """Read an Excel report even when the real header is not on the first row.

    If `required_hint` is provided (e.g., ["EMRNo"]), we first try normal read.
    If the required columns can't be found, we fall back to scanning the first
    ~60 rows to detect the true header row (common in hospital report exports
    that include big titles like 'EXCELLENT MEDICAL CENTER' before the table).
    """
    data = uploaded_file.getvalue() if hasattr(uploaded_file, "getvalue") else uploaded_file.read()
    bio = io.BytesIO(data)

    def has_required(df: pd.DataFrame) -> bool:
        if not required_hint:
            return False
        for r in required_hint:
            if r == "EMRNo":
                if _find_col(df, ["EMRNo", "EMR NO", "EMR", "MRN", "PatientID", "Patient Id", "FileNo"]):
                    return True
            elif r == "VisitNo":
                if _find_col(df, ["VisitNo", "Visit No", "Visit#", "Visit Number", "VisitID", "EncounterNo", "Encounter No"]):
                    return True
            else:
                if _find_col(df, [r]):
                    return True
        return False

    # 1) First attempt (normal)
    bio.seek(0)
    try:
        df1 = pd.read_excel(bio)
        # If required column NOT found, do header scan fallback
        if required_hint and not has_required(df1):
            raise ValueError("Header likely not on first row; retrying header scan.")
        return df1
    except Exception:
        pass

    # 2) Header scan fallback
    bio.seek(0)
    raw = pd.read_excel(bio, header=None)

    likely = {
        "emrno", "emr", "mrn", "patientid", "fileno",
        "visitno", "visit", "visitdate",
        "billno", "doctor", "insurance"
    }

    header_idx = 0
    for i in range(min(60, len(raw))):
        row = raw.iloc[i].astype(str).str.lower().tolist()
        row_keys = {_norm_col(x) for x in row}
        if row_keys & likely:
            header_idx = i
            break

    bio.seek(0)
    df = pd.read_excel(bio, header=header_idx)
    # Drop 'Unnamed' columns ONLY if they are truly empty (some EMR exports store real data under Unnamed headers)
    unnamed_cols = [c for c in df.columns if str(c).startswith("Unnamed")]
    if unnamed_cols:
        keep = []
        for c in df.columns:
            if str(c).startswith("Unnamed"):
                s = df[c]
                # keep if it has any non-empty value
                has_value = s.notna().any() and (s.astype(str).str.strip() != "").any()
                if has_value:
                    keep.append(c)
            else:
                keep.append(c)
        df = df[keep]
    return df


def ensure_required(df: pd.DataFrame, required: List[str], label: str) -> Dict[str, str]:
    mapping = {}
    for r in required:
        if r == "EMRNo":
            col = _find_col(df, ["EMRNo", "EMR NO", "EMR", "MRN", "PatientID", "Patient Id", "FileNo"])
        elif r == "VisitNo":
            col = _find_col(df, ["VisitNo", "Visit No", "Visit#", "Visit Number", "VisitID", "EncounterNo", "Encounter No"])
        else:
            col = _find_col(df, [r])
        if not col:
            raise ValueError(f"{label} file must contain '{r}'. Found: {list(df.columns)}")
        mapping[r] = col
    return mapping


def get_day_from_registration(reg_df: pd.DataFrame) -> Optional[pd.Timestamp]:
    """Detect the report day from Registration file.

    EMR exports often store dates as dd/mm/yyyy but pandas defaults to mm/dd/yyyy.
    We therefore try BOTH parses (dayfirst False and True) and pick the one that
    yields more valid dates. If tied, we prefer dayfirst=True (common in UAE).
    """
    date_col = _find_col(reg_df, ["RegDate", "RegistrationDate", "Date", "VisitDate", "Reg Date", "Registration Date"])
    if not date_col:
        return None

    s_raw = reg_df[date_col]

    # Try both date interpretations
    s1 = pd.to_datetime(s_raw, errors="coerce", dayfirst=False)
    s2 = pd.to_datetime(s_raw, errors="coerce", dayfirst=True)

    n1 = int(s1.notna().sum())
    n2 = int(s2.notna().sum())

    s = s2 if n2 >= n1 else s1
    s = s.dropna()
    if s.empty:
        return None

    day = s.dt.normalize()
    try:
        return day.mode().iloc[0]
    except Exception:
        return day.min()


def get_days_from_registration(reg_df: pd.DataFrame) -> List[pd.Timestamp]:
    """Return all unique days found in Registration file (normalized).
    Uses the same dayfirst heuristic as get_day_from_registration.
    """
    date_col = _find_col(reg_df, ["RegDate", "RegistrationDate", "Date", "VisitDate", "Reg Date", "Registration Date"])
    if not date_col:
        return []
    s_raw = reg_df[date_col]
    s1 = pd.to_datetime(s_raw, errors="coerce", dayfirst=False)
    s2 = pd.to_datetime(s_raw, errors="coerce", dayfirst=True)
    n1 = int(s1.notna().sum())
    n2 = int(s2.notna().sum())
    s = s2 if n2 >= n1 else s1
    s = s.dropna()
    if s.empty:
        return []
    days = sorted(pd.Series(s.dt.normalize().unique()).dropna())
    return [pd.to_datetime(d) for d in days]


def filter_df_by_day_if_possible(df: Optional[pd.DataFrame], day_ts: pd.Timestamp) -> Optional[pd.DataFrame]:
    """If df has a recognizable date column, filter it to the given day. Otherwise return df as-is."""
    if df is None or df.empty:
        return df
    date_col = _find_col(df, ["RegDate", "RegistrationDate", "Date", "VisitDate", "CreatedDate", "EntryDate", "Day"])
    if not date_col:
        # Try any column that contains 'date'
        for c in df.columns:
            if "date" in str(c).lower():
                date_col = c
                break
    if not date_col:
        return df

    s_raw = df[date_col]
    s1 = pd.to_datetime(s_raw, errors="coerce", dayfirst=False)
    s2 = pd.to_datetime(s_raw, errors="coerce", dayfirst=True)
    n1 = int(s1.notna().sum())
    n2 = int(s2.notna().sum())
    s = s2 if n2 >= n1 else s1
    day = pd.to_datetime(day_ts).normalize()
    mask = s.dt.normalize() == day
    if mask.notna().sum() == 0:
        return df
    out = df.loc[mask.fillna(False)].copy()
    return out


def top_counts(df: pd.DataFrame, col: Optional[str], n: int = 15, label: str = "Value") -> pd.DataFrame:
    """Return top-N counts for a column and append a TOTAL row.

    - Normalizes blanks -> 'Blank' (or 'CASH' for insurance-like columns)
    - Returns columns: <label>, Count
    - Appends TOTAL (sum of shown rows) at the end
    """
    if not col or col not in df.columns:
        return pd.DataFrame(columns=["Value", "Count"])

    col_l = str(col).lower()
    blank_label = "CASH" if any(k in col_l for k in ["insur", "payer", "tpa"]) else "Blank"

    out = (
        df[col]
        .fillna(blank_label)
        .astype(str)
        .str.strip()
        .replace("", blank_label)
        .replace("Blank", blank_label)
        .value_counts(dropna=False)
        .head(n)
        .reset_index()
    )
    out.columns = [label, "Count"]

    # ✅ TOTAL row (sum of displayed rows)
    total = int(out["Count"].sum()) if not out.empty else 0
    out.loc[len(out)] = ["TOTAL", total]
    return out


def employer_clean_key(x: str) -> str:
    """Return a normalized employer key suitable for matching (lowercase).

    This is intentionally conservative: it removes punctuation/extra spaces and
    normalizes common legal suffix formatting (WLL/LLC), but it does NOT try to
    guess company identity beyond what you explicitly map in EMPLOYER_ALIAS.
    """
    if x is None:
        return "blank"
    s = str(x).strip().upper()

    # Standardize common variants
    s = s.replace("&", " AND ")
    s = re.sub(r"\bW\s*L\s*L\b", "WLL", s)   # W L L -> WLL
    s = re.sub(r"\bL\s*L\s*C\b", "LLC", s)   # L L C -> LLC

    # Keep letters/numbers/spaces only
    s = re.sub(r"[^A-Z0-9\s]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()

    return s.lower() if s else "blank"


def employer_canonical_name(x: str) -> str:
    """Map employer to a single canonical display name using:
    1) prefix aliases (EMPLOYER_PREFIX_ALIAS)
    2) exact aliases (EMPLOYER_ALIAS)
    3) fallback to cleaned uppercase
    """
    key = employer_clean_key(x)

    # prefix rules first (e.g., ARCO -> ARCO)
    for pref, canon in EMPLOYER_PREFIX_ALIAS:
        if key.startswith(str(pref).lower()):
            return str(canon).strip()

    # exact aliases next
    if key in EMPLOYER_ALIAS:
        return str(EMPLOYER_ALIAS[key]).strip()

    # fallback
    return key.upper() if key != "blank" else "Blank"

def employer_wise_with_insurance(df: pd.DataFrame, emp_col: Optional[str], ins_col: Optional[str], n: int = 50) -> pd.DataFrame:
    """Employer Wise counts (DEDUPED) + ONE Insurance per employer-group.

    Grouping rule:
    - grouping key: canonical employer name from EMPLOYER_ALIAS / EMPLOYER_PREFIX_ALIAS
    - final safety: merge again by displayed Employer text (handles any weird edge cases)
    """
    if not emp_col or emp_col not in df.columns:
        return pd.DataFrame(columns=["Employer", "Count", "Insurance"])

    tmp = df.copy()

    # Employer cleanup + key
    tmp[emp_col] = tmp[emp_col].fillna("Blank").astype(str).str.strip().replace("", "Blank")
    tmp["__emp_key__"] = tmp[emp_col].apply(employer_canonical_name)

    # Insurance cleanup
    if ins_col and ins_col in tmp.columns:
        tmp[ins_col] = (
            tmp[ins_col]
            .fillna("CASH")
            .astype(str)
            .str.strip()
            .replace("", "CASH")
            .replace("Blank", "CASH")
        )
    else:
        tmp["__ins__"] = "CASH"
        ins_col = "__ins__"

    # Count per key
    counts = tmp.groupby("__emp_key__").size().reset_index(name="Count")

    # Canonical employer display = __emp_key__ (already mapped by EMPLOYER_ALIAS / EMPLOYER_PREFIX_ALIAS)

    # Insurance = most frequent within group
    dominant_ins = (
        tmp.groupby(["__emp_key__", ins_col])
        .size()
        .reset_index(name="cnt")
        .sort_values(["__emp_key__", "cnt"], ascending=[True, False])
        .drop_duplicates(subset=["__emp_key__"])
        [["__emp_key__", ins_col]]
        .rename(columns={ins_col: "Insurance"})
    )

    out = counts.merge(dominant_ins, on="__emp_key__", how="left")
    out = out.rename(columns={"__emp_key__": "Employer"})[["Employer", "Count", "Insurance"]]


    # final safety merge by displayed Employer text (sums counts, picks mode insurance)
    if not out.empty:
        def _mode_or_first(s: pd.Series) -> str:
            s2 = s.dropna().astype(str)
            if s2.empty:
                return ""
            md = s2.mode()
            return md.iat[0] if not md.empty else s2.iloc[0]

        out = (
            out.groupby("Employer", as_index=False)
            .agg(Count=("Count", "sum"), Insurance=("Insurance", _mode_or_first))
            .sort_values("Count", ascending=False)
            .reset_index(drop=True)
        )

    # Keep table readable but make TOTAL consistent with overall visits
    grand_total = int(out["Count"].sum()) if not out.empty else 0
    if n and len(out) > n:
        top = out.head(n).copy()
        others = int(out.iloc[n:]["Count"].sum())
        if others > 0:
            top.loc[len(top)] = ["OTHERS", others, ""]
        out = top.reset_index(drop=True)

    out.loc[len(out)] = ["TOTAL", grand_total, ""]
    return out


def employer_insurance_table(df: pd.DataFrame, emp_col: Optional[str], ins_col: Optional[str], n: int = 200) -> pd.DataFrame:
    """Employer x Insurance breakdown (top rows) with TOTAL row at end.
    Insurance blanks are shown as 'CASH'.
    """
    if not emp_col or emp_col not in df.columns or not ins_col or ins_col not in df.columns:
        return pd.DataFrame(columns=["Employer", "Insurance", "Count"])

    tmp = df[[emp_col, ins_col]].copy()

    # Employer: keep as Blank
    tmp[emp_col] = tmp[emp_col].fillna("Blank").astype(str).str.strip().replace("", "Blank")

    # Insurance: blanks => CASH
    tmp[ins_col] = (
        tmp[ins_col]
        .fillna("CASH")
        .astype(str)
        .str.strip()
        .replace("", "CASH")
        .replace("Blank", "CASH")
    )

    out = (
        tmp.groupby([emp_col, ins_col])
        .size()
        .reset_index(name="Count")
        .sort_values("Count", ascending=False)
        .head(n)
    )
    out.columns = ["Employer", "Insurance", "Count"]

    total = int(out["Count"].sum()) if not out.empty else 0
    out.loc[len(out)] = ["TOTAL", "", total]
    return out


def excel_bytes_from_dfs(dfs: Dict[str, pd.DataFrame]) -> bytes:
    bio = io.BytesIO()
    with pd.ExcelWriter(bio, engine="openpyxl") as writer:
        for name, df in dfs.items():
            df.to_excel(writer, sheet_name=str(name)[:31], index=False)
    bio.seek(0)
    return bio.read()


# ---------------------------
# S3 helpers
# ---------------------------

def _safe_filename(name: str, max_len: int = 80) -> str:
    """Make a filename-safe chunk (no slashes/illegal chars)."""
    name = str(name)
    name = re.sub(r'[\\/:*?"<>|\n\r\t]+', "_", name)
    name = re.sub(r"\s+", " ", name).strip()
    if len(name) > max_len:
        name = name[:max_len].rstrip()
    return name or "file"


def download_excel_button(df: pd.DataFrame, filename: str, label: str):
    """Download a dataframe as a single-sheet Excel file."""
    if df is None or df.empty:
        st.info("No data available to download.")
        return
    b = excel_bytes_from_dfs({"data": df})
    st.download_button(
        label,
        data=b,
        file_name=filename,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def load_secrets() -> Dict[str, str]:
    def get_any(*keys):
        for k in keys:
            if k in st.secrets:
                v = st.secrets.get(k)
                if v is not None and str(v).strip() != "":
                    return str(v).strip()
            v = os.getenv(k)
            if v is not None and str(v).strip() != "":
                return str(v).strip()
        return ""

    return {
        "AWS_ACCESS_KEY_ID": get_any("AWS_ACCESS_KEY_ID"),
        "AWS_SECRET_ACCESS_KEY": get_any("AWS_SECRET_ACCESS_KEY"),
        "AWS_REGION": get_any("AWS_REGION", "AWS_DEFAULT_REGION"),
        "S3_BUCKET_NAME": get_any("S3_BUCKET_NAME", "S3_BUCKET"),
        "S3_BASE_PREFIX": get_any("S3_BASE_PREFIX", "S3_PREFIX"),
    }


def s3_enabled(cfg: Dict[str, str]) -> bool:
    return bool(cfg.get("S3_BUCKET_NAME")) and bool(cfg.get("AWS_REGION")) and bool(cfg.get("AWS_ACCESS_KEY_ID")) and bool(cfg.get("AWS_SECRET_ACCESS_KEY")) and boto3 is not None


@st.cache_resource(show_spinner=False)
def s3_client_cached(cfg: Dict[str, str]):
    if not s3_enabled(cfg):
        return None
    return boto3.client(
        "s3",
        region_name=cfg["AWS_REGION"],
        aws_access_key_id=cfg["AWS_ACCESS_KEY_ID"],
        aws_secret_access_key=cfg["AWS_SECRET_ACCESS_KEY"],
    )


def s3_key(*parts: str) -> str:
    return "/".join([p.strip("/").strip() for p in parts if p is not None and str(p).strip() != ""])


def s3_put_bytes(s3, bucket: str, key: str, b: bytes, content_type: str = "application/octet-stream"):
    s3.put_object(Bucket=bucket, Key=key, Body=b, ContentType=content_type)


def s3_get_bytes(s3, bucket: str, key: str) -> Optional[bytes]:
    try:
        obj = s3.get_object(Bucket=bucket, Key=key)
        return obj["Body"].read()
    except Exception:
        return None


def s3_list_prefixes(s3, bucket: str, prefix: str) -> List[str]:
    out = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix.rstrip("/") + "/", Delimiter="/"):
        for cp in page.get("CommonPrefixes", []):
            p = cp.get("Prefix", "")
            if p:
                out.append(p)
    return out


# ---------------------------
# Center selection
# ---------------------------

CENTERS = {
    "easyhealth": "Easy Health Medical Clinic (MF8031)",
    "excellent": "Excellent Medical Center (MF4777)",
    "pharmacy": "Excellent Pharmacy (PF3205)",
}

# -------------------- Center default (Excellent) --------------------
SS = st.session_state
SS.setdefault("center_key", "excellent")

# if URL contains ?center=..., allow it (and persist it)
_q_center = st.query_params.get("center")
if _q_center in CENTERS:
    SS["center_key"] = _q_center

center_key = SS.get("center_key", "excellent")
if center_key not in CENTERS:
    center_key = "excellent"
    SS["center_key"] = center_key

# optional selector (only if you want to change center manually)
center_key = st.selectbox(
    "Center",
    options=list(CENTERS.keys()),
    index=(list(CENTERS.keys()).index(center_key) if center_key in CENTERS else 0),
    format_func=lambda k: CENTERS[k],
    key="center_selector",
)
SS["center_key"] = center_key
cfg = load_secrets()
s3_ok = s3_enabled(cfg)
s3 = s3_client_cached(cfg) if s3_ok else None

with st.expander("Storage Status (S3)", expanded=False):
    if s3_ok:
        st.success(f"S3 is configured ✅  Bucket: {cfg['S3_BUCKET_NAME']}  Region: {cfg['AWS_REGION']}")
        if cfg.get('S3_BASE_PREFIX'):
            st.caption(f"Base prefix: {cfg.get('S3_BASE_PREFIX')}")
        else:
            st.caption("No base prefix configured - using root bucket")
    else:
        st.warning("S3 is NOT configured. Uploaders will work and summary will display, but files will NOT be saved to S3.")
        st.caption("Expected secrets: S3_BUCKET_NAME (or S3_BUCKET), AWS_REGION (or AWS_DEFAULT_REGION), AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY. Optional: S3_BASE_PREFIX")


with st.expander("Employer Normalization Rules", expanded=False):
    st.caption("These rules merge employer name variations into ONE company for Employer Wise counts.")
    st.markdown("**Exact aliases (after cleaning):**")
    try:
        _alias_df = pd.DataFrame(sorted(EMPLOYER_ALIAS.items()), columns=["If employer is", "Group as"])
        st.dataframe(_alias_df, use_container_width=True, hide_index=True)
    except Exception:
        st.write(EMPLOYER_ALIAS)

    st.markdown("**Prefix aliases (take initial only):**")
    try:
        _pref_df = pd.DataFrame(
            [{"If employer starts with": a, "Group as": b} for a, b in EMPLOYER_PREFIX_ALIAS],
        )
        st.dataframe(_pref_df, use_container_width=True, hide_index=True)
    except Exception:
        st.write(EMPLOYER_PREFIX_ALIAS)

    st.caption("Admin tip: Add new spelling variations by editing EMPLOYER_ALIAS / EMPLOYER_PREFIX_ALIAS in this file.")

st.caption("✅ Day is read from Registration file (if it has a date column). Date picker is used only if file has no date column.")
manual_day = st.date_input("Manual Day (fallback only)", value=date.today())

SS = st.session_state

# -------------------- Defaults --------------------
DEFAULT_CENTER_KEY = "excellent"
if "center_key" not in SS or not SS.get("center_key"):
    SS["center_key"] = DEFAULT_CENTER_KEY

SS.setdefault("reg_file", None)
SS.setdefault("cash_file", None)
SS.setdefault("pend_file", None)
SS.setdefault("income_file", None)
SS.setdefault("reg_df", None)
SS.setdefault("cash_df", None)
SS.setdefault("pend_df", None)
SS.setdefault("income_df", None)
SS.setdefault("income_tables", {})

SS.setdefault("cpticd_file", None)
SS.setdefault("cpticd_df", None)
SS.setdefault("cpticd_tables", {})

if admin_mode:
    # Step 1
    c1, c2 = st.columns([3, 1])
    with c1:
        up1 = st.file_uploader("Upload Registration file", type=["xls", "xlsx"], key="uploader_reg")
    with c2:
        if st.button("🗑️ Delete Step 1", use_container_width=True):
            SS["reg_file"], SS["reg_df"] = None, None
            st.rerun()

    if up1 is not None:
        try:
            reg_df = read_excel_any(up1, required_hint=["EMRNo", "VisitNo"])
            SS["reg_df_cached"] = reg_df.copy()
            ensure_required(reg_df, ["EMRNo", "VisitNo"], "Step 1 (Registration)")
            SS["reg_file"] = {"name": up1.name, "bytes": up1.getvalue()}
            SS["reg_df"] = reg_df
            st.success(f"Step 1 OK ✅  ({up1.name})")
        except Exception as e:
            SS["reg_file"], SS["reg_df"] = None, None
            st.error(str(e))

    # Step 2
    st.markdown("### 2) PatientCashOutList (.xls / .xlsx)")
    c1, c2 = st.columns([3, 1])
    with c1:
        up2 = st.file_uploader("Upload CashOut file", type=["xls", "xlsx"], key="uploader_cash", disabled=(SS["reg_df"] is None))
    with c2:
        if st.button("🗑️ Delete Step 2", use_container_width=True):
            SS["cash_file"], SS["cash_df"] = None, None
            st.rerun()

    if up2 is not None:
        try:
            cash_df = read_excel_any(up2, required_hint=["EMRNo"])
            ensure_required(cash_df, ["EMRNo"], "Step 2 (CashOut)")
            SS["cash_file"] = {"name": up2.name, "bytes": up2.getvalue()}
            SS["cash_df"] = cash_df
            st.success(f"Step 2 OK ✅  ({up2.name})")
        except Exception as e:
            SS["cash_file"], SS["cash_df"] = None, None
            st.error(str(e))

    # Step 3
    st.markdown("### 3) Pending file (.xls / .xlsx)")
    c1, c2 = st.columns([3, 1])
    with c1:
        up3 = st.file_uploader("Upload Pending file", type=["xls", "xlsx"], key="uploader_pend", disabled=(SS["cash_df"] is None))
    with c2:
        if st.button("🗑️ Delete Step 3", use_container_width=True):
            SS["pend_file"], SS["pend_df"] = None, None
            st.rerun()

    if up3 is not None:
        try:
            pend_df = read_excel_any(up3, required_hint=["EMRNo"])
            ensure_required(pend_df, ["EMRNo"], "Step 3 (Pending)")
            SS["pend_file"] = {"name": up3.name, "bytes": up3.getvalue()}
            SS["pend_df"] = pend_df
            st.success(f"Step 3 OK ✅  ({up3.name})")
        except Exception as e:
            SS["pend_file"], SS["pend_df"] = None, None
            st.error(str(e))


def compute_summary(reg_df: pd.DataFrame, cash_df: pd.DataFrame, pend_df: pd.DataFrame, day_ts: pd.Timestamp) -> Dict[str, pd.DataFrame]:
    reg_map = ensure_required(reg_df, ["EMRNo", "VisitNo"], "Registration")
    emr_col, visit_col = reg_map["EMRNo"], reg_map["VisitNo"]

    doctor_col = _find_col(reg_df, ["Doctor", "DoctorName", "Physician", "Provider"])
    ins_col = _find_col(reg_df, ["Insurance", "InsuranceName", "Payer", "PayerName"])
    emp_col = _find_col(reg_df, ["Employer", "Employer Name", "EmployerName", "Company", "Company Name", "Sponsor", "Sponsor Name", "Corporate", "Corporate Name"])
    bill_col = _find_col(reg_df, ["BillType", "Bill Type", "Insurance/Cash", "Cash/Insurance"])
    visit_type_col = _find_col(reg_df, ["VisitType", "Visit Type", "VisitCategory"])
    status_col = _find_col(reg_df, ["Status", "VisitStatus"])
    pend_status_col = _find_col(pend_df, ["Status", "VisitStatus", "Pending Status"])
    reg_user_col = _find_col(reg_df, ["RegUser", "RegistrationUser", "User", "CreatedBy"])
    reg_date_col = _find_col(reg_df, ["RegDate", "RegistrationDate", "Date", "VisitDate", "Reg Date", "Registration Date"])

    total_visits = int(len(reg_df))
    unique_emr = int(pd.Series(reg_df[emr_col]).nunique(dropna=True))
    unique_visitno = int(pd.Series(reg_df[visit_col]).nunique(dropna=True))

    # Calculate New / Established / Follow Up from Visit Type
    new_visits = 0
    established_visits = 0
    follow_up_visits = 0

    if visit_type_col and visit_type_col in reg_df.columns:
        vt = reg_df[visit_type_col].astype(str).str.lower().str.strip().fillna("")

        follow_mask = vt.str.contains(r"\bfollow\b")  # follow up / follow-up
        est_mask = (~follow_mask) & (vt.str.contains(r"\bestablished\b") | vt.str.contains(r"\bestd\b"))
        new_mask = (~follow_mask) & (~est_mask) & (vt.str.len() > 0)

        follow_up_visits = int(follow_mask.sum())
        established_visits = int(est_mask.sum())
        new_visits = int(new_mask.sum())

    unclassified_visits = int(total_visits - (new_visits + established_visits + follow_up_visits))
    if unclassified_visits < 0:
        unclassified_visits = 0

    cash_emr = ensure_required(cash_df, ["EMRNo"], "CashOut")["EMRNo"]
    pend_emr = ensure_required(pend_df, ["EMRNo"], "Pending")["EMRNo"]
    cash_patients = int(pd.Series(cash_df[cash_emr]).nunique(dropna=True))
    pending_patients = int(pd.Series(pend_df[pend_emr]).nunique(dropna=True))

    if reg_date_col:
        d1 = pd.to_datetime(reg_df[reg_date_col], errors="coerce", dayfirst=False)
        d2 = pd.to_datetime(reg_df[reg_date_col], errors="coerce", dayfirst=True)
        d = (d2 if int(d2.notna().sum()) >= int(d1.notna().sum()) else d1).dt.date
        reg_daywise = pd.Series(d).dropna().value_counts().sort_index().reset_index()
        reg_daywise.columns = ["Reg Date", "Count"]
    else:
        reg_daywise = pd.DataFrame({"Reg Date": [day_ts.date()], "Count": [total_visits]})

    # Update KPI DataFrame with new structure
    kpi_data = [
        {"Metric": "Day", "Value": day_ts.date().isoformat()},
        {"Metric": "Total Visits", "Value": total_visits},
        {"Metric": "New Patients", "Value": new_visits},
        {"Metric": "Established Patients", "Value": established_visits},
        {"Metric": "Follow Up", "Value": follow_up_visits},
        {"Metric": "Unclassified Visits", "Value": unclassified_visits},
        {"Metric": "Pending Patients", "Value": pending_patients},
    ]

    return {
        "KPI": pd.DataFrame(kpi_data),
        "Doctor Wise Visits": top_counts(reg_df, doctor_col, n=50, label="Doctor"),
        "Insurance Wise Visits": top_counts(reg_df, ins_col, n=50, label="Insurance"),
        "Employer Wise": employer_wise_with_insurance(reg_df, emp_col=emp_col, ins_col=ins_col, n=50),
        "Bill Type": top_counts(reg_df, bill_col, n=20, label="Bill Type"),
        "Visit Type": top_counts(reg_df, visit_type_col, n=20, label="Visit Type"),
        "Status Wise": top_counts(reg_df, status_col, n=30, label="Status"),
        "Pending Status Wise": top_counts(pend_df, pend_status_col, n=30, label="Status"),
        "Registration User Wise": top_counts(reg_df, reg_user_col, n=30, label="User"),
        "Reg Date Wise (Daily)": reg_daywise,
    }


def history_paths(center: str, base_prefix: str = "") -> Tuple[str, str]:
    """Return (root_prefix, history_csv_key) for this center.
    
    MODIFIED: Saves to registration/{center}/ at same level as streamlit/, rejection_cache/
    """
    # Completely ignore any base_prefix to ensure we save at root level
    # This creates: registration/{center}/
    root = s3_key("registration", center)
    return root, s3_key(root, "history.csv")


def save_run_to_s3(day_ts: pd.Timestamp, dfs: Dict[str, pd.DataFrame]):
    # Use the modified history_paths that saves to registration/{center}/
    root, hist_key = history_paths(center_key, cfg.get("S3_BASE_PREFIX", ""))
    
    day_str = day_ts.date().isoformat()

    # Save files to the new location
    if SS["reg_file"]:
        s3_put_bytes(s3, cfg["S3_BUCKET_NAME"], s3_key(root, day_str, "registration.xlsx"), SS["reg_file"]["bytes"])
    if SS["cash_file"]:
        s3_put_bytes(s3, cfg["S3_BUCKET_NAME"], s3_key(root, day_str, "cashout.xlsx"), SS["cash_file"]["bytes"])
    if SS["pend_file"]:
        s3_put_bytes(s3, cfg["S3_BUCKET_NAME"], s3_key(root, day_str, "pending.xlsx"), SS["pend_file"]["bytes"])

    if SS.get("income_file"):
        s3_put_bytes(s3, cfg["S3_BUCKET_NAME"], s3_key(root, day_str, "income.xlsx"), SS["income_file"]["bytes"])
    if SS.get("cpticd_file"):
        s3_put_bytes(s3, cfg["S3_BUCKET_NAME"], s3_key(root, day_str, "cpticd.xlsx"), SS["cpticd_file"]["bytes"])


    s3_put_bytes(s3, cfg["S3_BUCKET_NAME"], s3_key(root, day_str, "summary.pkl"), pickle.dumps(dfs, protocol=pickle.HIGHEST_PROTOCOL))

    # Extract KPI values safely
    kpi = dfs.get("KPI")
    if kpi is not None and not kpi.empty and "Metric" in kpi.columns and "Value" in kpi.columns:
        k = kpi.set_index("Metric")["Value"]
        
        # Handle numeric conversion safely
        def safe_int(val, default=0):
            try:
                if isinstance(val, (int, float)):
                    return int(val)
                elif isinstance(val, str) and val.replace('.', '').isdigit():
                    return int(float(val))
                else:
                    return default
            except:
                return default
        
        row = {
            "day": pd.to_datetime(day_str),
            "total_visits": safe_int(k.get("Total Visits", 0)),
            "new_visits": safe_int(k.get("New Visits", 0)),
            "established_visits": safe_int(k.get("Established Visits", 0)),
            "pending_patients": safe_int(k.get("Pending Patients", 0)),
        }
    else:
        # Fallback if KPI not found
        row = {
            "day": pd.to_datetime(day_str),
            "total_visits": 0,
            "new_visits": 0,
            "established_visits": 0,
            "pending_patients": 0,
        }

    existing = None
    b = s3_get_bytes(s3, cfg["S3_BUCKET_NAME"], hist_key)
    if b:
        existing = pd.read_csv(io.BytesIO(b), parse_dates=["day"])
    if existing is None or existing.empty:
        new_hist = pd.DataFrame([row])
    else:
        existing["day"] = pd.to_datetime(existing["day"]).dt.normalize()
        new_hist = existing[existing["day"].dt.date.astype(str) != day_str].copy()
        new_hist = pd.concat([new_hist, pd.DataFrame([row])], ignore_index=True)

    new_hist = new_hist.sort_values("day").reset_index(drop=True)
    s3_put_bytes(s3, cfg["S3_BUCKET_NAME"], hist_key, new_hist.to_csv(index=False).encode("utf-8"), content_type="text/csv")


def load_history_from_s3() -> pd.DataFrame:
    if not s3_ok:
        return pd.DataFrame()
    _, hist_key = history_paths(center_key, cfg.get("S3_BASE_PREFIX", ""))
    b = s3_get_bytes(s3, cfg["S3_BUCKET_NAME"], hist_key)
    if not b:
        return pd.DataFrame()
    return pd.read_csv(io.BytesIO(b), parse_dates=["day"])


def load_summary_from_s3(day_ts: pd.Timestamp) -> Optional[Dict[str, pd.DataFrame]]:
    """Load a previously saved summary.pkl for a given day from S3."""
    if not s3_ok:
        return None
    root, _ = history_paths(center_key, cfg.get("S3_BASE_PREFIX", ""))
    day_str = pd.to_datetime(day_ts).date().isoformat()
    key = s3_key(root, day_str, "summary.pkl")
    b = s3_get_bytes(s3, cfg["S3_BUCKET_NAME"], key)
    if not b:
        return None
    try:
        return pickle.loads(b)
    except Exception:
        return None


def render_summary(dfs: Dict[str, pd.DataFrame], day_ts: pd.Timestamp):
    """Render the Current Day + Accumulated sections."""
    st.header(f"Current Day ({day_ts.date().isoformat()})")

    # KPI cards
    kpi = dfs.get("KPI")
    if kpi is not None and not kpi.empty and "Metric" in kpi.columns and "Value" in kpi.columns:
        k = kpi.set_index("Metric")["Value"]
        a, b, c, d = st.columns(4)
        a.metric("Total Visits", int(k.get("Total Visits", 0)))
        new_val = k.get("New Visits", 0)
        b.metric("New Visits", 
                int(new_val) if isinstance(new_val, (int, float)) else new_val)
        est_val = k.get("Established Visits", 0)
        c.metric("Established Visits", 
                int(est_val) if isinstance(est_val, (int, float)) else est_val)
        d.metric("Pending Patients", int(k.get("Pending Patients", 0)))
    else:
        st.info("KPI is not available for this summary.")

    # Pending Status Wise (before Insurance)
    st.subheader("Pending Status Wise")
    if "Pending Status Wise" in dfs:
        st.dataframe(dfs["Pending Status Wise"], use_container_width=True, hide_index=True)
    else:
        st.info("Pending Status Wise is not available for this saved summary. Please re-process today's files to generate it.")

    # Insurance Wise
    st.subheader("Insurance Wise Visits")
    if "Insurance Wise Visits" in dfs:
        st.dataframe(dfs["Insurance Wise Visits"], use_container_width=True, hide_index=True)
    else:
        st.info("Insurance Wise Visits is not available.")

    # Employer Wise
    st.subheader("Employer Wise")
    if "Employer Wise" in dfs:
        st.dataframe(dfs["Employer Wise"], use_container_width=True, hide_index=True)
    else:
        st.info("Employer Wise is not available for this saved summary. Please re-process today's files to generate it.")

    # Doctor Wise
    st.subheader("Doctor Wise Visits")
    if "Doctor Wise Visits" in dfs:
        st.dataframe(dfs["Doctor Wise Visits"], use_container_width=True, hide_index=True)
    else:
        st.info("Doctor Wise Visits is not available.")

    # Row-level Downloads
    st.markdown("---")
    st.subheader("Download Details (Row-level)")

    with st.expander("Download Pending Details (by Status)", expanded=False):
        pend_df = SS.get("pend_df")
        if pend_df is None:
            st.info("Pending file is not loaded in this session. Upload/Process today's files to enable row-level download.")
        else:
            pend_status_col = _find_col(pend_df, ["Status", "VisitStatus", "Pending Status"])
            if not pend_status_col:
                st.warning("Pending file has no Status column (Status / VisitStatus).")
            else:
                tmp = pend_df.copy()
                tmp[pend_status_col] = tmp[pend_status_col].fillna("Blank").astype(str).str.strip().replace("", "Blank")
                statuses = sorted(tmp[pend_status_col].unique())
                pick_status = st.selectbox("Select Pending Status", options=statuses, key="dl_pending_status")
                detail = tmp[tmp[pend_status_col] == pick_status].copy()
                fn = f"Pending_{_safe_filename(pick_status)}_{day_ts.date().isoformat()}.xlsx"
                download_excel_button(detail, fn, "⬇️ Download Pending Rows (Excel)")

    with st.expander("Download Registration Details (by Insurance)", expanded=False):
        reg_df = SS.get("reg_df")
        if reg_df is None:
            st.info("Registration file is not loaded in this session. Upload/Process today's files to enable row-level download.")
        else:
            ins_col = _find_col(reg_df, ["Insurance", "InsuranceName", "Payer", "PayerName"])
            if not ins_col:
                st.warning("Registration file has no Insurance/Payer column.")
            else:
                tmp = reg_df.copy()
                tmp[ins_col] = tmp[ins_col].fillna("CASH").astype(str).str.strip().replace("", "CASH").replace("Blank", "CASH")
                ins_list = sorted(tmp[ins_col].unique())
                pick_ins = st.selectbox("Select Insurance", options=ins_list, key="dl_insurance")
                detail = tmp[tmp[ins_col] == pick_ins].copy()
                fn = f"Registration_Insurance_{_safe_filename(pick_ins)}_{day_ts.date().isoformat()}.xlsx"
                download_excel_button(detail, fn, "⬇️ Download Insurance Rows (Excel)")

    with st.expander("Download Registration Details (by Employer)", expanded=False):
        reg_df = SS.get("reg_df")
        if reg_df is None:
            st.info("Registration file is not loaded in this session. Upload/Process today's files to enable row-level download.")
        else:
            emp_col = _find_col(reg_df, ["Employer", "Employer Name", "EmployerName", "Company", "Company Name", "Sponsor", "Sponsor Name", "Corporate", "Corporate Name"])
            if not emp_col:
                st.warning("Registration file has no Employer/Company column.")
            else:
                tmp = reg_df.copy()
                tmp[emp_col] = tmp[emp_col].fillna("Blank").astype(str).str.strip().replace("", "Blank")
                tmp["__emp_key__"] = tmp[emp_col].apply(employer_canonical_name)

                # display name = most frequent original in each normalized group
                disp = (
                    tmp.groupby(["__emp_key__", emp_col]).size().reset_index(name="cnt")
                    .sort_values(["__emp_key__", "cnt"], ascending=[True, False])
                    .drop_duplicates(subset=["__emp_key__"])
                )
                # build select options: "Display Name (count)"
                counts = tmp.groupby("__emp_key__").size().reset_index(name="Count")
                disp = disp.merge(counts, on="__emp_key__", how="left")
                disp = disp.sort_values("Count", ascending=False)

                options = disp["__emp_key__"].tolist()
                labels = {r["__emp_key__"]: f"{r[emp_col]} ({int(r['Count'])})" for _, r in disp.iterrows()}

                pick_key = st.selectbox(
                    "Select Employer (deduped)",
                    options=options,
                    format_func=lambda k: labels.get(k, k),
                    key="dl_employer_key",
                )
                detail = tmp[tmp["__emp_key__"] == pick_key].drop(columns=["__emp_key__"], errors="ignore").copy()
                fn = f"Registration_Employer_{_safe_filename(labels.get(pick_key, pick_key))}_{day_ts.date().isoformat()}.xlsx"
                download_excel_button(detail, fn, "⬇️ Download Employer Rows (Excel)")

    # Whole Summary Excel
    export_dfs = {k: dfs[k] for k in dfs.keys()}
    st.download_button(
        "⬇️ Download Summary Excel",
        data=excel_bytes_from_dfs(export_dfs),
        file_name=f"Registration_Summary_{center_key}_{day_ts.date().isoformat()}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    # Accumulated
    st.header("Accumulated (All Saved Days)")
    hist = load_history_from_s3() if s3_ok else pd.DataFrame()
    if hist.empty:
        st.info("No saved history found yet.")
    else:
        acc = add_cumulative(hist)
        latest = acc.sort_values("day").iloc[-1]
        a, b, c, d = st.columns(4)
        a.metric("Cumulative Visits", int(latest.get("cum_total_visits", 0)))
        b.metric("Cumulative New Visits", int(latest.get("cum_new_visits", 0)))
        c.metric("Cumulative Established Visits", int(latest.get("cum_established_visits", 0)))
        d.metric("Cumulative Pending", int(latest.get("cum_pending_patients", 0)))
        st.dataframe(acc, use_container_width=True, hide_index=True)

def add_cumulative(hist: pd.DataFrame) -> pd.DataFrame:
    if hist is None or hist.empty:
        return pd.DataFrame()
    h = hist.sort_values("day").copy()
    for c in ["total_visits", "new_visits", "established_visits", "pending_patients"]:
        if c in h.columns:
            h[c] = h[c].fillna(0).astype(int)
            h[f"cum_{c}"] = h[c].cumsum()

    cols = [
        "day", "total_visits", "new_visits", "established_visits", "pending_patients",
        "cum_total_visits", "cum_new_visits", "cum_established_visits", "cum_pending_patients"
    ]
    cols = [c for c in cols if c in h.columns]
    return h[cols].sort_values("day", ascending=False).reset_index(drop=True)


# ---------------------------
# Process & display
# ---------------------------

can_process = SS["reg_df"] is not None and SS["cash_df"] is not None and SS["pend_df"] is not None

# Persist last result in-session (so it doesn't disappear on rerun)
SS.setdefault("last_saved_day", None)
SS.setdefault("last_saved_center", None)

if admin_mode:
    # Day selection (prefer detected from Registration file; fallback to manual picker)
    detected = get_day_from_registration(SS["reg_df"]) if SS["reg_df"] is not None else None
    day_ts = detected if detected is not None else pd.to_datetime(manual_day)

    if detected is None and SS["reg_df"] is not None:
        st.warning("Registration file has no readable date column. Using Manual Day.")
    elif detected is not None:
        st.success(f"Detected Day from Registration file: {day_ts.date().isoformat()}")
    st.markdown("---")
    st.subheader("Processing Scope")
    scope = st.radio(
        "Select how you want to process the uploaded files:",
        options=["Daily (single date)", "Weekly", "Monthly", "Bulk (split & save all dates found in Registration)"],
        index=0,
        horizontal=True,
        help="Daily saves one selected/detected day. Bulk will split the Registration file by date and save each day to S3 (best for full-year uploads). Weekly/Monthly are for display in View page (no special save needed).",
    )
    bulk_mode = (scope == "Bulk (split & save all dates found in Registration)")

    # -------------------- Step 4 (Income / Doctor Revenue) - optional --------------------
    c1, c2 = st.columns([3, 1])
    with c1:
        st.subheader("4) Income Analysis Report (Doctor Revenue)")
        income_up = st.file_uploader(
            "Upload Daily Collection Details (.xls / .xlsx)",
            type=["xls", "xlsx"],
            key="income_uploader",
        )
        if income_up is not None:
            SS["income_file"] = {"name": income_up.name, "bytes": income_up.getvalue()}
    with c2:
        if st.button("🗑️ Delete Step 4", use_container_width=True):
            SS["income_file"] = None
            SS["income_df"] = None
            SS["income_tables"] = {}
            st.rerun()

    if SS.get("income_file") is not None:
        st.success(f"Step 4 OK ✅ ({SS['income_file']['name']})")
    else:
        st.info("Step 4 optional: upload your Daily Collection Details export to generate Doctor/Insurance revenue tables.")

    # -------------------- Step 5 (CPT / ICD Analysis) - optional --------------------
    c1, c2 = st.columns([3, 1])
    with c1:
        st.subheader("5) CPT ICD Analysis (Doctor / Company / CPT Mapping)")
        cpticd_up = st.file_uploader(
            "Upload RegistrationDetailswithICDandCPTList (.xls / .xlsx)",
            type=["xls", "xlsx"],
            key="cpticd_uploader",
        )
        if cpticd_up is not None:
            SS["cpticd_file"] = {"name": cpticd_up.name, "bytes": cpticd_up.getvalue()}
    with c2:
        if st.button("🗑️ Delete Step 5", use_container_width=True):
            SS["cpticd_file"] = None
            SS["cpticd_df"] = None
            SS["cpticd_tables"] = {}
            st.rerun()

    if SS.get("cpticd_file") is not None:
        st.success(f"Step 5 OK ✅ ({SS['cpticd_file']['name']})")
    else:
        st.info("Step 5 optional: upload your RegistrationDetailswithICDandCPTList export to generate CPT/ICD analytics + Employer expiry tracking.")

    # -------------------- Process & Save --------------------
    process_label = "✅ Process & Save to S3" if s3_ok else "✅ Process (S3 not configured)"
    if st.button(process_label, type="primary", disabled=not can_process):
        # defaults (avoid NameError in any edge-case)
        day_ts = pd.to_datetime(manual_day)
        _income_df = None

        # re-evaluate day_ts inside click (safe)
        detected = get_day_from_registration(SS['reg_df']) if SS['reg_df'] is not None else None
        if detected is not None:
            day_ts = detected

        # -------------------------
        # Daily vs Bulk processing
        # -------------------------
        if bulk_mode:
            days = get_days_from_registration(SS["reg_df"]) if SS["reg_df"] is not None else []
            if not days:
                st.error("Bulk mode selected, but no readable date column was found in Registration file. Please use Daily mode or upload a file with RegDate/Date.")
                st.stop()

            st.info(f"Bulk mode: found {len(days)} day(s) in Registration. Saving each day to S3...")

            # Optional income analysis file (applied as-is; if it contains multiple days, we will NOT split it)
            _income_df = None
            income_tbls = {}
            if SS.get('income_file') is not None:
                _income_df = load_income_details(io.BytesIO(SS.get('income_file', {}).get('bytes', b'')))
                if _income_df is None or _income_df.empty:
                    st.warning("Income Analysis file loaded, but header could not be detected. Skipping Income tables in bulk save.")
                else:
                    income_tbls = income_tables(_income_df)

            

            # Optional CPT/ICD analysis file (applied as-is; if it contains multiple days, we will NOT split it)
            cpticd_tbls = {}
            if SS.get("cpticd_file") is not None:
                _cpticd_df = load_cpticd_details(io.BytesIO(SS.get("cpticd_file", {}).get("bytes", b"")))
                if _cpticd_df is None or _cpticd_df.empty:
                    st.warning("CPT/ICD file loaded, but no data was found. Skipping CPT/ICD tables in bulk save.")
                else:
                    cpticd_df_bulk = _cpticd_df
                    cpticd_tbls = {}  # will be computed per-day inside the loop using reg_day
                    if not cpticd_tbls:
                        st.warning("CPT/ICD file loaded, but required columns were not detected. Skipping CPT/ICD tables in bulk save.")
progress = st.progress(0.0)
            saved = 0

            # Detect Registration date col once for filtering
            reg_date_col = _find_col(SS["reg_df"], ["RegDate", "RegistrationDate", "Date", "VisitDate", "Reg Date", "Registration Date"])
            s_raw = SS["reg_df"][reg_date_col] if reg_date_col else None
            s1 = pd.to_datetime(s_raw, errors="coerce", dayfirst=False) if s_raw is not None else None
            s2 = pd.to_datetime(s_raw, errors="coerce", dayfirst=True) if s_raw is not None else None
            n1 = int(s1.notna().sum()) if s1 is not None else 0
            n2 = int(s2.notna().sum()) if s2 is not None else 0
            s_reg = (s2 if n2 >= n1 else s1) if s1 is not None else None

            for idx, d in enumerate(days, start=1):
                d_norm = pd.to_datetime(d).normalize()
                if s_reg is None:
                    reg_day = SS["reg_df"].copy()
                else:
                    mask = s_reg.dt.normalize() == d_norm
                    reg_day = SS["reg_df"].loc[mask.fillna(False)].copy()

                cash_day = filter_df_by_day_if_possible(SS["cash_df"], d_norm)
                pend_day = filter_df_by_day_if_possible(SS["pend_df"], d_norm)

                dfs = compute_summary(reg_day, cash_day, pend_day, d_norm)

                # Attach income tables (same tables for all days; if you need day-wise split, upload day-wise income file)
                for _k, _v in income_tbls.items():
                    dfs[f"Income | {_k}"] = _v
                # Attach CPT/ICD tables (filtered to THIS day using reg_day visit IDs)
                if 'cpticd_df_bulk' in locals() and cpticd_df_bulk is not None and not cpticd_df_bulk.empty:
                    cpticd_tbls_day = cpticd_tables(cpticd_df_bulk, reg_df=reg_day)
                    for _k, _v in cpticd_tbls_day.items():
                        dfs[f"CPTICD | {_k}"] = _v


                if s3_ok:
                    save_run_to_s3(d_norm, dfs)

                saved += 1
                progress.progress(saved / max(1, len(days)))

            SS["last_saved_day"] = max(days)
            SS["last_saved_center"] = center_key
            st.success(f"Bulk save completed ✅  Days saved: {saved}")

        else:
            dfs = compute_summary(SS["reg_df"], SS["cash_df"], SS["pend_df"], day_ts)

            # ---- Step 4: Income analysis (optional) ----
            SS['income_df'] = None
            SS['income_tables'] = {}
            if SS.get('income_file') is not None:
                _income_df = load_income_details(io.BytesIO(SS.get('income_file', {}).get('bytes', b'')))
                if _income_df is None or _income_df.empty:
                    st.warning("Income Analysis file loaded, but table header could not be detected. Please upload the correct 'Daily Collection Details' export.")
                else:
                    SS['income_df'] = _income_df
                    SS['income_tables'] = income_tables(_income_df)
                    for _k, _v in SS['income_tables'].items():
                        dfs[f"Income | {_k}"] = _v

            # ---- Step 5: CPT/ICD analysis (optional) ----
            SS["cpticd_df"] = None
            SS["cpticd_tables"] = {}
            if SS.get("cpticd_file") is not None:
                _cpticd_df = load_cpticd_details(io.BytesIO(SS.get("cpticd_file", {}).get("bytes", b"")))
                if _cpticd_df is None or _cpticd_df.empty:
                    st.warning("CPT/ICD file loaded, but no data was found. Please upload the correct RegistrationDetailswithICDandCPTList export.")
                else:
                    SS["cpticd_df"] = _cpticd_df
                    SS["cpticd_tables"] = cpticd_tables(_cpticd_df, reg_df=SS.get("reg_df"))
                    if not SS["cpticd_tables"]:
                        st.warning("CPT/ICD file loaded, but required columns were not detected. Please check the template/headers.")
                    else:
                        for _k, _v in SS["cpticd_tables"].items():
                            dfs[f"CPTICD | {_k}"] = _v


            if s3_ok:
                try:
                    save_run_to_s3(day_ts, dfs)
                    st.success("Saved to S3 ✅")
                except Exception as e:
                    st.error(f"Failed to save to S3: {e}")

            SS["last_saved_day"] = day_ts
            SS["last_saved_center"] = center_key

# Confirmation (this admin upload page does not display KPI/details)
if SS.get("last_saved_day") is not None and SS.get("last_saved_center") is not None:
    st.success(
        f"✅ Uploaded & saved for {pd.to_datetime(SS['last_saved_day']).date().isoformat()}  |  "
        f"Center: {CENTERS.get(SS['last_saved_center'], SS['last_saved_center'])}"
    )
    st.caption("Open **Registration View** page to see the summary results.")
elif SS.get("reg_df") is not None:
    st.info("Upload Step 2 and Step 3, then click **Process & Save**.")
