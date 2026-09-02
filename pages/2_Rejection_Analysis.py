# pages/2_Rejection_Analysis.py

import boto3
from botocore.exceptions import ClientError
import io
import hashlib
from datetime import datetime as dt

import pandas as pd
import streamlit as st
from openpyxl import load_workbook
from openpyxl.styles import PatternFill, Font, Alignment

# =========================================
# PAGE CONFIG (wide + clean)
# =========================================
st.set_page_config(page_title="Rejection Analysis", layout="wide")

# ✅ Premium Deep Crimson + Warm Cream (CSS only)
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap');

    /* ---- Page Background ---- */
    .stApp{
      background: linear-gradient(145deg, #FDF6F6 0%, #FFF9F9 50%, #FFFBFB 100%) !important;
      font-family: 'Inter', sans-serif !important;
    }

    .block-container {
      max-width: 100% !important;
      padding-top: 1.0rem;
      padding-left: 1.2rem;
      padding-right: 1.2rem;
    }

    /* ---- Cards ---- */
    .card{
      background: rgba(255, 255, 255, 0.90);
      backdrop-filter: blur(10px);
      -webkit-backdrop-filter: blur(10px);
      border: 1.5px solid rgba(220, 170, 170, 0.35);
      border-left: 4px solid #9B1C1C;
      border-radius: 16px;
      padding: 14px 16px 12px 16px;
      box-shadow: 0 4px 18px rgba(155, 28, 28, 0.07), 0 1px 3px rgba(0,0,0,0.04), inset 0 1px 0 rgba(255,255,255,0.95);
      transition: box-shadow 0.2s ease, transform 0.2s ease;
    }
    .card:hover{
      box-shadow: 0 8px 28px rgba(155, 28, 28, 0.12), 0 2px 6px rgba(0,0,0,0.05);
      transform: translateY(-1px);
    }

    /* ---- Card Title ---- */
    .card-title{
      color: #9B1C1C;
      font-size: 11px;
      font-weight: 700;
      font-family: 'Inter', sans-serif;
      letter-spacing: 0.8px;
      text-transform: uppercase;
      margin-bottom: 8px;
    }

    /* ---- Card Value ---- */
    .card-value{
      color: #1A0A0A;
      font-size: 24px;
      font-weight: 900;
      font-family: 'Inter', sans-serif;
      line-height: 1.15;
      letter-spacing: -0.5px;
    }

    /* ---- Card Sub ---- */
    .card-sub{
      color: #9CA3AF;
      font-size: 11.5px;
      font-family: 'Inter', sans-serif;
      margin-top: 7px;
      font-weight: 500;
    }

    /* ---- Section Headings ---- */
    h3{
      font-size: 22px !important;
      font-weight: 800 !important;
      font-family: 'Inter', sans-serif !important;
      margin-top: 24px !important;
      margin-bottom: 10px !important;
      color: #1A0A0A !important;
      letter-spacing: -0.3px !important;
    }

    /* ---- HR Dividers ---- */
    hr{
      border: none !important;
      height: 1px !important;
      background: linear-gradient(90deg, transparent, #E8C5C5, transparent) !important;
    }

    /* ---- DataFrames ---- */
    div[data-testid="stDataFrame"] {
      border: 1px solid rgba(220,170,170,0.3);
      border-radius: 14px;
      overflow: hidden;
      box-shadow: 0 2px 10px rgba(155,28,28,0.05);
    }

    /* ---- Buttons ---- */
    div.stButton > button,
    div.stDownloadButton > button{
      background: linear-gradient(160deg, #9B1C1C 0%, #7F1D1D 100%) !important;
      color: #ffffff !important;
      border: 1px solid rgba(255,255,255,0.15) !important;
      border-radius: 12px !important;
      padding: 0.38rem 0.90rem !important;
      font-size: 0.875rem !important;
      font-weight: 700 !important;
      font-family: 'Inter', sans-serif !important;
      min-height: 2.25rem !important;
      box-shadow: 0 4px 14px rgba(127, 29, 29, 0.30), inset 0 1px 0 rgba(255,255,255,0.12) !important;
      letter-spacing: 0.1px !important;
      transition: all 0.2s ease !important;
    }

    div.stButton > button:hover,
    div.stDownloadButton > button:hover{
      background: linear-gradient(160deg, #B91C1C 0%, #9B1C1C 100%) !important;
      box-shadow: 0 6px 20px rgba(127, 29, 29, 0.38) !important;
      transform: translateY(-1px) !important;
    }

    div.stButton > button:active,
    div.stDownloadButton > button:active{
      background: linear-gradient(160deg, #7F1D1D 0%, #6B1919 100%) !important;
      transform: translateY(0px) !important;
      box-shadow: 0 2px 8px rgba(127, 29, 29, 0.25) !important;
    }
    </style>
    """,
    unsafe_allow_html=True
)

# =========================================
# CONFIG
# =========================================
S3_BUCKET = "emc-rcm-storage-2026"
SOURCE_FILENAME = "source.xlsx"
DEFAULT_YEAR_OPTIONS = ["2024", "2025", "2026"]

# ✅ Persistent cache (so results stay even after refresh / clicking again)
REJ_CACHE_PREFIX = "rejection_cache"
REJ_CACHE_FILENAME = "rejection_logic_v6.xlsx"

# =========================================
# CENTER NORMALIZATION (MUST be BEFORE use)
# =========================================
CENTER_ALIASES = {
    "excellent medical center": "excellent",
    "excellent pharmacy": "pharmacy",
    "easyhealth clinic": "easyhealth",
    "easy health medical clinic": "easyhealth",
    "easy health clinic": "easyhealth",
    "easyhealth": "easyhealth",
    "excellent": "excellent",
    "pharmacy": "pharmacy",
}

def normalize_center_for_s3(center_value: str) -> str:
    c = str(center_value).strip().lower()
    c = " ".join(c.split())
    return CENTER_ALIASES.get(c, c)

# =========================================
# S3 HELPERS
# =========================================
def s3_client():
    return boto3.client("s3")

def s3_exists(bucket: str, key: str) -> bool:
    try:
        s3_client().head_object(Bucket=bucket, Key=key)
        return True
    except ClientError:
        return False

def load_file_from_s3(bucket: str, key: str) -> bytes:
    obj = s3_client().get_object(Bucket=bucket, Key=key)
    return obj["Body"].read()

def save_file_to_s3(bucket: str, key: str, data: bytes) -> None:
    s3_client().put_object(Bucket=bucket, Key=key, Body=data)

def delete_file_from_s3(bucket: str, key: str) -> None:
    try:
        s3_client().delete_object(Bucket=bucket, Key=key)
    except Exception:
        pass

# =========================================
# REJECTION ANALYSIS ENGINE
# =========================================
def sha1_short_bytes(b: bytes) -> str:
    return hashlib.sha1(b).hexdigest()[:12]

def normalize_source_schema(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Normalize source columns while keeping the user's analytical rules.

    IMPORTANT:
    - Prefer the source column named Status for rejection journey analysis.
    - Fall back to ActivityStatus / CurrentActivityStatus only when Status is absent.
    - FinalPaidAmount and FinalBalance are NEVER used for analytical rejection/recovery.
    """
    info = {
        "format": "old",
        "status_source": "missing",
        "denial_source": "DenialCode",
        "paid_source": "remit/resub fields; TKBK override",
        "amount_source": "ActivityIns - actRemitInsShare",
    }

    if "Status" in df.columns:
        df["AnalysisStatus"] = df["Status"]
        info["status_source"] = "Status"
        info["format"] = "new"
    elif "ActivityStatus" in df.columns:
        df["AnalysisStatus"] = df["ActivityStatus"]
        info["status_source"] = "ActivityStatus"
    elif "CurrentActivityStatus" in df.columns:
        df["AnalysisStatus"] = df["CurrentActivityStatus"]
        info["status_source"] = "CurrentActivityStatus"
        info["format"] = "new"
    else:
        df["AnalysisStatus"] = ""

    # Keep ActivityStatus available for the old UI/detail columns.
    if "ActivityStatus" not in df.columns:
        df["ActivityStatus"] = df["AnalysisStatus"]

    # For initial rejection analysis, keep the original DenialCode when available.
    # FinalDenialCode is only a fallback if the original code is blank.
    if "FinalDenialCode" in df.columns:
        info["format"] = "new"
        final_code = df["FinalDenialCode"].astype(str).fillna("").str.strip()
        final_code = final_code.mask(final_code.str.lower().isin(["nan", "none", "null"]), "")
        if "DenialCode" in df.columns:
            base_code = df["DenialCode"].astype(str).fillna("").str.strip()
            base_code = base_code.mask(base_code.str.lower().isin(["nan", "none", "null"]), "")
            df["DenialCode"] = base_code.where(base_code.ne(""), final_code)
            info["denial_source"] = "DenialCode (fallback FinalDenialCode)"
        else:
            df["DenialCode"] = final_code
            info["denial_source"] = "FinalDenialCode fallback"

    if "FinalPaidAmount" in df.columns or "FinalBalance" in df.columns:
        info["format"] = "new"

    return df, info

def ensure_numeric(df: pd.DataFrame) -> pd.DataFrame:
    required_num_cols = [
        "ActivityIns",
        "actRemitInsShare", "actResub1RemitInsShare",
        "actResub2RemitInsShare", "actResub3RemitInsShare",
        "TKBKAmountAct",
    ]
    for c in required_num_cols:
        if c not in df.columns:
            df[c] = 0
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)

    # New-export numeric fields are optional; do not create them for old files,
    # because their presence is used to detect which calculation method to use.
    for c in ["FinalPaidAmount", "FinalBalance"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
    return df


def _positive_number(value) -> float:
    try:
        v = float(value)
    except Exception:
        return 0.0
    return v if v > 0 else 0.0


def _distinct_resub_sum(values) -> float:
    """Sum positive resub payments, counting an identical amount only once."""
    seen = set()
    total = 0.0
    for value in values:
        v = _positive_number(value)
        if v <= 0:
            continue
        key = round(v, 2)
        if key not in seen:
            seen.add(key)
            total += v
    return round(total, 2)


def compute_paid(df: pd.DataFrame) -> pd.DataFrame:
    """Calculate analytical Paid WITHOUT FinalPaidAmount.

    Normal Paid = initial remit + distinct resub remit payments.
    If TKBKAmountAct has a value, the user's rule is to replace Paid with
    the exact absolute TKBK figure (positive), not add/subtract it.
    """
    def calc(row):
        tkbk = row.get("TKBKAmountAct", 0)
        try:
            tkbk = float(tkbk or 0)
        except Exception:
            tkbk = 0.0
        if tkbk != 0:
            return round(abs(tkbk), 2)

        initial = _positive_number(row.get("actRemitInsShare", 0))
        resub = _distinct_resub_sum([
            row.get("actResub1RemitInsShare", 0),
            row.get("actResub2RemitInsShare", 0),
            row.get("actResub3RemitInsShare", 0),
        ])
        return round(initial + resub, 2)

    df["Paid"] = df.apply(calc, axis=1)
    return df


def _normalize_status_text(value) -> str:
    """Normalize harmless spacing/hyphen differences only."""
    s = str(value if value is not None else "").strip().lower()
    if s in ["", "nan", "none", "null", "<na>"]:
        return ""
    s = s.replace("–", "-").replace("—", "-")
    s = " ".join(s.split())
    # Normalize common Resub formatting without regex dependency.
    s = s.replace("resub - ", "resub-").replace("resub -", "resub-").replace("resub- ", "resub-")
    s = s.replace("( ", "(").replace(" )", ")")
    return s


def _status_info(value) -> tuple[str, int]:
    """Return exact business status family and resub stage 0-3."""
    s = _normalize_status_text(value)
    stage = 0
    for n in (1, 2, 3):
        if f"resub-{n}" in s or f"resub {n}" in s:
            stage = n
            break

    # Remove only the agreed resub suffix for base classification.
    base = s
    for n in (1, 2, 3):
        for token in [f"(resub-{n})", f"(resub {n})", f"resub-{n}", f"resub {n}"]:
            base = base.replace(token, "")
    base = base.strip(" -()")
    base = " ".join(base.split())
    return base, stage


def _is_initial_rejection_status(value) -> bool:
    base, stage = _status_info(value)
    if base in ["rejected", "rejection accepted"]:
        return True
    if stage >= 1 and base in ["approved", "submitted", "not submitted"]:
        return True
    return False


def _resub_recovery(row, stage: int) -> float:
    """Actual additional money received AFTER the initial rejection."""
    try:
        tkbk = float(row.get("TKBKAmountAct", 0) or 0)
    except Exception:
        tkbk = 0.0
    if tkbk != 0:
        return round(abs(tkbk), 2)

    values = []
    if stage >= 1:
        values.append(row.get("actResub1RemitInsShare", 0))
    if stage >= 2:
        values.append(row.get("actResub2RemitInsShare", 0))
    if stage >= 3:
        values.append(row.get("actResub3RemitInsShare", 0))
    return _distinct_resub_sum(values)

def ensure_insurance_column(df: pd.DataFrame) -> pd.DataFrame:
    insurance_col = next(
        (c for c in ["Insurance", "PayerName", "Insurer", "Plan"] if c in df.columns),
        "Insurance",
    )
    if insurance_col not in df.columns:
        df["Insurance"] = "Not Available"
    elif insurance_col != "Insurance":
        df["Insurance"] = df[insurance_col]
    df["Insurance"] = df["Insurance"].astype(str).fillna("").str.strip()
    df.loc[df["Insurance"].eq(""), "Insurance"] = "Not Available"
    return df


def add_refdate_and_aging(df: pd.DataFrame) -> pd.DataFrame:
    # Both supplied exports use SubDate. Keep legacy alternatives as fallbacks.
    date_candidates = [
        c for c in ["SubDate", "SubmissionDate", "ClaimDate", "VisitDate"]
        if c in df.columns
    ]
    if date_candidates:
        for c in date_candidates:
            df[c] = pd.to_datetime(df[c], errors="coerce", dayfirst=True)
        df["RefDate"] = df[date_candidates].bfill(axis=1).iloc[:, 0]
    else:
        df["RefDate"] = pd.NaT

    today = pd.Timestamp(dt.today().date())
    df["DaysDiff"] = (today - df["RefDate"]).dt.days

    bins = [-1, 30, 45, 60, 90, float("inf")]
    labels = ["0–30 Days", "31–45 Days", "46–60 Days", "61–90 Days", ">90 Days"]
    df["AgingBucket"] = pd.cut(df["DaysDiff"], bins=bins, labels=labels)
    return df


def normalize_denial_code(df: pd.DataFrame) -> pd.DataFrame:
    if "DenialCode" not in df.columns:
        df["DenialCode"] = ""
    df["DenialCode"] = df["DenialCode"].astype(str).fillna("").str.strip()
    df.loc[df["DenialCode"].str.lower().isin(["nan", "none", "null"]), "DenialCode"] = ""
    return df


def build_rejected_df(df: pd.DataFrame) -> pd.DataFrame:
    """Build ALL initial rejection activities from the agreed Status values.

    RejectedAmount = ActivityIns - actRemitInsShare.
    No FinalPaidAmount / FinalBalance and no Paid==0 requirement.
    """
    mask = df["AnalysisStatus"].apply(_is_initial_rejection_status)
    rej = df.loc[mask].copy()

    activity = pd.to_numeric(rej["ActivityIns"], errors="coerce").fillna(0)
    initial_paid = pd.to_numeric(rej["actRemitInsShare"], errors="coerce").fillna(0)
    rej["RejectedAmount"] = (activity - initial_paid).clip(lower=0).round(2)

    info = rej["AnalysisStatus"].apply(_status_info)
    rej["StatusBase"] = info.apply(lambda x: x[0])
    rej["ResubStage"] = info.apply(lambda x: x[1])
    rej["JourneyStatus"] = rej["AnalysisStatus"].astype(str).fillna("").str.strip()

    # Zero-balance activities are not rejection amount.
    rej = rej.loc[rej["RejectedAmount"] > 0].copy()
    return rej

def _unique_claim_count(series: pd.Series) -> int:
    """Count unique claim IDs without changing any amount calculation.

    Blank/missing UniqueID values are counted row-by-row instead of being
    collapsed into one claim, so we never undercount because of missing IDs.
    """
    s = series.astype("string").str.strip()
    valid = s.notna() & (~s.str.lower().isin(["", "nan", "none", "null", "<na>"]))
    return int(s[valid].nunique(dropna=True) + (~valid).sum())

def pivot_by_insurance(rej: pd.DataFrame) -> pd.DataFrame:
    # IMPORTANT: RejectedAmount remains the SUM of all rejected activities.
    # Only RejectedCount is deduplicated by claim UniqueID.
    if "UniqueID" in rej.columns:
        out = (
            rej.groupby("Insurance", dropna=False)
               .agg(
                   RejectedAmount=("RejectedAmount", "sum"),
                   RejectedCount=("UniqueID", _unique_claim_count),
               )
               .reset_index()
               .sort_values("RejectedAmount", ascending=False)
        )
        grand_count = _unique_claim_count(rej["UniqueID"])
    else:
        # Fallback for an unexpected export without UniqueID.
        out = (
            rej.groupby("Insurance", dropna=False)
               .agg(
                   RejectedAmount=("RejectedAmount", "sum"),
                   RejectedCount=("RejectedAmount", "size"),
               )
               .reset_index()
               .sort_values("RejectedAmount", ascending=False)
        )
        grand_count = int(len(rej))

    total_row = {
        "Insurance": "Grand Total",
        "RejectedAmount": out["RejectedAmount"].sum(),
        "RejectedCount": grand_count,
    }
    return pd.concat([out, pd.DataFrame([total_row])], ignore_index=True)

def pivot_by_denialcode(rej: pd.DataFrame) -> pd.DataFrame:
    # Same principle here: amounts are untouched; claim count is UniqueID-based.
    if "UniqueID" in rej.columns:
        out = (
            rej.groupby("DenialCode", dropna=False)
               .agg(
                   RejectedAmount=("RejectedAmount", "sum"),
                   RejectedCount=("UniqueID", _unique_claim_count),
               )
               .reset_index()
               .sort_values("RejectedAmount", ascending=False)
        )
        grand_count = _unique_claim_count(rej["UniqueID"])
    else:
        out = (
            rej.groupby("DenialCode", dropna=False)
               .agg(
                   RejectedAmount=("RejectedAmount", "sum"),
                   RejectedCount=("RejectedAmount", "size"),
               )
               .reset_index()
               .sort_values("RejectedAmount", ascending=False)
        )
        grand_count = int(len(rej))

    total_row = {
        "DenialCode": "Grand Total",
        "RejectedAmount": out["RejectedAmount"].sum(),
        "RejectedCount": grand_count,
    }
    return pd.concat([out, pd.DataFrame([total_row])], ignore_index=True)

def pivot_insurance_x_denialcode(rej: pd.DataFrame) -> pd.DataFrame:
    pv = pd.pivot_table(
        rej,
        index="Insurance",
        columns="DenialCode",
        values="RejectedAmount",
        aggfunc="sum",
        fill_value=0,
        observed=False,
    )
    pv["Grand Total"] = pv.sum(axis=1)
    pv.loc["Grand Total"] = pv.sum(axis=0)
    pv.reset_index(inplace=True)
    return pv

def pivot_rejection_aging(rej: pd.DataFrame) -> pd.DataFrame:
    labels = ["0–30 Days", "31–45 Days", "46–60 Days", "61–90 Days", ">90 Days"]
    pv = pd.pivot_table(
        rej,
        index="Insurance",
        columns="AgingBucket",
        values="RejectedAmount",
        aggfunc="sum",
        fill_value=0,
        observed=False,
    ).reindex(columns=labels)
    pv["Grand Total"] = pv.sum(axis=1)
    pv.loc["Grand Total"] = pv.sum(axis=0)
    pv.reset_index(inplace=True)
    return pv


# =========================================
# REJECTION RECOVERY / RESUBMISSION TRACKER
# =========================================
def build_recovery_detail(df: pd.DataFrame) -> pd.DataFrame:
    """Trace the initial rejection through the current Status journey.

    OriginalRejectedAmount = ActivityIns - actRemitInsShare.
    RecoveredAmount = ONLY additional payment in resub remit fields.
    """
    hist = build_rejected_df(df)
    if hist.empty:
        return hist

    hist["CurrentStatus"] = hist["JourneyStatus"]
    hist["OriginalRejectedAmount"] = pd.to_numeric(hist["RejectedAmount"], errors="coerce").fillna(0)

    hist["RecoveredAmount"] = hist.apply(
        lambda r: _resub_recovery(r, int(r.get("ResubStage", 0) or 0)), axis=1
    )
    # Never show recovery above the amount that was actually rejected.
    hist["RecoveredAmount"] = hist[["RecoveredAmount", "OriginalRejectedAmount"]].min(axis=1).clip(lower=0).round(2)
    hist["OutstandingAmount"] = (
        hist["OriginalRejectedAmount"] - hist["RecoveredAmount"]
    ).clip(lower=0).round(2)

    def classify(row):
        base = str(row.get("StatusBase", "")).strip().lower()
        stage = int(row.get("ResubStage", 0) or 0)
        if base == "approved" and stage >= 1:
            return "Approved / Recovered"
        if base == "submitted" and stage >= 1:
            return "Resubmitted / Pending"
        if base == "rejected":
            return "Still Rejected"
        if base == "rejection accepted":
            return "Rejection Accepted"
        if base == "not submitted" and stage >= 1:
            return "Not Resubmitted"
        return "Other"

    hist["RecoveryBucket"] = hist.apply(classify, axis=1)

    # Keep original denial code first; final is only fallback.
    if "DenialCode" in hist.columns:
        hist["RecoveryDenialCode"] = hist["DenialCode"].astype(str).fillna("").str.strip()
    else:
        hist["RecoveryDenialCode"] = ""

    return hist

def build_recovery_summary(recovery: pd.DataFrame) -> pd.DataFrame:
    cols = [
        "RecoveryBucket", "OriginalRejectedAmount", "RecoveredAmount",
        "OutstandingAmount", "ActivityRows", "UniqueClaims"
    ]
    if recovery.empty:
        return pd.DataFrame(columns=cols)

    rows = []
    for bucket, g in recovery.groupby("RecoveryBucket", dropna=False):
        rows.append({
            "RecoveryBucket": bucket,
            "OriginalRejectedAmount": pd.to_numeric(g["OriginalRejectedAmount"], errors="coerce").fillna(0).sum(),
            "RecoveredAmount": pd.to_numeric(g["RecoveredAmount"], errors="coerce").fillna(0).sum(),
            "OutstandingAmount": pd.to_numeric(g["OutstandingAmount"], errors="coerce").fillna(0).sum(),
            "ActivityRows": int(len(g)),
            "UniqueClaims": _unique_claim_count(g["UniqueID"]) if "UniqueID" in g.columns else int(len(g)),
        })
    out = pd.DataFrame(rows).sort_values("OriginalRejectedAmount", ascending=False)
    total = {
        "RecoveryBucket": "Grand Total",
        "OriginalRejectedAmount": out["OriginalRejectedAmount"].sum(),
        "RecoveredAmount": out["RecoveredAmount"].sum(),
        "OutstandingAmount": out["OutstandingAmount"].sum(),
        "ActivityRows": int(out["ActivityRows"].sum()),
        "UniqueClaims": _unique_claim_count(recovery["UniqueID"]) if "UniqueID" in recovery.columns else int(len(recovery)),
    }
    return pd.concat([out, pd.DataFrame([total])], ignore_index=True)


def build_recovery_by_insurance(recovery: pd.DataFrame) -> pd.DataFrame:
    cols = [
        "Insurance", "OriginalRejectedAmount", "RecoveredAmount",
        "OutstandingAmount", "UniqueClaims", "RecoveryRatePct"
    ]
    if recovery.empty:
        return pd.DataFrame(columns=cols)

    rows = []
    for insurance, g in recovery.groupby("Insurance", dropna=False):
        orig = pd.to_numeric(g["OriginalRejectedAmount"], errors="coerce").fillna(0).sum()
        rec = pd.to_numeric(g["RecoveredAmount"], errors="coerce").fillna(0).sum()
        outst = pd.to_numeric(g["OutstandingAmount"], errors="coerce").fillna(0).sum()
        rows.append({
            "Insurance": insurance,
            "OriginalRejectedAmount": orig,
            "RecoveredAmount": rec,
            "OutstandingAmount": outst,
            "UniqueClaims": _unique_claim_count(g["UniqueID"]) if "UniqueID" in g.columns else int(len(g)),
            "RecoveryRatePct": (rec / orig * 100) if orig > 0 else 0,
        })
    out = pd.DataFrame(rows).sort_values("OriginalRejectedAmount", ascending=False)
    orig = out["OriginalRejectedAmount"].sum()
    rec = out["RecoveredAmount"].sum()
    total = {
        "Insurance": "Grand Total",
        "OriginalRejectedAmount": orig,
        "RecoveredAmount": rec,
        "OutstandingAmount": out["OutstandingAmount"].sum(),
        "UniqueClaims": _unique_claim_count(recovery["UniqueID"]) if "UniqueID" in recovery.columns else int(len(recovery)),
        "RecoveryRatePct": (rec / orig * 100) if orig > 0 else 0,
    }
    return pd.concat([out, pd.DataFrame([total])], ignore_index=True)

# -------------------- excel styling --------------------
HEADER_FILL = PatternFill(start_color="BDD7EE", end_color="BDD7EE", fill_type="solid")
TOTAL_FILL  = PatternFill(start_color="FCE4D6", end_color="FCE4D6", fill_type="solid")

def style_headers(ws):
    for c in range(1, ws.max_column + 1):
        cell = ws.cell(row=1, column=c)
        cell.fill = HEADER_FILL
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal="center", vertical="center")

def highlight_grand_total_rows(ws, label_col=1, label_value="Grand Total"):
    for r in range(2, ws.max_row + 1):
        if ws.cell(row=r, column=label_col).value == label_value:
            for c in range(1, ws.max_column + 1):
                cell = ws.cell(row=r, column=c)
                cell.fill = TOTAL_FILL
                cell.font = Font(bold=True)

def highlight_last_col(ws):
    last_col = ws.max_column
    for r in range(1, ws.max_row + 1):
        cell = ws.cell(row=r, column=last_col)
        cell.fill = TOTAL_FILL
        cell.font = Font(bold=True)

def apply_styling_to_bytes(xlsx_bytes: bytes) -> bytes:
    wb = load_workbook(io.BytesIO(xlsx_bytes))
    for ws in wb.worksheets:
        style_headers(ws)
        if ws.title in [
            "Rejected_By_Insurance",
            "Rejected_By_DenialCode",
            "Rejected_Ins_x_DenialCode",
            "Rejected_Aging_Summary",
            "Recovery_Summary",
            "Recovery_By_Insurance",
        ]:
            highlight_grand_total_rows(ws, label_col=1, label_value="Grand Total")
            if ws.title in ["Rejected_Ins_x_DenialCode", "Rejected_Aging_Summary"]:
                highlight_last_col(ws)
    out_buf = io.BytesIO()
    wb.save(out_buf)
    return out_buf.getvalue()

def build_rejection_workbook_bytes(input_bytes: bytes, input_name: str = "source.xlsx") -> tuple[bytes, dict]:
    df = pd.read_excel(io.BytesIO(input_bytes), engine="openpyxl")
    df.columns = df.columns.str.strip()

    # Normalize old/new billing-software column layouts before analysis.
    df, source_info = normalize_source_schema(df)
    df = ensure_numeric(df)
    df = compute_paid(df)
    df = normalize_denial_code(df)
    df = ensure_insurance_column(df)
    df = add_refdate_and_aging(df)

    rejected_df = build_rejected_df(df)

    by_ins = pivot_by_insurance(rejected_df) if len(rejected_df) else pd.DataFrame(
        [{"Insurance": "Grand Total", "RejectedAmount": 0.0, "RejectedCount": 0}]
    )
    by_code = pivot_by_denialcode(rejected_df) if len(rejected_df) else pd.DataFrame(
        [{"DenialCode": "Grand Total", "RejectedAmount": 0.0, "RejectedCount": 0}]
    )
    ins_x_code = pivot_insurance_x_denialcode(rejected_df) if len(rejected_df) else pd.DataFrame(
        [{"Insurance": "Grand Total", "Grand Total": 0.0}]
    )
    aging_sum = pivot_rejection_aging(rejected_df) if len(rejected_df) else pd.DataFrame(
        [{"Insurance": "Grand Total", "Grand Total": 0.0}]
    )

    # Historical recovery analysis is available in the new export where
    # InitialActivityStatus / CurrentActivityStatus are present.
    recovery_detail = build_recovery_detail(df)
    recovery_summary = build_recovery_summary(recovery_detail)
    recovery_by_insurance = build_recovery_by_insurance(recovery_detail)

    stats = {
        "rejected_rows": int(len(rejected_df)),
        "sha1": sha1_short_bytes(input_bytes),
        "source_format": source_info["format"],
        "recovery_rows": int(len(recovery_detail)),
        "recovery_available": bool(not recovery_detail.empty),
    }

    meta = pd.DataFrame([{
        "InputFile": input_name,
        "InputSHA1": stats["sha1"],
        "GeneratedAt": dt.now().strftime("%Y-%m-%d %H:%M:%S"),
        "SourceFormat": source_info["format"],
        "StatusSource": source_info["status_source"],
        "DenialSource": source_info["denial_source"],
        "PaidSource": source_info["paid_source"],
        "RejectedAmountSource": source_info["amount_source"],
        "RejectedRule": "Agreed Status values; RejectedAmount = ActivityIns - actRemitInsShare",
        "RejectedRows": int(len(rejected_df)),
        "RecoveryTrackingAvailable": bool(not recovery_detail.empty),
        "HistoricalRejectedRows": int(len(recovery_detail)),
        "RecoveryRule": "Status journey; recovery only from resub remit fields; claim counts by UniqueID",
    }])

    out_buf = io.BytesIO()
    with pd.ExcelWriter(out_buf, engine="openpyxl") as writer:
        by_ins.to_excel(writer, sheet_name="Rejected_By_Insurance", index=False)
        by_code.to_excel(writer, sheet_name="Rejected_By_DenialCode", index=False)
        ins_x_code.to_excel(writer, sheet_name="Rejected_Ins_x_DenialCode", index=False)
        aging_sum.to_excel(writer, sheet_name="Rejected_Aging_Summary", index=False)
        rejected_df.to_excel(writer, sheet_name="Rejected_Detail", index=False)
        recovery_summary.to_excel(writer, sheet_name="Recovery_Summary", index=False)
        recovery_by_insurance.to_excel(writer, sheet_name="Recovery_By_Insurance", index=False)
        recovery_detail.to_excel(writer, sheet_name="Recovery_Detail", index=False)
        meta.to_excel(writer, sheet_name="Meta", index=False)

    styled = apply_styling_to_bytes(out_buf.getvalue())
    return styled, stats

# =========================================
# UI HELPERS
# =========================================
def _card(title: str, value: str, sub: str = ""):
    st.markdown(
        f"""
        <div class="card">
          <div class="card-title">{title}</div>
          <div class="card-value">{value}</div>
          <div class="card-sub">{sub}</div>
        </div>
        """,
        unsafe_allow_html=True
    )

def _fmt_aed(x):
    try:
        return f"AED {float(x):,.2f}"
    except Exception:
        return f"AED {x}"

def load_result_from_workbook_bytes(xlsx_bytes: bytes, center: str, year: str, s3_key: str) -> dict:
    xls = pd.ExcelFile(io.BytesIO(xlsx_bytes), engine="openpyxl")

    df_by_ins = pd.read_excel(xls, sheet_name="Rejected_By_Insurance")
    df_by_code = pd.read_excel(xls, sheet_name="Rejected_By_DenialCode")
    df_ins_x_code = pd.read_excel(xls, sheet_name="Rejected_Ins_x_DenialCode")
    df_aging = pd.read_excel(xls, sheet_name="Rejected_Aging_Summary")

    try:
        df_recovery_summary = pd.read_excel(xls, sheet_name="Recovery_Summary")
        df_recovery_by_insurance = pd.read_excel(xls, sheet_name="Recovery_By_Insurance")
        recovery_header = pd.read_excel(xls, sheet_name="Recovery_Detail", nrows=0).columns.tolist()
        recovery_preview_cols = [c for c in [
            "UniqueID", "Insurance", "VisitNo", "VisitDate", "Code", "Description",
            "InitialActivityStatus", "CurrentStatus", "RecoveryBucket", "RecoveryDenialCode",
            "OriginalRejectedAmount", "RecoveredAmount", "OutstandingAmount",
            "Resub1ActivityStatus", "Resub2ActivityStatus", "Resub3ActivityStatus",
            "Resub1Date", "Resub2Date", "Resub3Date"
        ] if c in recovery_header]
        df_recovery_preview = pd.read_excel(
            xls, sheet_name="Recovery_Detail", usecols=recovery_preview_cols, nrows=2000
        )
    except Exception:
        df_recovery_summary = pd.DataFrame()
        df_recovery_by_insurance = pd.DataFrame()
        df_recovery_preview = pd.DataFrame()

    PREVIEW_ROWS = 2000
    detail_header = pd.read_excel(xls, sheet_name="Rejected_Detail", nrows=0).columns.tolist()
    wanted_cols = [
        "UniqueID", "Insurance", "DenialCode", "FinalDenialCode",
        "ActivityStatus", "CurrentActivityStatus", "InitialActivityStatus",
        "ActivityIns", "FinalPaidAmount", "FinalBalance", "Paid",
        "AgingBucket", "DaysDiff", "RefDate"
    ]
    usecols = [c for c in wanted_cols if c in detail_header]
    df_preview = pd.read_excel(xls, sheet_name="Rejected_Detail", usecols=usecols, nrows=PREVIEW_ROWS)

    rejected_rows = 0
    source_format = "unknown"
    try:
        df_meta = pd.read_excel(xls, sheet_name="Meta")
        if "RejectedRows" in df_meta.columns and len(df_meta):
            rejected_rows = int(pd.to_numeric(df_meta.loc[0, "RejectedRows"], errors="coerce") or 0)
        if "SourceFormat" in df_meta.columns and len(df_meta):
            source_format = str(df_meta.loc[0, "SourceFormat"])
    except Exception:
        rejected_rows = 0

    stats = {
        "sha1": sha1_short_bytes(xlsx_bytes),
        "rejected_rows": rejected_rows,
        "source_format": source_format,
    }

    return {
        "center": center,
        "year": year,
        "s3_key": s3_key,
        "out_bytes": xlsx_bytes,
        "stats": stats,
        "df_by_ins": df_by_ins,
        "df_by_code": df_by_code,
        "df_ins_x_code": df_ins_x_code,
        "df_aging": df_aging,
        "df_recovery_summary": df_recovery_summary,
        "df_recovery_by_insurance": df_recovery_by_insurance,
        "df_recovery_preview": df_recovery_preview,
        "df_preview": df_preview,
        "preview_rows": PREVIEW_ROWS,
    }

# =========================================
# APP
# =========================================
def run_rejection_app():
    st.markdown("## Rejection Analysis")
    st.caption("Initial rejection = ActivityIns - actRemitInsShare; traced through Resub-1/2/3. FinalPaidAmount and FinalBalance are not used.")

    # --- session init ---
    if "rej_result" not in st.session_state:
        st.session_state.rej_result = None
    if "rej_prev_sel" not in st.session_state:
        st.session_state.rej_prev_sel = None

    # ✅ detect from URL (when clicking Rejected card)
    qp = st.query_params
    if qp.get("center"):
        st.session_state["selected_center"] = qp.get("center")
    if qp.get("year"):
        st.session_state["selected_year"] = qp.get("year")

    detected_center = st.session_state.get("selected_center")
    detected_year = st.session_state.get("selected_year")

    # ---- Sidebar controls ----
    with st.sidebar:
        st.subheader("Controls")

        if detected_center is None or detected_year is None:
            st.warning("Center/Year not detected. Select manually.")
            center = st.selectbox(
                "Center",
                ["Excellent Medical Center", "Excellent Pharmacy", "Easyhealth Clinic"],
                key="rej_center_manual",
            )
            year = st.selectbox("Year", DEFAULT_YEAR_OPTIONS, key="rej_year_manual")
        else:
            center = str(detected_center).lower().strip()
            year = str(detected_year).strip()

            st.success("Detected from dashboard ✅")
            st.selectbox(
                "Center",
                ["excellent", "pharmacy", "easyhealth"],
                index=["excellent", "pharmacy", "easyhealth"].index(center),
                disabled=True,
            )
            st.selectbox(
                "Year",
                DEFAULT_YEAR_OPTIONS,
                index=DEFAULT_YEAR_OPTIONS.index(year),
                disabled=True,
            )

        center_raw = center
        center = normalize_center_for_s3(center_raw)
        year = str(year)

        s3_key = f"streamlit/{center}/{year}/{SOURCE_FILENAME}"
        rej_cache_key = f"{REJ_CACHE_PREFIX}/{center}/{year}/{REJ_CACHE_FILENAME}"

        # ✅ When year/center changes: drop current in-memory result (then auto-load saved if exists)
        current_sel = f"{center}|{year}"
        if st.session_state.rej_prev_sel != current_sel:
            st.session_state.rej_prev_sel = current_sel
            st.session_state.rej_result = None

        st.write("**Source**")
        st.code(f"s3://{S3_BUCKET}/{s3_key}", language="text")

        # ✅ Direct upload from Rejection Analysis page
        st.write("**Upload / Replace Source File**")
        uploaded_source = st.file_uploader(
            "Upload Excel file",
            type=["xlsx"],
            key=f"rej_source_upload_{center}_{year}",
            help="Uploads this workbook directly as the source file for the selected center/year.",
        )

        if uploaded_source is not None:
            uploaded_bytes = uploaded_source.getvalue()
            upload_hash = sha1_short_bytes(uploaded_bytes)
            upload_state_key = f"rej_last_upload_hash_{center}_{year}"

            # Process only once per newly selected file, even after Streamlit reruns.
            if st.session_state.get(upload_state_key) != upload_hash:
                try:
                    with st.spinner("Uploading source and rebuilding rejection analysis..."):
                        # Save/replace source workbook in the same S3 location used by Generate.
                        save_file_to_s3(S3_BUCKET, s3_key, uploaded_bytes)

                        # A new source invalidates the previous cached rejection workbook.
                        delete_file_from_s3(S3_BUCKET, rej_cache_key)

                        # Build immediately so the user does not need a separate Generate click.
                        out_xlsx_bytes, _stats = build_rejection_workbook_bytes(
                            uploaded_bytes, uploaded_source.name
                        )
                        save_file_to_s3(S3_BUCKET, rej_cache_key, out_xlsx_bytes)
                        st.session_state.rej_result = load_result_from_workbook_bytes(
                            out_xlsx_bytes, center, year, s3_key
                        )
                        st.session_state[upload_state_key] = upload_hash

                    st.success(f"Uploaded and analyzed: {uploaded_source.name} ✅")
                except Exception as e:
                    st.error(f"Could not process uploaded file: {e}")

        # ✅ Auto-load saved result from S3 (so it stays until you upload new file or click Generate)
        if st.session_state.rej_result is None and s3_exists(S3_BUCKET, rej_cache_key):
            try:
                cached_bytes = load_file_from_s3(S3_BUCKET, rej_cache_key)
                st.session_state.rej_result = load_result_from_workbook_bytes(cached_bytes, center, year, s3_key)
                st.success("Loaded saved result ✅")
            except Exception:
                st.warning("Saved result found but could not be loaded. Click Generate once.")

        cA, cB = st.columns(2)
        with cA:
            generate = st.button("Generate", type="primary", use_container_width=True)
        with cB:
            clear = st.button("Clear", use_container_width=True)

        if clear:
            # ✅ Clear BOTH session + saved cache (so it won't reappear on refresh)
            st.session_state.rej_result = None
            delete_file_from_s3(S3_BUCKET, rej_cache_key)
            st.rerun()

        if generate:
            if not s3_exists(S3_BUCKET, s3_key):
                st.error("Source file not found in S3. Upload an Excel file above first.")
                st.stop()

            with st.spinner("Building rejection analysis..."):
                input_bytes = load_file_from_s3(S3_BUCKET, s3_key)
                out_xlsx_bytes, _stats = build_rejection_workbook_bytes(input_bytes, SOURCE_FILENAME)

                # ✅ Save to S3 cache (PERSISTENT) so it doesn't ask to process again
                save_file_to_s3(S3_BUCKET, rej_cache_key, out_xlsx_bytes)

                # ✅ Load into session
                st.session_state.rej_result = load_result_from_workbook_bytes(out_xlsx_bytes, center, year, s3_key)

            st.success("Done ✅")

    # ---- Main UI ----
    if st.session_state.rej_result is None:
        st.info("No saved result for this year yet. Click Generate once.")
        return

    R = st.session_state.rej_result
    out_xlsx_bytes = R["out_bytes"]
    stats = R["stats"]

    df_by_ins = R["df_by_ins"]
    df_by_code = R["df_by_code"]
    df_ins_x_code = R["df_ins_x_code"]
    df_aging = R["df_aging"]
    df_recovery_summary = R.get("df_recovery_summary", pd.DataFrame())
    df_recovery_by_insurance = R.get("df_recovery_by_insurance", pd.DataFrame())
    df_recovery_preview = R.get("df_recovery_preview", pd.DataFrame())
    df_preview = R["df_preview"]
    PREVIEW_ROWS = R["preview_rows"]

    st.download_button(
        "Download Rejection Analysis Excel",
        data=out_xlsx_bytes,
        file_name=f"Rejection_Analysis_{R['center']}_{R['year']}_{stats['sha1']}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    # ===== KPIs =====
    df_by_ins_nogt = df_by_ins[df_by_ins["Insurance"] != "Grand Total"].copy()
    total_amount = float(pd.to_numeric(df_by_ins_nogt["RejectedAmount"], errors="coerce").fillna(0).sum())
    total_claims = int(pd.to_numeric(df_by_ins.loc[df_by_ins["Insurance"] == "Grand Total", "RejectedCount"], errors="coerce").fillna(0).iloc[0]) if (df_by_ins["Insurance"] == "Grand Total").any() else int(pd.to_numeric(df_by_ins_nogt["RejectedCount"], errors="coerce").fillna(0).sum())

    c1, c2, c3 = st.columns(3)
    with c1:
        _card(
            "Rejected Rows",
            f"{int(stats.get('rejected_rows', 0)):,}",
            f"Initial rejection journey • format: {stats.get('source_format', 'unknown')}"
        )
    with c2:
        _card("Total Rejected Amount", _fmt_aed(total_amount), "All insurers (excluding Grand Total row)")
    with c3:
        _card("Total Rejected Claims", f"{total_claims:,}", "Unique rejected claims by UniqueID")

    # ===== Top 3 Insurance =====
    st.markdown("### Top 3 Insurances by Rejected Amount")
    top_ins = df_by_ins_nogt.sort_values("RejectedAmount", ascending=False).head(3)
    cols = st.columns(3)
    for i in range(3):
        with cols[i]:
            if i < len(top_ins):
                _card(f"#{i+1} {top_ins.iloc[i]['Insurance']}", _fmt_aed(top_ins.iloc[i]["RejectedAmount"]), "")
            else:
                _card(f"#{i+1}", "AED 0.00", "")

    # ===== Top 3 Denial (Insurance + Code) =====
    st.markdown("### Top 3 Denial (Insurance + Code) by Amount")
    top_den = pd.DataFrame(columns=["Insurance", "DenialCode", "Amount"])
    try:
        pv = df_ins_x_code.copy()
        if "Insurance" in pv.columns:
            pv = pv[pv["Insurance"] != "Grand Total"].copy()
            if "Grand Total" in pv.columns:
                pv = pv.drop(columns=["Grand Total"])
            melted = pv.melt(id_vars=["Insurance"], var_name="DenialCode", value_name="Amount")
            melted["Amount"] = pd.to_numeric(melted["Amount"], errors="coerce").fillna(0)
            melted["DenialCode"] = melted["DenialCode"].astype(str).fillna("").str.strip()
            melted = melted[(melted["DenialCode"] != "") & (melted["Amount"] > 0)]
            top_den = melted.sort_values("Amount", ascending=False).head(3)
    except Exception:
        pass

    cols = st.columns(3)
    for i in range(3):
        with cols[i]:
            if i < len(top_den):
                _card(
                    str(top_den.iloc[i]["Insurance"]),
                    str(top_den.iloc[i]["DenialCode"]),
                    _fmt_aed(float(top_den.iloc[i]["Amount"])),
                )
            else:
                _card("-", "-", "AED 0.00")

    # ===== Denial code drilldown =====
    st.markdown("### Denial Code Drilldown (Top Insurances by Amount)")
    code_options = df_by_code[df_by_code["DenialCode"] != "Grand Total"]["DenialCode"].astype(str).tolist()
    sel_focus_code = st.selectbox("Select Denial Code", [""] + code_options, key="focus_denial_code")

    if sel_focus_code:
        pv2 = df_ins_x_code.copy()
        pv2 = pv2[pv2["Insurance"] != "Grand Total"].copy()
        if sel_focus_code in pv2.columns:
            tmp = pv2[["Insurance", sel_focus_code]].copy()
            tmp[sel_focus_code] = pd.to_numeric(tmp[sel_focus_code], errors="coerce").fillna(0)
            tmp = tmp[tmp[sel_focus_code] > 0].sort_values(sel_focus_code, ascending=False).head(10)
            tmp = tmp.rename(columns={sel_focus_code: "Amount"})
            st.dataframe(tmp, use_container_width=True)
        else:
            st.info("No amounts found for this denial code.")

    st.divider()

    # ===== Recovery & Resubmission Analysis =====
    st.markdown("## Recovery & Resubmission Analysis")
    st.caption(
        "Tracks activities that were initially rejected and shows their current position. "
        "Amounts remain activity-level; claim counts use distinct UniqueID."
    )

    if df_recovery_summary.empty:
        st.info(
            "No activities matched the agreed rejection/resubmission Status values in this export."
        )
    else:
        rs = df_recovery_summary[df_recovery_summary["RecoveryBucket"] != "Grand Total"].copy()
        gt = df_recovery_summary[df_recovery_summary["RecoveryBucket"] == "Grand Total"].copy()

        original_rejected = float(pd.to_numeric(gt["OriginalRejectedAmount"], errors="coerce").fillna(0).iloc[0]) if len(gt) else 0.0
        recovered_amount = float(pd.to_numeric(gt["RecoveredAmount"], errors="coerce").fillna(0).iloc[0]) if len(gt) else 0.0
        outstanding_amount = float(pd.to_numeric(gt["OutstandingAmount"], errors="coerce").fillna(0).iloc[0]) if len(gt) else 0.0
        historical_claims = int(pd.to_numeric(gt["UniqueClaims"], errors="coerce").fillna(0).iloc[0]) if len(gt) else 0
        recovery_rate = (recovered_amount / original_rejected * 100) if original_rejected > 0 else 0.0

        pending_amount = float(pd.to_numeric(
            rs.loc[rs["RecoveryBucket"] == "Resubmitted / Pending", "OutstandingAmount"],
            errors="coerce"
        ).fillna(0).sum())
        still_rejected_amount = float(pd.to_numeric(
            rs.loc[rs["RecoveryBucket"] == "Still Rejected", "OutstandingAmount"],
            errors="coerce"
        ).fillna(0).sum())

        rc1, rc2, rc3, rc4 = st.columns(4)
        with rc1:
            _card("Historical Rejected", _fmt_aed(original_rejected), f"{historical_claims:,} unique claims")
        with rc2:
            _card("Recovered / Paid", _fmt_aed(recovered_amount), f"Recovery rate {recovery_rate:.1f}%")
        with rc3:
            _card("Resubmitted / Pending", _fmt_aed(pending_amount), "Outstanding amount currently submitted")
        with rc4:
            _card("Still Rejected", _fmt_aed(still_rejected_amount), "Outstanding amount still rejected")

        st.markdown("### Recovery Status Summary")
        st.dataframe(df_recovery_summary, use_container_width=True)

        st.markdown("### Recovery by Insurance")
        st.dataframe(df_recovery_by_insurance, use_container_width=True)

        st.markdown("### Trace Rejected → Current Status")
        if not df_recovery_preview.empty:
            ins_options = sorted([
                str(x) for x in df_recovery_preview.get("Insurance", pd.Series(dtype=str)).dropna().unique()
                if str(x).strip()
            ])
            bucket_options = sorted([
                str(x) for x in df_recovery_preview.get("RecoveryBucket", pd.Series(dtype=str)).dropna().unique()
                if str(x).strip()
            ])

            rf1, rf2, rf3 = st.columns([1, 1, 1])
            with rf1:
                rec_ins = st.selectbox("Recovery Insurance", ["All"] + ins_options, key="recovery_insurance_filter")
            with rf2:
                rec_bucket = st.selectbox("Recovery Status", ["All"] + bucket_options, key="recovery_bucket_filter")
            with rf3:
                rec_claim = st.text_input("UniqueID contains", key="recovery_uniqueid_filter")

            rec_filt = df_recovery_preview.copy()
            if rec_ins != "All" and "Insurance" in rec_filt.columns:
                rec_filt = rec_filt[rec_filt["Insurance"].astype(str) == rec_ins]
            if rec_bucket != "All" and "RecoveryBucket" in rec_filt.columns:
                rec_filt = rec_filt[rec_filt["RecoveryBucket"].astype(str) == rec_bucket]
            if rec_claim.strip() and "UniqueID" in rec_filt.columns:
                rec_filt = rec_filt[
                    rec_filt["UniqueID"].astype(str).str.contains(rec_claim.strip(), case=False, na=False)
                ]

            st.dataframe(rec_filt, use_container_width=True)
            st.caption(
                "Tip: choose 'Resubmitted / Pending' to see claims that were rejected before but are now submitted. "
                "Use UniqueID to trace the exact claim."
            )

    st.divider()

    # ===== Tabs =====
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "By Insurance",
        "By Denial Code",
        "Insurance × Denial",
        "Aging Summary",
        "Rejected Detail (Filter + Download)"
    ])

    with tab1:
        st.subheader("Rejected by Insurance")
        st.dataframe(df_by_ins, use_container_width=True)

    with tab2:
        st.subheader("Rejected by Denial Code")
        st.dataframe(df_by_code, use_container_width=True)

    with tab3:
        st.subheader("Insurance × Denial Code (Amounts)")
        st.dataframe(df_ins_x_code, use_container_width=True)

    with tab4:
        st.subheader("Rejected Aging Summary")
        st.dataframe(df_aging, use_container_width=True)

    with tab5:
        st.subheader("Rejected Detail (Filter + Download)")

        ins_list = sorted([x for x in df_preview["Insurance"].dropna().unique().tolist() if str(x).strip() != ""]) if "Insurance" in df_preview.columns else []
        code_list = sorted([x for x in df_preview["DenialCode"].dropna().unique().tolist() if str(x).strip() != ""]) if "DenialCode" in df_preview.columns else []

        c1, c2, c3 = st.columns([1, 1, 1])
        with c1:
            sel_ins = st.selectbox("Insurance", ["All"] + ins_list, key="rej_filter_ins")
        with c2:
            sel_code = st.selectbox("Denial Code", ["All"] + code_list, key="rej_filter_code")
        with c3:
            show_top = st.number_input("Preview rows", min_value=50, max_value=2000, value=500, step=50, key="rej_preview_rows")

        filt = df_preview.copy()
        if sel_ins != "All" and "Insurance" in filt.columns:
            filt = filt[filt["Insurance"].astype(str) == str(sel_ins)]
        if sel_code != "All" and "DenialCode" in filt.columns:
            filt = filt[filt["DenialCode"].astype(str) == str(sel_code)]

        st.caption(f"Preview (from first {PREVIEW_ROWS} rows only). Use Download for FULL filtered output.")
        st.dataframe(filt.head(int(show_top)), use_container_width=True)

        st.divider()
        st.write("### Download FULL filtered rejected detail")
        if st.button("Build & Download Filtered Detail Excel", type="primary", key="rej_dl_btn"):
            with st.spinner("Loading FULL detail and preparing filtered file..."):
                xls_full = pd.ExcelFile(io.BytesIO(out_xlsx_bytes), engine="openpyxl")
                df_full = pd.read_excel(xls_full, sheet_name="Rejected_Detail")

                if sel_ins != "All" and "Insurance" in df_full.columns:
                    df_full = df_full[df_full["Insurance"].astype(str) == str(sel_ins)]
                if sel_code != "All" and "DenialCode" in df_full.columns:
                    df_full = df_full[df_full["DenialCode"].astype(str) == str(sel_code)]

                buf = io.BytesIO()
                with pd.ExcelWriter(buf, engine="openpyxl") as writer:
                    df_full.to_excel(writer, sheet_name="Rejected_Detail_Filtered", index=False)

                safe_name = f"Rejected_Detail_{R['center']}_{R['year']}_{sel_ins}_{sel_code}_{stats['sha1']}.xlsx"
                safe_name = (safe_name.replace(" ", "_")
                                     .replace("/", "_")
                                     .replace("\\", "_")
                                     .replace(":", "_"))

                st.download_button(
                    "Download Filtered Detail Excel",
                    data=buf.getvalue(),
                    file_name=safe_name,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
                st.success(f"Filtered rows: {len(df_full):,} ✅")

run_rejection_app()
