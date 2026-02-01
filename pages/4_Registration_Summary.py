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
    date_col = _find_col(reg_df, ["RegDate", "RegistrationDate", "Date", "VisitDate", "Reg Date", "Registration Date"])
    if not date_col:
        return None
    s = pd.to_datetime(reg_df[date_col], errors="coerce").dropna()
    if s.empty:
        return None
    day = s.dt.normalize()
    try:
        return day.mode().iloc[0]
    except Exception:
        return day.min()


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


def employer_with_insurance(df: pd.DataFrame, emp_col: str, ins_col: str, n: int = 30) -> pd.DataFrame:
    tmp = df[[emp_col, ins_col]].copy()
    tmp[emp_col] = tmp[emp_col].fillna("Blank")
    tmp[ins_col] = tmp[ins_col].fillna("CASH")

    grp = (
        tmp.groupby([emp_col, ins_col])
        .size()
        .reset_index(name="Count")
        .sort_values("Count", ascending=False)
    )

    return grp.head(n)


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

center_key = st.session_state.get("center_key") or st.query_params.get("center") or None
if center_key not in CENTERS:
    center_key = st.selectbox("Center", options=list(CENTERS.keys()), format_func=lambda k: CENTERS[k])

cfg = load_secrets()
s3_ok = s3_enabled(cfg)
s3 = s3_client_cached(cfg) if s3_ok else None

with st.expander("Storage Status (S3)", expanded=False):
    if s3_ok:
        st.success(f"S3 is configured ✅  Bucket: {cfg['S3_BUCKET_NAME']}  Region: {cfg['AWS_REGION']}")
        st.caption(f"Base prefix: {cfg.get('S3_BASE_PREFIX') or '(none)'}")
    else:
        st.warning("S3 is NOT configured. Uploaders will work and summary will display, but files will NOT be saved to S3.")
        st.caption("Expected secrets: S3_BUCKET_NAME (or S3_BUCKET), AWS_REGION (or AWS_DEFAULT_REGION), AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY. Optional: S3_BASE_PREFIX")

st.caption("✅ Day is read from Registration file (if it has a date column). Date picker is used only if file has no date column.")
manual_day = st.date_input("Manual Day (fallback only)", value=date.today())

SS = st.session_state
SS.setdefault("reg_file", None)
SS.setdefault("cash_file", None)
SS.setdefault("pend_file", None)
SS.setdefault("reg_df", None)
SS.setdefault("cash_df", None)
SS.setdefault("pend_df", None)

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

    # 🔁 FINAL fallback: detect employer column by content (when headers are merged / show as Unnamed)
    if emp_col is None:
        for c in reg_df.columns:
            sample = reg_df[c].dropna().astype(str).head(10)
            if sample.empty:
                continue
            # employer names are usually text (company names), not pure numbers
            avg_len = sample.str.strip().str.len().mean()
            has_digits_only = sample.str.strip().str.match(r"^\d+$").any()
            if avg_len and avg_len > 12 and not has_digits_only:
                emp_col = c
                break

    bill_col = _find_col(reg_df, ["BillType", "Bill Type", "Insurance/Cash", "Cash/Insurance"])
    visit_type_col = _find_col(reg_df, ["VisitType", "Visit Type", "VisitCategory"])
    status_col = _find_col(reg_df, ["Status", "VisitStatus"])
    reg_user_col = _find_col(reg_df, ["RegUser", "RegistrationUser", "User", "CreatedBy"])
    reg_date_col = _find_col(reg_df, ["RegDate", "RegistrationDate", "Date", "VisitDate", "Reg Date", "Registration Date"])

    total_visits = int(len(reg_df))
    unique_emr = int(pd.Series(reg_df[emr_col]).nunique(dropna=True))
    unique_visitno = int(pd.Series(reg_df[visit_col]).nunique(dropna=True))

    cash_emr = ensure_required(cash_df, ["EMRNo"], "CashOut")["EMRNo"]
    pend_emr = ensure_required(pend_df, ["EMRNo"], "Pending")["EMRNo"]
    cash_patients = int(pd.Series(cash_df[cash_emr]).nunique(dropna=True))
    pending_patients = int(pd.Series(pend_df[pend_emr]).nunique(dropna=True))

    if reg_date_col:
        d = pd.to_datetime(reg_df[reg_date_col], errors="coerce").dt.date
        reg_daywise = pd.Series(d).dropna().value_counts().sort_index().reset_index()
        reg_daywise.columns = ["Reg Date", "Count"]
    else:
        reg_daywise = pd.DataFrame({"Reg Date": [day_ts.date()], "Count": [total_visits]})

    return {
        "KPI": pd.DataFrame([
            {"Metric": "Day", "Value": day_ts.date().isoformat()},
            {"Metric": "Total Visits", "Value": total_visits},
            {"Metric": "Unique EMR (Patients)", "Value": unique_emr},
            {"Metric": "Unique Visit No", "Value": unique_visitno},
            {"Metric": "CashOut Patients", "Value": cash_patients},
            {"Metric": "Pending Patients", "Value": pending_patients},
        ]),
        "Doctor Wise Visits": top_counts(reg_df, doctor_col, n=50, label="Doctor"),
        "Insurance Wise Visits": top_counts(reg_df, ins_col, n=50, label="Insurance"),
        "Employer Wise": top_counts(reg_df, emp_col, n=50, label="Employer"),
        "Bill Type": top_counts(reg_df, bill_col, n=20, label="Bill Type"),
        "Visit Type": top_counts(reg_df, visit_type_col, n=20, label="Visit Type"),
        "Status Wise": top_counts(reg_df, status_col, n=30, label="Status"),
        "Registration User Wise": top_counts(reg_df, reg_user_col, n=30, label="User"),
        "Reg Date Wise (Daily)": reg_daywise,
    }


def history_paths(center: str) -> Tuple[str, str]:
    base = cfg.get("S3_BASE_PREFIX") or ""
    root = s3_key(base, center, "registration_summary")
    return root, s3_key(root, "history.csv")


def save_run_to_s3(day_ts: pd.Timestamp, dfs: Dict[str, pd.DataFrame]):
    root, hist_key = history_paths(center_key)
    day_str = day_ts.date().isoformat()

    if SS["reg_file"]:
        s3_put_bytes(s3, cfg["S3_BUCKET_NAME"], s3_key(root, day_str, "registration.xlsx"), SS["reg_file"]["bytes"])
    if SS["cash_file"]:
        s3_put_bytes(s3, cfg["S3_BUCKET_NAME"], s3_key(root, day_str, "cashout.xlsx"), SS["cash_file"]["bytes"])
    if SS["pend_file"]:
        s3_put_bytes(s3, cfg["S3_BUCKET_NAME"], s3_key(root, day_str, "pending.xlsx"), SS["pend_file"]["bytes"])

    s3_put_bytes(s3, cfg["S3_BUCKET_NAME"], s3_key(root, day_str, "summary.pkl"), pickle.dumps(dfs, protocol=pickle.HIGHEST_PROTOCOL))

    kpi = dfs["KPI"].set_index("Metric")["Value"]
    row = {
        "day": pd.to_datetime(day_str),
        "total_visits": int(kpi["Total Visits"]),
        "unique_emr": int(kpi["Unique EMR (Patients)"]),
        "unique_visitno": int(kpi["Unique Visit No"]),
        "cash_patients": int(kpi["CashOut Patients"]),
        "pending_patients": int(kpi["Pending Patients"]),
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
    _, hist_key = history_paths(center_key)
    b = s3_get_bytes(s3, cfg["S3_BUCKET_NAME"], hist_key)
    if not b:
        return pd.DataFrame()
    return pd.read_csv(io.BytesIO(b), parse_dates=["day"])


def load_summary_from_s3(day_ts: pd.Timestamp) -> Optional[Dict[str, pd.DataFrame]]:
    """Load a previously saved summary.pkl for a given day from S3."""
    if not s3_ok:
        return None
    root, _ = history_paths(center_key)
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

    kpi = dfs["KPI"].set_index("Metric")["Value"]

    a, b, c, d = st.columns(4)
    a.metric("Total Visits", int(kpi["Total Visits"]))
    b.metric("Unique EMR (Patients)", int(kpi["Unique EMR (Patients)"]))
    c.metric("Unique Visit No", int(kpi["Unique Visit No"]))
    d.metric("CashOut Patients", int(kpi["CashOut Patients"]))
    e, f = st.columns(2)
    e.metric("Pending Patients", int(kpi["Pending Patients"]))
    f.metric("Generated", datetime.now().strftime("%Y-%m-%d %H:%M"))

    st.subheader("Insurance Wise Visits")
    st.dataframe(dfs["Insurance Wise Visits"], use_container_width=True, hide_index=True)

    
    st.subheader("Employer Wise (with Insurance)")

    emp_ins_df = employer_with_insurance(reg_df, emp_col, ins_col, n=50)
    st.dataframe(emp_ins_df, use_container_width=True)

    st.subheader
("Doctor Wise Visits")
    st.dataframe(dfs["Doctor Wise Visits"], use_container_width=True, hide_index=True)

    export_dfs = {k: dfs[k] for k in dfs.keys()}
    st.download_button(
        "⬇️ Download Summary Excel",
        data=excel_bytes_from_dfs(export_dfs),
        file_name=f"Registration_Summary_{center_key}_{day_ts.date().isoformat()}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    # Accumulated BELOW current day
    st.header("Accumulated (All Saved Days)")
    hist = load_history_from_s3() if s3_ok else pd.DataFrame()
    if hist.empty:
        st.info("No saved history found yet.")
    else:
        acc = add_cumulative(hist)
        latest = acc.sort_values("day").iloc[-1]
        a, b, c, d = st.columns(4)
        a.metric("Cumulative Visits", int(latest.get("cum_total_visits", 0)))
        b.metric("Cumulative Unique EMR", int(latest.get("cum_unique_emr", 0)))
        c.metric("Cumulative CashOut", int(latest.get("cum_cash_patients", 0)))
        d.metric("Cumulative Pending", int(latest.get("cum_pending_patients", 0)))
        st.dataframe(acc, use_container_width=True, hide_index=True)


def add_cumulative(hist: pd.DataFrame) -> pd.DataFrame:
    if hist is None or hist.empty:
        return pd.DataFrame()
    h = hist.sort_values("day").copy()
    for c in ["total_visits", "unique_emr", "unique_visitno", "cash_patients", "pending_patients"]:
        h[c] = h[c].fillna(0).astype(int)
        h[f"cum_{c}"] = h[c].cumsum()

    cols = [
        "day", "total_visits", "unique_emr", "unique_visitno", "cash_patients", "pending_patients",
        "cum_total_visits", "cum_unique_emr", "cum_unique_visitno", "cum_cash_patients", "cum_pending_patients"
    ]
    cols = [c for c in cols if c in h.columns]
    return h[cols].sort_values("day", ascending=False).reset_index(drop=True)


# ---------------------------
# Process & display
# ---------------------------

can_process = SS["reg_df"] is not None and SS["cash_df"] is not None and SS["pend_df"] is not None

# Persist last result in-session (so it doesn't disappear on rerun)
SS.setdefault("last_summary", None)
SS.setdefault("last_day_ts", None)

# If S3 is enabled, allow viewing previously saved results without re-processing
if s3_ok:
    hist_view = load_history_from_s3()
    if not hist_view.empty:
        days = sorted(pd.to_datetime(hist_view["day"]).dt.normalize().unique())
        # newest first in UI
        days_ui = list(reversed(days))
        picked = st.selectbox(
            "View saved day (from S3)",
            options=days_ui,
            format_func=lambda x: pd.to_datetime(x).date().isoformat(),
        )
        if st.button("📥 Load Saved Summary", use_container_width=True):
            loaded = load_summary_from_s3(pd.to_datetime(picked))
            if loaded:
                SS["last_summary"] = loaded
                SS["last_day_ts"] = pd.to_datetime(picked)
                st.success(f"Loaded saved summary for {pd.to_datetime(picked).date().isoformat()} ✅")
            else:
                st.warning("No saved summary.pkl found for that day.")
    else:
        st.caption("No history.csv found yet in S3 for this center.")


if admin_mode and can_process:
    detected = get_day_from_registration(SS["reg_df"])
    day_ts = detected if detected is not None else pd.to_datetime(manual_day)
    if detected is None:
        st.warning("Registration file has no readable date column. Using Manual Day.")
    else:
        st.success(f"Detected Day from Registration file: {day_ts.date().isoformat()}")

    if st.button("✅ Process & Save to S3" if s3_ok else "✅ Process (S3 not configured)", type="primary"):
        dfs = compute_summary(SS["reg_df"], SS["cash_df"], SS["pend_df"], day_ts)

        if s3_ok:
            try:
                save_run_to_s3(day_ts, dfs)
                st.success("Saved to S3 ✅")
            except Exception as e:
                st.error(f"Failed to save to S3: {e}")

        # ✅ keep result in session so it stays visible after any rerun
        SS["last_summary"] = dfs
        SS["last_day_ts"] = day_ts

# Show last result (either processed now, or loaded from S3)
if SS.get("last_summary") is not None and SS.get("last_day_ts") is not None:
    render_summary(SS["last_summary"], pd.to_datetime(SS["last_day_ts"]))
elif SS["reg_df"] is not None:
    st.info("Please upload Step 2 and Step 3 in sequence to enable processing, or load a saved day from S3.")
