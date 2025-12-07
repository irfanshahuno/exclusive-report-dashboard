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
# NOTE: adjust filenames here only if you rename the generators.
CENTERS = {
    "easyhealth": {
        "name": "Easy Health Medical Clinic (MF8031)",
        "folder": DATA_DIR / "easyhealth",
        "src_name": "source.xlsx",
        "out_name": "report.xlsx",
        "generator": BASE / "exclusive_report_with_aging_final.py",      # medical generator
    },
    "excellent": {
        "name": "Excellent Medical Center (MF4777)",
        "folder": DATA_DIR / "excellent",
        "src_name": "source.xlsx",
        "out_name": "report.xlsx",
        "generator": BASE / "exclusive_report_with_aging_final.py",      # medical generator
    },
    "excellent_pharmacy": {
        "name": "Excellent Pharmacy (PF code)",
        "folder": DATA_DIR / "excellent_pharmacy",
        "src_name": "source.xlsx",
        "out_name": "report.xlsx",
        "generator": BASE / "pharmacy_exclusive_report_with_aging.py",   # pharmacy generator
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

def rebuild_report(generator: Path, src_path: Path, out_path: Path) -> str:
    """Run the proper generator for the chosen center."""
    py = sys.executable
    out_path.parent.mkdir(parents=True, exist_ok=True)
    src, out = str(src_path), str(out_path)
    # Support both CLI orders: --out first or last
    try:
        res = _run([py, str(generator), "--out", out, src])
        return res.stdout or "OK"
    except Exception:
        res = _run([py, str(generator), src, "--out", out])
        return res.stdout or "OK"

def _sheet(xls: pd.ExcelFile, name: str) -> pd.DataFrame | None:
    """Return sheet (case-insensitive) if present, else None."""
    lname = {s.lower(): s for s in xls.sheet_names}
    key = name.lower()
    if key in lname:
        return xls.parse(lname[key])
    return None

@st.cache_data(show_spinner=True)
def load_core_sheets(report_path: str, _token: float):
    """
    Load the small sheets fast:
      - Insurance_Totals (ensure Grand Total row)
      - Balance_Aging_Summary
      - Remember the detail sheet name (we will lazy-load later)
    """
    xls = pd.ExcelFile(report_path)
    # Try canonical names first; fall back to first 2 sheets if needed.
    ins = _sheet(xls, "Insurance_Totals")
    if ins is None:
        name0 = xls.sheet_names[0] if xls.sheet_names else None
        ins = xls.parse(name0) if name0 else pd.DataFrame()

    summ = _sheet(xls, "Balance_Aging_Summary")
    if summ is None and len(xls.sheet_names) >= 2:
        summ = xls.parse(xls.sheet_names[1])
    if summ is None:
        summ = pd.DataFrame()

    # detect a likely detail sheet by name
    detail_name = None
    for s in xls.sheet_names:
        ls = s.lower()
        if "detail" in ls and "aging" in ls:
            detail_name = s
            break

    # Guarantee a Grand Total row on Insurance_Totals
    ins = _ensure_grand_total(ins)

    return ins, summ, detail_name, xls.sheet_names

def _ensure_grand_total(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure Insurance_Totals has a 'Grand Total' row; create if missing."""
    if df is None or df.empty:
        return df

    # Find the insurance/name column heuristically
    name_col = None
    for c in df.columns:
        if str(c).strip().lower() in {"insurance", "payer", "insurance/plan", "plan"}:
            name_col = c
            break
    if name_col is None:
        # fallback: assume first column is the name column
        name_col = df.columns[0]

    # Does it already have a Grand Total row?
    has_gt = False
    try:
        has_gt = df[name_col].astype(str).str.contains("grand total", case=False, na=False).any()
    except Exception:
        pass

    if not has_gt:
        num_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
        sums = df[num_cols].sum(numeric_only=True)
        gt_row = {c: 0 for c in df.columns}
        gt_row[name_col] = "Grand Total"
        for c in num_cols:
            gt_row[c] = float(sums.get(c, 0))
        df = pd.concat([df, pd.DataFrame([gt_row])], ignore_index=True)

    return df

@st.cache_data(show_spinner=True)
def load_detail(report_path: str, detail_sheet: str, _token: float):
    xls = pd.ExcelFile(report_path)
    return xls.parse(detail_sheet)

def totals_from_gt(df: pd.DataFrame):
    """Return (net, paid, balance, rejected, accepted) from the Grand Total row or from sums."""
    if df is None or df.empty:
        return (0, 0, 0, 0, 0)

    # common names across medical + pharmacy scripts
    # medical: Net Amount, Paid, Balance, Rejected, Accepted
    # pharmacy script: NetAmount, Paid, Balance, Rejected, Accepted
    def pick(*names):
        for n in names:
            if n in df.columns:
                return n
        return None

    name_col = pick("Insurance", "Payer", "Insurance/Plan", "Plan", df.columns[0])
    net_col  = pick("Net Amount", "NetAmount")
    paid_col = pick("Paid",)
    bal_col  = pick("Balance",)
    rej_col  = pick("Rejected",)
    acc_col  = pick("Accepted",)

    gt = None
    try:
        mask = df[name_col].astype(str).str.contains("grand total", case=False, na=False)
        if mask.any():
            gt = df.loc[mask].iloc[-1]
    except Exception:
        gt = None

    if gt is not None:
        def g(col): 
            return float(gt.get(col, 0)) if col in df.columns else 0.0
        return (g(net_col), g(paid_col), g(bal_col), g(rej_col), g(acc_col))

    # else fall back to sums
    def s(col):
        return float(df[col].sum()) if col in df.columns else 0.0
    return (s(net_col), s(paid_col), s(bal_col), s(rej_col), s(acc_col))

def full_height(df, row_px: int = 44, header_px: int = 70, padding_px: int = 140) -> int:
    n = 0 if df is None else len(df)
    return header_px + (n * row_px) + padding_px

# --------------------------- Streamlit state ---------------------------
if "center_key" not in st.session_state:
    st.session_state.center_key = None
if "detail_shown" not in st.session_state:
    st.session_state.detail_shown = False
if "last_center_key" not in st.session_state:
    st.session_state.last_center_key = None

# --------------------------- UI ---------------------------
left, right = st.columns([5, 2])
with left:
    st.title("📊 Exclusive Report with Aging — Dashboard")
with right:
    st.caption("View mode")

# reset caches when switching centers
if st.session_state.center_key != st.session_state.last_center_key:
    load_core_sheets.clear()
    load_detail.clear()
    st.session_state.detail_shown = False
    st.session_state.last_center_key = st.session_state.center_key

ck = st.session_state.center_key
if ck not in CENTERS:
    st.subheader("Choose a center")
    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button(CENTERS["easyhealth"]["name"], use_container_width=True):
            st.session_state.center_key = "easyhealth"; st.rerun()
    with c2:
        if st.button(CENTERS["excellent"]["name"], use_container_width=True):
            st.session_state.center_key = "excellent"; st.rerun()
    with c3:
        if st.button(CENTERS["excellent_pharmacy"]["name"], use_container_width=True):
            st.session_state.center_key = "excellent_pharmacy"; st.rerun()
    st.stop()

cfg = CENTERS[st.session_state.center_key]
folder = cfg["folder"]
src_path = folder / cfg["src_name"]
out_path = folder / cfg["out_name"]
generator = cfg["generator"]

st.caption(f"Center: **{cfg['name']}**  ·  Input: {src_path.name}  ·  Report: {out_path.name}")

if st.button("◀ Choose another center"):
    st.session_state.center_key = None
    st.rerun()

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
        load_core_sheets.clear()
        load_detail.clear()
    except Exception as e:
        st.error(str(e))
if colB.button("🗂 Show file locations", use_container_width=True):
    st.info(f"Source: {src_path}\nReport: {out_path}\nScript: {generator}")
if colC.button("🗑 Reset (delete) this center's report", use_container_width=True):
    try:
        if out_path.exists():
            out_path.unlink()
        st.success("Report deleted.")
        load_core_sheets.clear()
        load_detail.clear()
    except Exception as e:
        st.error(str(e))

token = mtime_token(out_path)
if token == 0.0:
    st.warning("Report not found for this center. (Upload source and click Rebuild.)")
    st.stop()

# --------------------------- Load & KPIs ---------------------------
try:
    ins_totals, aging_summary, detail_sheet_name, all_sheets = load_core_sheets(str(out_path), token)
except Exception as e:
    names = []
    try:
        names = pd.ExcelFile(str(out_path)).sheet_names
    except Exception:
        pass
    st.error(f"{e}\n\nAvailable sheets: {', '.join(names) if names else '(none)'}")
    st.stop()

net, paid, bal, rej, acc = totals_from_gt(ins_totals)
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Net Amount", f"{net:,.2f}")
c2.metric("Paid", f"{paid:,.2f}")
c3.metric("Balance", f"{bal:,.2f}")
c4.metric("Rejected", f"{rej:,.2f}")
c5.metric("Accepted", f"{acc:,.2f}")

# --------------------------- Tabs ---------------------------
tabs = st.tabs(["Insurance_Totals", "Balance_Aging_Summary", "Balance_Aging_Detail"])

with tabs[0]:
    st.dataframe(ins_totals, use_container_width=True, height=full_height(ins_totals))

with tabs[1]:
    st.dataframe(aging_summary, use_container_width=True, height=full_height(aging_summary))

with tabs[2]:
    if not detail_sheet_name:
        st.info("No Balance_Aging_Detail sheet detected in this report.")
    else:
        # Lazy load on click (for all centers)
        if not st.session_state.detail_shown:
            if st.button("📂 Load Balance_Aging_Detail (no styling)", use_container_width=True):
                st.session_state.detail_shown = True
                st.rerun()
            # show empty shell
            st.dataframe(pd.DataFrame(columns=[
                "…"  # placeholder header row to keep layout consistent
            ]), use_container_width=True, height=140)
        else:
            try:
                df_detail = load_detail(str(out_path), detail_sheet_name, token)
                st.dataframe(df_detail, use_container_width=True, height=full_height(df_detail))
            except Exception as e:
                st.error(str(e))
        st.caption(f"Available sheets: {', '.join(all_sheets)}")
