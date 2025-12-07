# exclusive_dashboard.py
import sys
import subprocess
from pathlib import Path
import pandas as pd
import streamlit as st

# ====================== Page Setup ======================
st.set_page_config(page_title="Exclusive Report with Aging — Dashboard", layout="wide")
BASE = Path(__file__).parent
DATA_DIR = BASE / "data"
for f in ["easyhealth", "excellent", "excellent_pharmacy"]:
    (DATA_DIR / f).mkdir(parents=True, exist_ok=True)

# ====================== Centers Config ======================
CENTERS = {
    "easyhealth": {
        "name": "Easy Health Medical Clinic (MF8031)",
        "folder": DATA_DIR / "easyhealth",
        "src": "source.xlsx",
        "out": "report.xlsx",
        "generator": BASE / "exclusive_report_with_aging_final.py",
    },
    "excellent": {
        "name": "Excellent Medical Center (MF4777)",
        "folder": DATA_DIR / "excellent",
        "src": "source.xlsx",
        "out": "report.xlsx",
        "generator": BASE / "exclusive_report_with_aging_final.py",
    },
    "pharmacy": {
        "name": "Excellent Pharmacy (PF code)",
        "folder": DATA_DIR / "excellent_pharmacy",
        "src": "source.xlsx",
        "out": "Pharmacy_Exclusive_Report_with_Aging.xlsx",
        "generator": BASE / "pharmacy_exclusive_report_with_aging.py",
    },
}

# ====================== Helpers ======================
def mtime_token(p: Path) -> float:
    try:
        return p.stat().st_mtime
    except FileNotFoundError:
        return 0.0

def _run(cmd):
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(
            f"Command failed: {' '.join(cmd)}\n\n{res.stderr or res.stdout}"
        )
    return res

def rebuild(gen, src, out):
    py = sys.executable
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        return _run([py, str(gen), str(src), "--out", str(out)])
    except Exception:
        return _run([py, str(gen), "--out", str(out), str(src)])

@st.cache_data(show_spinner=True)
def load_fast(path: str, token: float):
    xls = pd.ExcelFile(path)
    names = xls.sheet_names
    ins_tot = next((n for n in names if "insurance" in n.lower() and "total" in n.lower()), None)
    summary = next((n for n in names if "summary" in n.lower()), None)
    detail = next((n for n in names if "detail" in n.lower()), None)
    df1 = xls.parse(ins_tot) if ins_tot else pd.DataFrame()
    df2 = xls.parse(summary) if summary else pd.DataFrame()
    return df1, df2, ins_tot, summary, detail, names

@st.cache_data(show_spinner=True)
def load_detail(path: str, name: str, token: float):
    return pd.read_excel(path, sheet_name=name)

def trim(df: pd.DataFrame):
    if df is None or df.empty:
        return df
    df = df.dropna(how="all")
    blank = df.fillna("").astype(str).apply(lambda r: "".join(r).strip() == "", axis=1)
    return df.loc[~blank]

def full_height(df, row_px=45, header_px=70, pad=150):
    n = 0 if df is None else len(df)
    return header_px + (n * row_px) + pad

def style_grid(df: pd.DataFrame):
    if df.empty:
        return df
    df = df.copy()
    df.index = range(1, len(df) + 1)
    from pandas.io.formats.style import Styler
    border = "#D0D0D0"
    return (
        df.style
        .set_table_styles([
            {"selector": "th", "props": [("background-color", "#2196F3"), ("color", "white")]},
            {"selector": "td, th", "props": [("border", f"1px solid {border}")]}
        ])
        .format({c: "{:,.2f}".format for c in df.select_dtypes("number").columns})
    )

# ====================== UI State ======================
if "is_admin" not in st.session_state:
    st.session_state.is_admin = False
if "center_key" not in st.session_state:
    st.session_state.center_key = None

top, right = st.columns([5, 1])
with top:
    st.title("📊 Exclusive Report with Aging — Dashboard")
with right:
    st.session_state.is_admin = st.toggle("Admin Mode", value=st.session_state.is_admin)

ck = st.session_state.center_key
if ck not in CENTERS:
    st.subheader("Select Center")
    c1, c2, c3 = st.columns(3)
    for key, col in zip(CENTERS.keys(), [c1, c2, c3]):
        if col.button(CENTERS[key]["name"], use_container_width=True):
            st.session_state.center_key = key
            st.rerun()
    st.stop()

cfg = CENTERS[ck]
folder, src_path, out_path, gen_path = cfg["folder"], cfg["folder"]/cfg["src"], cfg["folder"]/cfg["out"], cfg["generator"]
st.caption(f"Center: **{cfg['name']}** · Mode: **{'Admin' if st.session_state.is_admin else 'View'}**")

if st.session_state.is_admin:
    with st.expander("⬆️ Upload Source Excel", expanded=False):
        up = st.file_uploader("Upload Excel", type=["xlsx"])
        if up:
            src_path.write_bytes(up.read())
            st.success(f"Uploaded: {src_path.name}")

    colA, colB = st.columns(2)
    if colA.button("↻ Rebuild Report", use_container_width=True):
        try:
            if not src_path.exists():
                st.error("No source file uploaded.")
            else:
                msg = rebuild(gen_path, src_path, out_path)
                st.success("Report rebuilt successfully.")
                st.code(msg.stdout or "Done", language="bash")
                load_fast.clear(); load_detail.clear()
        except Exception as e:
            st.error(str(e))
    if colB.button("🗂 Show Locations", use_container_width=True):
        st.info(f"Source: {src_path}\nReport: {out_path}\nGenerator: {gen_path}")

token = mtime_token(out_path)
if token == 0.0:
    st.warning("⚠️ Report not found. Please upload & rebuild in Admin Mode.")
    st.stop()

# ====================== Data + KPIs ======================
try:
    totals, summary, s_tot, s_sum, s_det, available = load_fast(str(out_path), token)
    totals, summary = trim(totals), trim(summary)

    def ksum(df, *cols):
        for c in cols:
            if c in df.columns:
                return float(df[c].sum())
        return 0.0

    net = ksum(totals, "Net Amount", "NetAmount", "Net")
    paid = ksum(totals, "Paid")
    bal  = ksum(totals, "Balance")
    rej  = ksum(totals, "Rejected", "Rejection")
    acc  = ksum(totals, "Accepted")

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Net Amount", f"{net:,.2f}")
    k2.metric("Paid", f"{paid:,.2f}")
    k3.metric("Balance", f"{bal:,.2f}")
    k4.metric("Rejected", f"{rej:,.2f}")
    k5.metric("Accepted", f"{acc:,.2f}")

    # ---------- Compact 3D-Style KPI Donut (3x3) ----------
    labels = ["Paid", "Balance", "Rejected", "Accepted"]
    values = [paid, bal, rej, acc]
    zipped = [(l, v) for l, v in zip(labels, values) if v and v > 0]

    try:
        import matplotlib.pyplot as plt
        import numpy as np

        if zipped:
            labels, values = zip(*zipped)
            colors = ["#27ae60", "#f39c12", "#c0392b", "#7f8c8d"]

            fig, ax = plt.subplots(figsize=(3, 3), subplot_kw=dict(aspect="equal"))
            wedges, _ = ax.pie(
                values,
                startangle=140,
                counterclock=False,
                colors=colors,
                wedgeprops=dict(width=0.35, edgecolor="white",
                                linewidth=1.2, shadow=True, alpha=0.92)
            )

            total = float(np.sum(values))
            ax.text(0, 0, f"{total:,.0f}\nTOTAL",
                    ha="center", va="center",
                    fontsize=10, fontweight="bold", color="#333")
            circle = plt.Circle((0, 0), 0.7, color="black",
                                fill=False, linewidth=0.5, alpha=0.25)
            ax.add_artist(circle)

            legend_labels = [f"{lbl}: {val:,.2f}" for lbl, val in zip(labels, values)]
            ax.legend(
                wedges, legend_labels, title="KPIs",
                loc="lower right", bbox_to_anchor=(1.05, 0.05),
                frameon=True, fontsize=8, title_fontsize=9
            )
            fig.tight_layout()
            st.pyplot(fig, use_container_width=False)
        else:
            st.info("No positive KPI values to chart.")
    except ModuleNotFoundError:
        st.warning("Matplotlib not installed — showing bars instead.")
        import pandas as _pd
        _df = _pd.DataFrame({"Value": [paid, bal, rej, acc]}, index=labels)
        st.bar_chart(_df, use_container_width=False)

    # ---------- Tabs ----------
    t1, t2, t3 = st.tabs(["Insurance_Totals", "Balance_Aging_Summary", "Balance_Aging_Detail"])

    with t1:
        st.dataframe(style_grid(totals), use_container_width=True, height=full_height(totals))
    with t2:
        st.dataframe(style_grid(summary), use_container_width=True, height=full_height(summary))
    with t3:
        st.caption("Loads only when you click (to keep fast).")
        if st.button("Load Balance_Aging_Detail (no styling)"):
            try:
                df3 = load_detail(str(out_path), s_det or "Balance_Aging_Detail", token)
                df3 = trim(df3)
                st.dataframe(df3, use_container_width=True, height=full_height(df3))
            except Exception as e:
                st.error(str(e))

except Exception as e:
    st.error(f"❌ {e}")

