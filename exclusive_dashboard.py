# dashboard.py
import shutil
import subprocess
from pathlib import Path
import pandas as pd
import streamlit as st

# ------------------------------------------------------------
# Page setup
# ------------------------------------------------------------
st.set_page_config(page_title="Exclusive Report with Aging — Dashboard", layout="wide")
BASE = Path(__file__).parent

# ------------------------------------------------------------
# CONFIG — adjust names if yours differ
# ------------------------------------------------------------
GENERATOR = BASE / "exclusive_report_with_aging_final.py"

# If your generator supports: python script.py <source.xlsx> --out <report.xlsx>
GENERATOR_SUPPORTS_OUT_ARG = False  # set True if you add --out to your script

# The default Excel filename your generator writes (used when no --out)
DEFAULT_GENERATED_REPORT = BASE / "Exclusive_Report_with_Aging.xlsx"

CENTERS = {
    "easyhealth": {
        "name": "Easy Health Medical Clinic (MF8031)",
        "source": BASE / "EH_Check3.xlsx",
        "report": BASE / "Exclusive_Report_with_Aging_EASYHEALTH.xlsx",
        "sheets": {
            "totals": "Insurance Totals",
            "summary": "Balance Aging Summary",
            "detail": "Balance Aging Detail",
        },
    },
    "excellent": {
        "name": "Excellent Medical Center (MF4777)",
        "source": BASE / "Check3.xlsx",
        "report": BASE / "Exclusive_Report_with_Aging_EXCELLENT.xlsx",
        "sheets": {
            "totals": "Insurance Totals",
            "summary": "Balance Aging Summary",
            "detail": "Balance Aging Detail",
        },
    },
}

# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------
def mtime_token(p: Path) -> float:
    try:
        return p.stat().st_mtime
    except FileNotFoundError:
        return 0.0

@st.cache_data(show_spinner=True)
def load_report(path: str, totals_sheet: str, summary_sheet: str, detail_sheet: str, _token: float):
    xls = pd.ExcelFile(path)
    totals  = xls.parse(totals_sheet)
    summary = xls.parse(summary_sheet)
    detail  = xls.parse(detail_sheet)
    return totals, summary, detail

def show_kpis(totals: pd.DataFrame):
    val = lambda c: float(totals[c].sum()) if c in totals else 0.0
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Net Amount", f"{val('Net Amount'):,.2f}")
    c2.metric("Paid", f"{val('Paid'):,.2f}")
    c3.metric("Balance", f"{val('Balance'):,.2f}")
    c4.metric("Rejected", f"{val('Rejected'):,.2f}")
    c5.metric("Accepted", f"{val('Accepted'):,.2f}")

def rebuild_report(cfg) -> str:
    src = str(cfg["source"])
    out = str(cfg["report"])
    if GENERATOR_SUPPORTS_OUT_ARG:
        res = subprocess.run(["python", str(GENERATOR), src, "--out", out],
                             capture_output=True, text=True)
        if res.returncode != 0:
            raise RuntimeError(res.stderr or "Generator failed")
        return res.stdout or "OK"
    else:
        res = subprocess.run(["python", str(GENERATOR), src],
                             capture_output=True, text=True)
        if res.returncode != 0:
            raise RuntimeError(res.stderr or "Generator failed")
        if not DEFAULT_GENERATED_REPORT.exists():
            raise RuntimeError(f"Expected output not found: {DEFAULT_GENERATED_REPORT.name}")
        shutil.copyfile(DEFAULT_GENERATED_REPORT, out)
        return res.stdout or "OK"

# ------------------------------------------------------------
# Routing (buttons → center, optional admin mode)
# ------------------------------------------------------------
qp = st.query_params

# Normalize mode + center from URL
mode = (qp.get("mode", ["view"])[0] or "view").strip().lower()
if mode not in ("view", "admin"):
    mode = "view"

center_key = qp.get("center", [None])[0]
center_key = (center_key or "").strip().lower()
if center_key == "":
    center_key = None

# Debug/status line so you can SEE the state (remove later if you want)
st.caption(f"Mode: **{mode}** · Center: **{center_key or 'none'}**")

# If no center chosen yet → show two big buttons and stop
if center_key not in CENTERS:
    st.title("📊 Exclusive Report with Aging — Dashboard")
    st.subheader("Choose a center")

    # Preserve mode when clicking a button
    current_mode = (st.query_params.get("mode", ["view"])[0] or "view").strip().lower()

    c1, c2 = st.columns(2)
    with c1:
        if st.button(CENTERS["easyhealth"]["name"], use_container_width=True):
            st.query_params.update(center="easyhealth", mode=current_mode)
            st.rerun()
    with c2:
        if st.button(CENTERS["excellent"]["name"], use_container_width=True):
            st.query_params.update(center="excellent", mode=current_mode)
            st.rerun()

    st.stop()

# Selected center
cfg = CENTERS[center_key]
st.title("📊 Exclusive Report with Aging — Dashboard")

# Admin badge so you KNOW you're in admin
if mode == "admin":
    st.success("You are in **ADMIN** mode — upload/rebuild is enabled.")

st.caption(f"Center: **{cfg['name']}**  ·  Input: {cfg['source'].name}  ·  Report: {cfg['report'].name}")

# Back button (preserves mode)
if st.button("◀ Choose another center"):
    current_mode = (st.query_params.get("mode", ["view"])[0] or "view").strip().lower()
    st.query_params.clear()
    st.query_params.update(mode=current_mode)
    st.rerun()

# ------------------------------------------------------------
# ADMIN (only when URL has ?mode=admin)
# ------------------------------------------------------------
if mode == "admin":
    with st.expander("⬆️ Upload/replace source Excel", expanded=False):
        up = st.file_uploader("Upload .xlsx", type=["xlsx"])
        if up:
            cfg["source"].write_bytes(up.read())
            st.success(f"Saved to {cfg['source'].name}")

    colA, colB = st.columns(2)
    if colA.button("↻ Rebuild report", use_container_width=True):
        try:
            out = rebuild_report(cfg)
            st.success("Report rebuilt successfully.")
            if out.strip():
                st.code(out, language="bash")
            load_report.clear()
        except Exception as e:
            st.error(str(e))

    if colB.button("🗂 Show file locations", use_container_width=True):
        st.info(f"Source: {cfg['source']}\nReport: {cfg['report']}\nScript: {GENERATOR}")

# ------------------------------------------------------------
# Viewer (KPIs + tables)
# ------------------------------------------------------------
token = mtime_token(cfg["report"])
if token == 0.0:
    st.warning("Report not found. (Open with ?mode=admin to upload source and rebuild.)")
else:
    totals, summary, detail = load_report(
        str(cfg["report"]),
        cfg["sheets"]["totals"],
        cfg["sheets"]["summary"],
        cfg["sheets"]["detail"],
        token,
    )
    show_kpis(totals)
    t1, t2, t3 = st.tabs(["Insurance Totals", "Balance Aging Summary", "Balance Aging Detail"])
    with t1:
        st.dataframe(totals, use_container_width=True, hide_index=True)
    with t2:
        st.dataframe(summary, use_container_width=True, hide_index=True)
    with t3:
        st.dataframe(detail, use_container_width=True, hide_index=True)


