#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import io
import json
import re
from datetime import datetime, date
from typing import Optional, Tuple, List, Dict

import pandas as pd
import streamlit as st

# ---- S3 (required) ----
import boto3
from botocore.exceptions import ClientError


# =========================================================
# Page Config
# =========================================================
st.set_page_config(page_title="Registration Summary (Registration + CashOut + Pending)", layout="wide")
st.title("Registration Summary (Registration + CashOut + Pending)")


# =========================================================
# Secrets (REQUIRED)
# =========================================================
REQUIRED_KEYS = ["S3_BUCKET_NAME", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_REGION"]

def get_secret(key: str, default=None):
    try:
        return st.secrets.get(key, default)
    except Exception:
        return default

def s3_required_or_stop():
    missing = [k for k in REQUIRED_KEYS if not get_secret(k)]
    if missing:
        st.error(
            "S3 is required for this page.\n\n"
            f"Missing secrets: {', '.join(missing)}\n\n"
            "Add them in Streamlit Cloud → App → Settings → Secrets:\n"
            "S3_BUCKET_NAME, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION\n\n"
            "Optional: S3_BASE_PREFIX"
        )
        st.stop()

s3_required_or_stop()

BUCKET = get_secret("S3_BUCKET_NAME")
REGION = get_secret("AWS_REGION")
BASE_PREFIX = (get_secret("S3_BASE_PREFIX", "streamlit") or "streamlit").strip("/")
MODULE = "registration"   # ✅ module folder

def get_s3_client():
    return boto3.client(
        "s3",
        region_name=REGION,
        aws_access_key_id=get_secret("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=get_secret("AWS_SECRET_ACCESS_KEY"),
    )

s3 = get_s3_client()


# =========================================================
# Helpers
# =========================================================
def norm_col(s: str) -> str:
    if s is None:
        return ""
    return re.sub(r"[^a-z0-9]+", "", str(s).strip().lower())

def pick_col(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    want = [norm_col(c) for c in candidates]
    for c in df.columns:
        if norm_col(c) in want:
            return c
    # fuzzy contains
    for c in df.columns:
        nc = norm_col(c)
        for w in want:
            if w and w in nc:
                return c
    return None

def try_parse_date_series(s: pd.Series) -> pd.Series:
    # handles Excel datetimes/strings
    return pd.to_datetime(s, errors="coerce")

def detect_header_row_xls(file_bytes: bytes, must_have: str = "emrno", scan_rows: int = 25) -> int:
    """
    Some .xls files have title rows and the real header is not row 0.
    We scan first N rows and find the row that contains 'EMRNo' (or similar).
    Returns header row index.
    """
    for hdr in range(0, scan_rows):
        try:
            tmp = pd.read_excel(io.BytesIO(file_bytes), header=hdr, engine="xlrd")
            cols = [norm_col(c) for c in tmp.columns]
            if any(must_have in c for c in cols):
                return hdr
        except Exception:
            continue
    return 0

def read_excel_smart(uploaded_file) -> Tuple[pd.DataFrame, bytes]:
    """
    Reads xlsx/xls. For xls, auto-detects header row if needed.
    Returns (df, raw_bytes)
    """
    raw = uploaded_file.getvalue()
    name = uploaded_file.name.lower()

    if name.endswith(".xls"):
        hdr = detect_header_row_xls(raw, must_have="emrno")
        df = pd.read_excel(io.BytesIO(raw), header=hdr, engine="xlrd")
        return df, raw

    # xlsx
    df = pd.read_excel(io.BytesIO(raw), engine="openpyxl")
    return df, raw

def extract_day_from_registration(reg_df: pd.DataFrame) -> Optional[str]:
    """
    Reads date from registration file.
    We take MAX date in the date column and normalize to YYYY-MM-DD.
    """
    date_col = pick_col(reg_df, [
        "Reg Date", "Registration Date", "Visit Date", "Date",
        "Created Date", "Created On", "RegDate", "VisitDate"
    ])
    if not date_col:
        return None

    ds = try_parse_date_series(reg_df[date_col])
    ds = ds.dropna()
    if ds.empty:
        return None

    d = ds.max().date()
    return d.strftime("%Y-%m-%d")

def df_value_counts(df: pd.DataFrame, col: str, top_n: int = 50) -> pd.DataFrame:
    s = df[col].fillna("Blank").astype(str).str.strip()
    vc = s.value_counts(dropna=False).head(top_n)
    out = vc.reset_index()
    out.columns = ["Value", "Count"]
    return out

def to_excel_bytes(dfs: Dict[str, pd.DataFrame]) -> bytes:
    out = io.BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as writer:
        for sheet, df in dfs.items():
            df.to_excel(writer, sheet_name=sheet[:31], index=False)
    return out.getvalue()

def s3_put_bytes(key: str, data: bytes, content_type: str):
    s3.put_object(Bucket=BUCKET, Key=key, Body=data, ContentType=content_type)

def s3_get_bytes(key: str) -> Optional[bytes]:
    try:
        obj = s3.get_object(Bucket=BUCKET, Key=key)
        return obj["Body"].read()
    except ClientError:
        return None

def s3_list_prefix(prefix: str) -> List[str]:
    keys = []
    token = None
    while True:
        kwargs = dict(Bucket=BUCKET, Prefix=prefix)
        if token:
            kwargs["ContinuationToken"] = token
        resp = s3.list_objects_v2(**kwargs)
        for it in resp.get("Contents", []):
            keys.append(it["Key"])
        if resp.get("IsTruncated"):
            token = resp.get("NextContinuationToken")
        else:
            break
    return keys

def s3_delete_prefix(prefix: str):
    keys = s3_list_prefix(prefix)
    if not keys:
        return
    # batch delete
    for i in range(0, len(keys), 1000):
        chunk = keys[i:i+1000]
        s3.delete_objects(
            Bucket=BUCKET,
            Delete={"Objects": [{"Key": k} for k in chunk], "Quiet": True},
        )

def day_prefix(day_str: str) -> str:
    # ✅ Correct structure: streamlit/registration/YYYY-MM-DD/
    return f"{BASE_PREFIX}/{MODULE}/{day_str}/"

def json_key(day_str: str) -> str:
    return day_prefix(day_str) + "summary.json"

def reg_key(day_str: str) -> str:
    return day_prefix(day_str) + "registration.xlsx"

def cash_key(day_str: str) -> str:
    return day_prefix(day_str) + "cashout.xls"

def pending_key(day_str: str) -> str:
    return day_prefix(day_str) + "pending.xls"


# =========================================================
# Session state
# =========================================================
if "step1" not in st.session_state:
    st.session_state.step1 = None  # (df, bytes, detected_day)
if "step2" not in st.session_state:
    st.session_state.step2 = None  # (df, bytes)
if "step3" not in st.session_state:
    st.session_state.step3 = None  # (df, bytes)
if "result" not in st.session_state:
    st.session_state.result = None


# =========================================================
# Storage Status
# =========================================================
with st.expander("Storage Status (S3)", expanded=False):
    st.success(f"S3 Configured ✅  Bucket: {BUCKET}  | Region: {REGION}  | Base: {BASE_PREFIX}/{MODULE}/")


# =========================================================
# Step 0: Choose day (optional) — used only if file has no date
# =========================================================
st.caption("✅ Day is read from Registration file. Date picker is used only if file has no date column.")
manual_day = st.date_input("Manual Day (fallback only)", value=date.today())
manual_day_str = manual_day.strftime("%Y-%m-%d")


# =========================================================
# Step 1 — Registration file
# =========================================================
st.subheader("1) RegistrationList (.xls / .xlsx)")

colA, colB = st.columns([3, 1])
with colA:
    up1 = st.file_uploader("Upload Registration file", type=["xls", "xlsx"], key="uploader_step1")

with colB:
    if st.button("🗑️ Delete Step 1"):
        st.session_state.step1 = None
        st.session_state.step2 = None
        st.session_state.step3 = None
        st.session_state.result = None
        st.rerun()

step1_error = None
detected_day = None

if up1 is not None:
    try:
        df1, raw1 = read_excel_smart(up1)

        # required columns for registration summary
        col_emr = pick_col(df1, ["EMRNo", "EMR No", "MRN", "Patient MRN", "EMR"])
        col_visit = pick_col(df1, ["Visit No", "VisitNo", "Visit Number", "VisitID", "Visit Id"])

        if not col_emr:
            step1_error = f"Step 1 error: Registration file must contain EMRNo (or MRN). Found: {list(df1.columns)}"
        if not col_visit:
            step1_error = (step1_error or "") + f"\nStep 1 error: Registration file must contain Visit No. Found: {list(df1.columns)}"

        detected_day = extract_day_from_registration(df1)
        if not detected_day:
            detected_day = manual_day_str

        if step1_error is None:
            st.session_state.step1 = (df1, raw1, detected_day)
            st.success(f"Step 1 OK ✅  Day detected: {detected_day}")

    except Exception as e:
        step1_error = f"Step 1 error: Could not read file. {e}"

if step1_error:
    st.error(step1_error)


# =========================================================
# Step 2 — CashOut file
# =========================================================
st.subheader("2) PatientCashOutList (.xls / .xlsx)  — only EMRNo required")

colA, colB = st.columns([3, 1])
with colA:
    up2 = st.file_uploader("Upload CashOut file", type=["xls", "xlsx"], key="uploader_step2")

with colB:
    if st.button("🗑️ Delete Step 2"):
        st.session_state.step2 = None
        st.session_state.step3 = None
        st.session_state.result = None
        st.rerun()

step2_error = None
if up2 is not None:
    if st.session_state.step1 is None:
        step2_error = "Step 2 error: Upload Step 1 (Registration) first."
    else:
        try:
            df2, raw2 = read_excel_smart(up2)
            col_emr2 = pick_col(df2, ["EMRNo", "EMR No", "MRN", "Patient MRN", "EMR"])
            if not col_emr2:
                step2_error = f"Step 2 error: CashOut file must contain EMRNo. Found: {list(df2.columns)}"
            else:
                st.session_state.step2 = (df2, raw2)
                st.success("Step 2 OK ✅")
        except Exception as e:
            step2_error = f"Step 2 error: Could not read file. {e}"

if step2_error:
    st.error(step2_error)


# =========================================================
# Step 3 — Pending file
# =========================================================
st.subheader("3) Pending file (.xls / .xlsx) — only EMRNo required (can be empty)")

colA, colB = st.columns([3, 1])
with colA:
    up3 = st.file_uploader("Upload Pending file", type=["xls", "xlsx"], key="uploader_step3")

with colB:
    if st.button("🗑️ Delete Step 3"):
        st.session_state.step3 = None
        st.session_state.result = None
        st.rerun()

step3_error = None
if up3 is not None:
    if st.session_state.step1 is None:
        step3_error = "Step 3 error: Upload Step 1 (Registration) first."
    elif st.session_state.step2 is None:
        step3_error = "Step 3 error: Upload Step 2 (CashOut) first."
    else:
        try:
            df3, raw3 = read_excel_smart(up3)
            # pending can be empty, but if has data it must have EMRNo
            if len(df3.columns) > 0 and len(df3) > 0:
                col_emr3 = pick_col(df3, ["EMRNo", "EMR No", "MRN", "Patient MRN", "EMR"])
                if not col_emr3:
                    step3_error = f"Step 3 error: Pending file must contain EMRNo. Found: {list(df3.columns)}"
            st.session_state.step3 = (df3, raw3)
            st.success("Step 3 OK ✅")
        except Exception as e:
            step3_error = f"Step 3 error: Could not read file. {e}"

if step3_error:
    st.error(step3_error)


# =========================================================
# Process & Save
# =========================================================
st.divider()
can_process = st.session_state.step1 is not None and st.session_state.step2 is not None and st.session_state.step3 is not None

if not can_process:
    st.warning("Upload all 3 files in order to enable processing.")
else:
    df1, raw1, day_str = st.session_state.step1
    df2, raw2 = st.session_state.step2
    df3, raw3 = st.session_state.step3

    if st.button("✅ Process & Save to S3"):
        # --- Required columns from Registration ---
        col_emr = pick_col(df1, ["EMRNo", "EMR No", "MRN", "Patient MRN", "EMR"])
        col_visit = pick_col(df1, ["Visit No", "VisitNo", "Visit Number", "VisitID", "Visit Id"])

        # Optional group columns (for tables)
        col_doc = pick_col(df1, ["Doctor", "Doctor Name", "Physician", "Provider"])
        col_ins = pick_col(df1, [
            "Insurance", "Insurance Name", "Insurance Company", "Payer", "Payer Name",
            "TPA", "TPA Name", "Receiver", "Receiver Name"
        ])
        col_emp = pick_col(df1, ["Employer", "Company", "Sponsor", "Employer Name"])
        col_bill = pick_col(df1, ["Bill Type", "BillType", "Insurance/Cash", "Payment Type", "Billing Type"])
        col_visit_type = pick_col(df1, ["Visit Type", "VisitType", "Type", "Consult/Follow-up"])
        col_status = pick_col(df1, ["Status", "Visit Status", "Reg Status"])
        col_user = pick_col(df1, ["User", "Created By", "Registration User", "Reg User", "Receptionist"])

        # --- CashOut / Pending EMR ---
        col_emr2 = pick_col(df2, ["EMRNo", "EMR No", "MRN", "Patient MRN", "EMR"])
        col_emr3 = pick_col(df3, ["EMRNo", "EMR No", "MRN", "Patient MRN", "EMR"])

        reg_emr = df1[col_emr].dropna().astype(str).str.strip()
        reg_visit = df1[col_visit].dropna().astype(str).str.strip()

        total_visits = int(len(reg_visit))
        unique_emr = int(reg_emr.nunique())
        unique_visit = int(reg_visit.nunique())

        cash_emr = df2[col_emr2].dropna().astype(str).str.strip()
        cash_patients = int(cash_emr.nunique())

        pending_patients = 0
        pending_emr = pd.Series([], dtype=str)
        if len(df3) > 0 and col_emr3:
            pending_emr = df3[col_emr3].dropna().astype(str).str.strip()
            pending_patients = int(pending_emr.nunique())

        # Build summary tables from Registration only
        tables = {}
        if col_doc:
            tables["Doctor Wise Visits"] = df_value_counts(df1, col_doc, top_n=50)
        if col_ins:
            tables["Insurance Wise Visits"] = df_value_counts(df1, col_ins, top_n=50)
        if col_emp:
            tables["Employer Wise"] = df_value_counts(df1, col_emp, top_n=50)
        if col_bill:
            tables["Bill Type (Insurance/Cash)"] = df_value_counts(df1, col_bill, top_n=50)
        if col_visit_type:
            tables["Visit Type (Consult/Follow-up)"] = df_value_counts(df1, col_visit_type, top_n=50)
        if col_status:
            tables["Status Wise"] = df_value_counts(df1, col_status, top_n=50)
        if col_user:
            tables["Registration User Wise"] = df_value_counts(df1, col_user, top_n=50)

        # Store the exact day used
        run_id = datetime.now().strftime("%H%M%S")

        summary = {
            "day": day_str,
            "run_id": run_id,
            "kpis": {
                "total_visits": total_visits,
                "unique_emr": unique_emr,
                "unique_visitno": unique_visit,
                "cash_patients": cash_patients,
                "pending_patients": pending_patients,
            },
            "detected_columns": {
                "doctor": col_doc, "insurance": col_ins, "employer": col_emp,
                "bill_type": col_bill, "visit_type": col_visit_type, "status": col_status, "user": col_user
            }
        }

        # ✅ Save in correct module/date folder (overwrite same day)
        prefix = day_prefix(day_str)

        # optional: clean that day folder before saving (keeps latest truth)
        s3_delete_prefix(prefix)

        s3_put_bytes(json_key(day_str), json.dumps(summary, ensure_ascii=False).encode("utf-8"), "application/json")
        s3_put_bytes(reg_key(day_str), raw1, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        s3_put_bytes(cash_key(day_str), raw2, "application/vnd.ms-excel")
        s3_put_bytes(pending_key(day_str), raw3, "application/vnd.ms-excel")

        # Also store “tables export” as Excel for easy download
        export_dfs = {"KPIs": pd.DataFrame([summary["kpis"]])}
        for k, v in tables.items():
            export_dfs[k] = v
        export_bytes = to_excel_bytes(export_dfs)
        s3_put_bytes(prefix + "summary_export.xlsx", export_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

        st.success(f"Saved ✅  {BASE_PREFIX}/{MODULE}/{day_str}/")
        st.session_state.result = {"day": day_str, "kpis": summary["kpis"], "tables": tables, "reg_df": df1}


# =========================================================
# Load day from S3 (history)
# =========================================================
st.divider()
st.subheader("Load Saved Day (from S3)")

# list days from S3: streamlit/registration/YYYY-MM-DD/summary.json
all_keys = s3_list_prefix(f"{BASE_PREFIX}/{MODULE}/")
day_list = sorted({
    k.split(f"{BASE_PREFIX}/{MODULE}/", 1)[1].split("/", 1)[0]
    for k in all_keys
    if k.endswith("summary.json")
})

if day_list:
    sel_day = st.selectbox("Select saved day", day_list, index=len(day_list)-1)
    if st.button("📥 Load Selected Day"):
        raw = s3_get_bytes(json_key(sel_day))
        if raw:
            summary = json.loads(raw.decode("utf-8"))
            # try load export tables xlsx? (optional)
            st.session_state.result = {
                "day": summary["day"],
                "kpis": summary["kpis"],
                "tables": {},
                "reg_df": None,
            }
            st.success(f"Loaded ✅ {sel_day}")
        else:
            st.error("Could not load summary.json")
else:
    st.info("No saved days found yet.")


# =========================================================
# Display — Current Day Summary + Tables
# =========================================================
if st.session_state.result:
    k = st.session_state.result["kpis"]
    day_str = st.session_state.result["day"]

    st.divider()
    st.subheader(f"Current Day Summary ({day_str})")

    a, b, c, d = st.columns(4)
    a.metric("Today Visits", k["total_visits"])
    b.metric("Today Unique EMR", k["unique_emr"])
    c.metric("Today CashOut", k["cash_patients"])
    d.metric("Today Pending", k["pending_patients"])

    # If we have registration df in session (processed this run) show tables live
    tables = st.session_state.result.get("tables", {})
    if tables:
        st.divider()
        st.subheader("Registration Breakdown (from Registration file)")

        # Show in same style: tables stacked like your Excel sections
        for title, df_tbl in tables.items():
            st.markdown(f"### {title}")
            st.dataframe(df_tbl, use_container_width=True, height=330)


# =========================================================
# Accumulated (All Saved Days)
# =========================================================
st.divider()
st.subheader("Accumulated (All Saved Days)")

if not day_list:
    st.info("No saved days yet.")
else:
    rows = []
    for d in sorted(day_list):
        raw = s3_get_bytes(json_key(d))
        if not raw:
            continue
        s = json.loads(raw.decode("utf-8"))
        k = s["kpis"]
        rows.append({
            "day": d,
            "total_visits": k["total_visits"],
            "unique_emr": k["unique_emr"],
            "unique_visitno": k["unique_visitno"],
            "cash_patients": k["cash_patients"],
            "pending_patients": k["pending_patients"],
            "run_id": s.get("run_id", "")
        })

    acc = pd.DataFrame(rows).sort_values("day")
    # cumulative sums
    acc["cum_total_visits"] = acc["total_visits"].cumsum()
    acc["cum_unique_emr"] = acc["unique_emr"].cumsum()
    acc["cum_cash_patients"] = acc["cash_patients"].cumsum()
    acc["cum_pending_patients"] = acc["pending_patients"].cumsum()

    # KPIs
    x1, x2, x3, x4 = st.columns(4)
    x1.metric("Cumulative Visits", int(acc["cum_total_visits"].iloc[-1]) if len(acc) else 0)
    x2.metric("Cumulative Unique EMR", int(acc["cum_unique_emr"].iloc[-1]) if len(acc) else 0)
    x3.metric("Cumulative CashOut", int(acc["cum_cash_patients"].iloc[-1]) if len(acc) else 0)
    x4.metric("Cumulative Pending", int(acc["cum_pending_patients"].iloc[-1]) if len(acc) else 0)

    st.dataframe(acc, use_container_width=True)

    # download accumulated CSV
    st.download_button(
        "⬇️ Download Accumulated CSV",
        data=acc.to_csv(index=False).encode("utf-8"),
        file_name="registration_accumulated.csv",
        mime="text/csv"
    )
