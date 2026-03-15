#!/usr/bin/env python3
# pages/5_Summary_Report.py
# Summary Report page — mirrors center selection flow.
# User selects a center → uploads a source file → runs exclusive_report_status_final.py
# logic in-memory → displays results (Insurance_Totals, Final_Bucket_Summary, Monthly_Totals,
# Balance_Aging_Summary, Balance_Status_Stage_Summary) + download button for full Excel.

import io
import sys
import hashlib
import re
import hmac
import base64
import json
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
import boto3
from botocore.exceptions import BotoCoreError, ClientError

# ─────────────────────────────────────────────────────────────────────────────
# PAGE CONFIG
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(page_title="Summary Report — Excellent Medical Group", layout="wide")
st.set_option("client.showErrorDetails", False)

# ─────────────────────────────────────────────────────────────────────────────
# AUTH — reuse same view password from main dashboard
# ─────────────────────────────────────────────────────────────────────────────
VIEW_PASSWORD = st.secrets.get("VIEW_PASSWORD", "Emc@2026")
TOKEN_SECRET  = st.secrets.get("TOKEN_SECRET", None)
TOKEN_TTL_SECONDS = int(st.secrets.get("TOKEN_TTL_SECONDS", 600))


def _b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def verify_url_token(token: str) -> dict | None:
    if not TOKEN_SECRET:
        return None
    try:
        body_b64, sig_b64 = token.split(".", 1)
        body = _b64url_decode(body_b64)
        sig  = _b64url_decode(sig_b64)
        expected = hmac.new(TOKEN_SECRET.encode("utf-8"), body, hashlib.sha256).digest()
        if not hmac.compare_digest(sig, expected):
            return None
        data = json.loads(body.decode("utf-8"))
        if int(time.time()) - int(data.get("iat", 0)) > TOKEN_TTL_SECONDS:
            return None
        return data
    except Exception:
        return None


def _auto_auth():
    tok = st.query_params.get("token")
    if tok:
        data = verify_url_token(tok)
        if data:
            st.session_state.is_view_auth = True
    auth_param = st.query_params.get("auth")
    if auth_param:
        _secret = st.secrets.get("TOKEN_SECRET", VIEW_PASSWORD)
        expected = hmac.new(_secret.encode("utf-8"), b"view_auth", hashlib.sha256).hexdigest()[:16]
        if auth_param == expected:
            st.session_state.is_view_auth = True


_auto_auth()


def require_view_access():
    if st.session_state.get("is_view_auth", False):
        return
    st.title("🔒 Dashboard Access")
    st.info("Enter the view password to open the dashboard.")
    pwd = st.text_input("View Password", type="password", key="sum_view_pwd")
    if st.button("Enter Dashboard", use_container_width=True):
        if pwd == VIEW_PASSWORD:
            st.session_state.is_view_auth = True
            st.rerun()
        else:
            st.error("Incorrect password.")
    st.stop()


require_view_access()

# ─────────────────────────────────────────────────────────────────────────────
# PREMIUM CSS (same as main dashboard)
# ─────────────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap');
.stApp{
  background: linear-gradient(145deg, #EDF2FB 0%, #F8FAFF 40%, #FAFCFF 100%) !important;
  font-family: 'Inter', sans-serif !important;
}
hr{ border:none!important;height:1px!important;background:linear-gradient(90deg,transparent,#C8D9F0,transparent)!important; }
div.stButton > button{
  width:100%!important;min-height:50px!important;padding:12px 20px!important;
  font-size:15px!important;font-weight:700!important;font-family:'Inter',sans-serif!important;
  background:linear-gradient(160deg,#FFFFFF 0%,#EEF4FF 100%)!important;
  color:#0A2647!important;border:1.5px solid #C5D8F5!important;border-radius:14px!important;
  box-shadow:0 2px 8px rgba(10,38,71,0.08),inset 0 1px 0 rgba(255,255,255,0.9)!important;
  transition:all 0.2s ease!important;
}
div.stButton > button:hover{
  background:linear-gradient(160deg,#E8F1FF 0%,#D6E8FF 100%)!important;
  border-color:#7DAAEE!important;box-shadow:0 6px 20px rgba(10,38,71,0.15)!important;
  transform:translateY(-1px)!important;
}
div.stButton > button:active{
  background:linear-gradient(160deg,#0A2647 0%,#154B8A 100%)!important;
  color:#fff!important;border-color:#0A2647!important;
}
.center-title{color:#0A2647!important;font-weight:900!important;font-family:'Inter',sans-serif!important;letter-spacing:-0.5px!important;margin-bottom:0!important;}
.kpi-grid{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:14px;margin-top:10px;margin-bottom:10px;}
.kpi-card{background:rgba(255,255,255,0.85);backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px);border:1.5px solid rgba(197,216,245,0.7);border-radius:18px;padding:16px 18px;box-shadow:0 4px 16px rgba(10,38,71,0.07),0 1px 3px rgba(10,38,71,0.05),inset 0 1px 0 rgba(255,255,255,0.95);min-width:0;transition:all 0.2s ease;}
.kpi-label{font-size:12px;color:#8A9BB5;font-weight:600;font-family:'Inter',sans-serif;letter-spacing:0.6px;text-transform:uppercase;margin-bottom:8px;}
.kpi-value{font-size:clamp(17px,2.1vw,28px);font-weight:800;color:#0D1B2E;letter-spacing:-0.5px;font-family:'Inter',sans-serif;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.kpi-card.balance{background:linear-gradient(145deg,rgba(10,38,71,0.96) 0%,rgba(15,56,110,0.96) 100%);border-color:rgba(180,210,255,0.25);}
.kpi-card.balance .kpi-label{color:rgba(180,205,255,0.75);}
.kpi-card.balance .kpi-value{color:#FFFFFF;}
@media(max-width:1100px){.kpi-grid{grid-template-columns:repeat(2,minmax(0,1fr));}}
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# CENTERS CONFIG (same as main dashboard)
# ─────────────────────────────────────────────────────────────────────────────
CENTERS = {
    "excellent":  {"key": "excellent",  "name": "Excellent Medical Center (MF4777)"},
    "pharmacy":   {"key": "pharmacy",   "name": "Excellent Pharmacy (PF3205)"},
    "easyhealth": {"key": "easyhealth", "name": "Easy Health Medical Clinic (MF8031)"},
}

# ─────────────────────────────────────────────────────────────────────────────
# S3 CONFIG — summary files ONLY (kept separate from main dashboard prefix)
# ─────────────────────────────────────────────────────────────────────────────
S3_BUCKET = st.secrets.get("S3_BUCKET", "emc-rcm-storage-2026")
SUMMARY_S3_PREFIX = st.secrets.get("SUMMARY_S3_PREFIX", "streamlit2")
AWS_REGION = st.secrets.get("AWS_REGION", "eu-north-1")


def get_s3_client():
    try:
        return boto3.client(
            "s3",
            aws_access_key_id=st.secrets.get("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=st.secrets.get("AWS_SECRET_ACCESS_KEY"),
            region_name=AWS_REGION,
        )
    except Exception:
        return None


def build_summary_s3_key(center_key: str, filename: str) -> str:
    year = st.session_state.get("rcm_year") or datetime.now().year
    safe_filename = re.sub(r"[^\w\-.]", "_", str(filename))
    return f"{SUMMARY_S3_PREFIX}/{year}/{center_key}/{safe_filename}"


def upload_bytes_to_s3(file_bytes: bytes, key: str, content_type: str | None = None):
    s3 = get_s3_client()
    if s3 is None:
        return False, "S3 client not available. Check AWS secrets."
    extra = {}
    if content_type:
        extra["ContentType"] = content_type
    try:
        s3.put_object(Bucket=S3_BUCKET, Key=key, Body=file_bytes, **extra)
        return True, None
    except (BotoCoreError, ClientError, Exception) as e:
        return False, str(e)

# ─────────────────────────────────────────────────────────────────────────────
# HEADER
# ─────────────────────────────────────────────────────────────────────────────
h1, h2 = st.columns([8, 2])
with h1:
    st.title("📋 Summary Report")
    st.caption("Upload a source file per center — results are generated instantly in-memory.")
with h2:
    if st.button("🏠 Back to Dashboard", use_container_width=True, key="sum_back"):
        st.switch_page("exclusive_dashboard.py")

st.markdown("---")

# ─────────────────────────────────────────────────────────────────────────────
# SESSION HELPERS
# ─────────────────────────────────────────────────────────────────────────────
SUM_CENTER_KEY = "sum_center_key"

def reset_sum_center():
    st.session_state[SUM_CENTER_KEY] = None
    st.rerun()

# ─────────────────────────────────────────────────────────────────────────────
# KPI RENDERER (same visual as main dashboard, no links needed here)
# ─────────────────────────────────────────────────────────────────────────────
def render_kpi_cards(net, paid, bal, rej, acc):
    def fmt(x):
        try: return f"{float(x):,.2f}"
        except: return "—"
    html = f"""
    <div class="kpi-grid">
      <div class="kpi-card"><div class="kpi-label">Net Amount</div><div class="kpi-value">{fmt(net)}</div></div>
      <div class="kpi-card"><div class="kpi-label">Paid</div><div class="kpi-value">{fmt(paid)}</div></div>
      <div class="kpi-card balance"><div class="kpi-label">Balance</div><div class="kpi-value">{fmt(bal)}</div></div>
      <div class="kpi-card"><div class="kpi-label">Rejected</div><div class="kpi-value">{fmt(rej)}</div></div>
      <div class="kpi-card"><div class="kpi-label">Accepted</div><div class="kpi-value">{fmt(acc)}</div></div>
    </div>"""
    st.markdown(html, unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# INLINE ENGINE — all logic from exclusive_report_status_final.py
# ─────────────────────────────────────────────────────────────────────────────
MAX_RESUB_STAGE = 10


def _normalize_status(value) -> str:
    s = str(value or "").strip().lower()
    return re.sub(r"\s+", " ", s)


def _extract_stage_info(status_value: str):
    s = _normalize_status(status_value)
    m = re.match(r"^(submitted|not submitted|approved)\s*(?:\(\s*resub\s*-\s*(\d+)\s*\))?$", s)
    if not m:
        return "Other", "Other", None
    base = m.group(1)
    stage_num = int(m.group(2)) if m.group(2) is not None else 0
    stage_label = "Initial" if stage_num == 0 else f"Resub-{stage_num}"
    base_label = {"submitted": "Submitted", "not submitted": "Not Submitted", "approved": "Approved"}[base]
    return base_label, stage_label, stage_num


def _classify_final_bucket(status_value: str) -> str:
    s = _normalize_status(status_value)
    if re.match(r"^rejected\s*(?:\(\s*resub\s*-\s*\d+\s*\))?$", s):
        return "Rejected"
    if re.match(r"^rejection accepted\s*(?:\(\s*resub\s*-\s*\d+\s*\))?$", s):
        return "Accepted"
    return "Balance"


def _choose_stage_date(row, df_columns):
    status_group = row.get("Balance Status Group", "")
    stage_no = row.get("Balance Submission No")
    if status_group == "Not Submitted":
        return pd.NaT
    candidates = []
    if stage_no is None or pd.isna(stage_no):
        candidates = []
    elif int(stage_no) == 0:
        candidates = ["SubDate"]
    else:
        candidates = [f"Resub{int(stage_no)}Date"]
    candidates += ["SubDate", "SubmissionDate", "ClaimDate", "VisitDate"]
    for c in candidates:
        if c in df_columns and pd.notna(row.get(c)):
            return row[c]
    return pd.NaT


def _add_grand_total_row(df: pd.DataFrame, key_col: str) -> pd.DataFrame:
    if df.empty:
        return df
    numeric_cols = df.select_dtypes(include="number").columns.tolist()
    total = {key_col: "Grand Total"}
    for c in df.columns:
        if c == key_col:
            continue
        total[c] = df[c].sum() if c in numeric_cols else ""
    return pd.concat([df, pd.DataFrame([total])], ignore_index=True)



def build_rcm_summary(df: pd.DataFrame, group_col: str) -> pd.DataFrame:
    """
    Build the RCM Summary table grouped by any column (Insurance, DocName, etc.)
    Columns match the EMC RCM Summary report exactly.

    Claim count     = count of unique UniqueID
    Claimed Amount  = sum of SubInsShare
    Remited Amt     = sum of RemitInsShare + sum of Difference
    Initial pay     = sum of RemitInsShare
    Resb1 pay       = sum of Resub1RemitInsShare
    Resb2 pay       = sum of Resub2RemitInsShare
    Resb3 pay       = sum of Resub3RemitInsShare
    Total pay       = Initial + Resb1 + Resb2 + Resb3
    Sub Nt Rmtd     = SubInsShare where Status == "Submitted" (initial only)
    Rsub Nt Rmtd    = Difference where Status matches Submitted (Resub-N)
    Rejection Accepted = SubInsShare where Status == "Rejection Accepted"
    Final Rejn      = Claimed - (Total pay + Sub Nt Rmtd + Rsub Nt Rmtd + Rej Accepted)
    Rej. %          = Final Rejn / Claimed Amount * 100
    """
    import re as _re

    d = df.copy()

    # Ensure needed columns exist
    for c in ["SubInsShare", "RemitInsShare", "Resub1RemitInsShare",
              "Resub2RemitInsShare", "Resub3RemitInsShare", "Difference",
              "UniqueID", "Status"]:
        if c not in d.columns:
            d[c] = 0 if c not in ("UniqueID", "Status") else ("" if c == "Status" else 0)

    for c in ["SubInsShare","RemitInsShare","Resub1RemitInsShare",
              "Resub2RemitInsShare","Resub3RemitInsShare","Difference"]:
        d[c] = pd.to_numeric(d[c], errors="coerce").fillna(0.0)

    # Status masks
    def _norm(v):
        return _re.sub(r"\s+", " ", str(v or "").strip().lower())

    d["_status_norm"] = d["Status"].apply(_norm)

    # Sub Nt Rmtd: Status exactly "submitted" (initial, no resub)
    mask_sub_init = d["_status_norm"] == "submitted"

    # Rsub Nt Rmtd: Status matches "submitted (resub-N)"
    mask_sub_resub = d["_status_norm"].str.match(
        r"^submitted\s*\(\s*resub\s*-\s*\d+\s*\)$"
    )

    # Rejection Accepted
    mask_rej_acc = d["_status_norm"].str.match(
        r"^rejection accepted(\s*\(\s*resub\s*-\s*\d+\s*\))?$"
    )

    # Per-row columns for aggregation
    d["_sub_nt_rmtd"]   = d["SubInsShare"].where(mask_sub_init,   0.0)
    d["_rsub_nt_rmtd"]  = d["Difference"].where(mask_sub_resub,   0.0)
    d["_rej_accepted"]  = d["Difference"].where(mask_rej_acc,      0.0)

    # Pending for Resubmission: SubInsShare where Status = "Not Submitted" (initial)
    mask_not_sub_init  = d["_status_norm"] == "not submitted"
    d["_pending_resub"] = d["SubInsShare"].where(mask_not_sub_init, 0.0)

    agg = d.groupby(group_col, dropna=False, sort=True).agg(
        claim_count     = ("UniqueID",            "nunique"),
        claimed_amt     = ("SubInsShare",          "sum"),
        remit_ins       = ("RemitInsShare",        "sum"),
        difference      = ("Difference",           "sum"),
        initial_pay     = ("RemitInsShare",        "sum"),
        resb1_pay       = ("Resub1RemitInsShare",  "sum"),
        resb2_pay       = ("Resub2RemitInsShare",  "sum"),
        resb3_pay       = ("Resub3RemitInsShare",  "sum"),
        sub_nt_rmtd     = ("_sub_nt_rmtd",        "sum"),
        pending_resub   = ("_pending_resub",       "sum"),
        rsub_nt_rmtd    = ("_rsub_nt_rmtd",       "sum"),
        rej_accepted    = ("_rej_accepted",        "sum"),
    ).reset_index()

    agg["remited_amt"]  = agg["remit_ins"] + agg["difference"]
    agg["total_pay"]    = agg["initial_pay"] + agg["resb1_pay"] + agg["resb2_pay"] + agg["resb3_pay"]
    agg["final_rejn"]   = (agg["claimed_amt"]
                           - agg["total_pay"]
                           - agg["sub_nt_rmtd"]
                           - agg["rsub_nt_rmtd"]
                           - agg["rej_accepted"]).clip(lower=0)
    agg["rej_pct"]      = (agg["final_rejn"] / agg["claimed_amt"].replace(0, float("nan")) * 100).fillna(0.0)

    # Build output with clean column names
    out = pd.DataFrame()
    out[group_col]                          = agg[group_col]
    out["Claim count"]                      = agg["claim_count"]
    out["Claimed Amount"]                   = agg["claimed_amt"]
    out["Remited Amt"]                      = agg["remited_amt"]
    out["Initial pay"]                      = agg["initial_pay"]
    out["Resb1 pay"]                        = agg["resb1_pay"]
    out["Resb2 pay"]                        = agg["resb2_pay"]
    out["Resb3 pay"]                        = agg["resb3_pay"]
    out["Total pay"]                        = agg["total_pay"]
    out["Sub Nt Rmtd (outstanding amount)"] = agg["sub_nt_rmtd"]
    out["Pending for Resubmission"]          = agg["pending_resub"]
    out["Rsub Nt Rmtd (outstanding amount)"] = agg["rsub_nt_rmtd"]
    out["Rejection Accepted"]               = agg["rej_accepted"]
    out["Final Rejn"]                       = agg["final_rejn"]
    out["Rej. %"]                           = agg["rej_pct"]

    # Grand Total row
    num_cols = out.select_dtypes(include="number").columns.tolist()
    gt = {c: out[c].sum() if c in num_cols else "Grand Total" for c in out.columns}
    gt[group_col] = "Grand Total"
    # Rej% for grand total: recalculate from totals
    gt_claimed = out["Claimed Amount"].sum()
    gt["Rej. %"] = (gt["Final Rejn"] / gt_claimed * 100) if gt_claimed else 0.0
    out = pd.concat([out, pd.DataFrame([gt])], ignore_index=True)

    return out

def run_summary_engine(uploaded_bytes: bytes, filename: str) -> dict:
    """
    Run the full exclusive_report_status_final.py logic in-memory.
    Returns a dict with all result DataFrames + metadata.
    """
    # ── Load ──────────────────────────────────────────────────────────────────
    buf = io.BytesIO(uploaded_bytes)
    df = pd.read_excel(buf, engine="openpyxl")
    df.columns = df.columns.astype(str).str.strip()

    # ── Ensure numeric cols ───────────────────────────────────────────────────
    numeric_cols = ["SubInsShare", "RemitInsShare",
                    "Resub1RemitInsShare", "Resub2RemitInsShare",
                    "Resub3RemitInsShare", "Resub4RemitInsShare", "TakeBack"]
    for col in numeric_cols:
        if col not in df.columns:
            df[col] = 0
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

    if "Status" not in df.columns:
        df["Status"] = ""

    # ── Compute measures ─────────────────────────────────────────────────────
    df["Net Amount"] = df["SubInsShare"]
    df["Paid"] = df[["RemitInsShare","Resub1RemitInsShare","Resub2RemitInsShare",
                      "Resub3RemitInsShare","Resub4RemitInsShare","TakeBack"]].sum(axis=1)
    df["Paid"] = df[["Paid","Net Amount"]].min(axis=1)
    df["Residual"] = (df["Net Amount"] - df["Paid"]).clip(lower=0)

    df["Rejected"] = 0.0
    df["Accepted"] = 0.0
    df["Balance"]  = 0.0

    df["Final Bucket"] = df["Status"].apply(_classify_final_bucket)
    mask_rej = df["Final Bucket"] == "Rejected"
    mask_acc = df["Final Bucket"] == "Accepted"
    mask_bal = df["Final Bucket"] == "Balance"

    df.loc[mask_rej, "Rejected"] = df.loc[mask_rej, "Residual"]
    df.loc[mask_acc, "Accepted"] = df.loc[mask_acc, "Residual"]
    df.loc[mask_bal, "Balance"]  = df.loc[mask_bal, "Residual"]

    df["Recon Total"] = df[["Paid","Balance","Rejected","Accepted"]].sum(axis=1)
    df["Recon Diff"]  = (df["Net Amount"] - df["Recon Total"]).round(2)

    stage_info = df["Status"].apply(_extract_stage_info)
    df["Balance Status Group"]      = stage_info.apply(lambda x: x[0])
    df["Balance Submission Stage"]  = stage_info.apply(lambda x: x[1])
    df["Balance Submission No"]     = stage_info.apply(lambda x: x[2])
    df.loc[~mask_bal, ["Balance Status Group","Balance Submission Stage","Balance Submission No"]] = ["","",None]

    # Bucket detail columns
    bucket_defs = [("Submitted",0,"Initial Submitted Balance"),
                   ("Approved", 0,"Initial Approved Balance"),
                   ("Not Submitted",0,"Initial Not Submitted Balance")]
    for n in range(1, MAX_RESUB_STAGE + 1):
        bucket_defs.extend([
            ("Submitted",n,f"Resub{n} Submitted Balance"),
            ("Approved", n,f"Resub{n} Approved Balance"),
            ("Not Submitted",n,f"Resub{n} Not Submitted Balance"),
        ])
    for _, _, col in bucket_defs:
        df[col] = 0.0
    for group, stage_no, col in bucket_defs:
        mask = (
            (df["Balance"] > 0)
            & (df["Balance Status Group"] == group)
            & (df["Balance Submission No"].fillna(-999).astype(int) == stage_no)
        )
        df.loc[mask, col] = df.loc[mask, "Balance"]

    # ── Dates & aging ─────────────────────────────────────────────────────────
    date_cols_all = ["SubDate","Resub1Date","Resub2Date","Resub3Date","Resub4Date","Resub5Date",
                     "Resub6Date","Resub7Date","Resub8Date","Resub9Date","Resub10Date",
                     "SubmissionDate","ClaimDate","VisitDate"]
    for c in [x for x in date_cols_all if x in df.columns]:
        df[c] = pd.to_datetime(df[c], errors="coerce", dayfirst=True)

    df_cols = list(df.columns)
    df["Balance RefDate"] = df.apply(lambda r: _choose_stage_date(r, df_cols), axis=1)
    today = pd.Timestamp(datetime.today().date())
    df["DaysDiff"] = (today - df["Balance RefDate"]).dt.days

    bins   = [-1, 30, 45, 60, 90, float("inf")]
    labels = ["0–30 Days","31–45 Days","46–60 Days","61–90 Days",">90 Days"]
    df["AgingBucket"] = pd.cut(df["DaysDiff"], bins=bins, labels=labels)

    # ── Insurance column ──────────────────────────────────────────────────────
    ins_col = next((c for c in ["Insurance","PayerName","Insurer","Plan"] if c in df.columns), None)
    if ins_col is None:
        df["Insurance"] = "Not Available"
    elif ins_col != "Insurance":
        df["Insurance"] = df[ins_col]
    df["Insurance"] = df["Insurance"].fillna("Not Available")

    # ── Build summary tables ──────────────────────────────────────────────────
    cols_base = ["Net Amount","Paid","Balance","Rejected","Accepted","Recon Diff"]

    # Insurance Totals
    ins_totals = df.groupby("Insurance", dropna=False)[cols_base].sum().reset_index()
    ins_totals = _add_grand_total_row(ins_totals, "Insurance")

    # Final Bucket Summary
    fb_summary = df.groupby("Final Bucket", dropna=False)[["Net Amount","Paid","Balance","Rejected","Accepted"]].sum().reset_index()
    fb_summary = _add_grand_total_row(fb_summary, "Final Bucket")

    # Monthly Totals
    date_col_m = next((c for c in ["VisitDate","SubDate","SubmissionDate","ClaimDate"] if c in df.columns), None)
    monthly = pd.DataFrame()
    if date_col_m:
        tmp = df.copy()
        tmp[date_col_m] = pd.to_datetime(tmp[date_col_m], errors="coerce", dayfirst=True)
        tmp = tmp.dropna(subset=[date_col_m])
        if not tmp.empty:
            tmp["Month"] = tmp[date_col_m].dt.to_period("M").dt.strftime("%B %Y")
            monthly = tmp.groupby("Month", observed=True)[cols_base].sum().reset_index()
            monthly = _add_grand_total_row(monthly, "Month")

    # Balance Aging Summary
    balance_df = df[(df["Balance"] > 0) & df["AgingBucket"].notna()].copy()
    if not balance_df.empty:
        aging_pivot = pd.pivot_table(
            balance_df, index="Insurance", columns="AgingBucket",
            values="Balance", aggfunc="sum", fill_value=0, observed=False,
        ).reindex(columns=labels, fill_value=0)
        aging_pivot["Grand Total"] = aging_pivot.sum(axis=1)
        aging_summary = aging_pivot.reset_index()
        aging_summary = _add_grand_total_row(aging_summary, "Insurance")
    else:
        aging_summary = pd.DataFrame(columns=["Insurance"] + labels + ["Grand Total"])

    # Balance Status Stage Summary
    bss_df = df[df["Balance"] > 0].copy()
    if not bss_df.empty:
        bss = (bss_df.groupby(["Balance Status Group","Balance Submission Stage"], dropna=False)["Balance"]
               .sum().reset_index()
               .sort_values(["Balance Status Group","Balance Submission Stage"]))
        gt_bss = pd.DataFrame([{"Balance Status Group":"Grand Total","Balance Submission Stage":"","Balance":bss["Balance"].sum()}])
        bss = pd.concat([bss, gt_bss], ignore_index=True)
    else:
        bss = pd.DataFrame(columns=["Balance Status Group","Balance Submission Stage","Balance"])

    # Recon check
    recon_diff_total = float(df["Recon Diff"].sum())

    # Grand KPIs (no GT row)
    kpi_df = ins_totals[ins_totals["Insurance"] != "Grand Total"]
    kpi_net  = float(pd.to_numeric(kpi_df["Net Amount"], errors="coerce").sum())
    kpi_paid = float(pd.to_numeric(kpi_df["Paid"],       errors="coerce").sum())
    kpi_bal  = float(pd.to_numeric(kpi_df["Balance"],    errors="coerce").sum())
    kpi_rej  = float(pd.to_numeric(kpi_df["Rejected"],   errors="coerce").sum())
    kpi_acc  = float(pd.to_numeric(kpi_df["Accepted"],   errors="coerce").sum())

    # ── RCM Summary (Insurance view) ─────────────────────────────────────────
    # Ensure Difference column exists
    if "Difference" not in df.columns:
        df["Difference"] = 0.0
    df["Difference"] = pd.to_numeric(df["Difference"], errors="coerce").fillna(0.0)
    if "UniqueID" not in df.columns:
        df["UniqueID"] = range(len(df))  # fallback sequential

    ins_col_rcm = next((c for c in ["Insurance","PayerName","Insurer","Plan"] if c in df.columns), None)
    rcm_group_col = ins_col_rcm if ins_col_rcm else "Insurance"
    if rcm_group_col not in df.columns:
        df[rcm_group_col] = "Not Available"
    df[rcm_group_col] = df[rcm_group_col].fillna("Not Available")

    rcm_insurance = build_rcm_summary(df, rcm_group_col)

    # Doctor wise — try DocName, DoctorName, Doctor, PhysicianName
    rcm_doctor = pd.DataFrame()
    doc_col = next((c for c in ["DocName","DoctorName","Doctor","PhysicianName"] if c in df.columns), None)
    if doc_col:
        df[doc_col] = df[doc_col].fillna("Not Available").astype(str).str.strip()
        rcm_doctor = build_rcm_summary(df, doc_col)

    # Month wise — source file has a "Month" column directly
    rcm_month = pd.DataFrame()
    # Priority: direct "Month" column first, then parse from date columns
    date_col_rcm = next((c for c in ["VisitDate","SubDate","SubmissionDate","ClaimDate"] if c in df.columns), None)
    if "Month" in df.columns:
        import calendar as _cal
        _month_name_map = {m.lower(): i for i, m in enumerate(_cal.month_name) if m}
        _month_abbr_map = {m.lower(): i for i, m in enumerate(_cal.month_abbr) if m}

        def _to_month_label(val):
            """Convert any month value to Jan-22 format."""
            import re as _re
            s = str(val).strip()
            # datetime string: "2022-01-01 00:00:00" or "2022-01-01"
            dt_match = _re.match(r"(\d{4})-(\d{2})-\d{2}", s)
            if dt_match:
                yr = int(dt_match.group(1)) % 100
                mo = int(dt_match.group(2))
                return f"{_cal.month_abbr[mo]}-{yr:02d}"
            # Already Jan-22 format
            if _re.match(r"[A-Za-z]{3}-\d{2}", s):
                return s.title()[:3] + s[3:]
            # Full month name "April" — no year available, use as-is abbreviated
            lower = s.lower()
            if lower in _month_name_map:
                return _cal.month_abbr[_month_name_map[lower]]
            return s

        tmp_m = df.copy()
        tmp_m["Month"] = tmp_m["Month"].apply(_to_month_label)
        tmp_m = tmp_m[tmp_m["Month"].str.lower() != "nan"]
        if not tmp_m.empty:
            rcm_month = build_rcm_summary(tmp_m, "Month")
            # Sort chronologically
            def _month_sort_key(val):
                import re as _re
                try:
                    parts = str(val).strip().split("-")
                    if len(parts) == 2:
                        mon = parts[0].strip().title()[:3]
                        yr  = int(parts[1].strip())
                        return (yr, _month_abbr_map.get(mon.lower(), 0))
                except Exception:
                    pass
                return (9999, 99)
            gt_mask = rcm_month["Month"].astype(str).str.match(r"^\s*(grand\s*total|total)\s*$", case=False)
            body   = rcm_month[~gt_mask].copy()
            gt_row = rcm_month[gt_mask].copy()
            body["_sort"] = body["Month"].apply(_month_sort_key)
            body = body.sort_values("_sort").drop(columns=["_sort"])
            rcm_month = pd.concat([body, gt_row], ignore_index=True)
    elif date_col_rcm:
        tmp_m = df.copy()
        tmp_m[date_col_rcm] = pd.to_datetime(tmp_m[date_col_rcm], errors="coerce", dayfirst=True)
        tmp_m = tmp_m.dropna(subset=[date_col_rcm])
        if not tmp_m.empty:
            tmp_m["Month"] = tmp_m[date_col_rcm].dt.strftime("%b-%y")
            rcm_month = build_rcm_summary(tmp_m, "Month")

    return {
        "df":            df,
        "ins_totals":    ins_totals,
        "fb_summary":    fb_summary,
        "monthly":       monthly,
        "aging_summary": aging_summary,
        "bss":           bss,
        "kpi":           (kpi_net, kpi_paid, kpi_bal, kpi_rej, kpi_acc),
        "recon_diff":    recon_diff_total,
        "row_count":     len(df),
        "filename":      filename,
        "generated_at":  datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "rcm_insurance": rcm_insurance,
        "rcm_doctor":    rcm_doctor,
        "rcm_month":     rcm_month,
        "rcm_group_col": rcm_group_col,
    }


def build_excel_output(result: dict) -> bytes:
    """
    Build a single-sheet Excel workbook matching the reference format:
    - Light grey title row with auto date range
    - Dark green column headers, green text for pay columns
    - White/light grey alternating rows
    - Green Grand Total row
    - All 3 sections (Insurance / Doctor / Month) in one sheet
    """
    from openpyxl import Workbook
    from openpyxl.styles import PatternFill, Font, Alignment, Border, Side
    from openpyxl.utils import get_column_letter

    # ── Colour palette (matching screenshot) ─────────────────────────────────
    C_TITLE_BG   = "D9D9D9"   # light grey  — title bg
    C_TITLE_FG   = "000000"   # black       — title text
    C_HDR_BG     = "595959"   # dark grey   — column header bg
    C_HDR_FG     = "FFFFFF"   # white       — header text
    C_GREEN_FG   = "00B050"   # green       — Initial/Resb pay col text
    C_SUBHDR_BG  = "BFBFBF"   # mid grey    — section label row
    C_SUBHDR_FG  = "000000"   # black       — section label text
    C_GT_BG      = "D9D9D9"   # grey        — grand total row
    C_GT_FG      = "000000"   # black bold  — grand total text
    C_ALT1       = "FFFFFF"   # white       — odd rows
    C_ALT2       = "F2F2F2"   # light grey  — even rows
    C_REJ_FG     = "FF0000"   # red         — Rej.% > 0
    C_BORDER     = "BFBFBF"   # grey border

    NUM_COLS = 13   # total columns (same as reference)

    def _thin():
        s = Side(style="thin", color=C_BORDER)
        return Border(left=s, right=s, top=s, bottom=s)

    def _fill(hex_color):
        return PatternFill("solid", fgColor=hex_color)

    def _font(bold=False, color="000000", size=10, italic=False):
        return Font(bold=bold, color=color, size=size, italic=italic,
                    name="Calibri")

    def _align(h="center", v="center", wrap=False):
        return Alignment(horizontal=h, vertical=v, wrap_text=wrap)

    wb = Workbook()
    ws = wb.active
    ws.title = "RCM SUMMARY"

    # ── Column widths ─────────────────────────────────────────────────────────
    col_widths = [42, 12, 16, 14, 13, 11, 11, 11, 13, 18, 18, 14, 9]
    for i, w in enumerate(col_widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w

    cur = 1  # current row pointer

    def _write_section(df_sec, section_label, start_row):
        """Write one section (Insurance / Doctor / Month) starting at start_row.
        Returns next available row."""
        r = start_row

        # Section label row (e.g. "Insurance Name")
        ws.row_dimensions[r].height = 20
        for c in range(1, NUM_COLS + 1):
            cell = ws.cell(row=r, column=c)
            cell.fill    = _fill(C_SUBHDR_BG)
            cell.font    = _font(bold=True, color=C_SUBHDR_FG, size=11)
            cell.border  = _thin()
            cell.alignment = _align("center")
        ws.cell(row=r, column=1, value=section_label)
        ws.cell(row=r, column=1).alignment = _align("left")
        r += 1

        # Column header row
        ws.row_dimensions[r].height = 36
        GREEN_COLS = {"Initial pay", "Resb1 pay", "Resb2 pay", "Resb3 pay"}
        for ci, col in enumerate(df_sec.columns, 1):
            cell = ws.cell(row=r, column=ci, value=col)
            cell.fill      = _fill(C_HDR_BG)
            cell.font      = _font(bold=True,
                                   color=("90EE90" if col in GREEN_COLS else C_HDR_FG),
                                   size=10)
            cell.border    = _thin()
            cell.alignment = _align("center", wrap=True)
        r += 1

        # Data rows
        for row_idx, (_, row) in enumerate(df_sec.iterrows()):
            is_gt = str(row.iloc[0]).strip().lower() in ("grand total", "total")
            ws.row_dimensions[r].height = 18

            for ci, val in enumerate(row, 1):
                cell = ws.cell(row=r, column=ci)

                # Format numbers
                if ci > 1 and not is_gt:
                    try:
                        val = float(val)
                        col_name = df_sec.columns[ci - 1]
                        if col_name == "Rej. %":
                            cell.number_format = "0.00%"
                            val = val / 100
                        elif col_name == "Claim count":
                            cell.number_format = "#,##0"
                            val = int(val)
                        else:
                            cell.number_format = "#,##0.00"
                    except (ValueError, TypeError):
                        pass
                elif ci > 1 and is_gt:
                    try:
                        val = float(val)
                        col_name = df_sec.columns[ci - 1]
                        if col_name == "Rej. %":
                            cell.number_format = "0.00%"
                            val = val / 100
                        elif col_name == "Claim count":
                            cell.number_format = "#,##0"
                            val = int(val)
                        else:
                            cell.number_format = "#,##0.00"
                    except (ValueError, TypeError):
                        pass

                cell.value = val

                if is_gt:
                    cell.fill      = _fill(C_GT_BG)
                    cell.font      = _font(bold=True, color=C_GT_FG, size=10)
                else:
                    bg = C_ALT1 if row_idx % 2 == 0 else C_ALT2
                    cell.fill = _fill(bg)
                    # Red Rej.%
                    col_name = df_sec.columns[ci - 1]
                    if col_name == "Rej. %" and not is_gt:
                        try:
                            if float(row.iloc[ci - 1]) > 0:
                                cell.font = _font(bold=True, color=C_REJ_FG, size=10)
                            else:
                                cell.font = _font(color="000000", size=10)
                        except Exception:
                            cell.font = _font(size=10)
                    elif col_name in ("Initial pay","Resb1 pay","Resb2 pay","Resb3 pay"):
                        cell.font = _font(color="1E8449", size=10)
                    else:
                        cell.font = _font(size=10)
                    cell.alignment = _align("right" if ci > 1 else "left")

                cell.border = _thin()
                if is_gt:
                    cell.alignment = _align("right" if ci > 1 else "left")
            r += 1

        return r  # next row after this section

    # ── Build title from date range in data ──────────────────────────────────
    def _get_date_range():
        """Get start/end month-year from rcm_month or from df dates."""
        try:
            rcm_m = result.get("rcm_month")
            if rcm_m is not None and not rcm_m.empty:
                import calendar as _cal
                month_map = {m: i for i, m in enumerate(_cal.month_abbr) if m}
                def _mk(v):
                    try:
                        p = str(v).strip().split("-")
                        if len(p) == 2:
                            return (int(p[1]), month_map.get(p[0].title()[:3], 0))
                    except Exception:
                        pass
                    return (9999, 99)
                gt_p = re.compile(r"^\s*(grand\s*total|total)\s*$", re.I)
                rows = [str(r) for r in rcm_m.iloc[:, 0] if not gt_p.match(str(r))]
                if rows:
                    rows_sorted = sorted(rows, key=_mk)
                    start = rows_sorted[0].upper()
                    end   = rows_sorted[-1].upper()
                    return f"EMC - RCM SUMMARY - {start} - {end}"
        except Exception:
            pass
        return "EMC - RCM SUMMARY"

    title_text = _get_date_range()

    # ── Title row ─────────────────────────────────────────────────────────────
    ws.merge_cells(start_row=cur, start_column=1, end_row=cur, end_column=NUM_COLS)
    title_cell = ws.cell(row=cur, column=1)
    title_cell.value     = title_text
    title_cell.fill      = _fill(C_TITLE_BG)
    title_cell.font      = _font(bold=True, color=C_TITLE_FG, size=14)
    title_cell.alignment = _align("center")
    ws.row_dimensions[cur].height = 36
    cur += 1

    # blank row
    ws.row_dimensions[cur].height = 8
    cur += 1

    # ── Insurance section ─────────────────────────────────────────────────────
    rcm_ins = result.get("rcm_insurance")
    if rcm_ins is not None and not rcm_ins.empty:
        cur = _write_section(rcm_ins, "Insurance Name", cur)
        ws.row_dimensions[cur].height = 8
        cur += 1   # blank separator

    # ── Doctor section ────────────────────────────────────────────────────────
    rcm_doc = result.get("rcm_doctor")
    if rcm_doc is not None and not rcm_doc.empty:
        cur = _write_section(rcm_doc, "Doctor Name", cur)
        ws.row_dimensions[cur].height = 8
        cur += 1

    # ── Month section ─────────────────────────────────────────────────────────
    rcm_mon = result.get("rcm_month")
    if rcm_mon is not None and not rcm_mon.empty:
        cur = _write_section(rcm_mon, "Month", cur)

    # freeze panes below title
    ws.freeze_panes = "A3"

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.read()


# ─────────────────────────────────────────────────────────────────────────────
# DISPLAY HELPER — styled dataframe (Grand Total last, highlighted)
# ─────────────────────────────────────────────────────────────────────────────
GT_PAT = re.compile(r'^\s*(grand\s*total|total)\s*$', re.I)


def _move_gt_last(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    first = df.columns[0]
    mask = df[first].astype(str).str.match(GT_PAT)
    return pd.concat([df.loc[~mask], df.loc[mask]], ignore_index=True)


def _style_gt(df: pd.DataFrame):
    """Apply Grand Total bold + orange highlight."""
    def _highlight(row):
        if GT_PAT.match(str(row.iloc[0])):
            return ["background-color:#FCE4D6;font-weight:bold"] * len(row)
        return [""] * len(row)
    return df.style.apply(_highlight, axis=1)


def _fmt_numeric(df: pd.DataFrame) -> pd.DataFrame:
    """Format numeric columns to 2 decimal places for display."""
    num_cols = df.select_dtypes(include="number").columns.tolist()
    return df.style.format({c: "{:,.2f}" for c in num_cols})


def show_table(df: pd.DataFrame, key: str):
    if df is None or df.empty:
        st.info("No data available.")
        return
    df = _move_gt_last(df)
    num_cols = df.select_dtypes(include="number").columns.tolist()
    styled = df.style.apply(
        lambda row: ["background-color:#FCE4D6;font-weight:bold" if GT_PAT.match(str(row.iloc[0])) else "" for _ in row],
        axis=1
    ).format({c: "{:,.2f}" for c in num_cols})
    st.dataframe(styled, use_container_width=True, hide_index=True, key=key)


# ─────────────────────────────────────────────────────────────────────────────
# CENTER SELECTION
# ─────────────────────────────────────────────────────────────────────────────
ck = st.session_state.get(SUM_CENTER_KEY)

if ck not in CENTERS:
    st.subheader("Choose a center")

    sel_year = st.session_state.get("rcm_year") or 2026
    if sel_year not in (2024, 2025, 2026):
        sel_year = 2026

    col1, col2, col3 = st.columns(3)
    with col1:
        if st.container(border=True).button(CENTERS["excellent"]["name"], use_container_width=True, key="sum_exc"):
            st.session_state[SUM_CENTER_KEY] = "excellent"
            st.rerun()
    with col2:
        if st.container(border=True).button(CENTERS["pharmacy"]["name"], use_container_width=True, key="sum_pharm"):
            st.session_state[SUM_CENTER_KEY] = "pharmacy"
            st.rerun()
    with col3:
        if st.container(border=True).button(CENTERS["easyhealth"]["name"], use_container_width=True, key="sum_easy"):
            st.session_state[SUM_CENTER_KEY] = "easyhealth"
            st.rerun()

    st.stop()

# ─────────────────────────────────────────────────────────────────────────────
# CENTER DETAIL + UPLOAD + RESULTS
# ─────────────────────────────────────────────────────────────────────────────
center_cfg = CENTERS[ck]

st.markdown(
    f"""
    <div style="
        background:#F5FAFF;border:1.5px solid #CFE3FF;padding:14px 18px;border-radius:16px;
        margin-bottom:10px;box-shadow:0 6px 18px rgba(11,45,92,0.08);
    ">
      <div style="font-size:24px;font-weight:900;color:#0B2D5C;">{center_cfg['name']}</div>
      <div style="font-size:13px;color:#334155;margin-top:2px;font-weight:600;">Summary Report — upload a source file to generate results</div>
    </div>
    """,
    unsafe_allow_html=True,
)

if st.button("◀ Choose another center", key="sum_back_center"):
    st.session_state[SUM_CENTER_KEY] = None
    st.rerun()

st.markdown("---")

# ── File uploader ────────────────────────────────────────────────────────────
RESULT_KEY = f"sum_result_{ck}"

up = st.file_uploader(
    f"Upload source Excel for **{center_cfg['name']}** (.xlsx)",
    type=["xlsx"],
    key=f"sum_uploader_{ck}",
    help="Upload the raw claims source file. The summary engine will process it and display results below.",
)

up_rcm = None  # placeholder — no second uploader in this version

if up is not None:
    if st.button("⚙️ Process File", use_container_width=True, key=f"sum_process_btn_{ck}"):
        with st.spinner("Processing file — please wait..."):
            try:
                file_bytes = up.read()

                source_s3_key = build_summary_s3_key(center_cfg["key"], up.name)
                ok_src, err_src = upload_bytes_to_s3(
                    file_bytes,
                    source_s3_key,
                    content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )

                result = run_summary_engine(file_bytes, up.name)
                result["source_s3_key"] = source_s3_key if ok_src else ""
                result["source_s3_saved"] = ok_src
                result["source_s3_error"] = err_src or ""
                result["rcm_summary_bytes"] = up_rcm.read() if up_rcm is not None else None
                result["rcm_summary_name"]  = up_rcm.name  if up_rcm is not None else None
                st.session_state[RESULT_KEY] = result
                st.rerun()
            except Exception as e:
                st.error(f"Processing failed: {e}")
                st.session_state.pop(RESULT_KEY, None)

# ── Show results ─────────────────────────────────────────────────────────────
result = st.session_state.get(RESULT_KEY)

if result:
    st.success(f"✅ Processed **{result['filename']}** — {result['row_count']:,} rows · Generated at {result['generated_at']}")

    recon = result["recon_diff"]
    if abs(recon) > 0.01:
        st.warning(f"⚠️ Recon Diff: {recon:,.2f} — Net Amount does not fully reconcile with Paid + Balance + Rejected + Accepted.")
    else:
        st.info("✅ Reconciliation check passed — Net = Paid + Balance + Rejected + Accepted.")

    # KPI cards
    net, paid, bal, rej, acc = result["kpi"]
    render_kpi_cards(net, paid, bal, rej, acc)

    st.markdown("---")

    # Download full Excel
    excel_bytes = build_excel_output(result)
    safe_name = re.sub(r"[^\w\-.]", "_", center_cfg["key"])
    dl_name = f"{safe_name}_summary_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"

    report_s3_key = build_summary_s3_key(center_cfg["key"], dl_name)
    ok_rep, err_rep = upload_bytes_to_s3(
        excel_bytes,
        report_s3_key,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    if result.get("source_s3_saved"):
        st.caption(f"Source saved to S3: {result.get('source_s3_key','')}")
    elif result.get("source_s3_error"):
        st.warning(f"Source file could not be saved to S3: {result['source_s3_error']}")

    if ok_rep:
        st.caption(f"Summary saved to S3: {report_s3_key}")
    else:
        st.warning(f"Summary report could not be saved to S3: {err_rep}")

    st.download_button(
        "⬇️ Download Full Summary Report (Excel)",
        data=excel_bytes,
        file_name=dl_name,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
        key=f"sum_dl_{ck}",
    )

    st.markdown("---")

    # ── Tabs ──────────────────────────────────────────────────────────────────
    # ── 3 RCM tabs ────────────────────────────────────────────────────────────
    tabs = st.tabs([
        "🏥 Insurance",
        "👨‍⚕️ Doctor",
        "📅 Month",
    ])

    def _show_rcm(df_rcm, key):
        """Shared styled display for all 3 RCM summary views."""
        if df_rcm is None or (hasattr(df_rcm, "empty") and df_rcm.empty):
            st.info("No data available.")
            return
        gt_p = re.compile(r'^\s*(grand\s*total|total)\s*$', re.I)
        nums = df_rcm.select_dtypes(include="number").columns.tolist()
        fmt  = {c: ("{:.2f}%" if c == "Rej. %" else "{:,.2f}") for c in nums}

        def _style(row):
            if gt_p.match(str(row.iloc[0])):
                return ["background-color:#FCE4D6;font-weight:bold"] * len(row)
            styles = [""] * len(row)
            if "Rej. %" in row.index:
                try:
                    if float(row["Rej. %"]) > 0:
                        styles[list(row.index).index("Rej. %")] = "color:#C0392B;font-weight:600"
                except Exception:
                    pass
            return styles

        st.dataframe(
            df_rcm.style.apply(_style, axis=1).format(fmt),
            use_container_width=True, hide_index=True, key=key
        )

    with tabs[0]:
        st.subheader("RCM Summary — by Insurance")
        _show_rcm(result.get("rcm_insurance"), "rcm_ins")

    with tabs[1]:
        st.subheader("RCM Summary — by Doctor")
        _show_rcm(result.get("rcm_doctor"), "rcm_doc")

    with tabs[2]:
        st.subheader("RCM Summary — by Month")
        _show_rcm(result.get("rcm_month"), "rcm_mon")

else:
    st.info("👆 Upload a source Excel file above to generate the summary report.")
