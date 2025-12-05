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
DATA_DIR = BASE / "data"
(DATA_DIR / "easyhealth").mkdir(parents=True, exist_ok=True)
(DATA_DIR / "excellent").mkdir(parents=True, exist_ok=True)

# ------------------------------------------------------------
# CONFIG — generator
# ------------------------------------------------------------
GENERATOR = BASE / "exclusive_report_with_aging_final.py"
GENERATOR_SUPPORTS_OUT_ARG = True  # your script requires --out

# Per-center files are now in separate subfolders
CENTERS = {
    "easyhealth": {
        "name": "Easy Health Medical Clinic (MF8031)",
        "folder": DATA_DIR / "easyhealth",
        "src_name": "source.xlsx",   # saved as data/easyhealth/source.xlsx
        "out_name": "report.xlsx",   # saved as data/easyhealth/report.xlsx
    },
    "excellent": {
        "name": "Excellent Medical Center (MF4777)",
        "folder": DATA_DIR / "excellent",
        "src_name": "source.xlsx",
        "out_name": "report.xlsx",
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

def rebuild_report(src_path: Path, out_path: Path) -> str:
    """Run your generator with --out using the SAME Python interpreter as Streamlit."""
    py = sys.executable
    out_path.parent.mkdir(parents=True, exist_ok=True)
    src = str(src_path)
    out = str(out_path)
    # your script usage (seen in error earlier):  --out OUT_XLSX input_xlsx
    try:
        res = _run([py, str(GENERATOR), "--out", out, src])
        return res.stdout or "OK"
    except Exception:
        res = _run([py, str(GENERATOR), src, "--out", out])  # alternate order
        return res.stdout or "OK"

def _pick_sheet(sheet_names, wants):
    lower = [s.lower() for s in sheet_names]
    for i, s in enumerate(lower):
        if all(w in s for w in wants):
            return sheet_names[i]
    for i, s in enumerate(lower):
        if any(w in s for w in wants):
            return sheet_names[i]
    return None

def autodetect_sheets(xls: pd.ExcelFile):
    names = xls.sheet_names
    totals  = _pick_sheet(names, ["total"]) or _pick_sheet(names, ["insurance"]) or _pick_sheet(names, ["summary total"])
    summary = _pick_sheet(names, ["aging", "summary"]) or _pick_sheet(names, ["summary"])
    detail  = _pick_sheet(names, ["aging", "detail"])  or _pick_sheet(names, ["detail"])
    missing = []
    if not totals:  missing.append("Totals (e.g., 'Insurance Totals')")
    if not summary: missing.append("Aging Summary (e.g., 'Balance Aging Summary')")
    if not detail:  missing.append("Aging Detail (e.g., 'Balance Aging Detail')")
    if missing:
        raise ValueError("Worksheet(s) not found: " + ", ".join(missing) + f". Found sheets: {', '.join(names)}")
    return totals, summary, detail

@st.cache_data(show_spinner=True)
def load_report_auto(path: str, _token: float):
    xls = pd.ExcelFile(path)
    totals_name, summary_name, detail_name = autodetect_sheets(xls)
    totals  = xls.parse(totals_name)
    summary = xls.parse(summary_name)
    detail  = xls.parse(detail_name)
    return totals, summary, detail, totals_name, summary_name, detail_name

def show_kpis(totals: pd.DataFrame):
    def v(col):
        try:
            return float(totals[col].sum())
        except Exception:
            return 0.0
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
    st.session_state.is_admin = False
if "center_key" not in st.session_state:
    st.session_state.center_key = None
if "last_center_key" not in st.session_state:
    st.session_state.last_center_key = None

# Header row: title + admin toggle
left, right = st.columns([5, 1])
with left:
    st.title("📊 Exclusive Report with Aging — Dashboard")
with right:
    st.session_state.is_admin = st.toggle("Admin mode", value=st.session_state.is_admin)

# If the user changed centers, clear the cache to avoid any confusion
if st.session_state.center_key != st.session_state.last_center_key:
    load_report_auto.clear()
    st.session_state.last_center_key = st.session_state.center_key

# Status
st.caption(f"Mode: **{'admin' if st.session_state.is_admin else 'view'}** · Center: **{st.session_state.center_key or 'none'}**")

# ------------------------------------------------------------
# Center chooser
# ------------------------------------------------------------
ck = st.session_state.center_key
if ck not in CENTERS:
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
folder   = cfg["folder"]
src_path = folder / cfg["src_name"]
out_path = folder / cfg["out_name"]

if st.session_state.is_admin:
    st.success("You are in **ADMIN** mode — upload/rebuild is enabled.")
st.caption(f"Center: **{cfg['name']}**  ·  Input: {src_path.name}  ·  Report: {out_path.name}")

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
            folder.mkdir(parents=True, exist_ok=True)
            src_path.write_bytes(up.read())
            st.success(f"Saved to {src_path}")

    colA, colB, colC = st.columns(3)
    if colA.button("↻ Rebuild report", use_container_width=True):
        try:
            msg = rebuild_report(src_path, out_path)
            st.success("Report rebuilt successfully.")
            if msg.strip():
                st.code(msg, language="bash")
            load_report_auto.clear()
        except Exception as e:
            st.error(str(e))

    if colB.button("🗂 Show file locations", use_container_width=True):
        st.info(f"Source: {src_path}\nReport: {out_path}\nScript: {GENERATOR}")

    if colC.button("🗑 Reset (delete) this center's report", use_container_width=True):
        try:
            if out_path.exists():
                out_path.unlink()
            st.success("Report deleted for this center.")
            load_report_auto.clear()
        except Exception as e:
            st.error(str(e))

# ------------------------------------------------------------
# VIEWER
# ------------------------------------------------------------
token = mtime_token(out_path)
if token == 0.0:
    msg = "Report not found for this center."
    if st.session_state.is_admin:
        msg += " (Upload a source file and click Rebuild.)"
    st.warning(msg)
else:
    try:
        totals, summary, detail, s_tot, s_sum, s_det = load_report_auto(str(out_path), token)
        show_kpis(totals)
        t1, t2, t3 = st.tabs([f"{s_tot}", f"{s_sum}", f"{s_det}"])
        with t1: st.dataframe(totals,  use_container_width=True, hide_index=True)
        with t2: st.dataframe(summary, use_container_width=True, hide_index=True)
        with t3: st.dataframe(detail,  use_container_width=True, hide_index=True)
    except Exception as e:
        try:
            names = pd.ExcelFile(str(out_path)).sheet_names
        except Exception:
            names = []
        st.error(f"{e}\n\nAvailable sheets: {', '.join(names) if names else '(could not read)'}")

