# exclusive_dashboard.py  — CRASH-SAFE LITE + Doc Performance (fixed columns + month filter)
# Outputs EXACT columns per doctor-month:
#   Doctor, Year, MonthNum, Month(=> Jan/Feb...), Visits, Consultation, Medicines, Procedure, Other, Row_Total, Avg_per_Visit
# Only the selected (Current or Last) month is processed & saved per center.

import sys
import subprocess
from pathlib import Path
from datetime import datetime, date
from io import BytesIO

import pandas as pd
import streamlit as st

# ====================== Page & base folders ======================
st.set_page_config(page_title="Exclusive Report with Aging — Dashboard", layout="wide")
st.set_option("client.showErrorDetails", False)

# 👉 External Doc Performance app URL
DOC_PERF_URL = "https://doc-perf-app.streamlit.app"   # <-- replace with your deployed URL if different

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
    try: return p.stat().st_mtime
    except FileNotFoundError: return 0.0

def _run(cmd):
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError("Command failed:\n" + " ".join(cmd)
                           + "\n\nSTDOUT:\n" + (res.stdout or "(empty)")
                           + "\n\nSTDERR:\n" + (res.stderr or "(empty)"))
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
        if p.exists(): return p
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
        try: names = pd.ExcelFile(path, engine=engine).sheet_names
        except Exception: names = []
        raise RuntimeError(f"Required sheets not found or failed to load. "
                           f"Available: {', '.join(names) if names else '(none)'}\nOriginal error: {e}")

def trim_empty_rows(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty: return df
    df2 = df.dropna(how="all")
    if df2.empty: return df2
    blank_rows = df2.fillna("").astype(str).apply(lambda r: "".join(r).strip() == "", axis=1)
    return df2.loc[~blank_rows]

def drop_empty_insurance(df: pd.DataFrame, name_col: str = "Insurance") -> pd.DataFrame:
    if df is None or df.empty or name_col not in df.columns: return df
    series = df[name_col].astype(str).fillna("").str.strip()
    bad = series.str.lower().isin(["", "none", "nan", "null", "na", "-", "--"])
    keep_grand = series.str.contains("grand total", case=False, na=False)
    return df.loc[~bad | keep_grand].copy()

def ensure_grand_total(df: pd.DataFrame, name_col: str = "Insurance") -> pd.DataFrame:
    if df is None or df.empty or name_col not in df.columns: return df
    if df[name_col].astype(str).str.lower().str.contains("grand total").any(): return df
    num_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    gt = {c: pd.to_numeric(df[c], errors="coerce").sum() for c in num_cols}
    row = {c: "" for c in df.columns}; row.update(gt); row[name_col] = "Grand Total"
    return pd.concat([df, pd.DataFrame([row])], ignore_index=True)

def full_height(df, row_px: int = 45, header_px: int = 70, padding_px: int = 150) -> int:
    n = 0 if df is None else len(df); return header_px + (n * row_px) + padding_px

def ksum(df: pd.DataFrame, *cands):
    for col in cands:
        if col in df.columns: return float(pd.to_numeric(df[col], errors="coerce").sum())
    return 0.0

def is_admin_mode() -> bool:
    secret_pwd = st.secrets.get("ADMIN_PASSWORD", "")
    if secret_pwd:
        if st.session_state.get("is_admin", False): return True
        with st.popover("🔒 Admin login"):
            pwd = st.text_input("Password", type="password", key="admin_pwd")
            if st.button("Login"):
                if pwd == secret_pwd:
                    st.session_state.is_admin = True; st.rerun()
                else:
                    st.error("Wrong password")
        return False
    else:
        return st.toggle("Admin mode", value=st.session_state.get("is_admin", False))

# ====================== Doc Performance helpers ======================
def month_options():
    today = date.today()
    cur_ym = today.year * 100 + today.month
    last_ym = (today.year - 1) * 100 + 12 if today.month == 1 else today.year * 100 + (today.month - 1)
    return [("Current month", str(cur_ym)), ("Last month", str(last_ym))]

def yyyymm_to_label(yyyymm: str) -> str:
    y = int(yyyymm[:4]); m = int(yyyymm[4:])
    return f"{date(y, m, 1):%b %Y}"

def docperf_folder(center_key: str) -> Path:
    return (CENTERS[center_key]["folder_root"] / "docperf")

def parquet_path(center_key: str, yyyymm: str) -> Path:
    folder = docperf_folder(center_key) / yyyymm
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "docperf.parquet"

def csv_doctor_index_path(center_key: str, yyyymm: str) -> Path:
    return docperf_folder(center_key) / yyyymm / "doctors.csv"

def _read_any_excel(upload_or_path):
    try:
        return pd.read_excel(upload_or_path, engine="openpyxl")
    except Exception:
        try:
            return pd.read_excel(upload_or_path, engine="pyxlsb")
        except Exception as e2:
            raise RuntimeError(f"Failed to read Excel. Please upload .xlsx or .xlsb. Original error: {e2}")

def _bucketize_item_group(x: str) -> str:
    g = (str(x) if x is not None else "").strip().lower()
    if "consult" in g: return "Consultation"
    if any(k in g for k in ["med", "drug", "pharm", "syrup", "capsule", "tablet"]): return "Medicines"
    if any(k in g for k in ["procedure", "inject", "nebuli", "ecg", "dressing", "iv", "vitamin", "physio", "x-ray", "xray", "ultra", "usg", "lab", "test"]):
        return "Procedure"
    return "Other"

def build_docperf_report(df: pd.DataFrame) -> pd.DataFrame:
    """
    Expect columns (case-insensitive):
      VisitNo, VisitDate, DocName, Item Group, ActivityIns/Net Amount
    Output per doctor-month (one row):
      Doctor, Year, MonthNum, Month(=Jan...), Visits, Consultation, Medicines, Procedure, Other, Row_Total, Avg_per_Visit
    """
    cols = {c.lower().strip(): c for c in df.columns}
    def has(name): return name in cols
    def col(name): return cols[name]

    vno = col("visitno") if has("visitno") else None
    vdt = col("visitdate") if has("visitdate") else None
    dnm = col("docname") if has("docname") else None
    igp = col("item group") if has("item group") else None

    amt_col = None
    for cand in ["activityins", "net amount", "netamount", "net"]:
        if has(cand): amt_col = cols[cand]; break
    if not all([vno, vdt, dnm]) or igp is None or amt_col is None:
        raise RuntimeError("Missing columns. Need: VisitNo, VisitDate, DocName, Item Group, and ActivityIns/Net Amount.")

    df2 = df[[vno, vdt, dnm, igp, amt_col]].copy()
    df2.rename(columns={vno: "VisitNo", vdt: "VisitDate", dnm: "Doctor", igp: "Item Group", amt_col: "Amount"}, inplace=True)
    df2["VisitDate"] = pd.to_datetime(df2["VisitDate"], errors="coerce")
    df2["Amount"] = pd.to_numeric(df2["Amount"], errors="coerce").fillna(0.0)

    # Year / MonthNum / Month (Jan)
    df2["Year"] = df2["VisitDate"].dt.year
    df2["MonthNum"] = df2["VisitDate"].dt.month
    df2["Month"] = df2["VisitDate"].dt.strftime("%b")  # Jan, Feb, ...

    # Bucketize item groups
    df2["Bucket"] = df2["Item Group"].apply(_bucketize_item_group)

    # Unique visits per doctor-month
    visits = (df2.dropna(subset=["VisitNo", "Doctor"])
                .groupby(["Year", "MonthNum", "Month", "Doctor"], as_index=False)
                .agg(Visits=("VisitNo", pd.Series.nunique)))

    # Amounts by bucket per doctor-month
    bucket_sum = (df2.groupby(["Year", "MonthNum", "Month", "Doctor", "Bucket"], as_index=False)
                     .agg(Amount=("Amount", "sum")))

    # Pivot to fixed columns
    pivot = (bucket_sum.pivot_table(index=["Year", "MonthNum", "Month", "Doctor"],
                                    columns="Bucket", values="Amount", aggfunc="sum")
                        .fillna(0.0).reset_index())

    # Ensure all fixed columns exist
    for c in ["Consultation", "Medicines", "Procedure", "Other"]:
        if c not in pivot.columns: pivot[c] = 0.0

    # Merge visits
    out = pivot.merge(visits, on=["Year", "MonthNum", "Month", "Doctor"], how="left")
    out["Visits"] = out["Visits"].fillna(0).astype(int)

    # Totals
    out["Row_Total"] = out["Consultation"] + out["Medicines"] + out["Procedure"] + out["Other"]
    out["Avg_per_Visit"] = out.apply(lambda r: round(r["Row_Total"] / r["Visits"]) if r["Visits"] else 0, axis=1)

    # Final order/sort
    out = out[["Doctor", "Year", "MonthNum", "Month", "Visits", "Consultation", "Medicines", "Procedure", "Other", "Row_Total", "Avg_per_Visit"]]
    out.sort_values(["Doctor", "Year", "MonthNum"], inplace=True)
    out.reset_index(drop=True, inplace=True)
    return out

def filter_month(df: pd.DataFrame, yyyymm: str) -> pd.DataFrame:
    y = int(yyyymm[:4]); m = int(yyyymm[4:])
    return df.loc[(df["Year"] == y) & (df["MonthNum"] == m)].copy()

def save_docperf_snapshot(center_key: str, yyyymm: str, df_month: pd.DataFrame):
    p = parquet_path(center_key, yyyymm)
    df_month.to_parquet(p, index=False)
    # doctor index for fast View
    doc_index = df_month[["Doctor", "Row_Total", "Visits"]].copy()
    doc_index = doc_index.sort_values(["Row_Total", "Visits"], ascending=[False, False])
    doc_index.to_csv(csv_doctor_index_path(center_key, yyyymm), index=False)

def load_docperf_snapshot(center_key: str, yyyymm: str) -> pd.DataFrame | None:
    p = parquet_path(center_key, yyyymm)
    return pd.read_parquet(p) if p.exists() else None

def load_doctor_index(center_key: str, yyyymm: str) -> pd.DataFrame | None:
    idx = csv_doctor_index_path(center_key, yyyymm)
    return pd.read_csv(idx) if idx.exists() else None

# ====================== Session state ======================
for key, default in [
    ("center_key", None), ("last_center_key", None),
    ("year", None), ("last_year", None),
    ("dp_center", None), ("dp_month", None), ("dp_selected_doc", None),
]:
    if key not in st.session_state: st.session_state[key] = default

# ====================== Doc Performance Page ======================
def render_docperf_page():
    st.title("👨‍⚕️ Doc monthly performance")
    st.caption("One row per doctor for the selected month, with fixed columns and averages.")

    # Center
    if st.session_state.dp_center is None:
        st.markdown("#### Choose a center")
        c1, c2 = st.columns(2)
        with c1:
            if st.button("Easy Health Medical Clinic (MF8031)", use_container_width=True):
                st.session_state.dp_center = "easyhealth"; st.rerun()
        with c2:
            if st.button("Excellent Medical Center (MF4777)", use_container_width=True):
                st.session_state.dp_center = "excellent"; st.rerun()
        st.stop()

    center_key = st.session_state.dp_center
    st.info(f"**Selected center:** {CENTERS[center_key]['name']}")

    # Month (Current/Last)
    opts = month_options()
    labels = [f"{lab} ({yyyymm_to_label(ym)})" for lab, ym in opts]
    ym_values = [ym for _, ym in opts]
    if st.session_state.dp_month not in ym_values:
        st.session_state.dp_month = ym_values[0]
    st.segmented_control("Choose month", options=ym_values,
                         format_func=lambda ym: [lbl for lbl, val in zip(labels, ym_values) if val == ym][0],
                         key="dp_month")

    t_view, t_admin = st.tabs(["👀 View (management)", "🛠️ Admin (upload & process)"])

    # ---------- View ----------
    with t_view:
        df_snap = load_docperf_snapshot(center_key, st.session_state.dp_month)
        if df_snap is None or df_snap.empty:
            st.warning("No processed snapshot for this month. Ask Admin to upload & process.")
        else:
            idx = load_doctor_index(center_key, st.session_state.dp_month)
            if idx is None or idx.empty:
                idx = df_snap[["Doctor", "Row_Total", "Visits"]].copy().sort_values(["Row_Total", "Visits"], ascending=[False, False])

            st.subheader(f"Doctors — {yyyymm_to_label(st.session_state.dp_month)}")
            st.dataframe(idx, use_container_width=True, height=min(600, 120 + 35*max(1, len(idx))))

            st.markdown("##### Open a doctor")
            doc_names = idx["Doctor"].tolist()
            default_doc = st.session_state.dp_selected_doc or (doc_names[0] if doc_names else None)
            selected_doc = st.selectbox("Choose doctor", doc_names, index=doc_names.index(default_doc) if default_doc in doc_names else 0)
            st.session_state.dp_selected_doc = selected_doc

            row = df_snap.loc[df_snap["Doctor"] == selected_doc]
            if row.empty:
                st.warning("No row for this doctor.")
            else:
                r = row.iloc[0]
                k1, k2, k3 = st.columns(3)
                k1.metric("Row Total", f"{float(r['Row_Total']):,.2f}")
                k2.metric("Visits", f"{int(r['Visits']):,}")
                k3.metric("Avg/Visit", f"{float(r['Avg_per_Visit']):,.0f}")

                # Show the exact row
                st.markdown("###### Summary row")
                st.dataframe(row, use_container_width=True, height=120)

                # Show bucket breakdown as a small table
                st.markdown("###### By bucket")
                by_bucket = pd.DataFrame({
                    "Bucket": ["Consultation", "Medicines", "Procedure", "Other"],
                    "Amount": [r["Consultation"], r["Medicines"], r["Procedure"], r["Other"]],
                }).sort_values("Amount", ascending=False)
                st.dataframe(by_bucket, use_container_width=True, height=210)

                # Download
                bio = BytesIO()
                with pd.ExcelWriter(bio, engine="openpyxl") as w:
                    idx.to_excel(w, sheet_name="Doctors_Index", index=False)
                    row.to_excel(w, sheet_name="Selected_Doctor", index=False)
                    df_snap.to_excel(w, sheet_name="All_Doctors_SelectedMonth", index=False)
                bio.seek(0)
                st.download_button(
                    f"⬇️ Download Doc_Performance_{center_key}_{st.session_state.dp_month}.xlsx",
                    data=bio.getvalue(),
                    file_name=f"Doc_Performance_{center_key}_{st.session_state.dp_month}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                )

    # ---------- Admin ----------
    with t_admin:
        if not st.session_state.is_admin:
            st.warning("Admin login required (click 🔒 Admin login at the top).")
        else:
            st.success("You are in ADMIN mode.")
            st.caption("Upload raw **doctor-wise** Excel (.xlsx or .xlsb). We will process ONLY the chosen month.")
            up = st.file_uploader("Upload file", type=["xlsx", "xlsb"], key=f"dp_upload_{center_key}")
            if st.button("▶ Process & Save snapshot", use_container_width=True, disabled=(up is None)):
                try:
                    raw = _read_any_excel(up)
                    # Build across all months, then keep only the selected yyyymm:
                    rep_all = build_docperf_report(raw)
                    month_df = filter_month(rep_all, st.session_state.dp_month)
                    if month_df.empty:
                        st.warning(f"No rows for {yyyymm_to_label(st.session_state.dp_month)} in this file.")
                    else:
                        save_docperf_snapshot(center_key, st.session_state.dp_month, month_df)
                        st.success(f"Snapshot saved — {CENTERS[center_key]['name']} — {yyyymm_to_label(st.session_state.dp_month)}")
                        st.rerun()
                except Exception as ex:
                    st.error(str(ex))

    # Footer
    c1, c2 = st.columns(2)
    with c1:
        if st.button("◀ Change center", use_container_width=True):
            st.session_state.dp_center = None
            st.session_state.dp_month = None
            st.session_state.dp_selected_doc = None
            st.rerun()
    with c2:
        if st.button("🏠 Back to main dashboard", use_container_width=True):
            st.session_state.center_key = None
            st.session_state.year = None
            st.session_state.dp_center = None
            st.session_state.dp_month = None
            st.session_state.dp_selected_doc = None
            st.rerun()

# ====================== Header & routing ======================
st.title("📊 Exclusive Report with Aging — Dashboard")
st.session_state.is_admin = is_admin_mode()

qs = st.query_params
if st.session_state.center_key is None and qs.get("center"):
    ck_qs = qs.get("center")
    if ck_qs in CENTERS or ck_qs == DOC_PERF_KEY: st.session_state.center_key = ck_qs
if st.session_state.year is None and qs.get("year"):
    try: st.session_state.year = int(qs.get("year"))
    except Exception: pass

if (st.session_state.center_key != st.session_state.last_center_key) or (st.session_state.year != st.session_state.last_year):
    load_core_sheets.clear(); get_report_bytes.clear()
    st.session_state.last_center_key = st.session_state.center_key
    st.session_state.last_year = st.session_state.year

st.caption(f"Mode: **{'admin' if st.session_state.is_admin else 'view'}** · Center: **{st.session_state.center_key or 'none'}** · Year: **{st.session_state.year or 'none'}**")

# ====================== Home cards (4 buttons) ======================
ck = st.session_state.center_key
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
            st.session_state.center_key = "easyhealth"; st.session_state.year = None; st.rerun()
    with c2:
        if st.container(border=True).button(CENTERS["excellent"]["name"], use_container_width=True, key="home_exc"):
            st.session_state.center_key = "excellent"; st.session_state.year = None; st.rerun()
    with c3:
        if st.container(border=True).button(CENTERS["pharmacy"]["name"], use_container_width=True, key="home_pharm"):
            st.session_state.center_key = "pharmacy"; st.session_state.year = None; st.rerun()
    with c4:
        # 👉 Open external Doc Performance app instead of internal route
        st.link_button("Doc monthly performance", DOC_PERF_URL, use_container_width=True, key="home_docperf_link")
    st.stop()

# ====================== Route: Doc Performance ======================
if st.session_state.center_key == DOC_PERF_KEY:
    render_docperf_page()
    st.stop()

# ====================== Main aging dashboard (unchanged logic) ======================
st.subheader("Select Year")
ycols = st.columns(len(YEARS))
for i, y in enumerate(YEARS):
    with ycols[i]:
        if st.session_state.year == y:
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
                st.session_state.year = y; st.rerun()

if st.session_state.year is None:
    cfg_tmp = CENTERS[st.session_state.center_key]
    found = None
    for y in reversed(YEARS):
        out_try = (cfg_tmp["folder_root"] / str(y) / cfg_tmp["out_name"])
        if out_try.exists(): found = y; break
    st.session_state.year = found or YEARS[-1]; st.rerun()

cfg = CENTERS[st.session_state.center_key]
folder = cfg["folder_root"] / str(st.session_state.year)
folder.mkdir(parents=True, exist_ok=True)

src_path = resolve_source_path(folder, preferred=cfg["src_name"])
out_path = folder / cfg["out_name"]
gen_path = cfg["generator"]

if (st.query_params.get("center") != st.session_state.center_key) or (st.query_params.get("year") != str(st.session_state.year)):
    st.query_params["center"] = st.session_state.center_key
    st.query_params["year"]   = str(st.session_state.year)

mt = mtime_token(out_path)
built = "—" if not mt else datetime.fromtimestamp(mt).strftime("%Y-%m-%d %H:%M")
st.caption(f"Built: **{built}** · Source: `{src_path}` · Report: `{out_path.name}`")

if st.button("◀ Choose another center", key="btn_back_center"):
    st.session_state.center_key = None
    st.session_state.year = None
    st.session_state.dp_center = None
    st.session_state.dp_month = None
    st.session_state.dp_selected_doc = None
    try:
        if "center" in st.query_params: del st.query_params["center"]
        if "year" in st.query_params:   del st.query_params["year"]
    except Exception:
        st.experimental_set_query_params()
    st.rerun()

if st.session_state.is_admin:
    st.success("You are in **ADMIN** mode — upload/rebuild is enabled.")
    with st.expander("⬆️ Upload/replace source Excel for this year", expanded=False):
        up = st.file_uploader(
            f"Upload source Excel for {st.session_state.year} (.xlsb/.xlsx/.xlsm)",
            type=["xlsb", "xlsx", "xlsm"],
            key=f"uploader_{st.session_state.center_key}_{st.session_state.year}",
        )
        if up:
            try: st.success(f"Saved to {save_uploaded_source(folder, up).name}")
            except Exception as e: st.error(str(e))

    if st.button("↻ Rebuild report", use_container_width=True, key=f"rebuild_{st.session_state.center_key}_{st.session_state.year}"):
        try:
            if not gen_path.exists(): st.error(f"Generator not found: {gen_path}")
            elif not src_path.exists(): st.error(f"No source file found. Please upload source.xlsb/.xlsx first.")
            else:
                t0 = datetime.now(); msg = rebuild_report(gen_path, src_path, out_path); t1 = datetime.now()
                st.success(f"Report rebuilt successfully in {(t1 - t0).total_seconds():.1f}s.")
                if msg.strip(): st.code(msg, language="bash")
            load_core_sheets.clear(); get_report_bytes.clear()
        except Exception as e:
            st.error(str(e))

token = mtime_token(out_path)
if token == 0.0:
    msg = f"Report not found for {cfg['name']} ({st.session_state.year})."
    if st.session_state.is_admin: msg += " (Upload source and click Rebuild.)"
    st.warning(msg); st.stop()

try:
    totals, summary, _ = load_core_sheets(str(out_path), token)

    totals = totals.copy()
    if "Insurance" not in totals.columns and len(totals.columns) > 0:
        totals = totals.rename(columns={totals.columns[0]: "Insurance"})
    for a in ["NetAmount","Net amount","Net"]:
        if a in totals.columns and "Net Amount" not in totals.columns:
            totals = totals.rename(columns={a: "Net Amount"})
    totals = trim_empty_rows(totals)
    totals = drop_empty_insurance(totals, "Insurance")
    totals = ensure_grand_total(totals, "Insurance")

    summary = trim_empty_rows(summary)
    if not summary.empty:
        summary = ensure_grand_total(summary, summary.columns[0])

    def drop_gt(df):
        if df is None or df.empty: return df
        f = df.columns[0]
        return df.loc[~df[f].astype(str).str.contains("grand total", case=False, na=False)]
    totals_no_gt = drop_gt(totals)

    net = ksum(totals_no_gt, "Net Amount", "NetAmount", "Net")
    paid = ksum(totals_no_gt, "Paid")
    bal  = ksum(totals_no_gt, "Balance")
    rej  = ksum(totals_no_gt, "Rejected", "Rejection")
    acc  = ksum(totals_no_gt, "Accepted")

    t1, t2, t3 = st.tabs([SHEET_INS_TOT, SHEET_SUMMARY, "Downloads"])
    c0, c1, c2, c3, c4 = st.columns(5)
    c0.metric("Net Amount", f"{net:,.2f}")
    c1.metric("Paid",       f"{paid:,.2f}")
    c2.metric("Balance",    f"{bal:,.2f}")
    c3.metric("Rejected",   f"{rej:,.2f}")
    c4.metric("Accepted",   f"{acc:,.2f}")

    with t1:
        st.dataframe(totals, use_container_width=True, height=full_height(totals))
        st.download_button(
            "⬇️ Export Insurance Totals (CSV)",
            totals.to_csv(index=False).encode("utf-8"),
            file_name=f"{cfg['key']}_{st.session_state.year}_insurance_totals.csv",
            use_container_width=True,
            key=f"dl_csv_totals_{st.session_state.center_key}_{st.session_state.year}"
        )

    with t2:
        st.dataframe(summary, use_container_width=True, height=full_height(summary))
        st.download_button(
            "⬇️ Export Summary (CSV)",
            summary.to_csv(index=False).encode("utf-8"),
            file_name=f"{cfg['key']}_{st.session_state.year}_summary.csv",
            use_container_width=True,
            key=f"dl_csv_summary_{st.session_state.center_key}_{st.session_state.year}"
        )

    with t3:
        st.markdown("### Report Download")
        st.write("Open the XLSX locally to inspect **Balance_Aging_Detail** if needed.")
        st.download_button(
            "⬇️ Download full report (.xlsx)",
            get_report_bytes(str(out_path)),
            file_name=out_path.name,
            use_container_width=True,
            key=f"dl_xlsx_full_{st.session_state.center_key}_{st.session_state.year}"
        )

except Exception as e:
    try:
        ext = Path(str(out_path)).suffix.lower()
        eng = "pyxlsb" if ext == ".xlsb" else "openpyxl"
        names = pd.ExcelFile(str(out_path), engine=eng).sheet_names
    except Exception:
        names = []
    st.error(f"{e}\n\nAvailable sheets: {', '.join(names) if names else '(none)'}")
