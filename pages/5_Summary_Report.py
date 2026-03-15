#!/usr/bin/env python3
# pages/5_Summary_Report.py
# Summary Report — upload source -> process in-memory -> display + save to S3

# =============================================================================
# STEP 1: Install missing packages BEFORE any other imports that need them
# =============================================================================
import subprocess, sys
for _pkg in ["openpyxl", "boto3"]:
    try:
        __import__(_pkg)
    except ImportError:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", _pkg, "-q"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )

# =============================================================================
# STEP 2: Standard imports (openpyxl & boto3 now guaranteed)
# =============================================================================
import io, re, hmac, hashlib, base64, json, time
from datetime import datetime

import pandas as pd
import streamlit as st
import boto3
from botocore.exceptions import ClientError
from openpyxl import Workbook
from openpyxl.styles import PatternFill, Font, Alignment

# =============================================================================
# PAGE CONFIG
# =============================================================================
st.set_page_config(page_title="Summary Report - Excellent Medical Group", layout="wide")
st.set_option("client.showErrorDetails", False)

# =============================================================================
# S3 CONFIG
# =============================================================================
S3_BUCKET = "emc-rcm-storage-2026"
S3_PREFIX = "streamlit2"


def _s3_client():
    return boto3.client(
        "s3",
        aws_access_key_id=st.secrets.get("AWS_ACCESS_KEY_ID", ""),
        aws_secret_access_key=st.secrets.get("AWS_SECRET_ACCESS_KEY", ""),
        region_name=(
            st.secrets.get("AWS_REGION")
            or st.secrets.get("AWS_DEFAULT_REGION")
            or "eu-north-1"
        ),
    )


def s3_key(center_key: str, filename: str) -> str:
    return f"{S3_PREFIX}/{center_key}/{filename}"


def s3_upload(data: bytes, center_key: str, filename: str) -> str:
    try:
        key = s3_key(center_key, filename)
        _s3_client().put_object(Bucket=S3_BUCKET, Key=key, Body=data)
        return f"s3://{S3_BUCKET}/{key}"
    except Exception as e:
        return f"ERROR: {e}"


def s3_download(center_key: str, filename: str):
    try:
        key = s3_key(center_key, filename)
        obj = _s3_client().get_object(Bucket=S3_BUCKET, Key=key)
        return obj["Body"].read()
    except ClientError as e:
        if e.response["Error"]["Code"] in ("NoSuchKey", "404"):
            return None
        raise


def s3_list_reports(center_key: str):
    try:
        prefix = f"{S3_PREFIX}/{center_key}/"
        resp = _s3_client().list_objects_v2(Bucket=S3_BUCKET, Prefix=prefix)
        return [
            obj["Key"].replace(prefix, "")
            for obj in resp.get("Contents", [])
            if obj["Key"].endswith(".xlsx") and "summary_report" in obj["Key"]
        ]
    except Exception:
        return []


# =============================================================================
# AUTH
# =============================================================================
VIEW_PASSWORD = st.secrets.get("VIEW_PASSWORD", "Emc@2026")
TOKEN_SECRET = st.secrets.get("TOKEN_SECRET", None)
TOKEN_TTL_SECONDS = int(st.secrets.get("TOKEN_TTL_SECONDS", 600))


def _b64url_decode(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _auto_auth():
    tok = st.query_params.get("token")
    if tok and TOKEN_SECRET:
        try:
            body_b64, sig_b64 = tok.split(".", 1)
            body = _b64url_decode(body_b64)
            sig = _b64url_decode(sig_b64)
            exp = hmac.new(TOKEN_SECRET.encode(), body, hashlib.sha256).digest()
            if hmac.compare_digest(sig, exp):
                d = json.loads(body)
                if int(time.time()) - int(d.get("iat", 0)) <= TOKEN_TTL_SECONDS:
                    st.session_state.is_view_auth = True
        except Exception:
            pass
    auth = st.query_params.get("auth")
    if auth:
        _sec = st.secrets.get("TOKEN_SECRET", VIEW_PASSWORD)
        if auth == hmac.new(_sec.encode(), b"view_auth", hashlib.sha256).hexdigest()[:16]:
            st.session_state.is_view_auth = True


_auto_auth()


def require_view_access():
    if st.session_state.get("is_view_auth"):
        return
    st.title("Dashboard Access")
    pwd = st.text_input("View Password", type="password", key="sum_view_pwd")
    if st.button("Enter Dashboard", use_container_width=True):
        if pwd == VIEW_PASSWORD:
            st.session_state.is_view_auth = True
            st.rerun()
        else:
            st.error("Incorrect password.")
    st.stop()


require_view_access()

# =============================================================================
# CSS
# =============================================================================
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap');
.stApp{background:linear-gradient(145deg,#EDF2FB 0%,#F8FAFF 40%,#FAFCFF 100%)!important;font-family:'Inter',sans-serif!important;}
hr{border:none!important;height:1px!important;background:linear-gradient(90deg,transparent,#C8D9F0,transparent)!important;}
div.stButton>button{width:100%!important;min-height:50px!important;padding:12px 20px!important;font-size:15px!important;font-weight:700!important;font-family:'Inter',sans-serif!important;background:linear-gradient(160deg,#FFFFFF 0%,#EEF4FF 100%)!important;color:#0A2647!important;border:1.5px solid #C5D8F5!important;border-radius:14px!important;box-shadow:0 2px 8px rgba(10,38,71,0.08),inset 0 1px 0 rgba(255,255,255,0.9)!important;transition:all 0.2s ease!important;}
div.stButton>button:hover{background:linear-gradient(160deg,#E8F1FF 0%,#D6E8FF 100%)!important;border-color:#7DAAEE!important;transform:translateY(-1px)!important;}
div.stButton>button:active{background:linear-gradient(160deg,#0A2647 0%,#154B8A 100%)!important;color:#fff!important;}
.kpi-grid{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:14px;margin-top:10px;margin-bottom:10px;}
.kpi-card{background:rgba(255,255,255,0.85);backdrop-filter:blur(12px);border:1.5px solid rgba(197,216,245,0.7);border-radius:18px;padding:16px 18px;box-shadow:0 4px 16px rgba(10,38,71,0.07),inset 0 1px 0 rgba(255,255,255,0.95);min-width:0;}
.kpi-label{font-size:12px;color:#8A9BB5;font-weight:600;letter-spacing:0.6px;text-transform:uppercase;margin-bottom:8px;}
.kpi-value{font-size:clamp(17px,2.1vw,28px);font-weight:800;color:#0D1B2E;letter-spacing:-0.5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.kpi-card.balance{background:linear-gradient(145deg,rgba(10,38,71,0.96) 0%,rgba(15,56,110,0.96) 100%);border-color:rgba(180,210,255,0.25);}
.kpi-card.balance .kpi-label{color:rgba(180,205,255,0.75);}
.kpi-card.balance .kpi-value{color:#FFFFFF;}
@media(max-width:1100px){.kpi-grid{grid-template-columns:repeat(2,minmax(0,1fr));}}
</style>
""", unsafe_allow_html=True)

# =============================================================================
# CENTERS
# =============================================================================
CENTERS = {
    "excellent":  {"key": "excellent",  "name": "Excellent Medical Center (MF4777)"},
    "pharmacy":   {"key": "pharmacy",   "name": "Excellent Pharmacy (PF3205)"},
    "easyhealth": {"key": "easyhealth", "name": "Easy Health Medical Clinic (MF8031)"},
}

# =============================================================================
# HEADER
# =============================================================================
h1, h2 = st.columns([8, 2])
with h1:
    st.title("Summary Report")
    st.caption(f"Files saved to  s3://{S3_BUCKET}/{S3_PREFIX}/<center>/")
with h2:
    if st.button("Back to Dashboard", use_container_width=True, key="sum_back"):
        st.switch_page("exclusive_dashboard.py")

st.markdown("---")

# =============================================================================
# KPI CARDS
# =============================================================================
def render_kpi_cards(net, paid, bal, rej, acc):
    def fmt(x):
        try:
            return f"{float(x):,.2f}"
        except Exception:
            return "0.00"
    st.markdown(f"""
    <div class="kpi-grid">
      <div class="kpi-card"><div class="kpi-label">Net Amount</div><div class="kpi-value">{fmt(net)}</div></div>
      <div class="kpi-card"><div class="kpi-label">Paid</div><div class="kpi-value">{fmt(paid)}</div></div>
      <div class="kpi-card balance"><div class="kpi-label">Balance</div><div class="kpi-value">{fmt(bal)}</div></div>
      <div class="kpi-card"><div class="kpi-label">Rejected</div><div class="kpi-value">{fmt(rej)}</div></div>
      <div class="kpi-card"><div class="kpi-label">Accepted</div><div class="kpi-value">{fmt(acc)}</div></div>
    </div>""", unsafe_allow_html=True)


# =============================================================================
# SUMMARY ENGINE  (exclusive_report_status_final.py logic inline)
# =============================================================================
MAX_RESUB = 10
GT_PAT = re.compile(r'^\s*(grand\s*total|total)\s*$', re.I)
AGE_LABELS = ["0-30 Days", "31-45 Days", "46-60 Days", "61-90 Days", ">90 Days"]


def _norm(v):
    return re.sub(r"\s+", " ", str(v or "").strip().lower())


def _stage_info(status):
    s = _norm(status)
    m = re.match(r"^(submitted|not submitted|approved)\s*(?:\(\s*resub\s*-\s*(\d+)\s*\))?$", s)
    if not m:
        return "Other", "Other", None
    base = m.group(1)
    n = int(m.group(2)) if m.group(2) else 0
    lbl = {"submitted": "Submitted", "not submitted": "Not Submitted", "approved": "Approved"}[base]
    return lbl, ("Initial" if n == 0 else f"Resub-{n}"), n


def _final_bucket(status):
    s = _norm(status)
    if re.match(r"^rejected\s*(?:\(\s*resub\s*-\s*\d+\s*\))?$", s):
        return "Rejected"
    if re.match(r"^rejection accepted\s*(?:\(\s*resub\s*-\s*\d+\s*\))?$", s):
        return "Accepted"
    return "Balance"


def _stage_date(row, cols):
    if row.get("Balance Status Group") == "Not Submitted":
        return pd.NaT
    sn = row.get("Balance Submission No")
    cands = ([] if sn is None or pd.isna(sn)
             else (["SubDate"] if int(sn) == 0 else [f"Resub{int(sn)}Date"]))
    cands += ["SubDate", "SubmissionDate", "ClaimDate", "VisitDate"]
    for c in cands:
        if c in cols and pd.notna(row.get(c)):
            return row[c]
    return pd.NaT


def _add_gt(df, key):
    if df.empty:
        return df
    nums = df.select_dtypes(include="number").columns.tolist()
    row = {c: (df[c].sum() if c in nums else "") for c in df.columns}
    row[key] = "Grand Total"
    return pd.concat([df, pd.DataFrame([row])], ignore_index=True)


def run_engine(raw_bytes: bytes, filename: str) -> dict:
    buf = io.BytesIO(raw_bytes)
    df = pd.read_excel(buf, engine="openpyxl")
    df.columns = df.columns.astype(str).str.strip()

    num_src = ["SubInsShare", "RemitInsShare", "Resub1RemitInsShare",
               "Resub2RemitInsShare", "Resub3RemitInsShare", "Resub4RemitInsShare", "TakeBack"]
    for c in num_src:
        if c not in df.columns:
            df[c] = 0
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)

    if "Status" not in df.columns:
        df["Status"] = ""

    df["Net Amount"] = df["SubInsShare"]
    df["Paid"] = df[num_src[1:]].sum(axis=1).clip(upper=df["SubInsShare"])
    df["Residual"] = (df["Net Amount"] - df["Paid"]).clip(lower=0)
    df["Rejected"] = df["Accepted"] = df["Balance"] = 0.0
    df["Final Bucket"] = df["Status"].apply(_final_bucket)

    for col, bkt in [("Rejected", "Rejected"), ("Accepted", "Accepted"), ("Balance", "Balance")]:
        m = df["Final Bucket"] == bkt
        df.loc[m, col] = df.loc[m, "Residual"]

    df["Recon Total"] = df[["Paid", "Balance", "Rejected", "Accepted"]].sum(axis=1)
    df["Recon Diff"] = (df["Net Amount"] - df["Recon Total"]).round(2)

    si = df["Status"].apply(_stage_info)
    df["Balance Status Group"] = si.apply(lambda x: x[0])
    df["Balance Submission Stage"] = si.apply(lambda x: x[1])
    df["Balance Submission No"] = si.apply(lambda x: x[2])
    mask_bal = df["Final Bucket"] == "Balance"
    df.loc[~mask_bal, ["Balance Status Group", "Balance Submission Stage", "Balance Submission No"]] = ["", "", None]

    bdefs = [("Submitted", 0, "Initial Submitted Balance"),
             ("Approved", 0, "Initial Approved Balance"),
             ("Not Submitted", 0, "Initial Not Submitted Balance")]
    for n in range(1, MAX_RESUB + 1):
        bdefs += [("Submitted", n, f"Resub{n} Submitted Balance"),
                  ("Approved", n, f"Resub{n} Approved Balance"),
                  ("Not Submitted", n, f"Resub{n} Not Submitted Balance")]
    for _, _, c in bdefs:
        df[c] = 0.0
    for grp, sn, c in bdefs:
        m = (mask_bal & (df["Balance Status Group"] == grp)
             & (df["Balance Submission No"].fillna(-999).astype(int) == sn))
        df.loc[m, c] = df.loc[m, "Balance"]

    dcols = ["SubDate"] + [f"Resub{i}Date" for i in range(1, 11)] + ["SubmissionDate", "ClaimDate", "VisitDate"]
    for c in [x for x in dcols if x in df.columns]:
        df[c] = pd.to_datetime(df[c], errors="coerce", dayfirst=True)
    cols_list = list(df.columns)
    df["Balance RefDate"] = df.apply(lambda r: _stage_date(r, cols_list), axis=1)
    today = pd.Timestamp(datetime.today().date())
    df["DaysDiff"] = (today - df["Balance RefDate"]).dt.days
    df["AgingBucket"] = pd.cut(df["DaysDiff"], bins=[-1, 30, 45, 60, 90, float("inf")], labels=AGE_LABELS)

    ins = next((c for c in ["Insurance", "PayerName", "Insurer", "Plan"] if c in df.columns), None)
    if ins is None:
        df["Insurance"] = "Not Available"
    elif ins != "Insurance":
        df["Insurance"] = df[ins]
    df["Insurance"] = df["Insurance"].fillna("Not Available")

    BASE = ["Net Amount", "Paid", "Balance", "Rejected", "Accepted", "Recon Diff"]
    ins_totals = _add_gt(df.groupby("Insurance", dropna=False)[BASE].sum().reset_index(), "Insurance")
    fb_summary = _add_gt(df.groupby("Final Bucket", dropna=False)[BASE[:5]].sum().reset_index(), "Final Bucket")

    dc = next((c for c in ["VisitDate", "SubDate", "SubmissionDate", "ClaimDate"] if c in df.columns), None)
    monthly = pd.DataFrame()
    if dc:
        tmp = df.copy()
        tmp[dc] = pd.to_datetime(tmp[dc], errors="coerce", dayfirst=True)
        tmp = tmp.dropna(subset=[dc])
        if not tmp.empty:
            tmp["Month"] = tmp[dc].dt.to_period("M").dt.strftime("%B %Y")
            monthly = _add_gt(tmp.groupby("Month", observed=True)[BASE].sum().reset_index(), "Month")

    bdf = df[(df["Balance"] > 0) & df["AgingBucket"].notna()].copy()
    if not bdf.empty:
        ap = pd.pivot_table(bdf, index="Insurance", columns="AgingBucket",
                            values="Balance", aggfunc="sum", fill_value=0, observed=False
                            ).reindex(columns=AGE_LABELS, fill_value=0)
        ap["Grand Total"] = ap.sum(axis=1)
        aging = _add_gt(ap.reset_index(), "Insurance")
    else:
        aging = pd.DataFrame(columns=["Insurance"] + AGE_LABELS + ["Grand Total"])

    bss_df = df[df["Balance"] > 0].copy()
    if not bss_df.empty:
        bss = bss_df.groupby(["Balance Status Group", "Balance Submission Stage"],
                              dropna=False)["Balance"].sum().reset_index()
        bss = bss.sort_values(["Balance Status Group", "Balance Submission Stage"])
        bss = pd.concat([bss, pd.DataFrame([{
            "Balance Status Group": "Grand Total",
            "Balance Submission Stage": "",
            "Balance": bss["Balance"].sum()
        }])], ignore_index=True)
    else:
        bss = pd.DataFrame(columns=["Balance Status Group", "Balance Submission Stage", "Balance"])

    kdf = ins_totals[~ins_totals["Insurance"].astype(str).str.match(GT_PAT)]
    kpis = tuple(float(pd.to_numeric(kdf.get(c, pd.Series([0])), errors="coerce").sum())
                 for c in ["Net Amount", "Paid", "Balance", "Rejected", "Accepted"])

    return {
        "df": df, "ins_totals": ins_totals, "fb_summary": fb_summary,
        "monthly": monthly, "aging": aging, "bss": bss,
        "kpi": kpis, "recon_diff": float(df["Recon Diff"].sum()),
        "row_count": len(df), "filename": filename,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


# =============================================================================
# EXCEL BUILDER
# =============================================================================
HEADER_FILL = PatternFill(start_color="BDD7EE", end_color="BDD7EE", fill_type="solid")
TOTAL_FILL = PatternFill(start_color="FCE4D6", end_color="FCE4D6", fill_type="solid")


def _write_ws(ws, df):
    for ci, col in enumerate(df.columns, 1):
        c = ws.cell(row=1, column=ci, value=col)
        c.fill = HEADER_FILL
        c.font = Font(bold=True)
        c.alignment = Alignment(horizontal="center", vertical="center")
    for ri, row in enumerate(df.itertuples(index=False), 2):
        is_gt = bool(GT_PAT.match(str(row[0])))
        for ci, val in enumerate(row, 1):
            c = ws.cell(row=ri, column=ci, value=val)
            if is_gt:
                c.fill = TOTAL_FILL
                c.font = Font(bold=True)


def build_excel(result: dict) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Insurance_Totals"
    _write_ws(ws, result["ins_totals"])

    ws = wb.create_sheet("Final_Bucket_Summary")
    _write_ws(ws, result["fb_summary"])

    if result["monthly"] is not None and not result["monthly"].empty:
        ws = wb.create_sheet("Monthly_Totals")
        _write_ws(ws, result["monthly"])

    ws = wb.create_sheet("Balance_Aging_Summary")
    _write_ws(ws, result["aging"])

    ws = wb.create_sheet("Balance_Status_Stage")
    _write_ws(ws, result["bss"])

    bd = result["df"][result["df"]["Balance"] > 0].copy()
    ws = wb.create_sheet("Balance_Detail")
    _write_ws(ws, bd)

    ws = wb.create_sheet("Meta")
    for ri, (k, v) in enumerate([
        ("InputFile",   result["filename"]),
        ("GeneratedAt", result["generated_at"]),
        ("TotalRows",   result["row_count"]),
        ("ReconDiff",   result["recon_diff"]),
        ("S3Bucket",    S3_BUCKET),
        ("S3Prefix",    S3_PREFIX),
    ], 1):
        ws.cell(row=ri, column=1, value=k).font = Font(bold=True)
        ws.cell(row=ri, column=2, value=v)

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.read()


# =============================================================================
# TABLE DISPLAY
# =============================================================================
def show_table(df, key):
    if df is None or df.empty:
        st.info("No data.")
        return
    first = df.columns[0]
    mask = df[first].astype(str).str.match(GT_PAT)
    df = pd.concat([df[~mask], df[mask]], ignore_index=True)
    nums = df.select_dtypes(include="number").columns.tolist()
    styled = df.style.apply(
        lambda row: [
            "background-color:#FCE4D6;font-weight:bold"
            if GT_PAT.match(str(row.iloc[0])) else "" for _ in row
        ], axis=1
    ).format({c: "{:,.2f}" for c in nums})
    st.dataframe(styled, use_container_width=True, hide_index=True, key=key)


# =============================================================================
# CENTER SELECTION
# =============================================================================
SUM_CK = "sum_center_key"
ck = st.session_state.get(SUM_CK)

if ck not in CENTERS:
    st.subheader("Choose a center")
    c1, c2, c3 = st.columns(3)
    for col, ckey in zip([c1, c2, c3], ["excellent", "pharmacy", "easyhealth"]):
        with col:
            if st.container(border=True).button(
                CENTERS[ckey]["name"], use_container_width=True, key=f"sum_{ckey}"
            ):
                st.session_state[SUM_CK] = ckey
                st.rerun()
    st.stop()

# =============================================================================
# CENTER DETAIL
# =============================================================================
ccfg = CENTERS[ck]

st.markdown(f"""
<div style="background:#F5FAFF;border:1.5px solid #CFE3FF;padding:14px 18px;border-radius:16px;
            margin-bottom:10px;box-shadow:0 6px 18px rgba(11,45,92,0.08);">
  <div style="font-size:24px;font-weight:900;color:#0B2D5C;">{ccfg['name']}</div>
  <div style="font-size:12px;color:#334155;margin-top:4px;">
    S3: <code>s3://{S3_BUCKET}/{S3_PREFIX}/{ck}/</code>
  </div>
</div>""", unsafe_allow_html=True)

if st.button("Choose another center", key="sum_back_center"):
    st.session_state[SUM_CK] = None
    st.rerun()

st.markdown("---")

# =============================================================================
# UPLOAD + PROCESS + SAVE TO S3
# =============================================================================
RESULT_KEY = f"sum_result_{ck}"

up = st.file_uploader(
    f"Upload source Excel for **{ccfg['name']}** (.xlsx)",
    type=["xlsx"],
    key=f"sum_up_{ck}",
    help="Upload raw claims source file. Results are processed instantly and saved to S3.",
)

if up is not None:
    with st.spinner("Processing file — please wait..."):
        try:
            raw = up.read()

            # Save raw source to S3
            src_uri = s3_upload(raw, ck, f"source_{up.name}")

            # Run engine
            result = run_engine(raw, up.name)

            # Build Excel and save report to S3
            xl_bytes = build_excel(result)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            rpt_name = f"summary_report_{ck}_{ts}.xlsx"
            rpt_uri = s3_upload(xl_bytes, ck, rpt_name)

            result["s3_source_uri"] = src_uri
            result["s3_report_uri"] = rpt_uri
            result["s3_report_name"] = rpt_name
            result["xl_bytes"] = xl_bytes

            st.session_state[RESULT_KEY] = result

        except Exception as e:
            st.error(f"Processing failed: {e}")
            st.session_state.pop(RESULT_KEY, None)

# =============================================================================
# LOAD PREVIOUS REPORT FROM S3
# =============================================================================
with st.expander("Load a previously saved report from S3", expanded=False):
    saved = s3_list_reports(ck)
    if saved:
        chosen = st.selectbox("Select saved report", sorted(saved, reverse=True), key=f"s3_pick_{ck}")
        if st.button("Load from S3", key=f"s3_load_{ck}", use_container_width=True):
            with st.spinner("Downloading from S3..."):
                try:
                    xl_data = s3_download(ck, chosen)
                    if xl_data:
                        xls = pd.ExcelFile(io.BytesIO(xl_data), engine="openpyxl")

                        def _read(sheet):
                            try:
                                return pd.read_excel(xls, sheet_name=sheet)
                            except Exception:
                                return pd.DataFrame()

                        loaded = {
                            "filename": chosen,
                            "generated_at": "loaded from S3",
                            "row_count": "—",
                            "recon_diff": 0.0,
                            "ins_totals": _read("Insurance_Totals"),
                            "fb_summary": _read("Final_Bucket_Summary"),
                            "monthly":    _read("Monthly_Totals"),
                            "aging":      _read("Balance_Aging_Summary"),
                            "bss":        _read("Balance_Status_Stage"),
                            "kpi":        (0, 0, 0, 0, 0),
                            "xl_bytes":   xl_data,
                            "s3_report_uri": f"s3://{S3_BUCKET}/{s3_key(ck, chosen)}",
                            "s3_report_name": chosen,
                        }
                        # Recompute KPIs from ins_totals
                        it = loaded["ins_totals"]
                        if not it.empty:
                            kdf = it[~it.iloc[:, 0].astype(str).str.match(GT_PAT)]
                            loaded["kpi"] = tuple(
                                float(pd.to_numeric(kdf[c], errors="coerce").sum())
                                for c in ["Net Amount", "Paid", "Balance", "Rejected", "Accepted"]
                                if c in kdf.columns
                            )
                            if len(loaded["kpi"]) < 5:
                                loaded["kpi"] = loaded["kpi"] + (0,) * (5 - len(loaded["kpi"]))
                        st.session_state[RESULT_KEY] = loaded
                        st.rerun()
                    else:
                        st.error("File not found in S3.")
                except Exception as e:
                    st.error(f"S3 load failed: {e}")
    else:
        st.info("No saved reports found for this center in S3.")

# =============================================================================
# DISPLAY RESULTS
# =============================================================================
result = st.session_state.get(RESULT_KEY)

if result:
    st.success(
        f"**{result['filename']}** | {result['row_count']} rows | {result['generated_at']}"
    )

    if result.get("s3_source_uri") and not result["s3_source_uri"].startswith("ERROR"):
        st.info(f"Source saved to S3: `{result['s3_source_uri']}`")
    if result.get("s3_report_uri") and not result["s3_report_uri"].startswith("ERROR"):
        st.info(f"Report saved to S3: `{result['s3_report_uri']}`")

    if abs(result.get("recon_diff", 0)) > 0.01:
        st.warning(f"Recon Diff: {result['recon_diff']:,.2f}")
    else:
        st.success("Reconciliation check passed.")

    render_kpi_cards(*result["kpi"])
    st.markdown("---")

    st.download_button(
        "Download Full Summary Report (Excel)",
        data=result["xl_bytes"],
        file_name=result.get("s3_report_name", f"{ck}_summary.xlsx"),
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
        key=f"sum_dl_{ck}",
    )
    st.markdown("---")

    tabs = st.tabs([
        "Insurance Totals", "Final Bucket", "Monthly", "Balance Aging", "Status x Stage"
    ])
    with tabs[0]:
        st.subheader("Insurance Totals")
        show_table(result["ins_totals"], f"t0_{ck}")
    with tabs[1]:
        st.subheader("Final Bucket Summary")
        show_table(result["fb_summary"], f"t1_{ck}")
    with tabs[2]:
        st.subheader("Monthly Totals")
        m = result.get("monthly")
        if m is not None and not m.empty:
            show_table(m, f"t2_{ck}")
        else:
            st.info("No monthly data — date column not found in source.")
    with tabs[3]:
        st.subheader("Balance Aging (by Insurance)")
        show_table(result["aging"], f"t3_{ck}")
    with tabs[4]:
        st.subheader("Balance Status x Stage")
        show_table(result["bss"], f"t4_{ck}")

else:
    st.info("Upload a source Excel file above to generate the summary report.")
