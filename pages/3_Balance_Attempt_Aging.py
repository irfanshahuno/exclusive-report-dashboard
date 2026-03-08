#!/usr/bin/env python3
import io
import re
from pathlib import Path
from datetime import datetime as dt

import pandas as pd
import streamlit as st

# ✅ NEEDFUL (S3 fallback)
import boto3
from botocore.exceptions import ClientError

# =========================================================
# ✅ NEEDFUL: View password gate that respects main dashboard session
# - If user already authenticated in main dashboard (is_view_auth=True), skip.
# - If balance page opened directly, ask password.
# =========================================================
VIEW_PASSWORD = st.secrets.get("VIEW_PASSWORD", "Emc@2026")


def require_view_access_balance():
    if st.session_state.get("is_view_auth", False):
        return

    st.set_page_config(page_title="Balance — Access", layout="wide")
    st.set_option("client.showErrorDetails", False)

    st.title("🔒 Dashboard Access")
    st.info("Enter the view password to open the balance page.")

    pwd = st.text_input("View Password", type="password", key="balance_view_pwd")
    if st.button("Enter", use_container_width=True, key="balance_view_btn"):
        if pwd == VIEW_PASSWORD:
            st.session_state.is_view_auth = True
            st.rerun()
        else:
            st.error("Incorrect password.")

    st.stop()


require_view_access_balance()

# =========================================================
# Settings
# =========================================================
st.set_page_config(page_title="Balance — Initial / Resub with Aging", layout="wide")
st.title("Balance — Initial / Resub with Aging (Summary)")

# ✅ NEEDFUL CHANGE ONLY:
# If this file is inside /pages, store data at repo root /data (not /pages/data)
THIS_FILE = Path(__file__).resolve()
BASE = THIS_FILE.parents[1] if THIS_FILE.parent.name == "pages" else THIS_FILE.parent

DATA_DIR = BASE / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

YEARS = [2024, 2025, 2026]

CENTERS = {
    "easyhealth": "Easy Health Medical Clinic (MF8031)",
    "excellent": "Excellent Medical Center (MF4777)",
    "pharmacy": "Excellent Pharmacy (PF3205)",
}

# Your required order: start from 0–30
AGING_ORDER = ["0–30 Days", "31–45 Days", "46–60 Days", "61–90 Days", "91–120 Days", ">120 Days"]

# Default sold-to-klaim keywords (for medical centers)
SOLD_TO_KLAIM_KEYWORDS_DEFAULT = ["NextCare", "Sukoon", "Almadallah", "Daman", "FMC"]

# Pharmacy sold insurers
SOLD_TO_KLAIM_KEYWORDS_PHARMACY = ["ALMADALLAH-AD", "Daman"]

GT_PAT = re.compile(r"^\s*(grand\s*total|total)\s*$", re.I)

# =========================================================
# PREMIUM + SOOTHING UI (ONLY STYLES) + KPI AUTO-FIT
# =========================================================
st.markdown(
    """
<style>
.stApp{
  background: linear-gradient(180deg, #F7FAFF 0%, #FFFFFF 45%) !important;
}
hr{ border: none !important; height:1px !important; background:#E6EEF8 !important; }

div.stButton > button{
  width: 100% !important;
  min-height: 58px !important;
  padding: 14px 22px !important;
  font-size: 18px !important;
  font-weight: 800 !important;

  background: #EEF6FF !important;
  color: #0B2D5C !important;
  border: 1.8px solid #B6D4FF !important;
  border-radius: 14px !important;

  box-shadow: 0 3px 10px rgba(11, 45, 92, 0.10) !important;
}
div.stButton > button:hover{
  background: #DCEBFF !important;
  border-color: #6FA4FF !important;
  box-shadow: 0 6px 16px rgba(11, 45, 92, 0.14) !important;
}
div.stButton > button:active,
div.stButton > button:focus,
div.stButton > button:focus-visible{
  background: #0B2D5C !important;
  color: #ffffff !important;
  border-color: #0B2D5C !important;
  outline: none !important;
  box-shadow: none !important;
}

.center-title{
  color:#0B2D5C !important;
  font-weight: 900 !important;
  margin-bottom: 0.15rem !important;
}

.kpi-grid{
  display:grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 14px;
  margin-top: 10px;
  margin-bottom: 10px;
}
.kpi-card{
  background: rgba(255,255,255,0.92);
  border: 1.4px solid #E3ECFA;
  border-radius: 16px;
  padding: 14px 16px;
  box-shadow: 0 8px 18px rgba(11,45,92,0.06);
  min-width: 0;
}
.kpi-label{
  font-size: 13px;
  color: #64748B;
  font-weight: 750;
  margin-bottom: 6px;
}
.kpi-value{
  font-size: clamp(16px, 2.0vw, 28px);
  font-weight: 900;
  color: #111827;
  letter-spacing: 0.2px;

  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.kpi-card.current{
  background: linear-gradient(180deg, #F1F7FF 0%, #FFFFFF 100%);
  border-color: #CFE3FF;
}
.kpi-card.current .kpi-value{
  color:#0B2D5C;
}

@media (max-width: 1100px){
  .kpi-grid{ grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
</style>
""",
    unsafe_allow_html=True,
)


def render_balance_kpi_cards(total_balance, sold_to_klaim_balance, current_balance, sold_over60, current_over60):
    def fmt(x):
        try:
            return f"{float(x):,.2f}"
        except Exception:
            return "—"

    html = f"""
    <div class="kpi-grid">
      <div class="kpi-card" title="{fmt(total_balance)}">
        <div class="kpi-label">Total Balance</div>
        <div class="kpi-value">{fmt(total_balance)}</div>
      </div>

      <div class="kpi-card" title="{fmt(sold_to_klaim_balance)}">
        <div class="kpi-label">Insurance Balance Sold to Klaim</div>
        <div class="kpi-value">{fmt(sold_to_klaim_balance)}</div>
      </div>

      <div class="kpi-card current" title="{fmt(current_balance)}">
        <div class="kpi-label">Current Balance (Total - Sold)</div>
        <div class="kpi-value">{fmt(current_balance)}</div>
      </div>

      <div class="kpi-card" title="{fmt(sold_over60)}">
        <div class="kpi-label">Sold to Klaim &gt;60 Days</div>
        <div class="kpi-value">{fmt(sold_over60)}</div>
      </div>

      <div class="kpi-card" title="{fmt(current_over60)}">
        <div class="kpi-label">Current &gt;60 Days</div>
        <div class="kpi-value">{fmt(current_over60)}</div>
      </div>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)


def render_submission_stage_kpis(stage_kpis: dict):
    def fmt(x):
        try:
            return f"{float(x):,.2f}"
        except Exception:
            return "—"

    html = f"""
    <div class="kpi-grid">
      <div class="kpi-card">
        <div class="kpi-label">Initial Submission Balance</div>
        <div class="kpi-value">{fmt(stage_kpis.get('Initial Submission', 0))}</div>
      </div>

      <div class="kpi-card">
        <div class="kpi-label">1st Resubmission Balance</div>
        <div class="kpi-value">{fmt(stage_kpis.get('Resubmission 1', 0))}</div>
      </div>

      <div class="kpi-card">
        <div class="kpi-label">2nd Resubmission Balance</div>
        <div class="kpi-value">{fmt(stage_kpis.get('Resubmission 2', 0))}</div>
      </div>

      <div class="kpi-card">
        <div class="kpi-label">3rd Resubmission Balance</div>
        <div class="kpi-value">{fmt(stage_kpis.get('Resubmission 3', 0))}</div>
      </div>

      <div class="kpi-card">
        <div class="kpi-label">Not Submitted Balance</div>
        <div class="kpi-value">{fmt(stage_kpis.get('Not Submitted', 0))}</div>
      </div>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)


# =========================================================
# Helpers (generic medical-center logic)
# =========================================================
INSURANCE_COLS = ["Insurance", "PayerName", "Insurer", "Plan"]
NET_COLS = ["ActivityIns", "Net Amount", "NetAmount"]
PAID_COLS = [
    "actRemitInsShare",
    "actResub1RemitInsShare",
    "actResub2RemitInsShare",
    "actResub3RemitInsShare",
    "TKBKAmountAct",
]
ACTIVITY_STATUS_COLS = ["ActivityStatus"]
DENIAL_COLS = ["DenialCode", "Denial Code"]
DATE_COLS = ["SubmissionDate", "ClaimDate", "VisitDate", "ServiceDate", "InvoiceDate", "EncounterDate"]


def pick(df, candidates):
    for c in candidates:
        if c in df.columns:
            return c
    return None


def ensure_insurance(df):
    c = pick(df, INSURANCE_COLS)
    if c is None:
        df["Insurance"] = "Not Available"
    elif c != "Insurance":
        df["Insurance"] = df[c]
    df["Insurance"] = df["Insurance"].fillna("Not Available").astype(str)
    return df


def ensure_numeric(df):
    net = pick(df, NET_COLS) or "ActivityIns"
    if net not in df.columns:
        df[net] = 0
    df[net] = pd.to_numeric(df[net], errors="coerce").fillna(0)

    present_paid = [c for c in PAID_COLS if c in df.columns]
    for c in present_paid:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)

    return df, net, present_paid


def compute_measures(df, net_col, paid_cols):
    df["Paid"] = df[paid_cols].sum(axis=1) if paid_cols else 0.0
    df["Rejected"] = 0.0
    df["Balance"] = 0.0
    df["Accepted"] = 0.0

    act_status = pick(df, ACTIVITY_STATUS_COLS)
    denial = pick(df, DENIAL_COLS)

    if act_status and denial:
        s = df[act_status].astype(str).str.lower().str.strip()
        denial_ok = df[denial].notna() & (df[denial].astype(str).str.strip() != "")

        paid_mask = df["Paid"] > 0
        reject_mask = (df["Paid"] == 0) & (s == "rejected") & denial_ok
        balance_mask = (df["Paid"] == 0) & (~reject_mask)

        df.loc[paid_mask, "Accepted"] = (df.loc[paid_mask, net_col] - df.loc[paid_mask, "Paid"]).clip(lower=0)
        df.loc[reject_mask, "Rejected"] = df.loc[reject_mask, net_col]
        df.loc[balance_mask, "Balance"] = df.loc[balance_mask, net_col]
    else:
        paid_mask = df["Paid"] > 0
        df.loc[paid_mask, "Accepted"] = (df.loc[paid_mask, net_col] - df.loc[paid_mask, "Paid"]).clip(lower=0)
        df.loc[df["Paid"] == 0, "Balance"] = df.loc[df["Paid"] == 0, net_col]

    return df


def add_aging(df):
    existing = [c for c in DATE_COLS if c in df.columns]
    for c in existing:
        df[c] = pd.to_datetime(df[c], errors="coerce", dayfirst=True)

    if existing:
        df["RefDate"] = df[existing].bfill(axis=1).iloc[:, 0]
    else:
        df["RefDate"] = pd.NaT

    today = pd.Timestamp(dt.today().date())
    df["DaysDiff"] = (today - df["RefDate"]).dt.days

    bins = [-1, 30, 45, 60, 90, 120, float("inf")]
    labels = ["0–30 Days", "31–45 Days", "46–60 Days", "61–90 Days", "91–120 Days", ">120 Days"]
    df["AgingBucket"] = pd.cut(df["DaysDiff"], bins=bins, labels=labels)

    df["AgingBucket"] = df["AgingBucket"].astype(str).replace("nan", "Unknown")
    return df


def sold_to_klaim_mask(series: pd.Series, keywords) -> pd.Series:
    s = series.fillna("").astype(str).str.lower()
    kws = [k.lower() for k in keywords if str(k).strip()]
    if not kws:
        return pd.Series([False] * len(series), index=series.index)
    pat = "|".join(re.escape(k) for k in kws)
    return s.str.contains(pat, regex=True)


def is_over_60_bucket(bucket_series: pd.Series) -> pd.Series:
    b = bucket_series.fillna("").astype(str)
    return b.isin(["61–90 Days", "91–120 Days", ">120 Days"])


# =========================================================
# Status fill + submission stage helpers
# =========================================================
def prepare_status_stage(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    status_col = None
    for c in df.columns:
        if str(c).strip().lower() == "status":
            status_col = c
            break

    if status_col is None:
        df["FilledStatus"] = "Unknown"
        df["SubmissionStage"] = "Unknown"
        return df

    raw = df[status_col].copy()

    # blank/empty -> NA, then fill downward
    s = raw.astype(str).replace("nan", "").replace("None", "").str.strip()
    s = s.replace("", pd.NA).ffill().fillna("Unknown")

    df["FilledStatus"] = s

    def map_stage(x):
        t = str(x).strip().lower()

        if t == "not submitted":
            return "Not Submitted"
        if t == "submitted":
            return "Initial Submission"

        # Handle common formats: Submitted(Resub- 1), Submitted (Resub-1), etc.
        if "submitted" in t and "resub" in t and "1" in t:
            return "Resubmission 1"
        if "submitted" in t and "resub" in t and "2" in t:
            return "Resubmission 2"
        if "submitted" in t and "resub" in t and "3" in t:
            return "Resubmission 3"
        if "submitted" in t and "resub" in t and "4" in t:
            return "Resubmission 4"

        return "Other"

    df["SubmissionStage"] = df["FilledStatus"].apply(map_stage)
    return df


def calculate_submission_stage_kpis(balance_df: pd.DataFrame):
    b = balance_df.copy()
    b["Balance"] = pd.to_numeric(b["Balance"], errors="coerce").fillna(0)

    def stage_sum(stage_name):
        return float(b.loc[b["SubmissionStage"] == stage_name, "Balance"].sum())

    initial_balance = stage_sum("Initial Submission")
    resub1_balance = stage_sum("Resubmission 1")
    resub2_balance = stage_sum("Resubmission 2")
    resub3_balance = stage_sum("Resubmission 3")
    not_submitted_balance = stage_sum("Not Submitted")

    return {
        "Initial Submission": initial_balance,
        "Resubmission 1": resub1_balance,
        "Resubmission 2": resub2_balance,
        "Resubmission 3": resub3_balance,
        "Not Submitted": not_submitted_balance,
    }


def build_insurance_stage_summary(balance_df: pd.DataFrame) -> pd.DataFrame:
    b = balance_df.copy()

    if "Insurance" not in b.columns:
        b["Insurance"] = "Not Available"

    b["Insurance"] = b["Insurance"].fillna("Not Available").astype(str).str.strip()
    b["Balance"] = pd.to_numeric(b["Balance"], errors="coerce").fillna(0)

    wanted_order = [
        "Initial Submission",
        "Resubmission 1",
        "Resubmission 2",
        "Resubmission 3",
        "Not Submitted",
    ]

    piv = pd.pivot_table(
        b,
        index="Insurance",
        columns="SubmissionStage",
        values="Balance",
        aggfunc="sum",
        fill_value=0,
    ).reset_index()

    for col in wanted_order:
        if col not in piv.columns:
            piv[col] = 0.0

    piv["Total Balance"] = (
        piv["Initial Submission"]
        + piv["Resubmission 1"]
        + piv["Resubmission 2"]
        + piv["Resubmission 3"]
        + piv["Not Submitted"]
    )

    piv = piv[["Insurance"] + wanted_order + ["Total Balance"]]
    piv = piv.sort_values("Total Balance", ascending=False).reset_index(drop=True)

    grand = pd.DataFrame([{
        "Insurance": "Grand Total",
        "Initial Submission": piv["Initial Submission"].sum(),
        "Resubmission 1": piv["Resubmission 1"].sum(),
        "Resubmission 2": piv["Resubmission 2"].sum(),
        "Resubmission 3": piv["Resubmission 3"].sum(),
        "Not Submitted": piv["Not Submitted"].sum(),
        "Total Balance": piv["Total Balance"].sum(),
    }])

    piv = pd.concat([piv, grand], ignore_index=True)
    return piv


# =========================================================
# Pharmacy logic (NEEDFUL)
# =========================================================
def ci_get(df, names):
    lower_map = {str(c).strip().lower(): c for c in df.columns}
    for n in names:
        k = str(n).strip().lower()
        if k in lower_map:
            return lower_map[k]
    return None


def compute_pharmacy_balance(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]

    col_net = ci_get(df, ["Claim Amount", "Claim Amount (Net)", "NetAmount", "Net Amount", "TotalAmount", "Total Amount", "Net"])
    col_paid = ci_get(df, ["Remitted Amount", "Remitted Amount (Paid)", "Paid", "Remit Amount", "RemitAmount"])
    col_stat = ci_get(df, ["ClaimStatus", "Status", "ResponseType"])
    col_payer = ci_get(df, ["Insurance", "PayerName", "Insurer", "Plan", "InsurancePlan"])
    col_date = ci_get(df, ["ClaimDate", "RxDate", "DispenseDate", "SubmissionDate", "VisitDate", "DOS", "DateOfService"])

    if not col_net or not col_paid or not col_stat:
        # fallback to generic
        df = ensure_insurance(df)
        df, net_col, paid_cols = ensure_numeric(df)
        df = compute_measures(df, net_col, paid_cols)
        return df

    if not col_payer:
        col_payer = "Insurance"
        df[col_payer] = "Not Available"
    if not col_date:
        col_date = "ClaimDate"
        df[col_date] = pd.NaT

    df[col_net] = pd.to_numeric(df[col_net], errors="coerce").fillna(0.0).clip(lower=0)
    df[col_paid] = pd.to_numeric(df[col_paid], errors="coerce").fillna(0.0).clip(lower=0)
    df[col_date] = pd.to_datetime(df[col_date], errors="coerce", dayfirst=True)

    lower_status = df[col_stat].astype(str).str.lower().str.strip()
    net = df[col_net]
    paid = df[col_paid]
    diff = (net - paid).clip(lower=0)

    df["Insurance"] = df[col_payer].fillna("Not Available").astype(str)

    df["Rejected"] = 0.0
    df["Accepted"] = 0.0
    df["Balance"] = 0.0
    df["Paid"] = paid

    mask_denied = lower_status.isin(["denied", "rejected"])
    df.loc[mask_denied, "Rejected"] = net
    df.loc[mask_denied, ["Accepted", "Balance"]] = 0.0

    tiny_threshold = 4.0
    mask_paid = paid > 0
    mask_tiny = diff <= tiny_threshold
    mask_acc = (~mask_denied) & mask_paid & mask_tiny
    df.loc[mask_acc, "Accepted"] = diff
    df.loc[mask_acc, "Balance"] = 0.0

    mask_bal = (~mask_denied) & (diff > tiny_threshold)
    df.loc[mask_bal, "Balance"] = diff

    df["RefDate"] = df[col_date]
    return df


# =========================================================
# Admin mode (optional)
# =========================================================
def is_admin_mode() -> bool:
    secret_pwd = st.secrets.get("ADMIN_PASSWORD", "")
    if secret_pwd:
        if st.session_state.get("is_admin", False):
            return True
        with st.popover("🔒 Admin login"):
            pwd = st.text_input("Password", type="password", key="admin_pwd")
            if st.button("Login", key="admin_login_btn"):
                if pwd == secret_pwd:
                    st.session_state.is_admin = True
                    st.rerun()
                else:
                    st.error("Wrong password")
        return False
    else:
        return st.toggle("Admin mode", value=st.session_state.get("is_admin", False))


st.session_state.is_admin = is_admin_mode()

# =========================================================
# ✅ S3 FALLBACK HELPERS (NEEDFUL)
# =========================================================
def _get_s3_cfg():
    access_key = st.secrets.get("AWS_ACCESS_KEY_ID", "")
    secret_key = st.secrets.get("AWS_SECRET_ACCESS_KEY", "")

    region = (
        st.secrets.get("AWS_REGION")
        or st.secrets.get("AWS_DEFAULT_REGION")
        or "eu-north-1"
    )

    bucket = (
        st.secrets.get("S3_BUCKET_NAME")
        or st.secrets.get("S3_BUCKET")
        or ""
    )

    prefix = st.secrets.get("S3_PREFIX", "").strip().strip("/")

    if not (access_key and secret_key and bucket):
        return None

    return {
        "access_key": access_key,
        "secret_key": secret_key,
        "region": region,
        "bucket": bucket,
        "prefix": prefix,
    }


def _s3_client(cfg):
    return boto3.client(
        "s3",
        aws_access_key_id=cfg["access_key"],
        aws_secret_access_key=cfg["secret_key"],
        region_name=cfg["region"],
    )


def s3_key_for(center_key: str, year: int, filename: str) -> str:
    cfg = _get_s3_cfg()
    pre = (cfg["prefix"] + "/") if (cfg and cfg.get("prefix")) else ""
    return f"{pre}{center_key}/{year}/{filename}"


def ensure_local_from_s3(local_path: Path, center_key: str, year: int) -> bool:
    if local_path.exists():
        return True

    cfg = _get_s3_cfg()
    if cfg is None:
        return False

    key = s3_key_for(center_key, year, local_path.name)
    client = _s3_client(cfg)

    try:
        local_path.parent.mkdir(parents=True, exist_ok=True)
        client.download_file(cfg["bucket"], key, str(local_path))
        return local_path.exists()
    except ClientError:
        return False


# =========================================================
# Paths (match main dashboard)
# =========================================================
def report_path(center_key: str, year: int) -> Path:
    if center_key == "pharmacy":
        return DATA_DIR / "excellent_pharmacy" / str(year) / "Pharmacy_Exclusive_Report_with_Aging.xlsx"
    elif center_key == "excellent":
        return DATA_DIR / "excellent" / str(year) / "report.xlsx"
    elif center_key == "easyhealth":
        return DATA_DIR / "easyhealth" / str(year) / "report.xlsx"
    else:
        return DATA_DIR / center_key / str(year) / "report.xlsx"


def save_uploaded_report(center_key: str, year: int, upload) -> Path:
    rp = report_path(center_key, year)
    rp.parent.mkdir(parents=True, exist_ok=True)
    rp.write_bytes(upload.read())
    return rp


# =========================================================
# ✅ NEEDFUL: Read query params from dashboard click
# - If center/year given → do NOT show password again (handled above) and do NOT show year selection.
# - If opened directly (no center/year), show the old year landing.
# =========================================================
def _qs_first(key: str):
    v = st.query_params.get(key)
    if isinstance(v, (list, tuple)):
        return v[0] if v else None
    return v


qs_year = _qs_first("year")
qs_center = _qs_first("center")

# set year from query OR from main dashboard selection
if qs_year:
    try:
        st.session_state.year = int(qs_year)
    except Exception:
        pass
elif st.session_state.get("year") is None:
    if st.session_state.get("rcm_year") in YEARS:
        st.session_state.year = int(st.session_state.get("rcm_year"))

# set center from query params (only when coming from dashboard click)
if qs_center:
    qs_center = str(qs_center).strip().lower()
    if qs_center in CENTERS:
        st.session_state.center_key = qs_center

st.caption(
    f"Mode: **{'admin' if st.session_state.get('is_admin') else 'view'}** · "
    f"Year: **{st.session_state.get('year') or 'none'}** · "
    f"Center: **{st.session_state.get('center_key') or 'all'}**"
)

# =========================================================
# Year landing (ONLY if opened directly, no year provided anywhere)
# =========================================================
if st.session_state.get("year") is None:
    st.subheader("Select Year")
    cols = st.columns(3)
    for i, y in enumerate(YEARS):
        with cols[i]:
            if st.button(f"Pending Balance {y}", use_container_width=True, key=f"pb_{y}"):
                st.session_state.year = y
                st.query_params["year"] = str(y)
                st.rerun()
    st.stop()

year = int(st.session_state.year)

# Keep query params consistent
if st.query_params.get("year") != str(year):
    st.query_params["year"] = str(year)

# =========================================================
# Centers to show (2024: no easyhealth)
# =========================================================
if year == 2024:
    centers_to_show = ["excellent", "pharmacy"]
else:
    centers_to_show = ["excellent", "pharmacy", "easyhealth"]

forced_center = st.session_state.get("center_key")
if forced_center in centers_to_show:
    centers_to_show = [forced_center]


# =========================================================
# ✅ LOAD KPI (detail sheet first) — FIXED + submission stage summary
# =========================================================
@st.cache_data(show_spinner=True)
def load_kpis_only(path_str: str, token: float, center_key: str):
    xls = pd.ExcelFile(path_str, engine="openpyxl")

    preferred = ["Balance_Aging_Detail", "Balance_Aging_Summary", "Insurance_Totals"]
    base_sheet = None
    for s in preferred:
        if s in xls.sheet_names:
            base_sheet = s
            break

    if base_sheet is None:
        base_sheet = xls.sheet_names[0]

    df = pd.read_excel(xls, sheet_name=base_sheet)
    df.columns = [str(c).strip() for c in df.columns]

    if center_key == "pharmacy":
        df = compute_pharmacy_balance(df)
        df = add_aging(df) if "AgingBucket" not in df.columns else df
        keywords = SOLD_TO_KLAIM_KEYWORDS_PHARMACY
    else:
        df = ensure_insurance(df)
        df, net_col, paid_cols = ensure_numeric(df)
        df = compute_measures(df, net_col, paid_cols)
        df = add_aging(df)
        keywords = SOLD_TO_KLAIM_KEYWORDS_DEFAULT

    # ✅ fill Status blanks downward and classify submission stage
    df = prepare_status_stage(df)

    balance_df = df[df["Balance"] > 0].copy()
    balance_df = balance_df[balance_df["AgingBucket"] != "Unknown"].copy()

    total_balance = float(pd.to_numeric(balance_df["Balance"], errors="coerce").fillna(0).sum())

    sold_mask = sold_to_klaim_mask(balance_df["Insurance"], keywords)
    sold_to_klaim_balance = float(pd.to_numeric(balance_df.loc[sold_mask, "Balance"], errors="coerce").fillna(0).sum())
    current_balance = total_balance - sold_to_klaim_balance

    over60_mask = is_over_60_bucket(balance_df["AgingBucket"])
    sold_over60 = float(pd.to_numeric(balance_df.loc[sold_mask & over60_mask, "Balance"], errors="coerce").fillna(0).sum())
    current_over60 = float(pd.to_numeric(balance_df.loc[(~sold_mask) & over60_mask, "Balance"], errors="coerce").fillna(0).sum())

    stage_kpis = calculate_submission_stage_kpis(balance_df)
    insurance_stage_summary = build_insurance_stage_summary(balance_df)

    return (
        total_balance,
        sold_to_klaim_balance,
        current_balance,
        sold_over60,
        current_over60,
        keywords,
        stage_kpis,
        insurance_stage_summary,
    )


# =========================================================
# Render per center
# =========================================================
def render_center_kpis_only(center_key: str, year: int):
    st.markdown(f"<h2 class='center-title'>{CENTERS[center_key]}</h2>", unsafe_allow_html=True)
    st.caption(f"Year: **{year}**")

    rp = report_path(center_key, year)

    # ✅ NEEDFUL: S3 fallback (download if local missing)
    ensure_local_from_s3(rp, center_key, year)

    token = rp.stat().st_mtime if rp.exists() else 0.0
    built = "—" if not token else dt.fromtimestamp(token).strftime("%Y-%m-%d %H:%M")
    st.caption(f"Saved report: `{rp}` · Built: **{built}**")

    if st.session_state.get("is_admin"):
        with st.expander("⬆️ Admin: Upload/replace report for this center & year", expanded=False):
            up = st.file_uploader("Upload report (.xlsx)", type=["xlsx"], key=f"u_{center_key}_{year}")
            if up:
                dst = save_uploaded_report(center_key, year, up)
                st.success(f"Saved ✅ {dst}")
                load_kpis_only.clear()
                st.rerun()

    if not rp.exists():
        st.warning(
            "No saved report found for this center/year.\n\n"
            "✅ Admin must upload/rebuild once (or ensure report exists in S3), then management can view anytime."
        )
        st.markdown("---")
        return

    (
        total_balance,
        sold_to_klaim_balance,
        current_balance,
        sold_over60,
        current_over60,
        keywords_used,
        stage_kpis,
        insurance_stage_summary,
    ) = load_kpis_only(str(rp), token, center_key)

    render_balance_kpi_cards(total_balance, sold_to_klaim_balance, current_balance, sold_over60, current_over60)
    render_submission_stage_kpis(stage_kpis)

    st.caption(f"Sold-to-Klaim keywords: {', '.join(keywords_used)}")

    st.subheader("Insurance-wise Submission Balance")

    show_df = insurance_stage_summary.copy()
    numeric_cols = [
        "Initial Submission",
        "Resubmission 1",
        "Resubmission 2",
        "Resubmission 3",
        "Not Submitted",
        "Total Balance",
    ]

    for c in numeric_cols:
        if c in show_df.columns:
            show_df[c] = pd.to_numeric(show_df[c], errors="coerce").fillna(0.0)

    st.dataframe(show_df, use_container_width=True, hide_index=True)

    # Download Excel
    excel_buffer = io.BytesIO()
    with pd.ExcelWriter(excel_buffer, engine="openpyxl") as writer:
        show_df.to_excel(writer, index=False, sheet_name="Insurance_Stage_Summary")
    excel_buffer.seek(0)

    st.download_button(
        label="📥 Download Insurance-wise Summary",
        data=excel_buffer.getvalue(),
        file_name=f"{center_key}_{year}_insurance_stage_summary.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
        key=f"download_stage_summary_{center_key}_{year}",
    )

    st.markdown("---")


# =========================================================
# Page output
# =========================================================
st.markdown(f"## Pending Balance — {year}")

for ckey in centers_to_show:
    render_center_kpis_only(ckey, year)
