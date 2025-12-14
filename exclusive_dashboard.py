# exclusive_dashboard.py — Main dashboard KPIs moved to TOP (Doc Performance unchanged)

import sys
import subprocess
from pathlib import Path
from datetime import datetime, date

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components  # used only for the home-card link

# ====================== Page & base folders ======================
st.set_page_config(page_title="Exclusive Report with Aging — Dashboard", layout="wide")
st.set_option("client.showErrorDetails", False)

# External Doc Performance app URL (kept as-is; doc-perf code/behavior unchanged)
DOC_PERF_URL = "https://doctor-performance-app-tjwqgmptk8fbo57t4qrfqr.streamlit.app/"

BASE = Path(__file__).parent
DATA_DIR = BASE / "data"
(DATA_DIR / "easyhealth").mkdir(parents=True, exist_ok=True)
(DATA_DIR / "excellent").mkdir(parents=True, exist_ok=True)
(DATA_DIR / "excellent_pharmacy").mkdir(parents=True, exist_ok=True)

DOC_PERF_KEY = "__docperf__"
YEARS = [2024, 2025]

# Canonical sheet names for main Aging report
SHEET_INS_TOT = "Insurance_Totals"
SHEET_SUMMARY = "Balance_Aging_Summary"
SHEET_DETAIL  = "Balance_Aging_Detail"
SHEET_INGROUP = "Balance_Aging_InsGroup"  # optional tab if present

# ====================== Centers config ======================
CENTERS = {
    "easyhealth": {
        "key": "easyhealth",
        "name": "Easy Health Medical Clinic (MF8031)",
        "folder_root": DATA_DIR / "easyhealth",
        "src_name": "source.xlsx",
        "out_name": "report.xlsx",
        "generator": BASE / "exclusive_report_with_aging_final.py",
    },
    "excellent": {
        "key": "excellent",
        "name": "Excellent Medical Center (MF4777)",
        "folder_root": DATA_DIR / "excellent",
        "src_name": "source.xlsx",
        "out_name": "report.xlsx",
        "generator": BASE / "exclusive_report_with_aging_final.py",
    },
    "pharmacy": {
        "key": "pharmacy",
        "name": "Excellent Pharmacy (PF3205)",
        "folder_root": DATA_DIR / "excellent_pharmacy",
        "src_name": "source.xlsx",
        "out_name": "Pharmacy_Exclusive_Report_with_Aging.xlsx",
        "generator": BASE / "pharmacy_exclusive_report_with_aging.py",
    },
}

# ====================== Small helpers ======================
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
    py = sys.executable
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [py, str(gen_path), str(src_path)]
    try:
        res = _run(cmd + ["--out", str(out_path)])
        return res.stdout or "OK"
    except Exception:
        res = _run([py, str(gen_path), "--out", str(out_path), str(src_path)])
        return res.stdout or "OK"

def resolve_source_path(folder: Path, preferred: str = "source.xlsx") -> Path:
    for p in [folder / "source.xlsb", folder / "source.xlsx", folder / "source.xlsm"]:
        if p.exists():
            return p
    return folder / preferred

def save_uploaded_source(folder: Path, upload) -> Path:
    ext = Path(upload.name).suffix.lower()
    if ext not in {".xlsb", ".xlsx", ".xlsm"}:
        raise ValueError("Please upload an .xlsb, .xlsx, or .xlsm file.")
    dst = folder / f"source{ext}"
    folder.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(upload.read())
    return dst

@st.cache_data(max_entries=6, show_spinner=False)
def get_report_bytes(path: str) -> bytes:
    return Path(path).read_bytes()

@st.cache_data(show_spinner=True)
def load_core_sheets(path: str, _token: float):
    ext = Path(path).suffix.lower()
    engine = "pyxlsb" if ext == ".xlsb" else "openpyxl"
    try:
        df_ins = pd.read_excel(path, sheet_name=SHEET_INS_TOT, engine=engine)
        df_sum = pd.read_excel(path, sheet_name=SHEET_SUMMARY, engine=engine)
        return df_ins, df_sum, [SHEET_INS_TOT, SHEET_SUMMARY]
    except Exception as e:
        try:
            names = pd.ExcelFile(path, engine=engine).sheet_names
        except Exception:
            names = []
        raise RuntimeError(
            f"Required sheets not found or failed to load. "
            f"Available: {', '.join(names) if names else '(none)'}\nOriginal error: {e}"
        )

def trim_empty_rows(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    df2 = df.dropna(how="all")
    if df2.empty:
        return df2
    blank_rows = df2.fillna("").astype(str).apply(lambda r: "".join(r).strip() == "", axis=1)
    return df2.loc[~blank_rows]

def drop_empty_insurance(df: pd.DataFrame, name_col: str = "Insurance") -> pd.DataFrame:
    if df is None or df.empty or name_col not in df.columns:
        return df
    series = df[name_col].astype(str).fillna("").str.strip()
    bad = series.str.lower().isin(["", "none", "nan", "null", "na", "-", "--"])
    keep_grand = series.str.contains("grand total", case=False, na=False)
    return df.loc[~bad | keep_grand].copy()

def ensure_grand_total(df: pd.DataFrame, name_col: str = "Insurance") -> pd.DataFrame:
    if df is None or df.empty or name_col not in df.columns:
        return df
    if df[name_col].astype(str).str.lower().str.contains("grand total").any():
        return df
    num_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    gt = {c: pd.to_numeric(df[c], errors="coerce").sum() for c in num_cols}
    row = {c: "" for c in df.columns}
    row.update(gt)
    row[name_col] = "Grand Total"
    return pd.concat([df, pd.DataFrame([row])], ignore_index=True)

def full_height(df, row_px: int = 45, header_px: int = 70, padding_px: int = 150) -> int:
    n = 0 if df is None else len(df)
    return header_px + (n * row_px) + padding_px

def ksum(df: pd.DataFrame, *cands):
    for col in cands:
        if col in df.columns:
            return float(pd.to_numeric(df[col], errors="coerce").sum())
    return 0.0

def is_admin_mode() -> bool:
    secret_pwd = st.secrets.get("ADMIN_PASSWORD", "")
    if secret_pwd:
        if st.session_state.get("is_admin", False):
            return True
        with st.popover("🔒 Admin login"):
            pwd = st.text_input("Password", type="password", key="admin_pwd")
            if st.button("Login"):
                if pwd == secret_pwd:
                    st.session_state.is_admin = True
                    st.rerun()
                else:
                    st.error("Wrong password")
        return False
    else:
        return st.toggle("Admin mode", value=st.session_state.get("is_admin", False))

# ====================== Doc Performance helpers (UNCHANGED) ======================
def month_options():
    today = date.today()
    cur_ym = today.year * 100 + today.month
    last_ym = (today.year - 1) * 100 + 12 if today.month == 1 else today.year * 100 + (today.month - 1)
    return [("Current month", str(cur_ym)), ("Last month", str(last_ym))]

def yyyymm_to_label(yyyymm: str) -> str:
    y = int(yyyymm[:4])
    m = int(yyyymm[4:])
    return f"{date(y, m, 1):%b %Y}"

# ====================== Header & routing ======================
st.title("📊 Exclusive Report with Aging — Dashboard")
st.session_state.is_admin = is_admin_mode()

qs = st.query_params
if st.session_state.get("center_key") is None and qs.get("center"):
    ck_qs = qs.get("center")
    if ck_qs in CENTERS or ck_qs == DOC_PERF_KEY:
        st.session_state.center_key = ck_qs
if st.session_state.get("year") is None and qs.get("year"):
    try:
        st.session_state.year = int(qs.get("year"))
    except Exception:
        pass

if (st.session_state.get("center_key") != st.session_state.get("last_center_key")) or \
   (st.session_state.get("year") != st.session_state.get("last_year")):
    load_core_sheets.clear()
    get_report_bytes.clear()
    st.session_state.last_center_key = st.session_state.get("center_key")
    st.session_state.last_year = st.session_state.get("year")

st.caption(
    f"Mode: **{'admin' if st.session_state.get('is_admin') else 'view'}** · "
    f"Center: **{st.session_state.get('center_key') or 'none'}** · "
    f"Year: **{st.session_state.get('year') or 'none'}**"
)

# ====================== Home cards (4 buttons) ======================
ck = st.session_state.get("center_key")
if ck not in CENTERS and ck != DOC_PERF_KEY:
    st.subheader("Choose a center")
    btn_css = """
    <style>
    .card-btn > button {
        border: 2px solid #e5e7eb !important;
        padding: 18px 14px !important;
        border-radius: 14px !important;
        font-weight: 600 !important;
        box-shadow: 0 2px 6px rgba(0,0,0,0.05) !important;
    }
    .card-btn > button:hover {
        border-color: #93c5fd !important;
        box-shadow: 0 6px 16px rgba(37,99,235,0.15) !important;
    }
    </style>
    """
    st.markdown(btn_css, unsafe_allow_html=True)
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        if st.container(border=True).button(CENTERS["easyhealth"]["name"], use_container_width=True, key="home_easy"):
            st.session_state.center_key = "easyhealth"
            st.session_state.year = None
            st.rerun()
    with c2:
        if st.container(border=True).button(CENTERS["excellent"]["name"], use_container_width=True, key="home_exc"):
            st.session_state.center_key = "excellent"
            st.session_state.year = None
            st.rerun()
    with c3:
        if st.container(border=True).button(CENTERS["pharmacy"]["name"], use_container_width=True, key="home_pharm"):
            st.session_state.center_key = "pharmacy"
            st.session_state.year = None
            st.rerun()
    with c4:
        # External link tile for Doc performance (UNCHANGED)
        components.html(
            f"""
            <a href="{DOC_PERF_URL}" target="_blank" style="text-decoration:none;">
              <div style="
                  border:2px solid #e5e7eb;border-radius:14px;padding:18px 14px;
                  font-weight:600;text-align:center;box-shadow:0 2px 6px rgba(0,0,0,.05);
                  color:inherit;
              " onmouseover="this.style.borderColor='#93c5fd'; this.style.boxShadow='0 6px 16px rgba(37,99,235,0.15)';"
                onmouseout="this.style.borderColor='#e5e7eb'; this.style.boxShadow='0 2px 6px rgba(0,0,0,.05)';">
                Doc monthly performance
              </div>
            </a>
            """,
            height=90,
        )
    st.stop()

# ====================== MAIN aging dashboard (KPIs moved to top) ======================
st.subheader("Select Year")
ycols = st.columns(len(YEARS))
for i, y in enumerate(YEARS):
    with ycols[i]:
        if st.session_state.get("year") == y:
            st.markdown(
                f"""
                <div style="
                    background-color:#2196F3;
                    color:white;
                    text-align:center;
                    padding:0.8em;
                    border-radius:6px;
                    font-weight:700;
                    font-size:1.1em;
                    border:2px solid #1976D2;">
                    {y}
                </div>
                """, unsafe_allow_html=True)
        else:
            if st.button(str(y), use_container_width=True, key=f"year_btn_{y}"):
                st.session_state.year = y
                st.rerun()

# Pick a year automatically if none
if st.session_state.get("year") is None:
    cfg_tmp = CENTERS[st.session_state.get("center_key")]
    found = None
    for y in reversed(YEARS):
        out_try = (cfg_tmp["folder_root"] / str(y) / cfg_tmp["out_name"])
        if out_try.exists():
            found = y
            break
    st.session_state.year = found or YEARS[-1]
    st.rerun()

cfg = CENTERS[st.session_state.get("center_key")]
folder = cfg["folder_root"] / str(st.session_state.get("year"))
folder.mkdir(parents=True, exist_ok=True)

src_path = resolve_source_path(folder, preferred=cfg["src_name"])
out_path = folder / cfg["out_name"]
gen_path = cfg["generator"]

# Keep URL query in sync
if (st.query_params.get("center") != st.session_state.get("center_key")) or \
   (st.query_params.get("year") != str(st.session_state.get("year"))):
    st.query_params["center"] = st.session_state.get("center_key")
    st.query_params["year"] = str(st.session_state.get("year"))

mt = mtime_token(out_path)
built = "—" if not mt else datetime.fromtimestamp(mt).strftime("%Y-%m-%d %H:%M")
st.caption(f"Built: **{built}** · Source: `{src_path}` · Report: `{out_path.name}`")

if st.button("◀ Choose another center", key="btn_back_center"):
    st.session_state.center_key = None
    st.session_state.year = None
    try:
        if "center" in st.query_params:
            del st.query_params["center"]
        if "year" in st.query_params:
            del st.query_params["year"]
    except Exception:
        st.experimental_set_query_params()
    st.rerun()

# ===== Admin controls (unchanged) =====
if st.session_state.get("is_admin"):
    st.success("You are in **ADMIN** mode — upload/rebuild is enabled.")
    with st.expander("⬆️ Upload/replace source Excel for this year", expanded=False):
        up = st.file_uploader(
            f"Upload source Excel for {st.session_state.get('year')} (.xlsb/.xlsx/.xlsm)",
            type=["xlsb", "xlsx", "xlsm"],
            key=f"uploader_{st.session_state.get('center_key')}_{st.session_state.get('year')}",
        )
        if up:
            try:
                st.success(f"Saved to {save_uploaded_source(folder, up).name}")
            except Exception as e:
                st.error(str(e))

    if st.button("↻ Rebuild report", use_container_width=True,
                 key=f"rebuild_{st.session_state.get('center_key')}_{st.session_state.get('year')}"):
        try:
            if not gen_path.exists():
                st.error(f"Generator not found: {gen_path}")
            elif not src_path.exists():
                st.error("No source file found. Please upload source.xlsb/.xlsx first.")
            else:
                t0 = datetime.now()
                msg = rebuild_report(gen_path, src_path, out_path)
                t1 = datetime.now()
                st.success(f"Report rebuilt successfully in {(t1 - t0).total_seconds():.1f}s.")
                if msg.strip():
                    st.code(msg, language="bash")
            load_core_sheets.clear()
            get_report_bytes.clear()
        except Exception as e:
            st.error(str(e))

# ===== Load report and render =====
token = mtime_token(out_path)
if token == 0.0:
    msg = f"Report not found for {cfg['name']} ({st.session_state.get('year')})."
    if st.session_state.get("is_admin"):
        msg += " (Upload source and click Rebuild.)"
    st.warning(msg)
    st.stop()

try:
    totals, summary, _ = load_core_sheets(str(out_path), token)

    totals = totals.copy()
    if "Insurance" not in totals.columns and len(totals.columns) > 0:
        totals = totals.rename(columns={totals.columns[0]: "Insurance"})
    for a in ["NetAmount", "Net amount", "Net"]:
        if a in totals.columns and "Net Amount" not in totals.columns:
            totals = totals.rename(columns={a: "Net Amount"})
    totals = trim_empty_rows(totals)
    totals = drop_empty_insurance(totals, "Insurance")
    totals = ensure_grand_total(totals, "Insurance")

    summary = trim_empty_rows(summary)
    if not summary.empty:
        summary = ensure_grand_total(summary, summary.columns[0])

    # Optionally load the InsGroup sheet (no errors if missing)
    ext = Path(str(out_path)).suffix.lower()
    engine = "pyxlsb" if ext == ".xlsb" else "openpyxl"
    try:
        insgroup_df = pd.read_excel(str(out_path), sheet_name=SHEET_INGROUP, engine=engine)
        insgroup_df = trim_empty_rows(insgroup_df)
    except Exception:
        insgroup_df = None

    # Helper: move "Grand Total" to last row if present
    def move_grand_total_last(df: pd.DataFrame) -> pd.DataFrame:
        if df is None or df.empty:
            return df
        first = df.columns[0]
        mask = df[first].astype(str).str.contains("grand total", case=False, na=False)
        if not mask.any():
            return df
        body = df.loc[~mask]
        gt = df.loc[mask]
        return pd.concat([body, gt], ignore_index=True)

    # Drop the "Grand Total" row from sums to avoid double counting in KPIs
    def drop_gt(df):
        if df is None or df.empty:
            return df
        f = df.columns[0]
        return df.loc[~df[f].astype(str).str.contains("grand total", case=False, na=False)]
    totals_no_gt = drop_gt(totals)

    # ===== KPI sums =====
    net = ksum(totals_no_gt, "Net Amount", "NetAmount", "Net")
    paid = ksum(totals_no_gt, "Paid")
    bal  = ksum(totals_no_gt, "Balance")
    rej  = ksum(totals_no_gt, "Rejected", "Rejection")
    acc  = ksum(totals_no_gt, "Accepted")

    # ===== TOP KPIs =====
    st.markdown(f"### Key metrics — {st.session_state.get('year')}")
    k0, k1, k2, k3, k4 = st.columns(5)
    k0.metric("Net Amount", f"{net:,.2f}")
    k1.metric("Paid",       f"{paid:,.2f}")
    k2.metric("Balance",    f"{bal:,.2f}")
    k3.metric("Rejected",   f"{rej:,.2f}")
    k4.metric("Accepted",   f"{acc:,.2f}")
    st.markdown("---")

    # ===== Tabs (optional InsGroup) =====
    if insgroup_df is not None:
        t1, t2, tIG, t3 = st.tabs([SHEET_INS_TOT, SHEET_SUMMARY, SHEET_INGROUP, "Downloads"])
    else:
        t1, t2, t3 = st.tabs([SHEET_INS_TOT, SHEET_SUMMARY, "Downloads"])

    # ---------- DISPLAY: hide "S.No" & index starts at 1 ----------
    def _display_df(df: pd.DataFrame) -> pd.DataFrame:
        d = df.drop(columns=["S.No"], errors="ignore").reset_index(drop=True)
        d.index = range(1, len(d) + 1)
        d.index.name = None
        return d
    # ---------------------------------------------------------------

    with t1:
        st.dataframe(
            _display_df(move_grand_total_last(totals)),
            use_container_width=True,
            height=full_height(totals)
        )
        st.download_button(
            "⬇️ Export Insurance Totals (CSV)",
            totals.to_csv(index=False).encode("utf-8"),
            file_name=f"{cfg['key']}_{st.session_state.get('year')}_insurance_totals.csv",
            use_container_width=True,
            key=f"dl_csv_totals_{st.session_state.get('center_key')}_{st.session_state.get('year')}"
        )

    with t2:
        st.dataframe(
            _display_df(move_grand_total_last(summary)),
            use_container_width=True,
            height=full_height(summary)
        )
        st.download_button(
            "⬇️ Export Summary (CSV)",
            summary.to_csv(index=False).encode("utf-8"),
            file_name=f"{cfg['key']}_{st.session_state.get('year')}_summary.csv",
            use_container_width=True,
            key=f"dl_csv_summary_{st.session_state.get('center_key')}_{st.session_state.get('year')}"
        )

    if insgroup_df is not None:
        with tIG:
            insurers = (
                insgroup_df["Insurance"]
                .dropna()
                .astype(str)
                .loc[lambda s: ~s.str.contains("grand total", case=False, na=False)]
                .sort_values()
                .unique()
                .tolist()
            )
            choice = st.selectbox(
                "Filter by Insurance",
                ["All"] + insurers,
                key=f"insgroup_select_{st.session_state.get('center_key')}_{st.session_state.get('year')}",
            )

            view_df = insgroup_df.copy()
            if choice != "All":
                view_df = view_df.loc[view_df["Insurance"].astype(str) == choice] \
                                 .drop(columns=["Insurance"], errors="ignore")
                st.caption(f"Showing InsGroup aging for **{choice}**")

            st.dataframe(
                _display_df(move_grand_total_last(view_df)),
                use_container_width=True,
                height=full_height(view_df)
            )

            st.download_button(
                "⬇️ Export InsGroup (CSV) — current view",
                view_df.to_csv(index=False).encode("utf-8"),
                file_name=f"{cfg['key']}_{st.session_state.get('year')}_insgroup{'_' + choice if choice != 'All' else ''}.csv",
                use_container_width=True,
                key=f"dl_csv_insgroup_view_{st.session_state.get('center_key')}_{st.session_state.get('year')}",
            )

    with t3:
        st.markdown("### Report Download")
        st.write("Open the XLSX locally to inspect **Balance_Aging_Detail** if needed.")
        st.download_button(
            "⬇️ Download full report (.xlsx)",
            get_report_bytes(str(out_path)),
            file_name=out_path.name,
            use_container_width=True,
            key=f"dl_xlsx_full_{st.session_state.get('center_key')}_{st.session_state.get('year')}"
        )

except Exception as e:
    try:
        ext = Path(str(out_path)).suffix.lower()
        eng = "pyxlsb" if ext == ".xlsb" else "openpyxl"
        names = pd.ExcelFile(str(out_path), engine=eng).sheet_names
    except Exception:
        names = []
    st.error(f"{e}\n\nAvailable sheets: {', '.join(names) if names else '(none)'}")

