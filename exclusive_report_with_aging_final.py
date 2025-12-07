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

GENERATOR = BASE / "exclusive_report_with_aging_final.py"

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
    """Invoke your generator with required --out arg and capture full logs."""
    cmd = [sys.executable, str(GENERATOR), "--out", str(out_xlsx), str(source_xlsx)]
    p = subprocess.run(cmd, capture_output=True, text=True)
    ok = p.returncode == 0
    log = (
        "Command: " + " ".join(p.args)
        + "\n\nSTDOUT:\n" + (p.stdout or "(empty)")
        + "\n\nSTDERR:\n" + (p.stderr or "(empty)")
    )
    return ok, log

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
    """Map likely column names → canonical keys."""
    candidates = {
        "net":  ["Net Amount", "NetAmount", "ActivityIns", "Net_Amount", "Net"],
        "paid": ["Paid", "Paid Amount", "PaidAmount", "Paid_Amount"],
        "bal":  ["Balance", "Pending", "Pending Balance", "Outstanding"],
        "rej":  ["Rejected", "Rejection", "Rejections"],
        "acc_amt": ["Accepted Amount", "AcceptedAmount", "Accepted_Amt"],  # explicit amount
        "acc":  ["Accepted", "Approval", "Approvals", "Approved"],         # may be counts
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

def _pick_label_col(df: pd.DataFrame) -> Optional[str]:
    for c in df.columns:
        if df[c].dtype == object:
            return c
    return None

def _grand_total_row(df: pd.DataFrame) -> Optional[pd.DataFrame]:
    lbl = _pick_label_col(df)
    if lbl is None:
        return None
    mask = df[lbl].astype(str).str.strip().str.lower().isin(
        ["grand total", "total", "totals", "grand_total"]
    )
    if mask.any():
        return df.loc[mask].tail(1)
    return None

def ensure_grand_total_row(df: pd.DataFrame) -> pd.DataFrame:
    """
    Make sure Insurance_Totals has exactly one Grand Total row at the end.
    If a GT row exists, re-compute and move it to the bottom.
    """
    if df is None or df.empty:
        return df

    label_col = _pick_label_col(df)
    if label_col is None:
        return df

    # Drop any existing total row(s)
    mask_gt = df[label_col].astype(str).str.strip().str.lower().isin(
        ["grand total", "grand_total", "totals", "total"]
    )
    df_no_gt = df.loc[~mask_gt].copy()

    # Build totals row
    total_row = {}
    for c in df_no_gt.columns:
        if pd.api.types.is_numeric_dtype(df_no_gt[c]) or to_num(df_no_gt[c]).notna().any():
            total_row[c] = float(to_num(df_no_gt[c]).fillna(0).sum())
        else:
            total_row[c] = "Grand Total"

    return pd.concat([df_no_gt, pd.DataFrame([total_row])], ignore_index=True)

def with_srno(df: pd.DataFrame, label_for_total: str = "Grand Total") -> pd.DataFrame:
    """Insert SrNo starting from 1; blank it for the Grand Total row."""
    if df is None or df.empty:
        return df
    df = df.copy()
    sr = list(range(1, len(df) + 1))
    label_col = _pick_label_col(df)
    if label_col is not None:
        if str(df.iloc[-1][label_col]).strip().lower() == label_for_total.lower():
            sr[-1] = ""
    df.insert(0, "SrNo", sr)
    return df

def kpis_from_totals(df: pd.DataFrame) -> Dict[str, float]:
    """
    KPIs from Insurance_Totals (preferred) or summarized sheet.
    Accepted amount is taken from explicit Accepted Amount column if present;
    otherwise Derived = Net - Paid - Balance - Rejected.
    """
    cols = detect_cols(df)
    grand = _grand_total_row(df)

    def v_from(frame, key):
        col = cols.get(key)
        if not col or col not in frame.columns:
            return 0.0
        return float(to_num(frame[col]).fillna(0).iloc[0])

    def s_from(key):
        col = cols.get(key)
        if not col or col not in df.columns:
            return 0.0
        return float(to_num(df[col]).fillna(0).sum())

    if grand is not None and not grand.empty:
        net = v_from(grand, "net")
        paid = v_from(grand, "paid")
        bal  = v_from(grand, "bal")
        rej  = v_from(grand, "rej")
        if cols.get("acc_amt") and cols["acc_amt"] in grand.columns:
            acc = v_from(grand, "acc_amt")
        else:
            acc = max(0.0, round(net - paid - bal - rej, 2))
        return {"net": net, "paid": paid, "bal": bal, "rej": rej, "acc": acc}

    net = s_from("net"); paid = s_from("paid"); bal = s_from("bal"); rej = s_from("rej")
    if cols.get("acc_amt") and cols["acc_amt"] in df.columns:
        acc = s_from("acc_amt")
    else:
        acc = max(0.0, round(net - paid - bal - rej, 2))
    return {"net": net, "paid": paid, "bal": bal, "rej": rej, "acc": acc}

def money(v: float) -> str:
    return f"{v:,.2f}"

# --------------------------- UI ---------------------------
st.title("📊 Exclusive Report with Aging — Dashboard")

# Admin toggle
mode_col, _ = st.columns([1, 5])
with mode_col:
    admin = st.toggle("Admin mode", value=False)

# Quick center buttons
b1, b2, b3, _sp = st.columns([1, 1, 1, 4])
if "center_key" not in st.session_state:
    st.session_state.center_key = "excellent"

def choose_center(k): st.session_state.center_key = k
if b1.button("EasyHealth", use_container_width=True): choose_center("easyhealth")
if b2.button("Excellent",  use_container_width=True): choose_center("excellent")
if b3.button("Pharmacy",   use_container_width=True): choose_center("excellent_pharmacy")

center_key = st.session_state.center_key
center = CENTERS[center_key]
center_dir = center["folder"]
source_path = center_dir / "source.xlsx"
report_path = center_dir / center["report_name"]

st.caption(f"Center: **{center['title']}** · Input: `source.xlsx` · Report: `{center['report_name']}`")

# --------------------------- Admin / View actions ---------------------------
if admin:
    st.subheader("Upload .xlsx")
    up = st.file_uploader("Drag and drop file here", type=["xlsx"], label_visibility="collapsed")
    if up is not None:
        source_path.write_bytes(up.getvalue())
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
                    st.success(f"✅ Report built: {report_path.name}")
                else:
                    st.error("❌ Build failed. See details below:")
                st.code(log, language="bash")  # <-- SHOW FULL LOG
    with c2:
        st.button("📁 Show file locations", use_container_width=True, help=str(center_dir.resolve()))
    with c3:
        if st.button("🗑️ Reset (delete) this center's report", use_container_width=True):
            try:
                if report_path.exists(): report_path.unlink()
                st.success("Report removed.")
            except Exception as e:
                st.error(f"Could not delete report: {e}")
else:
    st.info("View mode: read-only (toggle Admin mode to upload or rebuild).")

# --------------------------- Load report ---------------------------
if not report_path.exists():
    st.info("Report not found for this center. (Upload source and click Rebuild in Admin mode.)")
    st.stop()

# KPIs from Insurance_Totals preferred
df_totals = read_sheet_safe(report_path, "Insurance_Totals")
if df_totals is None or df_totals.empty:
    df_totals = read_sheet_safe(report_path, "Balance_Aging_Summary")

if df_totals is None or df_totals.empty:
    st.error("Could not load totals from the report.")
    st.stop()

kpis = kpis_from_totals(df_totals)
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
        st.caption("Includes a computed **Grand Total** row at the bottom.")
        df_display = ensure_grand_total_row(df)
        df_display = with_srno(df_display)  # SrNo from 1; blank at Grand Total
        st.dataframe(df_display, use_container_width=True, hide_index=True)

with tab2:
    df = read_sheet_safe(report_path, "Balance_Aging_Summary")
    if df is None:
        st.warning("Sheet `Balance_Aging_Summary` not found.")
    else:
        st.dataframe(with_srno(df), use_container_width=True, hide_index=True)

with tab3:
    st.caption("⚡ To keep the app fast, this sheet loads only when requested.")
    if st.checkbox("Load Balance_Aging_Detail"):
        df = read_sheet_safe(report_path, "Balance_Aging_Detail")
        if df is None:
            st.warning("Sheet `Balance_Aging_Detail` not found.")
        else:
            st.dataframe(with_srno(df), use_container_width=True, hide_index=True)
    else:
        st.info("Not loaded.")

