# dashboard.py
import sys
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
# CONFIG — adjust names if needed
# ------------------------------------------------------------
GENERATOR = BASE / "exclusive_report_with_aging_final.py"
GENERATOR_SUPPORTS_OUT_ARG = False  # set True if your generator accepts --out <report.xlsx>
DEFAULT_GENERATED_REPORT = BASE / "Exclusive_Report_with_Aging.xlsx"

CENTERS = {
    "easyhealth": {
        "name": "Easy Health Medical Clinic (MF8031)",
        "source": BASE / "EH_Check3.xlsx",
        "report": BASE / "Exclusive_Report_with_Aging_EASYHEALTH.xlsx",
        "sheets": {"totals": "Insurance Totals", "summary": "Balance Aging Summary", "detail": "Balance Aging Detail"},
    },
    "excellent": {
        "name": "Excellent Medical Center (MF4777)",
        "source": BASE / "Check3.xlsx",
        "report": BASE / "Exclusive_Report_with_Aging_EXCELLENT.xlsx",
        "sheets": {"totals": "Insurance Totals", "summary": "Balance Aging Summary", "detail": "Balance Aging Detail"},
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
    return xls.parse(totals_sheet), xls.parse(summary_sheet), xls.parse(detail_sheet)

def show_kpis(totals: pd.DataFrame):
    v = lambda c: float(totals[c].sum()) if c in totals else 0.0
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Net Amount", f"{v('Net Amount'):,.2f}")
    c2.metric("Paid", f"{v('Paid'):,.2f}")
    c3.metric("Balance", f"{v('Balance'):,.2f}")
    c4.metric("Rejected", f"{v('Rejected'):,.2f}")
    c5.metric("Accepted", f"{v('Accepted'):,.2f}")

def _run(cmd):
    """Run a command and return CompletedProcess; show the exact command if it fails."""
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(
            "Command failed:\n"
            + " ".join(cmd)
            + "\n\nSTDOUT:\n" + (res.stdout or "(empty)")
            + "\n\nSTDERR:\n" + (res.stderr or "(empty)")
        )
    return res

def rebuild_report(cfg) -> str:
    """
    Run the generator to produce the report for the selected center,
    using the SAME Python interpreter as Streamlit.
    """
    src, out = str(cfg["source"]), str(cfg["report"])
    py = sys.executable  # <-- critical fix: use current env so pandas/openpyxl are available
    if GENERATOR_SUPPORTS_OUT_ARG:
        res = _run([py, str(GENERATOR), src, "--out", out])
        return res.stdout or "OK"
    else:
        res = _run([py, str(GENERATOR), src])
        if not DEFAULT_GENERATED_REPORT.exists():
            raise RuntimeError(f"Expected output not found: {DEFAULT_GENERATED_REPORT.name}")
        shutil.copyfile(DEFAULT_GENERATED_REPORT, out)
        return res.stdout or "OK"

# ------------------------------------------------------------
# State: admin toggle + center selection
# ------------------------------------------------------------
if "is_admin" not in st.session_state:
    st.session_state.is_admin = False  # default view-only

if "center_key" not in st.session_state:
    st.session_state.center_key = None

# Header row: title + admin toggle on the right
left, right = st.columns([5, 1])
with left:
    st.title("📊 Exclusive Report with Aging — Dashboard")
with right:
    st.session_state.is_admin = st.toggle("Admin mode", value=st.session_state.is_admin)

# Status line (optional)
st.caption(f"Mode: **{'admin' if st.session_state.is_admin else 'view'}** · Center: **{st.session_state.center_key or 'none'}**")

# ------------------------------------------------------------
# Center chooser (two big buttons)
# ------------------------------------------------------------
center_key = st.session_state.center_key
if center_key not in CENTERS:
    st.subheader("Choose a center")
    c1, c2 = st.columns(2)
    with c1:
        if st.button(CENTERS["easyhealth"]["name"], use_container_width=True):
            st.session_state.center_key = "easyhealth"
            st.rerun()
    with c2:
        if st.button(CENTERS["excellent"]["name"], use_container_width=True):
            st.session_state.center_key = "excellent"
            st.rerun()
    st.stop()

# ------------------------------------------------------------
# Selected center view
# ------------------------------------------------------------
cfg = CENTERS[st.session_state.center_key]

if st.session_state.is_admin:
    st.success("You are in **ADMIN** mode — upload/rebuild is enabled.")

st.caption(f"Center: **{cfg['name']}**  ·  Input: {cfg['source'].name}  ·  Report: {cfg['report'].name}")

# Back button
if st.button("◀ Choose another center"):
    st.session_state.center_key = None
    st.rerun()

# ------------------------------------------------------------
# ADMIN tools (only when toggled)
# ------------------------------------------------------------
if st.session_state.is_admin:
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
# VIEWER
# ------------------------------------------------------------
token = mtime_token(cfg["report"])
if token == 0.0:
    msg = "Report not found."
    if st.session_state.is_admin:
        msg += " (Upload source and click Rebuild.)"
    st.warning(msg)
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


