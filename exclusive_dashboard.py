# exclusive_dashboard.py (robust v2)
import sys
import traceback
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

# Canonical sheet names
SHEET_INS_TOT = "Insurance_Totals"
SHEET_SUMMARY = "Balance_Aging_Summary"
SHEET_DETAIL  = "Balance_Aging_Detail"

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
            f"Command failed: {' '.join(cmd)}\n\nSTDOUT:\n{res.stdout}\n\nSTDERR:\n{res.stderr}"
        )
    return res

def rebuild(gen, src, out):
    py = sys.executable
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        return _run([py, str(gen), str(src), "--out", str(out)])
    except Exception:
        return _run([py, str(gen), "--out", str(out), str(src)])

def _pick_sheet(names, wants_all=None, wants_any=None):
    lower = [n.lower() for n in names]
    if wants_all:
        for i, s in enumerate(lower):
            if all(w in s for w in wants_all):
                return names[i]
    if wants_any:
        for i, s in enumerate(lower):
            if any(w in s for w in wants_any):
                return names[i]
    return None

@st.cache_data(show_spinner=True)
def load_core(path: str, _token: float):
    # returns: totals_df, summary_df, s_tot, s_sum, s_det, all_names
    xls = pd.ExcelFile(path)

    names = xls.sheet_names
    # Prefer exact canonical names first
    s_tot = SHEET_INS_TOT if SHEET_INS_TOT in names else None
    s_sum = SHEET_SUMMARY if SHEET_SUMMARY in names else None
    s_det = SHEET_DETAIL  if SHEET_DETAIL  in names else None

    # Fallbacks for old files
    if not s_tot:
        s_tot = _pick_sheet(names, wants_any=["insurance", "totals"]) or _pick_sheet(names, wants_any=["totals"])
    if not s_sum:
        s_sum = _pick_sheet(names, wants_all=["aging", "summary"]) or _pick_sheet(names, wants_any=["summary"])
    if not s_det:
        s_det = _pick_sheet(names, wants_all=["aging", "detail"]) or _pick_sheet(names, wants_any=["detail"])

    if not s_tot or not s_sum:
        # Return empty dfs but with names for diagnostics
        return pd.DataFrame(), pd.DataFrame(), s_tot, s_sum, s_det, names

    totals = xls.parse(s_tot)
    summary = xls.parse(s_sum)
    return totals, summary, s_tot, s_sum, s_det, names

@st.cache_data(show_spinner=True)
def load_detail(path: str, sheet_name: str, _token: float):
    return pd.read_excel(path, sheet_name=sheet_name)

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
    if df is None or df.empty:
        return df
    df = df.copy()
    df.index = range(1, len(df) + 1)
    border = "#D0D0D0"
    return (
        df.style
        .set_table_styles([
            {"selector": "th", "props": [("background-color", "#2196F3"), ("color", "white")]},
            {"selector": "td, th", "props": [("border", f"1px solid {border}")]}
        ])
        .format({c: "{:,.2f}".format for c in df.select_dtypes("number").columns})
    )

def ensure_grand_total(df: pd.DataFrame, name_col="Insurance"):
    if df is None or df.empty or name_col not in df.columns:
        return df
    if df[name_col].astype(str).str.lower().str.contains("grand total").any():
        return df
    num_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    sums = {c: pd.to_numeric(df[c], errors="coerce").sum() for c in num_cols}
    row = {c: "" for c in df.columns}
    row.update(sums)
    row[name_col] = "Grand Total"
    return pd.concat([df, pd.DataFrame([row])], ignore_index=True)

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
folder = cfg["folder"]; folder.mkdir(parents=True, exist_ok=True)
src_path = folder / cfg["src"]
out_path = folder / cfg["out"]
gen_path = cfg["generator"]
st.caption(f"Center: **{cfg['name']}** · Mode: **{'Admin' if st.session_state.is_admin else 'View'}**")

# ====================== Admin Controls ======================
if st.session_state.is_admin:
    with st.expander("⬆️ Upload Source Excel", expanded=False):
        up = st.file_uploader("Upload Excel (.xlsx)", type=["xlsx"])
        if up:
            src_path.write_bytes(up.read())
            st.success(f"Uploaded: {src_path}")

    colA, colB, colC = st.columns(3)
    if colA.button("↻ Rebuild Report", use_container_width=True):
        try:
            if not gen_path.exists():
                st.error(f"Generator missing: {gen_path.name}")
            elif not src_path.exists():
                st.error("No source file uploaded.")
            else:
                res = rebuild(gen_path, src_path, out_path)
                st.success("Report rebuilt.")
                if res.stdout.strip():
                    st.code(res.stdout, language="bash")
                load_core.clear(); load_detail.clear()
        except Exception as e:
            st.error(str(e))
    if colB.button("🗂 Show Paths", use_container_width=True):
        st.info(f"Source: {src_path}\nReport: {out_path}\nGenerator: {gen_path}")
    if colC.button("🗑 Delete Report", use_container_width=True):
        try:
            if out_path.exists():
                out_path.unlink()
            st.success("Report deleted.")
            load_core.clear(); load_detail.clear()
        except Exception as e:
            st.error(str(e))

# ====================== Render ======================
token = mtime_token(out_path)
if token == 0.0:
    st.warning("⚠️ Report not found. Upload & Rebuild in Admin Mode.")
    st.stop()

try:
    totals, summary, s_tot, s_sum, s_det, names = load_core(str(out_path), token)

    # Diagnostics if sheets missing
    if totals.empty or summary.empty:
        st.error("Required sheets not found in the report.")
        st.code(
            f"Available sheets: {', '.join(names) if names else '(none)'}\n"
            f"Detected -> Insurance_Totals: {s_tot or '(not found)'} | "
            f"Balance_Aging_Summary: {s_sum or '(not found)'} | "
            f"Balance_Aging_Detail: {s_det or '(not found)'}",
            language="bash"
        )
        st.stop()

    # Normalize & clean
    if "Insurance" not in totals.columns:
        # rename first col defensively to Insurance
        totals = totals.rename(columns={totals.columns[0]: "Insurance"})
    if "Net Amount" not in totals.columns:
        for cand in ["NetAmount", "Net amount", "Net"]:
            if cand in totals.columns:
                totals = totals.rename(columns={cand: "Net Amount"})
                break

    totals = trim(totals)
    totals = ensure_grand_total(totals, name_col="Insurance")
    summary = trim(summary)

    # KPIs
    def ksum(df, *cands):
        for c in cands:
            if c in df.columns:
                return float(pd.to_numeric(df[c], errors="coerce").sum())
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
            colors = ["#27ae60", "#f39c12", "#c0392b", "#7f8c8d"]  # green, orange, red, gray
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
            rim = plt.Circle((0, 0), 0.7, color="black", fill=False, linewidth=0.5, alpha=0.25)
            ax.add_artist(rim)
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
        _df = pd.DataFrame({"Value": [paid, bal, rej, acc]}, index=labels)
        st.bar_chart(_df, use_container_width=False)

    # ---------- Tabs ----------
    t1, t2, t3 = st.tabs(["Insurance_Totals", "Balance_Aging_Summary", "Balance_Aging_Detail"])

    with t1:
        st.dataframe(style_grid(totals), use_container_width=True, height=full_height(totals))
        # quick diagnostics
        st.caption("Columns (Insurance_Totals):")
        st.code(", ".join(map(str, totals.columns)))

    with t2:
        st.dataframe(style_grid(summary), use_container_width=True, height=full_height(summary))
        st.caption("Columns (Balance_Aging_Summary):")
        st.code(", ".join(map(str, summary.columns)))

    with t3:
        st.caption("Loads only when you click (to keep fast).")
        if st.button("Load Balance_Aging_Detail (no styling)"):
            try:
                detail_sheet = s_det or SHEET_DETAIL
                if not detail_sheet or detail_sheet not in names:
                    raise RuntimeError(
                        f"Detail sheet not found. Available: {', '.join(names) if names else '(none)'}"
                    )
                df3 = load_detail(str(out_path), detail_sheet, token)
                df3 = trim(df3)
                st.dataframe(df3, use_container_width=True, height=full_height(df3))
                st.caption("Columns (Balance_Aging_Detail):")
                st.code(", ".join(map(str, df3.columns)))
            except Exception as e:
                st.error(str(e))

except Exception:
    st.error("An unexpected error occurred:")
    st.code(traceback.format_exc(), language="python")
