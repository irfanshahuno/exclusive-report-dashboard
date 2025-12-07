# exclusive_dashboard.py
import sys
import subprocess
from pathlib import Path
from typing import Dict, Optional, Tuple

import pandas as pd
import streamlit as st

# --------------------------- Page setup ---------------------------
st.set_page_config(page_title="Exclusive Report with Aging — Dashboard", layout="wide")
BASE = Path(__file__).parent.resolve()

# The generator script (same one you already have)
GENERATOR = BASE / "exclusive_report_with_aging_final.py"

# Data roots and per-center config
DATA_DIR = BASE / "data"
CENTERS = {
    "easyhealth": {
        "title": "Easy Health Medical Clinic (MF8031)",
        "folder": DATA_DIR / "easyhealth",
        "report_name": "Exclusive_Report_with_Aging.xlsx",
        "short": "EasyHealth",
    },
    "excellent": {
        "title": "Excellent Medical Center (MF4777)",
        "folder": DATA_DIR / "excellent",
        "report_name": "Exclusive_Report_with_Aging.xlsx",
        "short": "Excellent",
    },
    "excellent_pharmacy": {
        "title": "Excellent Pharmacy (PF3205)",
        "folder": DATA_DIR / "excellent_pharmacy",
        "report_name": "Pharmacy_Exclusive_Report_with_Aging.xlsx",
        "short": "Pharmacy",
    },
}
for c in CENTERS.values():
    c["folder"].mkdir(parents=True, exist_ok=True)

# --------------------------- Helpers ---------------------------
def run_generator(source_xlsx: Path, out_xlsx: Path) -> Tuple[bool, str]:
    """Call the generator with the required --out argument."""
    cmd = [
        sys.executable,
        str(GENERATOR),
        "--out", str(out_xlsx),
        str(source_xlsx),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    ok = proc.returncode == 0
    msg = (
        "Command: " + " ".join(proc.args)
        + "\n\nSTDOUT:\n" + (proc.stdout or "(empty)")
        + "\n\nSTDERR:\n" + (proc.stderr or "(empty)")
    )
    return ok, msg

def read_sheet_safe(xlsx_path: Path, sheet_name: str) -> Optional[pd.DataFrame]:
    if not xlsx_path.exists():
        return None
    try:
        return pd.read_excel(xlsx_path, sheet_name=sheet_name, engine="openpyxl")
    except Exception:
        return None

def to_num(s):
    return pd.to_numeric(s, errors="coerce")

def detect_cols(df: pd.DataFrame) -> Dict[str, Optional[str]]:
    """Map common column name variants → canonical keys."""
    candidates = {
        "net": ["Net Amount", "NetAmount", "ActivityIns", "Net_Amount", "Net"],
        "paid": ["Paid", "Paid Amount", "PaidAmount", "Paid_Amount"],
        "bal": ["Balance", "Pending", "Pending Balance", "Outstanding"],
        "rej": ["Rejected", "Rejection", "Rejections"],
        "acc": ["Accepted", "Approval", "Approvals", "Approved"],
    }
    found = {}
    lc = {c.lower(): c for c in df.columns}
    for key, names in candidates.items():
        hit = None
        for n in names:
            if n in df.columns:
                hit = n; break
            if n.lower() in lc:
                hit = lc[n.lower()]; break
        found[key] = hit
    return found

def kpis_from_insurance_totals(df: pd.DataFrame) -> Dict[str, float]:
    """
    Prefer the 'Grand Total' row if it exists; otherwise sum columns.
    Works across any column-name variant set by detect_cols().
    """
    cols = detect_cols(df)
    # Try to find a "Grand Total" row by looking at the first string column
    label_col = None
    for c in df.columns:
        if df[c].dtype == object:
            label_col = c; break

    grand = None
    if label_col is not None:
        # accept many variants of grand total text
        mask = df[label_col].astype(str).str.strip().str.lower().isin(
            ["grand total", "total", "totals", "grand_total"]
        )
        if mask.any():
            grand = df.loc[mask].tail(1)  # take the last if multiple

    if grand is not None and not grand.empty:
        getv = lambda k: float(to_num(grand[cols[k]]).fillna(0).iloc[0]) if cols[k] in grand.columns else 0.0
        return {
            "net": getv("net"),
            "paid": getv("paid"),
            "bal": getv("bal"),
            "rej": getv("rej"),
            "acc": getv("acc"),
        }
    else:
        # Sum the whole sheet
        getsum = lambda k: float(to_num(df.get(cols[k], 0)).fillna(0).sum()) if cols[k] else 0.0
        return {"net": getsum("net"), "paid": getsum("paid"), "bal": getsum("bal"),
                "rej": getsum("rej"), "acc": getsum("acc")}

def ensure_grand_total_row(df: pd.DataFrame) -> pd.DataFrame:
    """
    If Insurance_Totals lacks a Grand Total row, append one (display only).
    Detects numeric columns automatically.
    """
    if df is None or df.empty:
        return df
    label_col = None
    for c in df.columns:
        if df[c].dtype == object:
            label_col = c; break
    has_gt = False
    if label_col is not None:
        has_gt = df[label_col].astype(str).str.strip().str.lower().isin(
            ["grand total", "total", "totals", "grand_total"]
        ).any()
    if has_gt:
        return df

    # build a totals row
    total_row = {}
    for c in df.columns:
        if pd.api.types.is_numeric_dtype(df[c]) or to_num(df[c]).notna().any():
            total_row[c] = to_num(df[c]).fillna(0).sum()
        else:
            total_row[c] = "Grand Total"
    return pd.concat([df, pd.DataFrame([total_row])], ignore_index=True)

def money(v: float) -> str:
    return f"{v:,.2f}"

# --------------------------- UI ---------------------------
st.title("📊 Exclusive Report with Aging — Dashboard")

# Admin toggle
mode_col, _ = st.columns([1, 5])
with mode_col:
    admin = st.toggle("Admin mode", value=False)

# Quick center buttons (left to right)
b1, b2, b3, _sp = st.columns([1, 1, 1, 4])
if "center_key" not in st.session_state:
    st.session_state.center_key = "excellent_pharmacy"  # default to your last screenshot

def choose_center(key: str):
    st.session_state.center_key = key

if b1.button("EasyHealth", use_container_width=True):
    choose_center("easyhealth")
if b2.button("Excellent", use_container_width=True):
    choose_center("excellent")
if b3.button("Pharmacy", use_container_width=True):
    choose_center("excellent_pharmacy")

center_key = st.session_state.center_key
center = CENTERS[center_key]
center_dir: Path = center["folder"]
source_path: Path = center_dir / "source.xlsx"
report_path: Path = center_dir / center["report_name"]

st.caption(f"Center: **{center['title']}** · Input: `source.xlsx` · Report: `{center['report_name']}`")

# --------------------------- Admin / View actions ---------------------------
if admin:
    st.subheader("Upload .xlsx")
    uploaded = st.file_uploader("Drag and drop file here", type=["xlsx"], label_visibility="collapsed")
    if uploaded is not None:
        source_path.write_bytes(uploaded.getvalue())
        st.success(f"Saved to {source_path.as_posix()}")

    c1, c2, c3 = st.columns([1, 1, 1])
    with c1:
        if st.button("🔄 Rebuild report", use_container_width=True):
            if not GENERATOR.exists():
                st.error(f"Generator not found: {GENERATOR}")
            elif not source_path.exists():
                st.error("No input found. Upload a source .xlsx first.")
            else:
                ok, log = run_generator(source_path, report_path)
                if ok:
                    st.success(f"Report built: {report_path.name}")
                else:
                    st.error("Build failed. See details below.")
                    st.code(log)
    with c2:
        st.button("📁 Show file locations", use_container_width=True,
                  help=str(center_dir.resolve()))
    with c3:
        if st.button("🗑️ Reset (delete) this center's report", use_container_width=True):
            try:
                if report_path.exists(): report_path.unlink()
                st.success("Report removed for this center.")
            except Exception as e:
                st.error(f"Could not delete report: {e}")
else:
    st.info("View mode: read-only (toggle Admin mode to upload or rebuild).")

# --------------------------- Load report ---------------------------
if not report_path.exists():
    st.info("Report not found for this center. (Upload source and click Rebuild in Admin mode.)")
    st.stop()

# KPI source preference: Insurance_Totals
df_totals = read_sheet_safe(report_path, "Insurance_Totals")
if df_totals is None:
    df_totals = read_sheet_safe(report_path, "Balance_Aging_Summary")

# KPIs — rely on Grand Total row when available
if df_totals is None or df_totals.empty:
    st.error("Could not load totals from the report.")
    st.stop()

kpis = kpis_from_insurance_totals(df_totals)

m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("Net Amount",  money(kpis["net"]))
m2.metric("Paid",        money(kpis["paid"]))
m3.metric("Balance",     money(kpis["bal"]))
m4.metric("Rejected",    money(kpis["rej"]))
m5.metric("Accepted",    money(kpis["acc"]))

# --------------------------- Tabs ---------------------------
tab1, tab2, tab3 = st.tabs(["Insurance_Totals", "Balance_Aging_Summary", "Balance_Aging_Detail"])

with tab1:
    df = read_sheet_safe(report_path, "Insurance_Totals")
    if df is None:
        st.warning("Sheet `Insurance_Totals` not found.")
    else:
        st.caption("Includes a computed **Grand Total** row if the file does not have one.")
        st.dataframe(ensure_grand_total_row(df), use_container_width=True)

with tab2:
    df = read_sheet_safe(report_path, "Balance_Aging_Summary")
    if df is None:
        st.warning("Sheet `Balance_Aging_Summary` not found.")
    else:
        st.dataframe(df, use_container_width=True)

with tab3:
    st.caption("⚡ To keep the app fast, this sheet loads only when requested.")
    if st.checkbox("Load Balance_Aging_Detail"):
        df = read_sheet_safe(report_path, "Balance_Aging_Detail")
        if df is None:
            st.warning("Sheet `Balance_Aging_Detail` not found.")
        else:
            st.dataframe(df, use_container_width=True)
    else:
        st.info("Not loaded.")

