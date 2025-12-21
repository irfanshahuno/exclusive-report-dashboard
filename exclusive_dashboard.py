# exclusive_dashboard.py
# Main dashboard KPIs at TOP (Doc Performance unchanged)
# NOTE:
# • Optional Balance_Aging_InsGroup tab (already supported)
# • Optional Balance_Aging_Plan tab (already supported)
# • S.No hidden and display index starts at 1
# • Grand Total row is always LAST
# • NEW: View-only password protection
# NOTHING ELSE CHANGED

import sys
import subprocess
import re
from pathlib import Path
from datetime import datetime, date

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

# ====================== VIEW PASSWORD ======================
VIEW_PASSWORD = "Emc@2026"


def require_view_access():
    if st.session_state.get("is_view_auth", False):
        return

    st.title("🔒 Dashboard Access")
    st.info("Please enter the view password to continue")

    pwd = st.text_input("View Password", type="password")
    if st.button("Enter Dashboard"):
        if pwd == VIEW_PASSWORD:
            st.session_state.is_view_auth = True
            st.rerun()
        else:
            st.error("Incorrect password")

    st.stop()


# ====================== Page setup ======================
st.set_page_config(
    page_title="Exclusive Report with Aging — Dashboard",
    layout="wide"
)
st.set_option("client.showErrorDetails", False)

# 🔒 View gate
require_view_access()

# ====================== Constants ======================
DOC_PERF_URL = "https://doctor-performance-app-tjwqgmptk8fbo57t4qrfqr.streamlit.app/"
BASE = Path(__file__).parent
DATA_DIR = BASE / "data"

(DATA_DIR / "easyhealth").mkdir(parents=True, exist_ok=True)
(DATA_DIR / "excellent").mkdir(parents=True, exist_ok=True)
(DATA_DIR / "excellent_pharmacy").mkdir(parents=True, exist_ok=True)

DOC_PERF_KEY = "__docperf__"
YEARS = [2024, 2025]

SHEET_INS_TOT = "Insurance_Totals"
SHEET_SUMMARY = "Balance_Aging_Summary"
SHEET_INGROUP = "Balance_Aging_InsGroup"
SHEET_IPLAN = "Balance_Aging_Plan"

GT_PAT = re.compile(r"^\s*(grand\s*total|total)\s*$", re.I)

# ====================== Centers ======================
CENTERS = {
    "easyhealth": {
        "key": "easyhealth",
        "name": "Easy Health Medical Clinic (MF8031)",
        "folder_root": DATA_DIR / "easyhealth",
        "src_name": "source.xlsx",
        "out_name": "report.xlsx",
        "generator": BASE / "exclusive_report_with_aging_final.py",
    },
    "excellent": {
        "key": "excellent",
        "name": "Excellent Medical Center (MF4777)",
        "folder_root": DATA_DIR / "excellent",
        "src_name": "source.xlsx",
        "out_name": "report.xlsx",
        "generator": BASE / "exclusive_report_with_aging_final.py",
    },
    "pharmacy": {
        "key": "pharmacy",
        "name": "Excellent Pharmacy (PF3205)",
        "folder_root": DATA_DIR / "excellent_pharmacy",
        "src_name": "source.xlsx",
        "out_name": "Pharmacy_Exclusive_Report_with_Aging.xlsx",
        "generator": BASE / "pharmacy_exclusive_report_with_aging.py",
    },
}

# ====================== Helpers ======================
def mtime_token(p: Path):
    try:
        return p.stat().st_mtime
    except FileNotFoundError:
        return 0.0


def _run(cmd):
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(res.stderr or res.stdout)
    return res


def rebuild_report(gen, src, out):
    py = sys.executable
    try:
        return _run([py, gen, src, "--out", out]).stdout
    except Exception:
        return _run([py, gen, "--out", out, src]).stdout


def resolve_source_path(folder):
    for ext in ("xlsb", "xlsx", "xlsm"):
        p = folder / f"source.{ext}"
        if p.exists():
            return p
    return folder / "source.xlsx"


def ensure_grand_total(df):
    first = df.columns[0]
    if df[first].astype(str).str.match(GT_PAT).any():
        return df
    nums = df.select_dtypes("number").sum()
    row = {c: "" for c in df.columns}
    row.update(nums)
    row[first] = "Grand Total"
    return pd.concat([df, pd.DataFrame([row])], ignore_index=True)


def move_gt_last(df):
    first = df.columns[0]
    body = df[~df[first].astype(str).str.match(GT_PAT)]
    gt = df[df[first].astype(str).str.match(GT_PAT)]
    return pd.concat([body, gt], ignore_index=True)


def drop_gt(df):
    first = df.columns[0]
    return df[~df[first].astype(str).str.match(GT_PAT)]


def ksum(df, *cols):
    for c in cols:
        if c in df.columns:
            return float(pd.to_numeric(df[c], errors="coerce").sum())
    return 0.0


def is_admin_mode():
    secret = st.secrets.get("ADMIN_PASSWORD", "")
    if not secret:
        return st.toggle("Admin mode", value=st.session_state.get("is_admin", False))

    with st.popover("🔒 Admin login"):
        pwd = st.text_input("Password", type="password")
        if st.button("Login"):
            if pwd == secret:
                st.session_state.is_admin = True
                st.rerun()
            else:
                st.error("Wrong password")
    return st.session_state.get("is_admin", False)


# ====================== Header ======================
st.title("📊 Exclusive Report with Aging — Dashboard")
st.session_state.is_admin = is_admin_mode()

# ====================== Home ======================
if st.session_state.get("center_key") not in CENTERS:
    st.subheader("Choose a center")
    c1, c2, c3, c4 = st.columns(4)

    with c1:
        if st.button(CENTERS["easyhealth"]["name"], use_container_width=True):
            st.session_state.center_key = "easyhealth"
            st.rerun()

    with c2:
        if st.button(CENTERS["excellent"]["name"], use_container_width=True):
            st.session_state.center_key = "excellent"
            st.rerun()

    with c3:
        if st.button(CENTERS["pharmacy"]["name"], use_container_width=True):
            st.session_state.center_key = "pharmacy"
            st.rerun()

    with c4:
        components.html(
            f"""
            <a href="{DOC_PERF_URL}" target="_blank"
            style="text-decoration:none">
            <div style="border:2px solid #e5e7eb;
                        padding:18px;
                        border-radius:12px;
                        text-align:center;">
                Doctor Monthly Performance
            </div>
            </a>
            """,
            height=90,
        )
    st.stop()

# ====================== Year selection ======================
st.subheader("Select Year")
ycols = st.columns(len(YEARS))
for i, y in enumerate(YEARS):
    with ycols[i]:
        if st.button(str(y), use_container_width=True):
            st.session_state.year = y
            st.rerun()

if st.session_state.get("year") is None:
    st.session_state.year = YEARS[-1]
    st.rerun()

# ====================== Load report ======================
cfg = CENTERS[st.session_state.center_key]
folder = cfg["folder_root"] / str(st.session_state.year)
folder.mkdir(parents=True, exist_ok=True)

src = resolve_source_path(folder)
out = folder / cfg["out_name"]

if not out.exists():
    st.warning("Report not found.")
    st.stop()

engine = "pyxlsb" if out.suffix == ".xlsb" else "openpyxl"

totals = pd.read_excel(out, sheet_name=SHEET_INS_TOT, engine=engine)
summary = pd.read_excel(out, sheet_name=SHEET_SUMMARY, engine=engine)

totals = ensure_grand_total(totals)
summary = ensure_grand_total(summary)

totals_ngt = drop_gt(totals)

# ====================== KPIs ======================
net = ksum(totals_ngt, "Net Amount", "Net")
paid = ksum(totals_ngt, "Paid")
bal = ksum(totals_ngt, "Balance")
rej = ksum(totals_ngt, "Rejected")
acc = ksum(totals_ngt, "Accepted")

k0, k1, k2, k3, k4 = st.columns(5)
k0.metric("Net", f"{net:,.2f}")
k1.metric("Paid", f"{paid:,.2f}")
k2.metric("Balance", f"{bal:,.2f}")
k3.metric("Rejected", f"{rej:,.2f}")
k4.metric("Accepted", f"{acc:,.2f}")

# ====================== Tabs ======================
t1, t2 = st.tabs(["Insurance Totals", "Aging Summary"])

with t1:
    st.dataframe(move_gt_last(totals), use_container_width=True)

with t2:
    st.dataframe(move_gt_last(summary), use_container_width=True)

