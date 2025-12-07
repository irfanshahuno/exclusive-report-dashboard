# exclusive_dashboard.py
import sys
import subprocess
from pathlib import Path
import pandas as pd
import streamlit as st

# ========================= Page setup =========================
st.set_page_config(page_title="Exclusive Report with Aging — Dashboard", layout="wide")
BASE = Path(__file__).parent

DATA_DIR = BASE / "data"
(DATA_DIR / "easyhealth").mkdir(parents=True, exist_ok=True)
(DATA_DIR / "excellent").mkdir(parents=True, exist_ok=True)
(DATA_DIR / "excellent_pharmacy").mkdir(parents=True, exist_ok=True)

# ========================= Generators =========================
GEN_MEDICAL = BASE / "exclusive_report_with_aging_final.py"
GEN_PHARM   = BASE / "pharmacy_exclusive_report_with_aging.py"  # your pharmacy generator

# ========================= Centers config =====================
CENTERS = {
    "easyhealth": {
        "name": "Easy Health Medical Clinic (MF8031)",
        "folder": DATA_DIR / "easyhealth",
        "src_name": "source.xlsx",
        "out_name": "report.xlsx",
        "generator": GEN_MEDICAL,
    },
    "excellent": {
        "name": "Excellent Medical Center (MF4777)",
        "folder": DATA_DIR / "excellent",
        "src_name": "source.xlsx",
        "out_name": "report.xlsx",
        "generator": GEN_MEDICAL,
    },
    "excellent_pharmacy": {
        "name": "Excellent Pharmacy (PF code)",
        "folder": DATA_DIR / "excellent_pharmacy",
        "src_name": "source.xlsx",
        "out_name": "report.xlsx",
        "generator": GEN_PHARM,
    },
}

# ========================= Helpers =========================
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

def rebuild_report(generator: Path, src_path: Path, out_path: Path) -> str:
    py = sys.executable
    out_path.parent.mkdir(parents=True, exist_ok=True)
    src, out = str(src_path), str(out_path)
    try:
        res = _run([py, str(generator), "--out", out, src])
        return res.stdout or "OK"
    except Exception:
        # support reversed order (older scripts)
        res = _run([py, str(generator), src, "--out", out])
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

def find_detail_sheet_name(sheet_names: list[str]) -> str | None:
    """Best-effort locator for the detail sheet."""
    for s in sheet_names:
        ls = s.lower()
        if "balance" in ls and "aging" in ls and "detail" in ls:
            return s
    for s in sheet_names:
        if "detail" in s.lower():
            return s
    # fallback: third sheet if present (0: totals, 1: summary, 2: detail)
    if len(sheet_names) >= 3:
        return sheet_names[2]
    return None

def autodetect_sheets(xls: pd.ExcelFile):
    names = xls.sheet_names
    totals  = _pick_sheet(names, ["total"]) or _pick_sheet(names, ["insurance"])
    summary = _pick_sheet(names, ["aging", "summary"]) or _pick_sheet(names, ["summary"])
    detail  = find_detail_sheet_name(names)

    # lenient fallbacks
    if totals is None and names: totals = names[0]
    if summary is None and len(names) > 1: summary = names[1]
    if detail is None and len(names) > 2: detail = names[2] if len(names) > 2 else names[-1]
    return totals, summary, detail

def trim_empty_rows(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    df2 = df.dropna(how="all")
    if df2.empty:
        return df2
    blank_rows = df2.fillna("").astype(str).apply(lambda row: "".join(row).strip() == "", axis=1)
    return df2.loc[~blank_rows]

def full_height(df, row_px: int = 45, header_px: int = 70, padding_px: int = 150) -> int:
    n = 0 if df is None else len(df)
    return header_px + (n * row_px) + padding_px

# ---- simple blue header + white index style for Totals/Summary
def style_grid(df: pd.DataFrame):
    if not isinstance(df, pd.DataFrame):
        return df
    if df.shape[1] == 0:
        return df.style

    # index starts at 1, white index column
    df = df.copy()
    df.index = range(1, len(df) + 1)

    first_col = df.columns[0]
    num_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    fmt_map = {c: "{:,.2f}".format for c in num_cols}

    border = "#CBD5E1"
    header_bg = "#2196F3"
    header_font = "#FFFFFF"

    styler = (
        df.style
        .set_table_styles([
            {"selector": "table",
             "props": [("border-collapse", "collapse"), ("width", "100%")]},
            {"selector": "th.col_heading",
             "props": [("border", f"1px solid {border}"),
                       ("background-color", header_bg),
                       ("font-weight", "700"),
                       ("color", header_font)]},
            {"selector": "th.row_heading",
             "props": [("border", f"1px solid {border}"),
                       ("background-color", "#FFFFFF"),
                       ("color", "#000000"),
                       ("font-weight", "500")]},
            {"selector": "td",
             "props": [("border", f"1px solid {border}")]}
        ])
        .set_properties(subset=[first_col], **{"font-weight": "600"})
        .format(fmt_map)
    )

    # highlight grand total row if present in first column
    try:
        mask_gt = df[first_col].astype(str).str.contains("grand total", case=False, na=False)
        if mask_gt.any():
            def hi(row):
                return (["font-weight:700; color:black; background-color:#FFF7E0"] * len(row)
                        if mask_gt.iloc[row.name - 1] else [""] * len(row))
            styler = styler.apply(hi, axis=1)
    except Exception:
        pass
    return styler

# ========================= Caches =========================
@st.cache_data(show_spinner=True)
def load_core_sheets(path: str, _token: float):
    xls = pd.ExcelFile(path)
    totals_name, summary_name, detail_name = autodetect_sheets(xls)
    totals  = xls.parse(totals_name)
    summary = xls.parse(summary_name)
    return totals, summary, totals_name, summary_name, detail_name

@st.cache_data(show_spinner=True)
def load_detail(path: str, sheet_name: str, _token: float):
    xls = pd.ExcelFile(path)
    return xls.parse(sheet_name)

# ========================= Streamlit state =========================
if "is_admin" not in st.session_state:
    st.session_state.is_admin = False

if "center_key" not in st.session_state:
    st.session_state.center_key = None

# remember which center has its detail loaded
if "detail_shown" not in st.session_state:
    st.session_state.detail_shown = {}

if "last_center_key" not in st.session_state:
    st.session_state.last_center_key = None

# ========================= Header & mode =========================
left, right = st.columns([5, 1])
with left:
    st.title("📊 Exclusive Report with Aging — Dashboard")
with right:
    st.session_state.is_admin = st.toggle("Admin mode", value=st.session_state.is_admin)

mode_label = "admin" if st.session_state.is_admin else "view"
st.caption(f"Mode: **{mode_label}** · Center: **{st.session_state.center_key or 'none'}**")

# clear caches when center changes
if st.session_state.center_key != st.session_state.last_center_key:
    load_core_sheets.clear()
    load_detail.clear()
    st.session_state.detail_shown[st.session_state.center_key] = False
    st.session_state.last_center_key = st.session_state.center_key

# ========================= Center chooser =========================
ck = st.session_state.center_key
if ck not in CENTERS:
    st.subheader("Choose a center")
    cols = st.columns(3)
    if cols[0].button(CENTERS["easyhealth"]["name"], use_container_width=True):
        st.session_state.center_key = "easyhealth"; st.rerun()
    if cols[1].button(CENTERS["excellent"]["name"], use_container_width=True):
        st.session_state.center_key = "excellent"; st.rerun()
    if cols[2].button(CENTERS["excellent_pharmacy"]["name"], use_container_width=True):
        st.session_state.center_key = "excellent_pharmacy"; st.rerun()
    st.stop()

# ========================= Paths & controls =========================
cfg = CENTERS[st.session_state.center_key]
folder = cfg["folder"]
src_path = folder / cfg["src_name"]
out_path = folder / cfg["out_name"]
generator = cfg["generator"]

if st.button("◀ Choose another center"):
    st.session_state.center_key = None
    st.rerun()

if st.session_state.is_admin:
    st.success("You are in **ADMIN** mode — upload/rebuild is enabled.")
st.caption(f"Center: **{cfg['name']}**  ·  Input: {src_path.name}  ·  Report: {out_path.name}")

if st.session_state.is_admin:
    with st.expander("⬆️ Upload/replace source Excel", expanded=False):
        up = st.file_uploader("Upload .xlsx", type=["xlsx"], key=f"upload_{ck}")
        if up:
            folder.mkdir(parents=True, exist_ok=True)
            src_path.write_bytes(up.read())
            st.success(f"Saved to {src_path}")

    colA, colB, colC = st.columns(3)
    if colA.button("↻ Rebuild report", use_container_width=True):
        try:
            msg = rebuild_report(generator, src_path, out_path)
            st.success("Report rebuilt successfully.")
            if msg.strip():
                st.code(msg, language="bash")
            load_core_sheets.clear(); load_detail.clear()
            st.session_state.detail_shown[ck] = False
        except Exception as e:
            st.error(str(e))

    if colB.button("🗂 Show file locations", use_container_width=True):
        st.info(f"Source: {src_path}\nReport: {out_path}\nScript: {generator}")

    if colC.button("🗑 Reset (delete) this center's report", use_container_width=True):
        try:
            if out_path.exists():
                out_path.unlink()
            st.success("Report deleted.")
            load_core_sheets.clear(); load_detail.clear()
            st.session_state.detail_shown[ck] = False
        except Exception as e:
            st.error(str(e))

# ========================= Render sheets =========================
token = mtime_token(out_path)
if token == 0.0:
    msg = "Report not found for this center."
    if st.session_state.is_admin:
        msg += " (Upload source and click Rebuild.)"
    st.warning(msg)
    st.stop()

try:
    totals, summary, s_tot, s_sum, s_det = load_core_sheets(str(out_path), token)

    # Top KPIs (use Grand Total row if present)
    def kpi_vals(totals_df: pd.DataFrame):
        ins_col = "Insurance" if "Insurance" in totals_df.columns else None
        row = None
        if ins_col:
            mask_gt = totals_df[ins_col].astype(str).str.contains("grand total", case=False, na=False)
            if mask_gt.any():
                row = totals_df.loc[mask_gt].iloc[-1]
        if row is not None:
            def g(c): 
                try: return float(row.get(c, 0))
                except: return 0.0
            return g("NetAmount") or g("Net Amount"), g("Paid"), g("Balance"), g("Rejected"), g("Accepted")
        # fallback: sum columns
        def s(c): return float(totals_df[c].sum()) if c in totals_df.columns else 0.0
        # allow either NetAmount or Net Amount
        net_col = "NetAmount" if "NetAmount" in totals_df.columns else ("Net Amount" if "Net Amount" in totals_df.columns else None)
        net = totals_df[net_col].sum() if net_col else 0.0
        return float(net), s("Paid"), s("Balance"), s("Rejected"), s("Accepted")

    k_net, k_paid, k_bal, k_rej, k_acc = kpi_vals(totals)
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Net Amount", f"{k_net:,.2f}")
    c2.metric("Paid", f"{k_paid:,.2f}")
    c3.metric("Balance", f"{k_bal:,.2f}")
    c4.metric("Rejected", f"{k_rej:,.2f}")
    c5.metric("Accepted", f"{k_acc:,.2f}")

    tabs = st.tabs([f"{s_tot or 'Insurance_Totals'}", f"{s_sum or 'Balance_Aging_Summary'}", f"{s_det or 'Balance_Aging_Detail'}"])

    # Totals (styled)
    with tabs[0]:
        df1 = trim_empty_rows(totals)
        st.dataframe(style_grid(df1), use_container_width=True, height=full_height(df1))

    # Summary (styled)
    with tabs[1]:
        df2 = trim_empty_rows(summary)
        st.dataframe(style_grid(df2), use_container_width=True, height=full_height(df2))

    # Detail (no styling; load on click)
    with tabs[2]:
        if not s_det:
            st.info("No Balance_Aging_Detail sheet detected in this report.")
        else:
            shown = st.session_state.detail_shown.get(ck, False)
            if not shown:
                if st.button("📂 Load Balance_Aging_Detail (no styling)", key=f"load_detail_{ck}", use_container_width=True):
                    st.session_state.detail_shown[ck] = True
                    st.rerun()
                st.caption(f"(Sheet: {s_det})")
            else:
                try:
                    df3 = load_detail(str(out_path), s_det, token)
                    st.dataframe(df3, use_container_width=True, height=full_height(df3))
                except Exception as e:
                    st.error(str(e))

except Exception as e:
    try:
        names = pd.ExcelFile(str(out_path)).sheet_names
    except Exception:
        names = []
    st.error(f"{e}\n\nAvailable sheets: {', '.join(names) if names else '(none)'}")
