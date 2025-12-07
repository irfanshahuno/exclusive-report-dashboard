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
(DATA_DIR / "excellent_pharmacy").mkdir(parents=True, exist_ok=True)

# --------------------------- Centers & Generators -----------------
CENTERS = {
    "easyhealth": {
        "name": "Easy Health Medical Clinic (MF8031)",
        "folder_root": DATA_DIR / "easyhealth",
        "src_name": "source.xlsx",
        "out_name": "report.xlsx",
        "generator": BASE / "exclusive_report_with_aging_final.py",
    },
    "excellent": {
        "name": "Excellent Medical Center (MF4777)",
        "folder_root": DATA_DIR / "excellent",
        "src_name": "source.xlsx",
        "out_name": "report.xlsx",
        "generator": BASE / "exclusive_report_with_aging_final.py",
    },
    "pharmacy": {
        "name": "Excellent Pharmacy (PF code)",
        "folder_root": DATA_DIR / "excellent_pharmacy",
        "src_name": "source.xlsx",
        "out_name": "Pharmacy_Exclusive_Report_with_Aging.xlsx",
        "generator": BASE / "pharmacy_exclusive_report_with_aging.py",
    },
}

YEARS = [2024, 2025]
DETAIL_SHEET_NAME = "Balance_Aging_Detail"

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

def rebuild_report(gen_path: Path, src_path: Path, out_path: Path) -> str:
    """Run generator with tolerant --out ordering."""
    py = sys.executable
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [py, str(gen_path), str(src_path)]
    try:
        res = _run(cmd + ["--out", str(out_path)])
        return res.stdout or "OK"
    except Exception:
        res = _run([py, str(gen_path), "--out", str(out_path), str(src_path)])
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
    totals  = _pick_sheet(names, ["insurance", "total"]) or _pick_sheet(names, ["totals"]) or _pick_sheet(names, ["insurance"])
    summary = _pick_sheet(names, ["aging", "summary"]) or _pick_sheet(names, ["summary"])
    detail  = _pick_sheet(names, ["aging", "detail"])  or DETAIL_SHEET_NAME
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

def ensure_grand_total(df: pd.DataFrame, name_col: str = "Insurance") -> pd.DataFrame:
    """Append a Grand Total row if missing."""
    if df is None or df.empty or name_col not in df.columns:
        return df
    if df[name_col].astype(str).str.lower().str.contains("grand total").any():
        return df
    num_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    gt = {c: df[c].sum() for c in num_cols}
    row = {c: "" for c in df.columns}
    row.update(gt)
    row[name_col] = "Grand Total"
    return pd.concat([df, pd.DataFrame([row])], ignore_index=True)

def full_height(df, row_px: int = 45, header_px: int = 70, padding_px: int = 150) -> int:
    n = 0 if df is None else len(df)
    return header_px + (n * row_px) + padding_px

# --------------------------- Styling ---------------------------
def style_grid(df: pd.DataFrame):
    """Blue header, white index, index from 1, Grand Total highlight."""
    if not isinstance(df, pd.DataFrame):
        return df
    if df.shape[1] == 0:
        return df.style

    df = df.copy()
    df.index = range(1, len(df) + 1)
    first_col = df.columns[0]
    num_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    fmt_map = {c: "{:,.2f}".format for c in num_cols}

    border = "#CBD5E1"; header_bg = "#2196F3"; header_font = "#FFFFFF"
    styler = (
        df.style
        .set_table_styles([
            {"selector": "table", "props": [("border-collapse", "collapse"), ("width", "100%")]},
            {"selector": "th.col_heading", "props": [("border", f"1px solid {border}"),
                                                    ("background-color", header_bg),
                                                    ("font-weight", "700"),
                                                    ("color", header_font)]},
            {"selector": "th.row_heading", "props": [("border", f"1px solid {border}"),
                                                     ("background-color", "#FFFFFF"),
                                                     ("color", "#000000"),
                                                     ("font-weight", "500")]},
            {"selector": "td", "props": [("border", f"1px solid {border}")]}
        ])
        .set_properties(subset=[first_col], **{"font-weight": "600"})
        .format(fmt_map)
    )

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
if "year" not in st.session_state:
    st.session_state.year = None
if "last_year" not in st.session_state:
    st.session_state.last_year = None

top_left, top_right = st.columns([5, 1])
with top_left:
    st.title("📊 Exclusive Report with Aging — Dashboard")
with top_right:
    st.session_state.is_admin = st.toggle("Admin mode", value=st.session_state.is_admin)

# Clear caches if center/year changed
if (st.session_state.center_key != st.session_state.last_center_key) or (st.session_state.year != st.session_state.last_year):
    load_report_fast.clear()
    load_detail_sheet.clear()
    st.session_state.last_center_key = st.session_state.center_key
    st.session_state.last_year = st.session_state.year

st.caption(f"Mode: **{'admin' if st.session_state.is_admin else 'view'}** · Center: **{st.session_state.center_key or 'none'}** · Year: **{st.session_state.year or 'none'}**")

# --------------------------- Center selection ---------------------------
ck = st.session_state.center_key
if ck not in CENTERS:
    st.subheader("Choose a center")
    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button(CENTERS["easyhealth"]["name"], use_container_width=True):
            st.session_state.center_key = "easyhealth"; st.session_state.year = None; st.rerun()
    with c2:
        if st.button(CENTERS["excellent"]["name"], use_container_width=True):
            st.session_state.center_key = "excellent"; st.session_state.year = None; st.rerun()
    with c3:
        if st.button(CENTERS["pharmacy"]["name"], use_container_width=True):
            st.session_state.center_key = "pharmacy"; st.session_state.year = None; st.rerun()
    st.stop()

# --------------------------- Year selection ---------------------------
st.subheader("Select Year")
ycols = st.columns(len(YEARS))
chosen_year = None
for i, y in enumerate(YEARS):
    with ycols[i]:
        if st.button(str(y), use_container_width=True):
            chosen_year = y
if chosen_year is not None:
    st.session_state.year = chosen_year
    st.rerun()

if st.session_state.year is None:
    cfg_tmp = CENTERS[ck]
    found = None
    for y in reversed(YEARS):
        folder_try = (cfg_tmp["folder_root"] / str(y))
        out_try = folder_try / cfg_tmp["out_name"]
        if out_try.exists():
            found = y; break
    st.session_state.year = found or YEARS[-1]  # default to latest (2025)
    st.rerun()

# Resolve active paths
cfg = CENTERS[st.session_state.center_key]
folder = cfg["folder_root"] / str(st.session_state.year)
folder.mkdir(parents=True, exist_ok=True)
src_path = folder / cfg["src_name"]
out_path = folder / cfg["out_name"]
gen_path = cfg["generator"]

if st.session_state.is_admin:
    st.success("You are in **ADMIN** mode — upload/rebuild is enabled.")
st.caption(f"Center: **{cfg['name']}**  ·  Year: **{st.session_state.year}**  ·  Input: {src_path.name}  ·  Report: {out_path.name}")

if st.button("◀ Choose another center"):
    st.session_state.center_key = None
    st.session_state.year = None
    st.rerun()

# -------- Admin controls (per year)
if st.session_state.is_admin:
    with st.expander("⬆️ Upload/replace source Excel for this year", expanded=False):
        up = st.file_uploader(
            f"Upload .xlsx for {st.session_state.year}",
            type=["xlsx"],
            key=f"uploader_{st.session_state.center_key}_{st.session_state.year}",
        )
        if up:
            folder.mkdir(parents=True, exist_ok=True)
            src_path.write_bytes(up.read())
            st.success(f"Saved to {src_path}")

    colA, colB, colC = st.columns(3)
    if colA.button("↻ Rebuild report", use_container_width=True, key=f"rebuild_{ck}_{st.session_state.year}"):
        try:
            if not gen_path.exists():
                st.error(f"Generator not found: {gen_path}")
            elif not src_path.exists():
                st.error(f"No source file found for {st.session_state.year}. Please upload {src_path.name} first.")
            else:
                msg = rebuild_report(gen_path, src_path, out_path)
                st.success("Report rebuilt successfully.")
                if msg.strip():
                    st.code(msg, language="bash")
            load_report_fast.clear(); load_detail_sheet.clear()
        except Exception as e:
            st.error(str(e))

    if colB.button("🗂 Show file locations", use_container_width=True, key=f"loc_{ck}_{st.session_state.year}"):
        st.info(f"Source: {src_path}\nReport: {out_path}\nGenerator: {gen_path}")

    if colC.button("🗑 Reset (delete) this year's report", use_container_width=True, key=f"del_{ck}_{st.session_state.year}"):
        try:
            if out_path.exists():
                out_path.unlink()
            st.success("Report deleted.")
            load_report_fast.clear(); load_detail_sheet.clear()
        except Exception as e:
            st.error(str(e))

# -------- Render
token = mtime_token(out_path)
if token == 0.0:
    msg = f"Report not found for {cfg['name']} ({st.session_state.year})."
    if st.session_state.is_admin:
        msg += " (Upload source and click Rebuild.)"
    st.warning(msg)
    st.stop()

try:
    totals, summary, s_tot, s_sum, s_det = load_report_fast(str(out_path), token)

    # Guarantee Grand Total on insurance totals
    totals = ensure_grand_total(trim_empty_rows(totals), name_col="Insurance")
    summary = trim_empty_rows(summary)

    # KPIs
    def ksum(df, col):
        return float(df[col].sum()) if col in df.columns else 0.0

    net = ksum(totals, "NetAmount") or ksum(totals, "Net Amount") or ksum(totals, "Net")
    paid = ksum(totals, "Paid")
    bal  = ksum(totals, "Balance")
    rej  = ksum(totals, "Rejected")
    acc  = ksum(totals, "Accepted")

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Net Amount", f"{net:,.2f}")
    k2.metric("Paid", f"{paid:,.2f}")
    k3.metric("Balance", f"{bal:,.2f}")
    k4.metric("Rejected", f"{rej:,.2f}")
    k5.metric("Accepted", f"{acc:,.2f}")

    # ---------- KPI Donut ("football" circle) ----------
    import matplotlib.pyplot as plt
    import numpy as np

    labels = ["Net Amount", "Paid", "Balance", "Rejected", "Accepted"]
    values = [net, paid, bal, rej, acc]

    # Filter out zero/negative to avoid tiny wedges
    zipped = [(l, v) for l, v in zip(labels, values) if v and v > 0]
    if not zipped:
        st.info("No positive KPI values to chart.")
    else:
        labels, values = zip(*zipped)
        color_map = {
            "Net Amount": "#1976D2",  # blue
            "Paid":       "#2E7D32",  # green
            "Balance":    "#FB8C00",  # orange
            "Rejected":   "#C62828",  # red
            "Accepted":   "#6D6D6D",  # gray
        }
        colors = [color_map.get(lbl, "#9E9E9E") for lbl in labels]

        fig, ax = plt.subplots(figsize=(6.5, 6.5))
        wedges, _, _ = ax.pie(
            values,
            labels=None,
            autopct=lambda pct: (f"{pct:.1f}%") if pct >= 3 else "",
            startangle=90,
            counterclock=False,
            colors=colors,
            wedgeprops=dict(width=0.35, edgecolor="white")  # thickness of ring
        )

        total = float(np.sum(values))
        ax.text(
            0, 0,
            f"TOTAL\n{total:,.0f}",
            ha="center", va="center",
            fontsize=14, fontweight="bold"
        )

        legend_labels = [f"{lbl}: {val:,.2f}" for lbl, val in zip(labels, values)]
        ax.legend(wedges, legend_labels, title="KPIs", loc="center left", bbox_to_anchor=(1, 0.5))
        ax.set_aspect("equal")
        st.pyplot(fig, use_container_width=True)

    # ---------- Tabs ----------
    t1, t2, t3 = st.tabs([f"Insurance_Totals", f"Balance_Aging_Summary", f"{DETAIL_SHEET_NAME}"])

    with t1:
        st.dataframe(style_grid(totals), use_container_width=True, height=full_height(totals))

    with t2:
        st.dataframe(style_grid(summary), use_container_width=True, height=full_height(summary))

    with t3:
        st.caption("Loads only when you click to keep the app fast.")
        if st.button("Load Balance_Aging_Detail (no styling)"):
            try:
                detail_sheet = s_det or DETAIL_SHEET_NAME
                df3 = load_detail_sheet(str(out_path), detail_sheet, token)
                df3 = trim_empty_rows(df3)
                st.dataframe(df3, use_container_width=True, height=full_height(df3))
            except Exception as e:
                try:
                    names = pd.ExcelFile(str(out_path)).sheet_names
                except Exception:
                    names = []
                st.error(f"{e}\n\nAvailable sheets: {', '.join(names) if names else '(none)'}")

except Exception as e:
    try:
        names = pd.ExcelFile(str(out_path)).sheet_names
    except Exception:
        names = []
    st.error(f"{e}\n\nAvailable sheets: {', '.join(names) if names else '(none)'}")
