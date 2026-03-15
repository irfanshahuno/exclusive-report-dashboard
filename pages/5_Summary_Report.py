#!/usr/bin/env python3
# pages/5_Summary_Report.py
# Clean Summary Report page:
# - Upload file
# - Click Process Summary Report
# - Show only 3 tabs: Insurance / Doctor Wise / Month Wise
# - One download button with one Excel containing all 3 sheets

import io
import hashlib
import re
import hmac
import base64
import json
import time
from datetime import datetime

import pandas as pd
import streamlit as st
import boto3
from botocore.exceptions import BotoCoreError, ClientError

st.set_page_config(page_title="Summary Report — Excellent Medical Group", layout="wide")
st.set_option("client.showErrorDetails", False)

# -----------------------------------------------------------------------------
# AUTH
# -----------------------------------------------------------------------------
VIEW_PASSWORD = st.secrets.get("VIEW_PASSWORD", "Emc@2026")
TOKEN_SECRET = st.secrets.get("TOKEN_SECRET", None)
TOKEN_TTL_SECONDS = int(st.secrets.get("TOKEN_TTL_SECONDS", 600))


def _b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def verify_url_token(token: str):
    if not TOKEN_SECRET:
        return None
    try:
        body_b64, sig_b64 = token.split(".", 1)
        body = _b64url_decode(body_b64)
        sig = _b64url_decode(sig_b64)
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


_auto_auth()
require_view_access()

# -----------------------------------------------------------------------------
# CSS
# -----------------------------------------------------------------------------
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
.kpi-grid{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:14px;margin-top:10px;margin-bottom:10px;}
.kpi-card{background:rgba(255,255,255,0.85);border:1.5px solid rgba(197,216,245,0.7);border-radius:18px;padding:16px 18px;
box-shadow:0 4px 16px rgba(10,38,71,0.07),0 1px 3px rgba(10,38,71,0.05),inset 0 1px 0 rgba(255,255,255,0.95);}
.kpi-label{font-size:12px;color:#8A9BB5;font-weight:600;letter-spacing:0.6px;text-transform:uppercase;margin-bottom:8px;}
.kpi-value{font-size:clamp(17px,2.1vw,28px);font-weight:800;color:#0D1B2E;letter-spacing:-0.5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.kpi-card.balance{background:linear-gradient(145deg,rgba(10,38,71,0.96) 0%,rgba(15,56,110,0.96) 100%);border-color:rgba(180,210,255,0.25);}
.kpi-card.balance .kpi-label{color:rgba(180,205,255,0.75);}
.kpi-card.balance .kpi-value{color:#FFFFFF;}
@media(max-width:1100px){.kpi-grid{grid-template-columns:repeat(2,minmax(0,1fr));}}
</style>
""", unsafe_allow_html=True)

CENTERS = {
    "excellent": {"key": "excellent", "name": "Excellent Medical Center (MF4777)"},
    "pharmacy": {"key": "pharmacy", "name": "Excellent Pharmacy (PF3205)"},
    "easyhealth": {"key": "easyhealth", "name": "Easy Health Medical Clinic (MF8031)"},
}

# -----------------------------------------------------------------------------
# S3 FOR SUMMARY ONLY
# -----------------------------------------------------------------------------
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


# -----------------------------------------------------------------------------
# UI HELPERS
# -----------------------------------------------------------------------------
def render_kpi_cards(net, paid, bal, rej, acc):
    def fmt(x):
        try:
            return f"{float(x):,.2f}"
        except Exception:
            return "—"

    html = f"""
    <div class="kpi-grid">
      <div class="kpi-card"><div class="kpi-label">Net Amount</div><div class="kpi-value">{fmt(net)}</div></div>
      <div class="kpi-card"><div class="kpi-label">Paid</div><div class="kpi-value">{fmt(paid)}</div></div>
      <div class="kpi-card balance"><div class="kpi-label">Balance</div><div class="kpi-value">{fmt(bal)}</div></div>
      <div class="kpi-card"><div class="kpi-label">Rejected</div><div class="kpi-value">{fmt(rej)}</div></div>
      <div class="kpi-card"><div class="kpi-label">Accepted</div><div class="kpi-value">{fmt(acc)}</div></div>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)


GT_PAT = re.compile(r'^\s*(grand\s*total|total)\s*$', re.I)


def style_summary_table(df: pd.DataFrame):
    if df is None or df.empty:
        return None

    num_cols = df.select_dtypes(include="number").columns.tolist()
    pct_cols = ["Rej. %"]
    fmt_dict = {c: "{:,.2f}" for c in num_cols if c not in pct_cols}
    fmt_dict.update({c: "{:.2f}%" for c in pct_cols if c in df.columns})

    def _style_row(row):
        styles = [""] * len(row)
        if GT_PAT.match(str(row.iloc[0])):
            return ["background-color:#FCE4D6;font-weight:bold"] * len(row)
        if "Rej. %" in row.index:
            try:
                if float(row["Rej. %"]) > 0:
                    idx = list(row.index).index("Rej. %")
                    styles[idx] = "color:#C0392B;font-weight:700"
            except Exception:
                pass
        return styles

    return df.style.apply(_style_row, axis=1).format(fmt_dict)


# -----------------------------------------------------------------------------
# SUMMARY ENGINE
# -----------------------------------------------------------------------------
def _normalize_status(value) -> str:
    s = str(value or "").strip().lower()
    return re.sub(r"\s+", " ", s)


def _classify_final_bucket(status_value: str) -> str:
    s = _normalize_status(status_value)
    if re.match(r"^rejected\s*(?:\(\s*resub\s*-\s*\d+\s*\))?$", s):
        return "Rejected"
    if re.match(r"^rejection accepted\s*(?:\(\s*resub\s*-\s*\d+\s*\))?$", s):
        return "Accepted"
    return "Balance"


def pick_first_existing_column(df: pd.DataFrame, candidates):
    for c in candidates:
        if c in df.columns:
            return c
    return None


def build_rcm_summary(df: pd.DataFrame, group_col: str, label_name: str, month_mode: bool = False) -> pd.DataFrame:
    d = df.copy()

    # Required/fallback columns
    id_col = pick_first_existing_column(d, ["UniqueID", "ID", "ClaimID", "Claim Id", "VisitNo"])
    if not id_col:
        d["_tmp_id"] = range(1, len(d) + 1)
        id_col = "_tmp_id"

    for c in ["SubInsShare", "RemitInsShare", "Resub1RemitInsShare", "Resub2RemitInsShare", "Resub3RemitInsShare", "Difference"]:
        if c not in d.columns:
            d[c] = 0.0
        d[c] = pd.to_numeric(d[c], errors="coerce").fillna(0.0)

    if "Status" not in d.columns:
        d["Status"] = ""

    d["_status_norm"] = d["Status"].apply(_normalize_status)

    # Grouping prep
    if month_mode:
        date_col = pick_first_existing_column(d, ["VisitDate", "SubDate", "SubmissionDate", "ClaimDate"])
        if date_col:
            d[date_col] = pd.to_datetime(d[date_col], errors="coerce", dayfirst=True)
            d = d.dropna(subset=[date_col]).copy()
            d[group_col] = d[date_col].dt.strftime("%b-%y")
        else:
            d[group_col] = "No Date"
    else:
        if group_col not in d.columns:
            d[group_col] = "Not Available"
        d[group_col] = d[group_col].fillna("Not Available").astype(str).str.strip()
        d.loc[d[group_col] == "", group_col] = "Not Available"

    mask_sub_init = d["_status_norm"] == "submitted"
    mask_sub_resub = d["_status_norm"].str.match(r"^submitted\s*\(\s*resub\s*-\s*\d+\s*\)$")
    mask_rej_acc = d["_status_norm"] == "rejection accepted"

    d["_sub_nt_rmtd"] = d["Difference"].where(mask_sub_init, 0.0)
    d["_rsub_nt_rmtd"] = d["Difference"].where(mask_sub_resub, 0.0)
    d["_rej_accepted"] = d["Difference"].where(mask_rej_acc, 0.0)

    agg = d.groupby(group_col, dropna=False, sort=False).agg(
        claim_count=(id_col, "nunique"),
        claimed_amt=("SubInsShare", "sum"),
        remit_ins=("RemitInsShare", "sum"),
        difference=("Difference", "sum"),
        initial_pay=("RemitInsShare", "sum"),
        resb1_pay=("Resub1RemitInsShare", "sum"),
        resb2_pay=("Resub2RemitInsShare", "sum"),
        resb3_pay=("Resub3RemitInsShare", "sum"),
        sub_nt_rmtd=("_sub_nt_rmtd", "sum"),
        rsub_nt_rmtd=("_rsub_nt_rmtd", "sum"),
        rej_accepted=("_rej_accepted", "sum"),
    ).reset_index()

    agg["remited_amt"] = agg["remit_ins"] + agg["difference"]
    agg["total_pay"] = agg["initial_pay"] + agg["resb1_pay"] + agg["resb2_pay"] + agg["resb3_pay"]
    agg["final_rejn"] = (
        agg["claimed_amt"]
        - agg["total_pay"]
        - agg["sub_nt_rmtd"]
        - agg["rsub_nt_rmtd"]
        - agg["rej_accepted"]
    ).clip(lower=0)
    agg["rej_pct"] = (agg["final_rejn"] / agg["claimed_amt"].replace(0, pd.NA) * 100).fillna(0.0)

    out = pd.DataFrame()
    out[label_name] = agg[group_col]
    out["Claim count"] = agg["claim_count"]
    out["Claimd Amount"] = agg["claimed_amt"]
    out["Remited Amt"] = agg["remited_amt"]
    out["Initial pay"] = agg["initial_pay"]
    out["Resb1 pay"] = agg["resb1_pay"]
    out["Resb2 pay"] = agg["resb2_pay"]
    out["Resb3 pay"] = agg["resb3_pay"]
    out["Total pay"] = agg["total_pay"]
    out["Sub Nt Rmtd"] = agg["sub_nt_rmtd"]
    out["Rsub Nt Rmtd"] = agg["rsub_nt_rmtd"]
    if label_name == "Insurance Name":
        out["Rejection Accepted"] = agg["rej_accepted"]
    out["Final Rejn"] = agg["final_rejn"]
    out["Rej. %"] = agg["rej_pct"]

    # Grand total
    gt = {}
    for c in out.columns:
        if c == label_name:
            gt[c] = "Grand Total"
        elif pd.api.types.is_numeric_dtype(out[c]):
            gt[c] = out[c].sum()
        else:
            gt[c] = ""
    claimed = out["Claimd Amount"].sum()
    gt["Rej. %"] = (gt["Final Rejn"] / claimed * 100) if claimed else 0.0
    out = pd.concat([out, pd.DataFrame([gt])], ignore_index=True)

    return out


def run_summary_engine(uploaded_bytes: bytes, filename: str) -> dict:
    buf = io.BytesIO(uploaded_bytes)
    df = pd.read_excel(buf, engine="openpyxl")
    df.columns = df.columns.astype(str).str.strip()

    # Base reconciliation/KPIs
    for col in ["SubInsShare", "RemitInsShare", "Resub1RemitInsShare", "Resub2RemitInsShare", "Resub3RemitInsShare", "Resub4RemitInsShare", "TakeBack"]:
        if col not in df.columns:
            df[col] = 0.0
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

    if "Status" not in df.columns:
        df["Status"] = ""

    df["Net Amount"] = df["SubInsShare"]
    df["Paid"] = df[["RemitInsShare", "Resub1RemitInsShare", "Resub2RemitInsShare", "Resub3RemitInsShare", "Resub4RemitInsShare", "TakeBack"]].sum(axis=1)
    df["Paid"] = df[["Paid", "Net Amount"]].min(axis=1)
    df["Residual"] = (df["Net Amount"] - df["Paid"]).clip(lower=0)

    df["Final Bucket"] = df["Status"].apply(_classify_final_bucket)
    df["Rejected"] = 0.0
    df["Accepted"] = 0.0
    df["Balance"] = 0.0
    df.loc[df["Final Bucket"] == "Rejected", "Rejected"] = df.loc[df["Final Bucket"] == "Rejected", "Residual"]
    df.loc[df["Final Bucket"] == "Accepted", "Accepted"] = df.loc[df["Final Bucket"] == "Accepted", "Residual"]
    df.loc[df["Final Bucket"] == "Balance", "Balance"] = df.loc[df["Final Bucket"] == "Balance", "Residual"]

    df["Recon Total"] = df[["Paid", "Balance", "Rejected", "Accepted"]].sum(axis=1)
    df["Recon Diff"] = (df["Net Amount"] - df["Recon Total"]).round(2)

    # Group columns
    insurance_col = pick_first_existing_column(df, ["Insurance", "PayerName", "Insurer", "Plan"])
    if not insurance_col:
        df["Insurance"] = "Not Available"
        insurance_col = "Insurance"

    doctor_col = pick_first_existing_column(df, ["Doctor Name", "DoctorName", "Doctor", "Provider", "PhysicianName", "DocName"])
    if not doctor_col:
        df["Doctor Name"] = "Not Available"
        doctor_col = "Doctor Name"

    if "Difference" not in df.columns:
        df["Difference"] = 0.0
    df["Difference"] = pd.to_numeric(df["Difference"], errors="coerce").fillna(0.0)

    insurance_summary = build_rcm_summary(df, insurance_col, "Insurance Name", month_mode=False)
    doctor_summary = build_rcm_summary(df, doctor_col, "Doctor Name", month_mode=False)
    month_summary = build_rcm_summary(df, "Month", "Month", month_mode=True)

    kpi_net = float(df["Net Amount"].sum())
    kpi_paid = float(df["Paid"].sum())
    kpi_bal = float(df["Balance"].sum())
    kpi_rej = float(df["Rejected"].sum())
    kpi_acc = float(df["Accepted"].sum())

    return {
        "filename": filename,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "row_count": len(df),
        "recon_diff": float(df["Recon Diff"].sum()),
        "kpi": (kpi_net, kpi_paid, kpi_bal, kpi_rej, kpi_acc),
        "insurance_summary": insurance_summary,
        "doctor_summary": doctor_summary,
        "month_summary": month_summary,
    }


def build_excel_output(result: dict) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import PatternFill, Font, Alignment

    HEADER_FILL = PatternFill(start_color="BDD7EE", end_color="BDD7EE", fill_type="solid")
    TOTAL_FILL = PatternFill(start_color="FCE4D6", end_color="FCE4D6", fill_type="solid")

    def write_sheet(ws, df):
        for ci, col in enumerate(df.columns, 1):
            cell = ws.cell(row=1, column=ci, value=col)
            cell.fill = HEADER_FILL
            cell.font = Font(bold=True)
            cell.alignment = Alignment(horizontal="center", vertical="center")

        for ri, row in df.iterrows():
            for ci, val in enumerate(row, 1):
                cell = ws.cell(row=ri + 2, column=ci, value=val)
                if GT_PAT.match(str(row.iloc[0])):
                    cell.fill = TOTAL_FILL
                    cell.font = Font(bold=True)

    wb = Workbook()
    ws1 = wb.active
    ws1.title = "Insurance"
    write_sheet(ws1, result["insurance_summary"])

    ws2 = wb.create_sheet("Doctor Wise")
    write_sheet(ws2, result["doctor_summary"])

    ws3 = wb.create_sheet("Month Wise")
    write_sheet(ws3, result["month_summary"])

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.read()


# -----------------------------------------------------------------------------
# HEADER
# -----------------------------------------------------------------------------
h1, h2 = st.columns([8, 2])
with h1:
    st.title("📋 Summary Report")
    st.caption("Upload a source file, click process, and view only Insurance / Doctor Wise / Month Wise summaries.")
with h2:
    if st.button("🏠 Back to Dashboard", use_container_width=True, key="sum_back"):
        st.switch_page("exclusive_dashboard.py")

st.markdown("---")

SUM_CENTER_KEY = "sum_center_key"
RESULT_KEY_PREFIX = "sum_result_"

ck = st.session_state.get(SUM_CENTER_KEY)

if ck not in CENTERS:
    st.subheader("Choose a center")
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

center_cfg = CENTERS[ck]
RESULT_KEY = f"{RESULT_KEY_PREFIX}{ck}"

st.markdown(
    f"""
    <div style="background:#F5FAFF;border:1.5px solid #CFE3FF;padding:14px 18px;border-radius:16px;
    margin-bottom:10px;box-shadow:0 6px 18px rgba(11,45,92,0.08);">
      <div style="font-size:24px;font-weight:900;color:#0B2D5C;">{center_cfg['name']}</div>
      <div style="font-size:13px;color:#334155;margin-top:2px;font-weight:600;">Only 3 summaries: Insurance, Doctor Wise, Month Wise</div>
    </div>
    """,
    unsafe_allow_html=True,
)

if st.button("◀ Choose another center", key="sum_back_center"):
    st.session_state[SUM_CENTER_KEY] = None
    st.session_state.pop(RESULT_KEY, None)
    st.rerun()

st.markdown("---")

uploaded = st.file_uploader(
    f"Upload source Excel for **{center_cfg['name']}** (.xlsx)",
    type=["xlsx"],
    key=f"sum_uploader_{ck}",
)

if uploaded is not None:
    st.success(f"File uploaded: {uploaded.name}")
    st.warning("After uploading, click **Process Summary Report**.")
    if st.button("🚀 Process Summary Report", type="primary", use_container_width=True, key=f"process_{ck}"):
        with st.spinner("Processing summary report..."):
            try:
                file_bytes = uploaded.getvalue()

                source_s3_key = build_summary_s3_key(center_cfg["key"], uploaded.name)
                ok_src, err_src = upload_bytes_to_s3(
                    file_bytes,
                    source_s3_key,
                    content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )

                result = run_summary_engine(file_bytes, uploaded.name)
                result["source_s3_saved"] = ok_src
                result["source_s3_key"] = source_s3_key if ok_src else ""
                result["source_s3_error"] = err_src or ""
                st.session_state[RESULT_KEY] = result
                st.success("Summary Report Generated")
            except Exception as e:
                st.error(f"Processing failed: {e}")
                st.session_state.pop(RESULT_KEY, None)

result = st.session_state.get(RESULT_KEY)

if result:
    st.markdown("---")
    st.success(f"✅ Processed **{result['filename']}** — {result['row_count']:,} rows · Generated at {result['generated_at']}")

    recon = result["recon_diff"]
    if abs(recon) > 0.01:
        st.warning(f"⚠️ Recon Diff: {recon:,.2f}")
    else:
        st.info("✅ Reconciliation check passed.")

    net, paid, bal, rej, acc = result["kpi"]
    render_kpi_cards(net, paid, bal, rej, acc)

    excel_bytes = build_excel_output(result)
    dl_name = f"{center_cfg['key']}_rcm_summary_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"

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
        "⬇️ Download RCM Summary Excel",
        data=excel_bytes,
        file_name=dl_name,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
        key=f"sum_dl_{ck}",
    )

    st.markdown("---")

    tab1, tab2, tab3 = st.tabs(["📊 Insurance", "👨‍⚕️ Doctor Wise", "📅 Month Wise"])

    with tab1:
        st.subheader("by Insurance")
        styled = style_summary_table(result["insurance_summary"])
        st.dataframe(styled, use_container_width=True, hide_index=True, key="ins_sum")

    with tab2:
        st.subheader("by Doctor")
        styled = style_summary_table(result["doctor_summary"])
        st.dataframe(styled, use_container_width=True, hide_index=True, key="doc_sum")

    with tab3:
        st.subheader("by Month")
        styled = style_summary_table(result["month_summary"])
        st.dataframe(styled, use_container_width=True, hide_index=True, key="month_sum")
else:
    st.info("👆 Upload a source Excel file above, then click Process Summary Report.")
