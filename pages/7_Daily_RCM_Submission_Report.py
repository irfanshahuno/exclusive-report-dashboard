#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Streamlit Page: Daily RCM Submission Report

Purpose
-------
Upload the daily claim-status report and calculate:
- NOT ASSIGNED = not coded yet / within 48-hour coding window
- CLOSED       = done / already submitted
- OPEN         = pending for query (doctor, nursing/lab, reception, etc.)
- PROCESSED    = complete / ready to submit

Amount basis:
- "Ins Share" = net insurance amount

Main analysis:
- Status-wise claim count + Ins Share amount
- Open-query department classification using User remark
- Insurance-wise status/count/amount
- Doctor-wise status/count/amount
- Not Assigned >48 hours alert
- Saved results in S3 so the latest report remains after Streamlit reopens

The report uses Visit No as the claim key where available.
"""

import io
import os
import re
import pickle
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

# Optional S3
try:
    import boto3
except Exception:
    boto3 = None


# =========================================================
# PAGE
# =========================================================
st.set_page_config(
    page_title="Daily RCM Submission Report",
    layout="wide",
    initial_sidebar_state="collapsed",
)

SS = st.session_state


# =========================================================
# CONFIG / CENTER / S3
# =========================================================
CENTERS = {
    "easyhealth": "Easy Health Medical Clinic (MF8031)",
    "excellent": "Excellent Medical Center (MF4777)",
    "pharmacy": "Excellent Pharmacy (PF3205)",
}

SS.setdefault("center_key", "excellent")
_q_center = st.query_params.get("center")
if _q_center in CENTERS:
    SS["center_key"] = _q_center

center_key = SS.get("center_key", "excellent")
if center_key not in CENTERS:
    center_key = "excellent"
    SS["center_key"] = center_key


def load_secrets() -> Dict[str, str]:
    def get_any(*keys):
        for k in keys:
            if k in st.secrets:
                v = st.secrets.get(k)
                if v is not None and str(v).strip():
                    return str(v).strip()
            v = os.getenv(k)
            if v is not None and str(v).strip():
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
    return bool(
        cfg.get("S3_BUCKET_NAME")
        and cfg.get("AWS_REGION")
        and cfg.get("AWS_ACCESS_KEY_ID")
        and cfg.get("AWS_SECRET_ACCESS_KEY")
        and boto3 is not None
    )


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
    return "/".join(
        [str(p).strip("/").strip() for p in parts if p is not None and str(p).strip()]
    )


def daily_root(cfg: Dict[str, str], center: str) -> str:
    return s3_key(cfg.get("S3_BASE_PREFIX", ""), "daily_rcm", center)


def s3_put_bytes(s3, bucket: str, key: str, data: bytes, content_type="application/octet-stream"):
    s3.put_object(Bucket=bucket, Key=key, Body=data, ContentType=content_type)


def s3_get_bytes(s3, bucket: str, key: str) -> Optional[bytes]:
    try:
        obj = s3.get_object(Bucket=bucket, Key=key)
        return obj["Body"].read()
    except Exception:
        return None


cfg = load_secrets()
s3_ok = s3_enabled(cfg)
s3 = s3_client_cached(cfg) if s3_ok else None

# Respect center already selected in the main dashboard, while still allowing manual change.
center_key = st.selectbox(
    "Center",
    options=list(CENTERS.keys()),
    index=list(CENTERS.keys()).index(center_key),
    format_func=lambda x: CENTERS[x],
    key="daily_rcm_center_selector",
)
SS["center_key"] = center_key


# =========================================================
# STYLE
# =========================================================
st.markdown(
    """
<style>
.block-container{
    max-width:100% !important;
    padding-top:0.7rem !important;
    padding-left:2rem !important;
    padding-right:2rem !important;
}
h1,h2,h3{letter-spacing:-0.02em;}
.rcm-kpi-grid{
    display:grid;
    grid-template-columns:repeat(3,minmax(0,1fr));
    gap:10px;
    margin:.25rem 0 .75rem 0;
}
.rcm-card{
    min-height:98px;
    padding:12px 16px;
    border-radius:16px;
    border:1px solid rgba(15,23,42,.08);
    box-shadow:0 6px 16px rgba(15,23,42,.055);
    display:flex;
    align-items:center;
    gap:13px;
}
.rcm-blue{background:#eef8ff;border-color:#bfe2ff;}
.rcm-green{background:#f0fcf4;border-color:#c9efd4;}
.rcm-yellow{background:#fff9e9;border-color:#f4dda0;}
.rcm-red{background:#fff1f3;border-color:#ffcbd2;}
.rcm-purple{background:#f7f1ff;border-color:#e1ccff;}
.rcm-white{background:#f7f9fc;border:2px solid #2b78ff;}
.rcm-icon{font-size:32px;min-width:42px;text-align:center;line-height:1;}
.rcm-label{font-size:13px;font-weight:800;color:#17335f;margin-bottom:4px;}
.rcm-value{font-size:27px;font-weight:950;color:#071a5d;line-height:1.05;}
.rcm-sub{font-size:12px;font-weight:700;color:#52667f;margin-top:5px;}
.rcm-section{
    margin-top:.8rem;
    margin-bottom:.35rem;
    font-size:1.45rem;
    font-weight:850;
    color:#202939;
}
@media(max-width:1000px){
  .rcm-kpi-grid{grid-template-columns:repeat(2,minmax(0,1fr));}
}
@media(max-width:650px){
  .rcm-kpi-grid{grid-template-columns:repeat(1,minmax(0,1fr));}
}
</style>
""",
    unsafe_allow_html=True,
)


def money(v) -> str:
    try:
        return f"AED {float(v):,.2f}"
    except Exception:
        return "AED 0.00"


def kpi_cards(items: List[Tuple[str, str, str, str, str]]):
    """
    item = (label, value, subtitle, icon, color_class)
    """
    cards = []
    for label, value, subtitle, icon, cls in items:
        cards.append(
            f"""
            <div class="rcm-card {cls}">
                <div class="rcm-icon">{icon}</div>
                <div>
                    <div class="rcm-label">{label}</div>
                    <div class="rcm-value">{value}</div>
                    <div class="rcm-sub">{subtitle}</div>
                </div>
            </div>
            """
        )
    st.markdown(
        f'<div class="rcm-kpi-grid">{"".join(cards)}</div>',
        unsafe_allow_html=True,
    )


# =========================================================
# COLUMN HELPERS
# =========================================================
def norm_col(v: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(v).strip().lower())


def find_col(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    cmap = {norm_col(c): c for c in df.columns}
    for cand in candidates:
        n = norm_col(cand)
        if n in cmap:
            return cmap[n]

    # cautious contains fallback
    for cand in candidates:
        n = norm_col(cand)
        if not n:
            continue
        for nc, original in cmap.items():
            if n == nc or (len(n) >= 5 and n in nc):
                return original
    return None


def clean_amount(series: pd.Series) -> pd.Series:
    if series is None:
        return pd.Series(dtype=float)
    s = series.astype(str).str.replace(",", "", regex=False)
    s = s.str.replace("AED", "", case=False, regex=False)
    s = s.str.replace(r"[^\d\.\-]", "", regex=True)
    return pd.to_numeric(s, errors="coerce").fillna(0.0)


def parse_date_series(series: pd.Series) -> pd.Series:
    s1 = pd.to_datetime(series, errors="coerce", dayfirst=False)
    s2 = pd.to_datetime(series, errors="coerce", dayfirst=True)
    return s2 if s2.notna().sum() >= s1.notna().sum() else s1


# =========================================================
# EXCEL LOADER
# =========================================================
EXPECTED_HEADERS = [
    "Visit No",
    "Visit Date",
    "Ins Share",
    "Doctor Name",
    "Ins. Company",
    "Status",
    "User remark",
]


def read_daily_report(file_obj, filename: str) -> pd.DataFrame:
    """
    Reads .xls/.xlsx and also scans the first rows if the true header is not row 1.
    For legacy .xls, Streamlit environment should include xlrd>=2.0.1.
    """
    data = file_obj.getvalue() if hasattr(file_obj, "getvalue") else file_obj.read()
    bio = io.BytesIO(data)

    def header_score(columns) -> int:
        norms = {norm_col(c) for c in columns}
        return sum(1 for h in EXPECTED_HEADERS if norm_col(h) in norms)

    # First attempt
    try:
        bio.seek(0)
        df = pd.read_excel(bio)
        if header_score(df.columns) >= 4:
            df.columns = [str(c).strip() for c in df.columns]
            return df.dropna(how="all").reset_index(drop=True)
    except ImportError as exc:
        if str(filename).lower().endswith(".xls"):
            raise RuntimeError(
                "Legacy .xls support is missing. Add `xlrd==2.0.1` to requirements.txt."
            ) from exc
    except Exception:
        pass

    # Header scan fallback
    try:
        bio.seek(0)
        raw = pd.read_excel(bio, header=None)
    except ImportError as exc:
        raise RuntimeError(
            "Legacy .xls support is missing. Add `xlrd==2.0.1` to requirements.txt."
        ) from exc

    best_row = None
    best_score = -1
    for r in range(min(60, len(raw))):
        vals = [str(v).strip() for v in raw.iloc[r].tolist()]
        score = header_score(vals)
        if score > best_score:
            best_score = score
            best_row = r

    if best_row is None or best_score < 4:
        raise ValueError(
            "Could not detect the daily report header. Expected columns such as "
            "Visit No, Ins Share, Doctor Name, Ins. Company, Status and User remark."
        )

    header = [str(v).strip() for v in raw.iloc[best_row].tolist()]
    df = raw.iloc[best_row + 1 :].copy()
    df.columns = header
    df = df.dropna(how="all").reset_index(drop=True)
    return df


# =========================================================
# QUERY OWNER CLASSIFICATION
# =========================================================
def classify_query_owner(remark: object) -> str:
    s = "" if pd.isna(remark) else str(remark).strip().lower()
    s = re.sub(r"\s+", " ", s)

    if not s:
        return "Unspecified"

    # Explicit doctor wording takes priority even if the sentence later mentions lab.
    doctor_terms = [
        "dear doctor", "dear dr", "dear doc", "doctor please", "dr please",
        "chief complaint", "chief complains", "laterality", "diagnosis",
        "clinical note", "medical note", "specify diagnosis", "add diagnosis",
    ]
    if any(x in s for x in doctor_terms):
        return "Doctor"

    # User rule: if remark says lab -> Nursing / Lab department.
    nursing_lab_terms = [
        "lab", "laboratory", "sample", "specimen", "nurse", "nursing",
        "vital", "temperature", "bp reading", "blood pressure",
    ]
    if any(x in s for x in nursing_lab_terms):
        return "Nursing / Lab"

    reception_terms = [
        "reception", "registration", "card no", "card number", "emirates id",
        "patient id", "mobile", "phone", "demographic", "visit type",
        "eligibility", "member id", "policy no", "policy number",
    ]
    if any(x in s for x in reception_terms):
        return "Reception"

    approval_terms = [
        "approval", "authorization", "authorisation", "pre approval",
        "preapproval", "insurance confirmation", "benefit", "coverage",
        "network", "portal",
    ]
    if any(x in s for x in approval_terms):
        return "Insurance / Approval"

    rcm_terms = [
        "coding", "coder", "cpt", "icd", "modifier", "billing", "claim",
        "resubmit", "resubmission",
    ]
    if any(x in s for x in rcm_terms):
        return "RCM / Coding"

    return "Other"


# =========================================================
# PROCESSING
# =========================================================
STATUS_ORDER = ["CLOSED", "PROCESSED", "OPEN", "NOT ASSIGNED"]


def process_report(raw: pd.DataFrame) -> Dict[str, object]:
    df = raw.copy()
    df.columns = [str(c).strip() for c in df.columns]

    col_visit = find_col(df, ["Visit No", "VisitNo", "Visit Number", "Visit ID", "VisitID"])
    col_visit_date = find_col(df, ["Visit Date", "VisitDate", "Enc Date", "Encounter Date"])
    col_amount = find_col(df, ["Ins Share", "Insurance Share", "InsShare"])
    col_status = find_col(df, ["Status"])
    col_claim_status = find_col(df, ["ClaimStatus", "Claim Status"])
    col_remark = find_col(df, ["User remark", "User Remark", "Remark", "Remarks"])
    col_ins = find_col(df, ["Ins. Company", "Ins Company", "Insurance Company", "Payer"])
    col_doc = find_col(df, ["Doctor Name", "Doctor"])
    col_patient = find_col(df, ["Patient Name", "Name"])
    col_opened = find_col(df, ["Opened Date", "Open Date"])
    col_processed = find_col(df, ["Processed Date"])
    col_closed = find_col(df, ["Closed Date"])
    col_submission = find_col(df, ["Submission Date"])
    col_assigned = find_col(df, ["Assigned Date"])

    required = {
        "Visit No": col_visit,
        "Ins Share": col_amount,
        "Status": col_status,
        "Ins. Company": col_ins,
        "Doctor Name": col_doc,
    }
    missing = [k for k, v in required.items() if v is None]
    if missing:
        raise ValueError("Missing required column(s): " + ", ".join(missing))

    # Canonical fields
    df["_VisitNo"] = df[col_visit].fillna("").astype(str).str.strip()
    df["_Amount"] = clean_amount(df[col_amount])
    df["_Status"] = (
        df[col_status]
        .fillna("")
        .astype(str)
        .str.replace(r"\s+", " ", regex=True)
        .str.strip()
        .str.upper()
    )
    df["_Insurance"] = df[col_ins].fillna("UNKNOWN").astype(str).str.strip()
    df["_Doctor"] = df[col_doc].fillna("UNKNOWN").astype(str).str.strip()
    df["_Remark"] = df[col_remark].fillna("").astype(str).str.strip() if col_remark else ""
    df["_ClaimStatus"] = (
        df[col_claim_status].fillna("").astype(str).str.strip()
        if col_claim_status else ""
    )

    if col_visit_date:
        df["_VisitDate"] = parse_date_series(df[col_visit_date])
    else:
        df["_VisitDate"] = pd.NaT

    if col_opened:
        df["_OpenedDate"] = parse_date_series(df[col_opened])
    else:
        df["_OpenedDate"] = pd.NaT

    if col_processed:
        df["_ProcessedDate"] = parse_date_series(df[col_processed])
    else:
        df["_ProcessedDate"] = pd.NaT

    if col_closed:
        df["_ClosedDate"] = parse_date_series(df[col_closed])
    else:
        df["_ClosedDate"] = pd.NaT

    if col_submission:
        df["_SubmissionDate"] = parse_date_series(df[col_submission])
    else:
        df["_SubmissionDate"] = pd.NaT

    if col_assigned:
        df["_AssignedDate"] = parse_date_series(df[col_assigned])
    else:
        df["_AssignedDate"] = pd.NaT

    # Remove clearly empty rows
    df = df[(df["_VisitNo"] != "") | (df["_Status"] != "")].copy()

    # One claim = one Visit No. Keep last report row when duplicates exist.
    # Blank Visit No rows remain as separate rows.
    with_visit = df[df["_VisitNo"] != ""].drop_duplicates(subset=["_VisitNo"], keep="last")
    without_visit = df[df["_VisitNo"] == ""]
    claims = pd.concat([with_visit, without_visit], ignore_index=True)

    claims["_QueryOwner"] = claims["_Remark"].apply(classify_query_owner)

    # Reporting day: most common Visit Date; fallback today Dubai.
    valid_days = claims["_VisitDate"].dropna().dt.normalize()
    if not valid_days.empty:
        report_day = valid_days.value_counts().index[0]
    else:
        report_day = pd.Timestamp.now(tz=ZoneInfo("Asia/Dubai")).tz_localize(None).normalize()

    # SLA age for NOT ASSIGNED
    now_dubai = pd.Timestamp.now(tz=ZoneInfo("Asia/Dubai")).tz_localize(None)
    claims["_AgeHours"] = (
        (now_dubai - claims["_VisitDate"]).dt.total_seconds() / 3600.0
    )
    claims["_NotAssignedOver48h"] = (
        claims["_Status"].eq("NOT ASSIGNED")
        & claims["_AgeHours"].notna()
        & claims["_AgeHours"].gt(48)
    )

    # Status summary
    status_rows = []
    for status in STATUS_ORDER:
        part = claims[claims["_Status"] == status]
        status_rows.append({
            "Status": status,
            "Claims": int(len(part)),
            "Ins Share": float(part["_Amount"].sum()),
        })
    status_summary = pd.DataFrame(status_rows)

    # Any other statuses
    other_status = claims[~claims["_Status"].isin(STATUS_ORDER)].copy()
    if not other_status.empty:
        extra = (
            other_status.groupby("_Status", dropna=False)
            .agg(Claims=("_VisitNo", "size"), **{"Ins Share": ("_Amount", "sum")})
            .reset_index()
            .rename(columns={"_Status": "Status"})
        )
        status_summary = pd.concat([status_summary, extra], ignore_index=True)

    # Query owner breakdown only OPEN
    open_df = claims[claims["_Status"] == "OPEN"].copy()
    if open_df.empty:
        query_summary = pd.DataFrame(columns=["Query Department", "Claims", "Ins Share"])
    else:
        query_summary = (
            open_df.groupby("_QueryOwner", dropna=False)
            .agg(Claims=("_VisitNo", "size"), **{"Ins Share": ("_Amount", "sum")})
            .reset_index()
            .rename(columns={"_QueryOwner": "Query Department"})
            .sort_values(["Claims", "Ins Share"], ascending=[False, False])
        )

    def build_group_summary(group_col: str, display_name: str) -> pd.DataFrame:
        rows = []
        for grp, gdf in claims.groupby(group_col, dropna=False):
            row = {
                display_name: grp if str(grp).strip() else "UNKNOWN",
                "Total Claims": int(len(gdf)),
                "Total Ins Share": float(gdf["_Amount"].sum()),
            }
            for st in STATUS_ORDER:
                p = gdf[gdf["_Status"] == st]
                row[f"{st} Claims"] = int(len(p))
                row[f"{st} Amount"] = float(p["_Amount"].sum())
            rows.append(row)
        out = pd.DataFrame(rows)
        if not out.empty:
            out = out.sort_values("Total Ins Share", ascending=False)
        return out

    insurance_summary = build_group_summary("_Insurance", "Insurance")
    doctor_summary = build_group_summary("_Doctor", "Doctor")

    # ClaimStatus optional
    if col_claim_status:
        claim_status_summary = (
            claims.groupby("_ClaimStatus", dropna=False)
            .agg(Claims=("_VisitNo", "size"), **{"Ins Share": ("_Amount", "sum")})
            .reset_index()
            .rename(columns={"_ClaimStatus": "Claim Status"})
            .sort_values("Claims", ascending=False)
        )
    else:
        claim_status_summary = pd.DataFrame()

    return {
        "report_day": pd.to_datetime(report_day),
        "claims": claims,
        "status_summary": status_summary,
        "query_summary": query_summary,
        "insurance_summary": insurance_summary,
        "doctor_summary": doctor_summary,
        "claim_status_summary": claim_status_summary,
        "columns": {
            "visit": col_visit,
            "patient": col_patient,
            "visit_date": col_visit_date,
            "amount": col_amount,
            "status": col_status,
            "claim_status": col_claim_status,
            "remark": col_remark,
            "insurance": col_ins,
            "doctor": col_doc,
            "opened": col_opened,
            "processed": col_processed,
            "closed": col_closed,
            "submission": col_submission,
            "assigned": col_assigned,
        },
    }


# =========================================================
# S3 SAVE / LOAD
# =========================================================
def save_analysis_to_s3(result: Dict[str, object], raw_bytes: bytes, raw_name: str):
    if not s3_ok:
        return False, "S3 is not configured."

    bucket = cfg["S3_BUCKET_NAME"]
    root = daily_root(cfg, center_key)
    day = pd.to_datetime(result["report_day"]).strftime("%Y-%m-%d")
    day_root = s3_key(root, day)

    # Save processed analysis
    payload = pickle.dumps(result, protocol=pickle.HIGHEST_PROTOCOL)
    s3_put_bytes(
        s3, bucket, s3_key(day_root, "analysis.pkl"), payload,
        "application/octet-stream"
    )

    # Save raw report with original extension
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", raw_name or "daily_report.xls")
    s3_put_bytes(
        s3, bucket, s3_key(day_root, safe_name), raw_bytes,
        "application/vnd.ms-excel"
    )

    # History
    hist_key = s3_key(root, "history.csv")
    hist_b = s3_get_bytes(s3, bucket, hist_key)
    if hist_b:
        try:
            hist = pd.read_csv(io.BytesIO(hist_b))
        except Exception:
            hist = pd.DataFrame(columns=["day", "saved_at"])
    else:
        hist = pd.DataFrame(columns=["day", "saved_at"])

    new_row = pd.DataFrame([{
        "day": day,
        "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }])
    hist = pd.concat([hist, new_row], ignore_index=True)
    hist = hist.drop_duplicates(subset=["day"], keep="last").sort_values("day")

    s3_put_bytes(
        s3, bucket, hist_key,
        hist.to_csv(index=False).encode("utf-8"),
        "text/csv",
    )
    return True, day


def load_history() -> pd.DataFrame:
    if not s3_ok:
        return pd.DataFrame(columns=["day", "saved_at"])
    key = s3_key(daily_root(cfg, center_key), "history.csv")
    b = s3_get_bytes(s3, cfg["S3_BUCKET_NAME"], key)
    if not b:
        return pd.DataFrame(columns=["day", "saved_at"])
    try:
        h = pd.read_csv(io.BytesIO(b))
        h["day"] = pd.to_datetime(h["day"], errors="coerce")
        return h.dropna(subset=["day"]).sort_values("day")
    except Exception:
        return pd.DataFrame(columns=["day", "saved_at"])


def load_saved_day(day) -> Optional[Dict[str, object]]:
    if not s3_ok:
        return None
    day_s = pd.to_datetime(day).strftime("%Y-%m-%d")
    key = s3_key(daily_root(cfg, center_key), day_s, "analysis.pkl")
    b = s3_get_bytes(s3, cfg["S3_BUCKET_NAME"], key)
    if not b:
        return None
    try:
        return pickle.loads(b)
    except Exception:
        return None


# =========================================================
# DISPLAY
# =========================================================
def status_value(result: Dict[str, object], status: str) -> Tuple[int, float]:
    s = result["status_summary"]
    row = s[s["Status"].astype(str).str.upper() == status]
    if row.empty:
        return 0, 0.0
    return int(row.iloc[0]["Claims"]), float(row.iloc[0]["Ins Share"])


def render_result(result: Dict[str, object]):
    claims = result["claims"]
    report_day = pd.to_datetime(result["report_day"])

    total_claims = int(len(claims))
    total_amount = float(claims["_Amount"].sum())

    closed_n, closed_a = status_value(result, "CLOSED")
    proc_n, proc_a = status_value(result, "PROCESSED")
    open_n, open_a = status_value(result, "OPEN")
    na_n, na_a = status_value(result, "NOT ASSIGNED")

    st.markdown(
        f"## Daily RCM Submission Report — {report_day.strftime('%d %b %Y')}"
    )

    kpi_cards([
        ("Total Claims", f"{total_claims:,}", money(total_amount), "📊", "rcm-blue"),
        ("Already Submitted", f"{closed_n:,}", money(closed_a), "✅", "rcm-green"),
        ("Ready to Submit", f"{proc_n:,}", money(proc_a), "📤", "rcm-white"),
        ("Open for Query", f"{open_n:,}", money(open_a), "❓", "rcm-yellow"),
        ("Not Assigned", f"{na_n:,}", money(na_a), "⏳", "rcm-purple"),
        (
            "Not Assigned >48h",
            f"{int(claims['_NotAssignedOver48h'].sum()):,}",
            money(claims.loc[claims["_NotAssignedOver48h"], "_Amount"].sum()),
            "⚠️",
            "rcm-red",
        ),
    ])

    # Submission pipeline
    st.markdown('<div class="rcm-section">Status Summary</div>', unsafe_allow_html=True)
    status_show = result["status_summary"].copy()
    status_show["Ins Share"] = pd.to_numeric(status_show["Ins Share"], errors="coerce").fillna(0).round(2)
    st.dataframe(status_show, use_container_width=True, hide_index=True)

    # OPEN query analysis
    st.markdown('<div class="rcm-section">Open Query Breakdown</div>', unsafe_allow_html=True)
    q = result["query_summary"].copy()
    if q.empty:
        st.success("No OPEN claims found.")
    else:
        q["Ins Share"] = pd.to_numeric(q["Ins Share"], errors="coerce").fillna(0).round(2)
        st.dataframe(q, use_container_width=True, hide_index=True)

        owner_options = ["All"] + sorted(q["Query Department"].dropna().astype(str).unique().tolist())
        owner_pick = st.selectbox("Open Query Department", owner_options, key="daily_rcm_query_owner")
        odf = claims[claims["_Status"] == "OPEN"].copy()
        if owner_pick != "All":
            odf = odf[odf["_QueryOwner"] == owner_pick].copy()

        cols = result["columns"]
        detail_cols = []
        for c in [
            cols.get("visit"),
            cols.get("patient"),
            cols.get("visit_date"),
            cols.get("doctor"),
            cols.get("insurance"),
            cols.get("amount"),
            cols.get("remark"),
            cols.get("opened"),
        ]:
            if c and c in odf.columns and c not in detail_cols:
                detail_cols.append(c)

        odf["Query Department"] = odf["_QueryOwner"]
        if "Query Department" not in detail_cols:
            detail_cols.append("Query Department")

        if detail_cols:
            st.dataframe(odf[detail_cols], use_container_width=True, hide_index=True)

    # Insurance / Doctor tabs
    st.markdown('<div class="rcm-section">Performance Breakdown</div>', unsafe_allow_html=True)
    t1, t2, t3 = st.tabs(["Insurance Wise", "Doctor Wise", "Claim Status"])

    with t1:
        ins = result["insurance_summary"].copy()
        amount_cols = [c for c in ins.columns if c.endswith("Amount") or c == "Total Ins Share"]
        for c in amount_cols:
            ins[c] = pd.to_numeric(ins[c], errors="coerce").fillna(0).round(2)
        st.dataframe(ins, use_container_width=True, hide_index=True)

    with t2:
        doc = result["doctor_summary"].copy()
        amount_cols = [c for c in doc.columns if c.endswith("Amount") or c == "Total Ins Share"]
        for c in amount_cols:
            doc[c] = pd.to_numeric(doc[c], errors="coerce").fillna(0).round(2)
        st.dataframe(doc, use_container_width=True, hide_index=True)

    with t3:
        cs = result.get("claim_status_summary", pd.DataFrame())
        if isinstance(cs, pd.DataFrame) and not cs.empty:
            cs = cs.copy()
            cs["Ins Share"] = pd.to_numeric(cs["Ins Share"], errors="coerce").fillna(0).round(2)
            st.dataframe(cs, use_container_width=True, hide_index=True)
        else:
            st.info("ClaimStatus column is not available or has no values.")

    # Detailed filterable claim list
    st.markdown('<div class="rcm-section">Claim Detail</div>', unsafe_allow_html=True)
    f1, f2, f3 = st.columns(3)
    with f1:
        statuses = sorted([x for x in claims["_Status"].dropna().astype(str).unique() if x])
        pick_status = st.selectbox("Status", ["All"] + statuses, key="daily_rcm_status_filter")
    with f2:
        doctors = sorted([x for x in claims["_Doctor"].dropna().astype(str).unique() if x])
        pick_doc = st.selectbox("Doctor", ["All"] + doctors, key="daily_rcm_doc_filter")
    with f3:
        insurers = sorted([x for x in claims["_Insurance"].dropna().astype(str).unique() if x])
        pick_ins = st.selectbox("Insurance", ["All"] + insurers, key="daily_rcm_ins_filter")

    fd = claims.copy()
    if pick_status != "All":
        fd = fd[fd["_Status"] == pick_status]
    if pick_doc != "All":
        fd = fd[fd["_Doctor"] == pick_doc]
    if pick_ins != "All":
        fd = fd[fd["_Insurance"] == pick_ins]

    cols = result["columns"]
    display_cols = []
    for c in [
        cols.get("visit"),
        cols.get("patient"),
        cols.get("visit_date"),
        cols.get("doctor"),
        cols.get("insurance"),
        cols.get("status"),
        cols.get("claim_status"),
        cols.get("amount"),
        cols.get("remark"),
        cols.get("processed"),
        cols.get("closed"),
        cols.get("submission"),
    ]:
        if c and c in fd.columns and c not in display_cols:
            display_cols.append(c)

    fd["Query Department"] = fd["_QueryOwner"]
    if "Query Department" not in display_cols:
        display_cols.append("Query Department")

    if display_cols:
        st.dataframe(fd[display_cols], use_container_width=True, hide_index=True)
    else:
        st.dataframe(fd, use_container_width=True, hide_index=True)

    # CSV download avoids any Excel writer dependency.
    csv_bytes = fd[display_cols].to_csv(index=False).encode("utf-8-sig") if display_cols else fd.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "⬇️ Download Filtered Claim List (CSV)",
        data=csv_bytes,
        file_name=f"daily_rcm_{report_day.strftime('%Y-%m-%d')}.csv",
        mime="text/csv",
    )


# =========================================================
# TOP UI
# =========================================================
st.title("Daily RCM Submission Report")
st.caption(
    "Status logic: NOT ASSIGNED = not coded yet / 48-hour window · "
    "CLOSED = submitted · OPEN = pending query · PROCESSED = ready to submit · "
    "Amount = Ins Share."
)

with st.expander("Storage Status", expanded=False):
    if s3_ok:
        st.success(
            f"S3 connected ✅  Bucket: {cfg['S3_BUCKET_NAME']} · "
            f"Center: {CENTERS[center_key]}"
        )
        st.caption(f"Path: {daily_root(cfg, center_key)}/<YYYY-MM-DD>/analysis.pkl")
    else:
        st.warning("S3 is not configured. The page will work, but results will not persist after restart.")

# Upload
up = st.file_uploader(
    "Upload Daily Report (.xls / .xlsx)",
    type=["xls", "xlsx"],
    key="daily_rcm_upload",
)

c1, c2 = st.columns([2, 1])
with c1:
    process_clicked = st.button(
        "✅ Process Daily Report",
        type="primary",
        use_container_width=True,
        disabled=(up is None),
    )
with c2:
    if st.button("🗑️ Clear Current", use_container_width=True):
        SS.pop("daily_rcm_result", None)
        st.rerun()

if process_clicked and up is not None:
    try:
        raw = read_daily_report(up, up.name)
        result = process_report(raw)
        SS["daily_rcm_result"] = result

        if s3_ok:
            ok, saved_day = save_analysis_to_s3(result, up.getvalue(), up.name)
            if ok:
                st.success(f"Processed and saved to S3 ✅  {saved_day}")
            else:
                st.warning("Processed successfully, but S3 save failed.")
        else:
            st.success("Processed successfully ✅")
    except Exception as exc:
        st.error(f"Could not process the report: {exc}")

# Saved history
hist = load_history()
if not hist.empty:
    saved_days = list(hist["day"].dt.normalize().drop_duplicates().sort_values())
    latest = saved_days[-1]

    with st.expander("Saved Daily Reports", expanded=False):
        pick_day = st.selectbox(
            "Select saved day",
            options=saved_days,
            index=len(saved_days) - 1,
            format_func=lambda d: pd.to_datetime(d).strftime("%A, %d %b %Y"),
            key="daily_rcm_saved_day",
        )
        if st.button("Load Saved Report", use_container_width=True):
            loaded = load_saved_day(pick_day)
            if loaded is None:
                st.error("Saved report could not be loaded.")
            else:
                SS["daily_rcm_result"] = loaded
                st.rerun()

    # Auto-load latest when page opens and nothing is in session.
    if SS.get("daily_rcm_result") is None:
        latest_result = load_saved_day(latest)
        if latest_result is not None:
            SS["daily_rcm_result"] = latest_result

# Display current/latest
current = SS.get("daily_rcm_result")
if current is not None:
    st.markdown("---")
    render_result(current)
else:
    st.info("Upload today's Daily Report to start the analysis.")
