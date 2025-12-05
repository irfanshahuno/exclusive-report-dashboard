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

# --------------------------- Generator config ---------------------
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
        raise RuntimeError(
            "Command failed:\n" + " ".join(cmd)
            + "\n\nSTDOUT:\n" + (res.stdout or "(empty)")
            + "\n\nSTDERR:\n" + (res.stderr or "(empty)")
        )
    return res

def rebuild_report(src_path: Path, out_path: Path) -> str:
    py = sys.executable
    out_path.parent.mkdir(parents=True, exist_ok=True)
    src, out = str(src_path), str(out_path)
    try:
        res = _run([py, str(GENERATOR), "--out", out, src])
        return res.stdout or "OK"
    except Exception:
        res = _run([py, str(GENERATOR), src, "--out", out])
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
    totals  = _pick_sheet(names, ["total"]) or _pick_sheet(names, ["insurance"])
    summary = _pick_sheet(names, ["aging", "summary"]) or _pick_sheet(names, ["summary"])
    detail  = _pick_sheet(names, ["aging", "detail"])  or _pick_sheet(names, ["detail"])
    if totals is None and names: totals = names[0]
    if summary is None and len(names) > 1: summary = names[1]
    if detail is None and len(names) > 2: detail = names[2] if len(names) > 2 else names[-1]
    return totals, summary, detail

@st.cache_data(show_spinner=True)
def load_report_fast(path: str, _token: float):
    xls = pd.ExcelFile(path)
    totals_name, summary_name, detail_name = autodetect_sheets(xls)
    totals  = xls.parse(totals_name)
    summary = xls.parse(summary_name)
    return totals, summary, totals_name, summary_name, detail_name

@st.cache_data(show_spinner=True)
def load_detail_sheet(path: str, detail_sheet: str, _token: float):
    xls = pd.ExcelFile(path)
    return xls.parse(detail_sheet)

def trim_empty_rows(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    df2 = df.dropna(how="all")
    if df2.empty:
        return df2
    blank_rows = df2.fillna("").astype(str).apply(lambda row: "".join(row).strip() == "", axis=1)
    return df2.loc[~blank_rows]

def show_kpis_smart(totals: pd.DataFrame):
    ins_col = "Insurance" if "Insurance" in totals.columns else None
    gt = None
    if ins_col:
        mask_gt = totals[ins_col].astype(str).str.contains("grand total", case=False, na=False)
        if mask_gt.any():
            gt = totals.loc[mask_gt].iloc[-1]
    if gt is not None:
        net = float(gt.get("Net Amount", 0)); paid = float(gt.get("Paid", 0))
        bal = float(gt.get("Balance", 0)); rej = float(gt.get("Rejected", 0))
        acc = float(gt.get("Accepted", 0))
    else:
        def v(c): return float(totals[c].sum()) if c in totals.columns else 0.0
        net, paid, bal, rej, acc = v("Net Amount"), v("Paid"), v("Balance"), v("Rejected"), v("Accepted")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Net Amount", f"{net:,.2f}")
    c2.metric("Paid", f"{paid:,.2f}")
    c3.metric("Balance", f"{bal:,.2f}")
    c4.metric("Rejected", f"{rej:,.2f}")
    c5.metric("Accepted", f"{acc:,.2f}")

def full_height(df, row_px: int = 45, header_px: int = 70, padding_px: int = 150) -> int:
    n = 0 if df is None else len(df)
    return header_px + (n * row_px) + padding_px

# --------------------------- Styling ---------------------------
def style_grid(df: pd.DataFrame):
    """
    Styled DataFrame with:
    - Blue header row
    - White index column (no color)
    - Index starts from 1
    - Borders + Grand Total highlight
    """
    if not isinstance(df, pd.DataFrame):
        return df
    if df.shape[1] == 0:
        return df.style

    # ✅ Reset index to start from 1
    df.index = range(1, len(df) + 1)

    first_col = df.columns[0]
    num_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    fmt_map = {c: "{:,.2f}".format for c in num_cols}

    border = "#CBD5E1"
    header_bg = "#2196F3"  # 🔵 Blue header background
    header_font = "#FFFFFF"  # White text

    styler = (
        df.style
        .set_table_styles([
            {"selector": "table",
             "props": [("border-collapse", "collapse"), ("width", "100%")]},

            # ✅ Blue header
            {"selector": "th.col_heading",
             "props": [("border", f"1px solid {border}"),
                       ("background-color", header_bg),
                       ("font-weight", "700"),
                       ("color", header_font)]},

            # ✅ White index (no blue strip)
            {"selector": "th.row_heading",
             "props": [("border", f"1px solid {border}"),
                       ("background-color", "#FFFFFF"),
                       ("color", "#000000"),
                       ("font-weight", "500")]},

            # ✅ Normal table cells
            {"selector": "td",
             "props": [("border", f"1px solid {border}")]}
        ])
        .set_properties(subset=[first_col], **{"font-weight": "600"})
        .format(fmt_map)
    )

    # ✅ Highlight "Grand Total"
    try:
        mask_gt = df[first_col].astype(str).str.contains("grand total", case=False, na=False)
        if mask_gt.any():
            def highlight(row):
                return (["font-weight:700; color:black; background-color:#FFF7E0"] * len(row)
                        if mask_gt.iloc[row.name - 1] else [""] * len(row))
            styler = styler.apply(highlight, axis=1)
    except Exception:
        pass

    return styler

# --------------------------- Streamlit state ---------------------------
if "is_admin" not in st.session_state:
    st.session_state.is_admin = False
if "center_key" not in st.session_state:
    st.session_state.center_key = None
if "last_center_key" not in st.session_state:
    st.session_state.last_center_key = None

left, right = st.columns([5, 1])
with left:
    st.title("📊 Exclusive Report with Aging — Dashboard")
with right:
    st.session_state.is_admin = st.toggle("Admin mode", value=st.session_state.is_admin)

if st.session_state.center_key != st.session_state.last_center_key:
    load_report_fast.clear()
    load_detail_sheet.clear()
    st.session_state.last_center_key = st.session_state.center_key

st.caption(f"Mode: **{'admin' if st.session_state.is_admin else 'view'}** · Center: **{st.session_state.center_key or 'none'}**")

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

cfg = CENTERS[st.session_state.center_key]
folder, src_path, out_path = cfg["folder"], cfg["folder"]/cfg["src_name"], cfg["folder"]/cfg["out_name"]

if st.session_state.is_admin:
    st.success("You are in **ADMIN** mode — upload/rebuild is enabled.")
st.caption(f"Center: **{cfg['name']}**  ·  Input: {src_path.name}  ·  Report: {out_path.name}")

if st.button("◀ Choose another center"):
    st.session_state.center_key = None
    st.rerun()

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
            if msg.strip(): st.code(msg, language="bash")
            load_report_fast.clear(); load_detail_sheet.clear()
        except Exception as e: st.error(str(e))
    if colB.button("🗂 Show file locations", use_container_width=True):
        st.info(f"Source: {src_path}\nReport: {out_path}\nScript: {GENERATOR}")
    if colC.button("🗑 Reset (delete) this center's report", use_container_width=True):
        try:
            if out_path.exists(): out_path.unlink()
            st.success("Report deleted.")
            load_report_fast.clear(); load_detail_sheet.clear()
        except Exception as e: st.error(str(e))

token = mtime_token(out_path)
if token == 0.0:
    msg = "Report not found for this center."
    if st.session_state.is_admin: msg += " (Upload source and click Rebuild.)"
    st.warning(msg)
else:
    try:
        totals, summary, s_tot, s_sum, s_det = load_report_fast(str(out_path), token)
        show_kpis_smart(totals)
        t1, t2, t3 = st.tabs([f"{s_tot}", f"{s_sum}", f"{s_det}"])
        with t1:
            df1 = trim_empty_rows(totals)
            st.dataframe(style_grid(df1), use_container_width=True, height=full_height(df1))
        with t2:
            df2 = trim_empty_rows(summary)
            st.dataframe(style_grid(df2), use_container_width=True, height=full_height(df2))
        with t3:
            df3 = load_detail_sheet(str(out_path), s_det, token)
            st.dataframe(style_grid(df3), use_container_width=True, height=full_height(df3))
    except Exception as e:
        try:
            names = pd.ExcelFile(str(out_path)).sheet_names
        except Exception: names = []
        st.error(f"{e}\n\nAvailable sheets: {', '.join(names) if names else '(none)'}")

