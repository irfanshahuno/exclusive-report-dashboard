#!/usr/bin/env python3
import re
from pathlib import Path
from datetime import datetime as dt

import pandas as pd
import streamlit as st

# =========================================================
# Settings
# =========================================================
st.set_page_config(page_title="Balance — Initial / Resub with Aging", layout="wide")
st.title("Balance — Initial / Resub with Aging (Summary)")

BASE = Path(__file__).parent
DATA_DIR = BASE / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

YEARS = [2024, 2025]

CENTERS = {
    "easyhealth": "Easy Health Medical Clinic (MF8031)",
    "excellent": "Excellent Medical Center (MF4777)",
    "pharmacy": "Excellent Pharmacy (PF3205)",
}

# Your required order: start from 0–30
AGING_ORDER = ["0–30 Days", "31–45 Days", "46–60 Days", "61–90 Days", "91–120 Days", ">120 Days"]

# Default sold-to-klaim keywords (for medical centers)
SOLD_TO_KLAIM_KEYWORDS_DEFAULT = ["NextCare", "Sukoon", "Almadallah", "Daman", "FMC"]

# Pharmacy sold insurers (as per your instruction)
SOLD_TO_KLAIM_KEYWORDS_PHARMACY = ["ALMADALLAH-AD", "Daman"]

GT_PAT = re.compile(r"^\s*(grand\s*total|total)\s*$", re.I)

# =========================================================
# PREMIUM + SOOTHING UI (ONLY STYLES) + KPI AUTO-FIT
# =========================================================
st.markdown(
    """
<style>
/* ---------- Page background (soothing) ---------- */
.stApp{
  background: linear-gradient(180deg, #F7FAFF 0%, #FFFFFF 45%) !important;
}
hr{ border: none !important; height:1px !important; background:#E6EEF8 !important; }

/* ---------- Premium Buttons (Light-blue) ---------- */
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

/* ---------- Center title (dark navy) ---------- */
.center-title{
  color:#0B2D5C !important;
  font-weight: 900 !important;
  margin-bottom: 0.15rem !important;
}

/* ---------- Premium KPI Cards (5 columns) ---------- */
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
  min-width: 0; /* important */
}
.kpi-label{
  font-size: 13px;
  color: #64748B;
  font-weight: 750;
  margin-bottom: 6px;
}
/* ✅ AUTO-FIT number inside card + keep in box */
.kpi-value{
  font-size: clamp(16px, 2.0vw, 28px);
  font-weight: 900;
  color: #111827;
  letter-spacing: 0.2px;

  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* Slight highlight for Current Balance card (same bold, different color) */
.kpi-card.current{
  background: linear-gradient(180deg, #F1F7FF 0%, #FFFFFF 100%);
  border-color: #CFE3FF;
}
.kpi-card.current .kpi-value{
  color:#0B2D5C;
}

/* Mobile */
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


# =========================================================
# Helpers (same logic as your working script)
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
STATUS_COLS = ["Status"]
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


def derive_attempt_stage(balance_df):
    status_col = pick(balance_df, STATUS_COLS)
    act_status_col = pick(balance_df, ACTIVITY_STATUS_COLS)

    status = (
        balance_df[status_col].astype(str).fillna("").str.strip()
        if status_col
        else pd.Series([""] * len(balance_df), index=balance_df.index)
    )
    act = (
        balance_df[act_status_col].astype(str).fillna("").str.strip()
        if act_status_col
        else pd.Series([""] * len(balance_df), index=balance_df.index)
    )

    src = status.where(status != "", act)
    s = src.astype(str).str.lower().str.replace(r"\s+", " ", regex=True).str.strip()

    def attempt_num(txt: str) -> int:
        t = (txt or "").lower().strip()
        m = re.search(r"resub(?:mission)?\s*[-]?\s*([123])", t)
        if m:
            return int(m.group(1)) + 1
        if "submitted" in t or "not submitted" in t:
            return 1
        return 1

    balance_df["AttemptNum"] = s.apply(attempt_num).astype(int)
    stage_map = {
        1: "Initial Submission",
        2: "Resub-1 (2nd Submission)",
        3: "Resub-2 (3rd Submission)",
        4: "Resub-3 (4th Submission)",
    }
    balance_df["AttemptStage"] = balance_df["AttemptNum"].map(stage_map).fillna("Initial Submission")
    return balance_df


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


def is_admin_mode() -> bool:
    """
    Admin login like your main dashboard:
    - If ADMIN_PASSWORD is in st.secrets → require it.
    - If not → show toggle (for local/testing).
    """
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


def report_path(center_key: str, year: int) -> Path:
    return DATA_DIR / center_key / str(year) / "report.xlsx"


def save_uploaded_report(center_key: str, year: int, upload) -> Path:
    folder = DATA_DIR / center_key / str(year)
    folder.mkdir(parents=True, exist_ok=True)
    dst = folder / "report.xlsx"
    dst.write_bytes(upload.read())
    return dst


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


@st.cache_data(show_spinner=True)
def load_kpis_only(path_str: str, token: float, center_key: str):
    xls = pd.ExcelFile(path_str, engine="openpyxl")
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

    balance_df = df[df["Balance"] > 0].copy()
    balance_df = derive_attempt_stage(balance_df)
    balance_df = balance_df[balance_df["AgingBucket"] != "Unknown"].copy()

    total_balance = float(pd.to_numeric(balance_df["Balance"], errors="coerce").fillna(0).sum())

    sold_mask = sold_to_klaim_mask(balance_df["Insurance"], keywords)
    sold_to_klaim_balance = float(pd.to_numeric(balance_df.loc[sold_mask, "Balance"], errors="coerce").fillna(0).sum())
    current_balance = total_balance - sold_to_klaim_balance

    over60_mask = is_over_60_bucket(balance_df["AgingBucket"])
    sold_over60 = float(pd.to_numeric(balance_df.loc[sold_mask & over60_mask, "Balance"], errors="coerce").fillna(0).sum())
    current_over60 = float(pd.to_numeric(balance_df.loc[(~sold_mask) & over60_mask, "Balance"], errors="coerce").fillna(0).sum())

    return total_balance, sold_to_klaim_balance, current_balance, sold_over60, current_over60, keywords


# =========================================================
# UI: Year-first landing like main dashboard
# =========================================================
st.session_state.is_admin = is_admin_mode()

def _qs_first(key: str):
    v = st.query_params.get(key)
    if isinstance(v, (list, tuple)):
        return v[0] if v else None
    return v

qs_year = _qs_first("year")

if qs_year and st.session_state.get("year") is None:
    try:
        st.session_state.year = int(qs_year)
    except Exception:
        pass

st.caption(
    f"Mode: **{'admin' if st.session_state.get('is_admin') else 'view'}** · "
    f"Year: **{st.session_state.get('year') or 'none'}**"
)

# ---- Landing: only year buttons ----
if st.session_state.get("year") is None:
    st.subheader("Select Year")
    y1, y2 = st.columns(2)

    with y1:
        if st.button("Pending Balance 2024", use_container_width=True, key="pb_2024"):
            st.session_state.year = 2024
            st.query_params["year"] = "2024"
            st.rerun()

    with y2:
        if st.button("Pending Balance 2025", use_container_width=True, key="pb_2025"):
            st.session_state.year = 2025
            st.query_params["year"] = "2025"
            st.rerun()

    st.stop()

year = int(st.session_state.year)

# Back to year selection
if st.button("◀ Back to Year Selection"):
    st.session_state.year = None
    try:
        if "year" in st.query_params:
            del st.query_params["year"]
    except Exception:
        pass
    st.rerun()

if st.query_params.get("year") != str(year):
    st.query_params["year"] = str(year)

# =========================================================
# NEEDFUL: Order + 2024 rule (no EasyHealth)
# =========================================================
if year == 2024:
    centers_to_show = ["excellent", "pharmacy"]
else:
    centers_to_show = ["excellent", "pharmacy", "easyhealth"]

# =========================================================
# Render KPIs ONLY per center (premium cards)
# =========================================================
def render_center_kpis_only(center_key: str, year: int):
    st.markdown(f"<h2 class='center-title'>{CENTERS[center_key]}</h2>", unsafe_allow_html=True)
    st.caption(f"Year: **{year}**")

    rp = report_path(center_key, year)
    token = rp.stat().st_mtime if rp.exists() else 0.0
    built = "—" if not token else dt.fromtimestamp(token).strftime("%Y-%m-%d %H:%M")
    st.caption(f"Saved report: `{rp}` · Built: **{built}**")

    if st.session_state.get("is_admin"):
        with st.expander("⬆️ Admin: Upload/replace report.xlsx for this center & year", expanded=False):
            up = st.file_uploader(
                "Upload report (.xlsx)",
                type=["xlsx"],
                key=f"u_{center_key}_{year}",
            )
            if up:
                dst = save_uploaded_report(center_key, year, up)
                st.success(f"Saved ✅ {dst}")
                load_kpis_only.clear()
                st.rerun()

    if not rp.exists():
        st.warning(
            "No saved report found for this center/year.\n\n"
            "✅ Admin must upload **report.xlsx** once, then management can view anytime."
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
    ) = load_kpis_only(str(rp), token, center_key)

    render_balance_kpi_cards(
        total_balance,
        sold_to_klaim_balance,
        current_balance,
        sold_over60,
        current_over60,
    )

    st.caption(f"Sold-to-Klaim keywords: {', '.join(keywords_used)}")
    st.markdown("---")


# =========================================================
# Show centers KPIs for selected year
# =========================================================
st.markdown(f"## Pending Balance — {year}")

for ckey in centers_to_show:
    render_center_kpis_only(ckey, year)
