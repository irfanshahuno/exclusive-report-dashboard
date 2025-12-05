# exclusive_dashboard.py
import sys
import subprocess
from pathlib import Path
import pandas as pd
import streamlit as st

# --------------------------- Page setup ---------------------------
st.set_page_config(page_title="Exclusive Report with Aging — Dashboard", layout="wide")
BASE = Path(__file__).parent
DATA_DIR = BASE / "data"
(DATA_DIR / "easyhealth").mkdir(parents=True, exist_ok=True)
(DATA_DIR / "excellent").mkdir(parents=True, exist_ok=True)

GENERATOR = BASE / "exclusive_report_with_aging_final.py"

CENTERS = {
    "easyhealth": {
        "name": "Easy Health Medical Clinic (MF8031)",
        "folder": DATA_DIR / "easyhealth",
        "src_name": "source.xlsx",
        "out_name": "report.xlsx",
    },
    "excellent": {
        "name": "Excellent Medical Center (MF4777)",
        "folder": DATA_DIR / "excellent",
        "src_name": "source.xlsx",
        "out_name": "report.xlsx",
    },
}

# --------------------------- Helpers ------------------------------
def mtime_token(p: Path) -> float:
    try:
        return p.stat().st_mtime
    except FileNotFoundError:
        return 0.0

def _run(cmd):
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(res.stderr)
    return res

def rebuild_report(src_path: Path, out_path: Path) -> str:
    py = sys.executable
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [py, str(GENERATOR), str(src_path), "--out", str(out_path)]
    res = _run(cmd)
    return res.stdout or "OK"

def autodetect_sheets(xls: pd.ExcelFile):
    names = xls.sheet_names
    totals = next((n for n in names if "total" in n.lower()), names[0])
    summary = next((n for n in names if "summary" in n.lower()), names[min(1, len(names)-1)])
    detail = next((n for n in names if "detail" in n.lower()), names[-1])
    return totals, summary, detail

@st.cache_data(show_spinner=True)
def load_report_fast(path: str, _token: float):
    xls = pd.ExcelFile(path)
    t, s, d = autodetect_sheets(xls)
    return xls.parse(t), xls.parse(s), t, s, d

@st.cache_data(show_spinner=True)
def load_detail(path: str, sheet: str, _token: float):
    return pd.read_excel(path, sheet_name=sheet)

def trim_empty_rows(df):
    if df is None or df.empty:
        return df
    df2 = df.dropna(how="all")
    blank = df2.fillna("").astype(str).apply(lambda x: "".join(x).strip() == "", axis=1)
    return df2.loc[~blank]

def show_kpis(df):
    cols = [c for c in ["Net Amount", "Paid", "Balance", "Rejected", "Accepted"] if c in df.columns]
    sums = df[cols].sum()
    c1, c2, c3, c4, c5 = st.columns(5)
    metrics = [c1, c2, c3, c4, c5]
    for i, c in enumerate(cols):
        metrics[i].metric(c, f"{sums[c]:,.2f}")

def full_height(df, row_px=45, header_px=70, padding_px=150):
    return header_px + len(df)*row_px + padding_px

# --------------------------- Styling ------------------------------
def style_grid(df: pd.DataFrame):
    if not isinstance(df, pd.DataFrame) or df.empty:
        return df
    df.index = range(1, len(df)+1)
    first_col = df.columns[0]
    fmt = {c: "{:,.2f}".format for c in df.select_dtypes(include='number').columns}

    styler = df.style.format(fmt)

    # ✅ Force blue header, white index, borders, and yellow Grand Total
    styler.set_table_styles([
        # Whole table border collapse
        {"selector": "table", "props": [("border-collapse", "collapse"), ("width", "100%")]},
        # ✅ Blue header
        {"selector": "th.col_heading", "props": [
            ("background-color", "#2196F3"),   # bright blue
            ("color", "white"),
            ("font-weight", "700"),
            ("border", "1px solid #BBBBBB"),
            ("text-align", "center"),
        ]},
        # ✅ White index column (no blue strip)
        {"selector": "th.row_heading", "props": [
            ("background-color", "white"),
            ("color", "#000000"),
            ("border", "1px solid #BBBBBB"),
            ("text-align", "center"),
        ]},
        {"selector": "td", "props": [
            ("border", "1px solid #DDDDDD"),
            ("text-align", "center"),
        ]}
    ], overwrite=False)

    # ✅ Highlight Grand Total row
    try:
        mask = df[first_col].astype(str).str.contains("grand total", case=False, na=False)
        if mask.any():
            def color_row(row):
                return ["background-color:#FFF9C4; font-weight:700;" if mask.iloc[row.name-1] else "" for _ in row]
            styler = styler.apply(color_row, axis=1)
    except Exception:
        pass

    return styler

# --------------------------- Streamlit UI ---------------------------
if "is_admin" not in st.session_state:
    st.session_state.is_admin = False
if "center_key" not in st.session_state:
    st.session_state.center_key = None

left, right = st.columns([5,1])
with left:
    st.title("📊 Exclusive Report with Aging — Dashboard")
with right:
    st.session_state.is_admin = st.toggle("Admin mode", value=st.session_state.is_admin)

ck = st.session_state.center_key
if ck not in CENTERS:
    st.subheader("Select a center")
    c1, c2 = st.columns(2)
    if c1.button(CENTERS["easyhealth"]["name"], use_container_width=True):
        st.session_state.center_key = "easyhealth"; st.rerun()
    if c2.button(CENTERS["excellent"]["name"], use_container_width=True):
        st.session_state.center_key = "excellent"; st.rerun()
    st.stop()

cfg = CENTERS[st.session_state.center_key]
src_path, out_path = cfg["folder"]/cfg["src_name"], cfg["folder"]/cfg["out_name"]

if st.session_state.is_admin:
    st.info("Admin mode active — You can upload or rebuild reports.")
    up = st.file_uploader("Upload Excel", type=["xlsx"])
    if up:
        cfg["folder"].mkdir(parents=True, exist_ok=True)
        src_path.write_bytes(up.read())
        st.success(f"Uploaded to {src_path}")
    if st.button("Rebuild report"):
        msg = rebuild_report(src_path, out_path)
        st.success("Report rebuilt successfully.")
        if msg.strip(): st.code(msg)
        st.cache_data.clear()

if not out_path.exists():
    st.warning("No report found. Upload source and click Rebuild.")
    st.stop()

token = mtime_token(out_path)
try:
    totals, summary, s_tot, s_sum, s_det = load_report_fast(str(out_path), token)
    show_kpis(totals)
    t1, t2, t3 = st.tabs([s_tot, s_sum, s_det])
    with t1:
        df = trim_empty_rows(totals)
        st.dataframe(style_grid(df), use_container_width=True, height=full_height(df))
    with t2:
        df = trim_empty_rows(summary)
        st.dataframe(style_grid(df), use_container_width=True, height=full_height(df))
    with t3:
        df = load_detail(str(out_path), s_det, token)
        st.dataframe(style_grid(df), use_container_width=True, height=full_height(df))
except Exception as e:
    st.error(str(e))

