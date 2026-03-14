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

    return {
        "df":           df,
        "ins_totals":   ins_totals,
        "fb_summary":   fb_summary,
        "monthly":      monthly,
        "aging_summary":aging_summary,
        "bss":          bss,
        "kpi":          (kpi_net, kpi_paid, kpi_bal, kpi_rej, kpi_acc),
        "recon_diff":   recon_diff_total,
        "row_count":    len(df),
        "filename":     filename,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def build_excel_output(result: dict) -> bytes:
    """Build a styled Excel workbook from results (same styling as exclusive_report_status_final.py)."""
    from openpyxl import Workbook
    from openpyxl.styles import PatternFill, Font, Alignment

    HEADER_FILL = PatternFill(start_color="BDD7EE", end_color="BDD7EE", fill_type="solid")
    TOTAL_FILL  = PatternFill(start_color="FCE4D6", end_color="FCE4D6", fill_type="solid")

    def _write_sheet(ws, df):
        # Header row
        for ci, col in enumerate(df.columns, 1):
            cell = ws.cell(row=1, column=ci, value=col)
            cell.fill = HEADER_FILL
            cell.font = Font(bold=True)
            cell.alignment = Alignment(horizontal="center", vertical="center")
        # Data rows
        for ri, row in df.iterrows():
            for ci, val in enumerate(row, 1):
                cell = ws.cell(row=ri + 2, column=ci, value=val)
                if str(row.iloc[0]) == "Grand Total":
                    cell.fill = TOTAL_FILL
                    cell.font = Font(bold=True)

    wb = Workbook()
    ws_ins = wb.active
    ws_ins.title = "Insurance_Totals"
    _write_sheet(ws_ins, result["ins_totals"])

    ws_fb = wb.create_sheet("Final_Bucket_Summary")
    _write_sheet(ws_fb, result["fb_summary"])

    if result["monthly"] is not None and not result["monthly"].empty:
        ws_m = wb.create_sheet("Monthly_Totals")
        _write_sheet(ws_m, result["monthly"])

    ws_age = wb.create_sheet("Balance_Aging_Summary")
    _write_sheet(ws_age, result["aging_summary"])

    ws_bss = wb.create_sheet("Balance_Status_Stage_Summary")
    _write_sheet(ws_bss, result["bss"])

    ws_det = wb.create_sheet("Balance_Detail")
    balance_detail = result["df"][result["df"]["Balance"] > 0].copy()
    _write_sheet(ws_det, balance_detail)

    ws_meta = wb.create_sheet("Meta")
    meta_data = [
        ("InputFile",     result["filename"]),
        ("GeneratedAt",   result["generated_at"]),
        ("TotalRows",     result["row_count"]),
        ("ReconDiffTotal",result["recon_diff"]),
    ]
    for ri, (k, v) in enumerate(meta_data, 1):
        ws_meta.cell(row=ri, column=1, value=k).font = Font(bold=True)
        ws_meta.cell(row=ri, column=2, value=v)

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

if up is not None:
    with st.spinner("⚙️ Processing file — please wait..."):
        try:
            file_bytes = up.read()
            result = run_summary_engine(file_bytes, up.name)
            st.session_state[RESULT_KEY] = result
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
    st.download_button(
        "⬇️ Download Full Summary Report (Excel)",
        data=excel_bytes,
        file_name=dl_name,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
        key=f"sum_dl_{ck}",
    )

    st.markdown("---")

    # Tabs for each summary table
    tabs = st.tabs([
        "📊 Insurance Totals",
        "🪣 Final Bucket",
        "📅 Monthly Totals",
        "⏳ Balance Aging",
        "🔀 Status × Stage",
    ])

    with tabs[0]:
        st.subheader("Insurance Totals")
        show_table(result["ins_totals"], key="sum_ins")

    with tabs[1]:
        st.subheader("Final Bucket Summary")
        show_table(result["fb_summary"], key="sum_fb")

    with tabs[2]:
        st.subheader("Monthly Totals")
        if result["monthly"] is not None and not result["monthly"].empty:
            show_table(result["monthly"], key="sum_monthly")
        else:
            st.info("No monthly data — date column (VisitDate / SubDate / SubmissionDate / ClaimDate) not found in source.")

    with tabs[3]:
        st.subheader("Balance Aging Summary (by Insurance)")
        show_table(result["aging_summary"], key="sum_aging")

    with tabs[4]:
        st.subheader("Balance Status × Submission Stage")
        show_table(result["bss"], key="sum_bss")

else:
    st.info("👆 Upload a source Excel file above to generate the summary report.")
