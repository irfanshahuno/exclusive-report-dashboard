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

def rebuild_report(cfg) -> str:
    src, out = str(cfg["source"]), str(cfg["report"])
    if GENERATOR_SUPPORTS_OUT_ARG:
        r = subprocess.run(["python", str(GENERATOR), src, "--out", out], capture_output=True, text=True)
        if r.returncode: raise RuntimeError(r.stderr or "Generator failed")
        return r.stdout or "OK"
    else:
        r = subprocess.run(["python", str(GENERATOR), src], capture_output=True, text=True)
        if r.returncode: raise RuntimeError(r.stderr or "Generator failed")
        if not DEFAULT_GENERATED_REPORT.exists():
            raise RuntimeError(f"Expected output not found: {DEFAULT_GENERATED_REPORT.name}")
        shutil.copyfile(DEFAULT_GENERATED_REPORT, out)
        return r.stdout or "OK"

# ------------------------------------------------------------
# MODE + CENTER (robust: use session_state)
# ------------------------------------------------------------
qp = st.query_params

# Initialize session_state flags once
if "is_admin" not in st.session_state:
    # Accept either ?mode=admin or ?admin=1 to turn admin on from URL
    url_mode = (qp.get("mode", ["view"])[0] or "view").strip().lower()
    url_admin = (qp.get("admin", ["0"])[0] or "0").strip()
    st.session_state.is_admin = (url_mode == "admin") or (url_admin in ("1", "true", "yes"))

if "center_key" not in st.session_state:
    ck = qp.get("center", [None])[0]
    st.session_state.center_key = (ck or "").strip().lower() or None

is_admin = bool(st.session_state.is_admin)
center_key = st.session_state.center_key

# Status line (you can remove later)
st.caption(f"Mode: **{'admin' if is_admin else 'view'}** · Center: **{center_key or 'none'}**")

# ------------------------------------------------------------
# Center chooser (two big buttons)
# ------------------------------------------------------------
if center_key not in CENTERS:
    st.title("📊 Exclusive Report with Aging — Dashboard")
    st.subheader("Choose a center")

    c1, c2 = st.columns(2)
    with c1:
        if st.button(CENTERS["easyhealth"]["name"], use_container_width=True):
            st.session_state.center_key = "easyhealth"
            # keep URL clean; also keep admin flag in URL if you came with it
            new = {"center": "easyhealth"}
            if is_admin: new["mode"] = "admin"
            st.query_params.update(**new)
            st.rerun()
    with c2:
        if st.button(CENTERS["excellent"]["name"], use_container_width=True):
            st.session_state.center_key = "excellent"
            new = {"center": "excellent"}
            if is_admin: new["mode"] = "admin"
            st.query_params.update(**new)
            st.rerun()

    st.stop()

# ------------------------------------------------------------
# Selected center view
# ------------------------------------------------------------
cfg = CENTERS[center_key]
st.title("📊 Exclusive Report with Aging — Dashboard")

if is_admin:
    st.success("You are in **ADMIN** mode — upload/rebuild is enabled.")

st.caption(f"Center: **{cfg['name']}**  ·  Input: {cfg['source'].name}  ·  Report: {cfg['report'].name}")

# Back button (preserves admin flag)
if st.button("◀ Choose another center"):
    st.session_state.center_key = None
    st.query_params.clear()
    if is_admin:
        st.query_params.update(mode="admin")
    st.rerun()

# ------------------------------------------------------------
# ADMIN tools (visible only in admin)
# ------------------------------------------------------------
if is_admin:
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
    warn = "Report not found."
    if is_admin:
        warn += " (Upload source and click Rebuild.)"
    st.warning(warn)
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

