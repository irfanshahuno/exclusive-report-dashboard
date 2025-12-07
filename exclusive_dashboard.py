# exclusive_dashboard.py
import sys
import subprocess
from pathlib import Path
from typing import Dict, Optional, List

import pandas as pd
import streamlit as st

# --------------------------- Page setup ---------------------------
st.set_page_config(page_title="Exclusive Report with Aging — Dashboard", layout="wide")
BASE = Path(__file__).parent.resolve()

# Where the generator lives
GENERATOR = BASE / "exclusive_report_with_aging_final.py"

# Data directories for each center
DATA_DIR = BASE / "data"
CENTERS = {
    "easyhealth": {
        "title": "Easy Health Medical Clinic (MF8031)",
        "folder": DATA_DIR / "easyhealth",
        # Output Excel file name produced by the generator for this center
        "report_name": "Exclusive_Report_with_Aging.xlsx",
    },
    "excellent": {
        "title": "Excellent Medical Center (MF4777)",
        "folder": DATA_DIR / "excellent",
        "report_name": "Exclusive_Report_with_Aging.xlsx",
    },
    "excellent_pharmacy": {
        "title": "Excellent Pharmacy (PF3205)",
        "folder": DATA_DIR / "excellent_pharmacy",
        # Your pharmacy generator produces this name (per your screenshot)
        "report_name": "Pharmacy_Exclusive_Report_with_Aging.xlsx",
    },
}

# Ensure folders exist
for c in CENTERS.values():
    c["folder"].mkdir(parents=True, exist_ok=True)

# --------------------------- Helpers ---------------------------
def run_generator(source_xlsx: Path, out_xlsx: Path) -> subprocess.CompletedProcess:
    """
    Call the generator with the correct CLI signature.
    The script's usage is:  exclusive_report_with_aging_final.py --out OUT_XLSX input_xlsx
    """
    cmd = [
        sys.executable,
        str(GENERATOR),
        "--out",
        str(out_xlsx),
        str(source_xlsx),
    ]
    return subprocess.run(cmd, capture_output=True, text=True, check=False)

def read_sheet_safe(xlsx_path: Path, sheet_name: str) -> Optional[pd.DataFrame]:
    if not xlsx_path.exists():
        return None
    try:
        return pd.read_excel(xlsx_path, sheet_name=sheet_name, engine="openpyxl")
    except Exception:
        return None

def detect_cols(df: pd.DataFrame) -> Dict[str, Optional[str]]:
    """
    Try to map common metric column names.
    """
    candidates = {
        "net": ["Net Amount", "NetAmount", "Net_Amount", "ActivityIns", "Net"],
        "paid": ["Paid", "Paid Amount", "PaidAmount", "Paid_Amount"],
        "bal": ["Balance", "Pending", "Pending Balance", "Outstanding"],
        "rej": ["Rejected", "Rejection", "Rejections"],
        "acc": ["Accepted", "Approval", "Approvals"],
    }
    found = {}
    lower_cols = {c.lower(): c for c in df.columns}
    for key, names in candidates.items():
        hit = None
        for n in names:
            if n in df.columns:
                hit = n
                break
            if n.lower() in lower_cols:
                hit = lower_cols[n.lower()]
                break
        found[key] = hit
    return found

def sum_metric(df: Optional[pd.DataFrame], col: Optional[str]) -> float:
    if df is None or col is None or col not in (df.columns if df is not None else []):
        return 0.0
    return float(pd.to_numeric(df[col], errors="coerce").fillna(0).sum())

def format_money(v: float) -> str:
    return f"{v:,.2f}"

# --------------------------- UI ---------------------------
st.title("📊 Exclusive Report with Aging — Dashboard")

left, right = st.columns([1, 1])
with left:
    st.caption("Mode:")
    admin = st.toggle("Admin mode", value=False)

with right:
    st.caption("Center:")
    center_key = st.selectbox(
        "Choose another center",
        options=list(CENTERS.keys()),
        format_func=lambda k: CENTERS[k]["title"],
        label_visibility="collapsed",
    )

center = CENTERS[center_key]
center_dir: Path = center["folder"]
source_path: Path = center_dir / "source.xlsx"
report_path: Path = center_dir / center["report_name"]

st.write(
    f"*Center:* **{CENTERS[center_key]['title']}** · *Input:* `source.xlsx` · "
    f"*Report:* `{center['report_name']}`"
)

# --------------------------- Upload & Actions ---------------------------
st.subheader("Upload .xlsx")
uploaded = st.file_uploader(
    "Drag and drop file here", type=["xlsx"], accept_multiple_files=False, label_visibility="collapsed"
)
if uploaded is not None:
    source_path.write_bytes(uploaded.getvalue())
    st.success(f"Saved to `{source_path.as_posix()}`")

btn_col1, btn_col2, btn_col3 = st.columns([1, 1, 1])

with btn_col1:
    if st.button("🔄 Rebuild report", use_container_width=True):
        if not source_path.exists():
            st.error("No input found. Upload a source .xlsx first.")
        elif not GENERATOR.exists():
            st.error(f"Generator not found: {GENERATOR.name}")
        else:
            proc = run_generator(source_path, report_path)
            if proc.returncode == 0:
                st.success(f"Report built: `{report_path.name}`")
            else:
                st.error(
                    "Command failed:\n\n"
                    + "```\n"
                    + " ".join(proc.args)
                    + "\n```\n\nSTDOUT:\n```\n"
                    + (proc.stdout or "(empty)")
                    + "\n```\n\nSTDERR:\n```\n"
                    + (proc.stderr or "(empty)")
                    + "\n```"
                )

with btn_col2:
    st.button("📁 Show file locations", use_container_width=True,
              help=str(center_dir.resolve()))

with btn_col3:
    if admin and st.button("🗑️ Reset (delete) this center's report", use_container_width=True):
        try:
            if report_path.exists():
                report_path.unlink()
            st.success("Report removed for this center.")
        except Exception as e:
            st.error(f"Could not delete report: {e}")

# --------------------------- Load summary to show KPIs ---------------------------
if not report_path.exists():
    st.info("Report not found for this center. (Upload source and click Rebuild.)")
    st.stop()

# Prefer using Insurance_Totals for headline numbers; if absent, fall back to Balance_Aging_Summary
df_totals = read_sheet_safe(report_path, "Insurance_Totals")
if df_totals is None:
    df_totals = read_sheet_safe(report_path, "Balance_Aging_Summary")

cols_map = detect_cols(df_totals if df_totals is not None else pd.DataFrame())

kpi_net = sum_metric(df_totals, cols_map.get("net"))
kpi_paid = sum_metric(df_totals, cols_map.get("paid"))
kpi_bal = sum_metric(df_totals, cols_map.get("bal"))
kpi_rej = sum_metric(df_totals, cols_map.get("rej"))
kpi_acc = sum_metric(df_totals, cols_map.get("acc"))

m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("Net Amount", format_money(kpi_net))
m2.metric("Paid", format_money(kpi_paid))
m3.metric("Balance", format_money(kpi_bal))
m4.metric("Rejected", format_money(kpi_rej))
m5.metric("Accepted", format_money(kpi_acc))

# --------------------------- Tabs (lazy load for Detail) ---------------------------
tab1, tab2, tab3 = st.tabs(["Insurance_Totals", "Balance_Aging_Summary", "Balance_Aging_Detail"])

with tab1:
    df = read_sheet_safe(report_path, "Insurance_Totals")
    if df is None:
        st.warning("Sheet `Insurance_Totals` not found.")
    else:
        st.dataframe(df, use_container_width=True)

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


