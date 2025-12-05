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
GENERATOR_SUPPORTS_OUT_ARG = True          # your script now requires --out
DEFAULT_GENERATED_REPORT = BASE / "Exclusive_Report_with_Aging.xlsx"  # fallback only

CENTERS = {
    "easyhealth": {
        "name": "Easy Health Medical Clinic (MF8031)",
        "source": BASE / "EH_Check3.xlsx",
        "report": BASE / "Exclusive_Report_with_Aging_EASYHEALTH.xlsx",
        # kept for reference, but loader now auto-detects:
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

def _run(cmd):
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
    """Run the generator using the SAME Python interpreter as Streamlit, pass --out correctly."""
    src, out = str(cfg["source"]), str(cfg["report"])
    py = sys.executable
    if GENERATOR_SUPPORTS_OUT_ARG:
        # your script usage (from error): exclusive_report_with_aging_final.py --out OUT_XLSX input_xlsx
        try:
            res = _run([py, str(GENERATOR), "--out", out, src])
            return res.stdout or "OK"
        except Exception as e_first:
            res = _run([py, str(GENERATOR), src, "--out", out])  # alternate ordering
            return res.stdout or "OK"
    else:
        res = _run([py, str(GENERATOR), src])
        if not DEFAULT_GENERATED_REPORT.exists():
            raise RuntimeError(f"Expected output not found: {DEFAULT_GENERATED_REPORT.name}")
        shutil.copyfile(DEFAULT_GENERATED_REPORT, out)
        return res.stdout or "OK"

def _pick_sheet(sheet_names, wants):
    """
    Find best match for a logical sheet among workbook sheet_names.
    wants: list of keywords to look for (lowercased)
    """
    lower = [s.lower() for s in sheet_names]
    # perfect contains-all match by keywords
    for i, s in enumerate(lower):
        if all(w in s for w in wants):
            return sheet_names[i]
    # partial fallback: any one keyword
    for i, s in enumerate(lower):
        if any(w in s for w in wants):
            return sheet_names[i]
    return None

def autodetect_sheets(xls: pd.ExcelFile):
    """
    Tries to find the three sheets by common names/keywords.
    Returns (totals, summary, detail) exact sheet names, or raises ValueError with guidance.
    """
    names = xls.sheet_names
    totals  = _pick_sheet(names, ["total"]) or _pick_sheet(names, ["insurance"]) or _pick_sheet(names, ["summary total"])
    summary = _pick_sheet(names, ["aging", "summary"]) or _pick_sheet(names, ["summary"])
    detail  = _pick_sheet(names, ["aging", "detail"])  or _pick_sheet(names, ["detail"])

    missing = []
    if not totals:  missing.append("Totals (e.g., 'Insurance Totals' / 'Totals')")
    if not summary: missing.append("Aging Summary (e.g., 'Balance Aging Summary')")
    if not detail:  missing.append("Aging Detail (e.g., 'Balance Aging Detail')")

    if missing:
        raise ValueError(
            "Worksheet(s) not found: " + ", ".join(missing) +
            f".\nFound sheets: {', '.join(names)}"
        )
    return totals, summary, detail

@st.cache_data(show_spinner=True)
def load_report_auto(path: str, _token: float):
    """
    Open the Excel once, auto-detect the three relevant sheets, and return dataframes.
    """
    xls = pd.ExcelFile(path)
    totals_name, summary_name, detail_name = autodetect_sheets(xls)
    totals  = xls.parse(totals_name)
    summary = xls.parse(summary_name)
    detail  = xls.parse(detail_name)
    return totals, summary, detail, totals_name, summary_name, detail_name

def show_kpis(totals: pd.DataFrame):
    def v(col): 
        try: return float(totals[col].sum())
        except Exception: return 0.0
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Net Amount", f"{v('Net Amount'):,.2f}")
    c2.metric("Paid", f"{v('Paid'):,.2f}")
    c3.metric("Balance", f"{v('Balance'):,.2f}")
    c4.metric("Rejected", f"{v('Rejected'):,.2f}")
    c5.metric("Accepted", f"{v('Accepted'):,.2f}")

# ------------------------------------------------------------
# State: admin toggle + center selection
# ------------------------------------------------------------
if "is_admin" not in st.session_state:
    st.session_state.is_admin = False  # default view-only
if "center_key" not in st.session_state:
    st.session_state.center_key = None

# Header row: title + admin toggle
left, right = st.columns([5, 1])
with left:
    st.title("📊 Exclusive Report with Aging — Dashboard")
with right:
    st.session_state.is_admin = st.toggle("Admin mode", value=st.session_state.is_admin)

# Status (optional)
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
            st.session_state.center_key = "easyhealth"; st.rerun()
    with c2:
        if st.button(CENTERS["excellent"]["name"], use_container_width=True):
            st.session_state.center_key = "excellent"; st.rerun()
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
            msg = rebuild_report(cfg)
            st.success("Report rebuilt successfully.")
            if msg.strip(): st.code(msg, language="bash")
            load_report_auto.clear()
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
    if st.session_state.is_admin: msg += " (Upload source and click Rebuild.)"
    st.warning(msg)
else:
    try:
        totals, summary, detail, s_tot, s_sum, s_det = load_report_auto(str(cfg["report"]), token)
        show_kpis(totals)
        t1, t2, t3 = st.tabs([f"{s_tot}", f"{s_sum}", f"{s_det}"])
        with t1: st.dataframe(totals,  use_container_width=True, hide_index=True)
        with t2: st.dataframe(summary, use_container_width=True, hide_index=True)
        with t3: st.dataframe(detail,  use_container_width=True, hide_index=True)
    except Exception as e:
        # show sheet names to help if workbook is very differently named
        try:
            names = pd.ExcelFile(str(cfg["report"])).sheet_names
        except Exception:
            names = []
        st.error(f"{e}\n\nAvailable sheets: {', '.join(names) if names else '(could not read)'}")

