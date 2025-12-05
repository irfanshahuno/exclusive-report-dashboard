# dashboard.py
import shutil, subprocess
from pathlib import Path
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Exclusive Report with Aging — Dashboard", layout="wide")
BASE = Path(__file__).parent

# ---- ONE generator for both centers ----
GENERATOR = BASE / "exclusive_report_with_aging_final.py"

# If your generator can do: python script.py <source> --out <report>
GENERATOR_SUPPORTS_OUT_ARG = False          # set True if you add --out support
DEFAULT_GENERATED_REPORT = BASE / "Exclusive_Report_with_Aging.xlsx"  # fallback copy source

# ---- Centers (edit only file names if needed) ----
CENTERS = {
    "Easy Health Medical Clinic (MF8031)": {
        "key": "easyhealth",
        "source": BASE / "EH_Check3.xlsx",
        "report": BASE / "Exclusive_Report_with_Aging_EASYHEALTH.xlsx",
        "sheets": {"totals":"Insurance Totals","summary":"Balance Aging Summary","detail":"Balance Aging Detail"},
    },
    "Excellent Medical Center (MF4777)": {
        "key": "excellent",
        "source": BASE / "Check3.xlsx",
        "report": BASE / "Exclusive_Report_with_Aging_EXCELLENT.xlsx",
        "sheets": {"totals":"Insurance Totals","summary":"Balance Aging Summary","detail":"Balance Aging Detail"},
    },
}

# ---- helpers ----
def mtime_token(p: Path) -> float:
    try: return p.stat().st_mtime
    except FileNotFoundError: return 0.0

@st.cache_data(show_spinner=True)
def load_report(path: str, totals: str, summary: str, detail: str, _token: float):
    x = pd.ExcelFile(path)
    return x.parse(totals), x.parse(summary), x.parse(detail)

def kpis(df: pd.DataFrame):
    val = lambda c: float(df[c].sum()) if c in df else 0.0
    c1,c2,c3,c4,c5 = st.columns(5)
    c1.metric("Net Amount", f"{val('Net Amount'):,.2f}")
    c2.metric("Paid", f"{val('Paid'):,.2f}")
    c3.metric("Balance", f"{val('Balance'):,.2f}")
    c4.metric("Rejected", f"{val('Rejected'):,.2f}")
    c5.metric("Accepted", f"{val('Accepted'):,.2f}")

def rebuild(cfg) -> str:
    src, out = str(cfg["source"]), str(cfg["report"])
    if GENERATOR_SUPPORTS_OUT_ARG:
        cmd = ["python", str(GENERATOR), src, "--out", out]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode: raise RuntimeError(r.stderr or "Generator failed")
        return r.stdout or "OK"
    else:
        r = subprocess.run(["python", str(GENERATOR), src], capture_output=True, text=True)
        if r.returncode: raise RuntimeError(r.stderr or "Generator failed")
        if not DEFAULT_GENERATED_REPORT.exists():
            raise RuntimeError(f"Expected output not found: {DEFAULT_GENERATED_REPORT.name}")
        shutil.copyfile(DEFAULT_GENERATED_REPORT, out)
        return r.stdout or "OK"

# ---- sidebar (center + mode) ----
names = list(CENTERS.keys())
qp = st.query_params
idx = next((i for i,(n,c) in enumerate(CENTERS.items()) if qp.get("center",[None])[0]==c["key"]), 0)
picked = st.sidebar.radio("Select Center", names, index=idx)
cfg = CENTERS[picked]
mode_toggle = st.sidebar.toggle("Admin mode", value=(qp.get("mode",["view"])[0]=="admin"))
mode = "admin" if mode_toggle else "view"
st.query_params.update(center=cfg["key"], mode=mode)

# optional simple lock for admin (add ADMIN_PASS in Streamlit secrets)
if mode=="admin":
    secret = st.secrets.get("ADMIN_PASS","")
    if secret:
        if st.sidebar.text_input("Admin password", type="password") != secret:
            st.title("🔒 Admin locked"); st.stop()

# ---- header ----
st.title("📊 Exclusive Report with Aging — Dashboard")
st.caption(f"Center: **{picked}** · Input: {cfg['source'].name} · Report: {cfg['report'].name}")

# ---- admin tools ----
if mode=="admin":
    with st.expander("⬆️ Upload/replace source Excel", expanded=False):
        up = st.file_uploader("Upload .xlsx", type=["xlsx"])
        if up:
            cfg["source"].write_bytes(up.read())
            st.success(f"Saved to {cfg['source'].name}")

    col1,col2 = st.columns(2)
    if col1.button("↻ Rebuild report", use_container_width=True):
        try:
            out = rebuild(cfg)
            st.success("Report rebuilt successfully.")
            if out.strip(): st.code(out, language="bash")
            load_report.clear()
        except Exception as e:
            st.error(str(e))
    if col2.button("🗂 Show file locations", use_container_width=True):
        st.info(f"Source: {cfg['source']}\nReport: {cfg['report']}\nScript: {GENERATOR}")

# ---- viewer ----
token = mtime_token(cfg["report"])
if token==0.0:
    st.warning("Report not found. (Admin can upload source and click Rebuild.)")
else:
    totals, summary, detail = load_report(str(cfg["report"]),
        cfg["sheets"]["totals"], cfg["sheets"]["summary"], cfg["sheets"]["detail"], token)
    kpis(totals)
    t1,t2,t3 = st.tabs(["Insurance Totals","Balance Aging Summary","Balance Aging Detail"])
    with t1: st.dataframe(totals, use_container_width=True, hide_index=True)
    with t2: st.dataframe(summary, use_container_width=True, hide_index=True)
    with t3: st.dataframe(detail, use_container_width=True, hide_index=True)

st.sidebar.caption("Deep links → ?center=easyhealth&mode=view   |   ?center=excellent&mode=admin")
