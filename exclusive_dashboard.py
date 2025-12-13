# exclusive_dashboard.py (CRASH-SAFE LITE)
# Streamlit dashboard for Exclusive Report with Aging — optimized for 50MB+ Excel files
# Key changes vs your previous script:
#  - Removed heavy Pandas Styler and all complex CSS
#  - Single cached read of XLSX bytes for downloads
#  - Removed date-range scanning/filter (no re-reading huge detail sheet)
#  - Removed SHA-1 hashing and bar chart
#  - Direct, minimal sheet reads to reduce memory

import sys
import subprocess
from pathlib import Path
from datetime import datetime
from io import BytesIO  # <-- added

import pandas as pd
import streamlit as st

# add imports for doctor performance helper
from doctor_month_performance import load_minimal, build_report  # <-- added

# =========================== Page & Folders ===========================
st.set_page_config(page_title="Exclusive Report with Aging — Dashboard", layout="wide")
st.set_option("client.showErrorDetails", False)

BASE = Path(__file__).parent
DATA_DIR = BASE / "data"
(DATA_DIR / "easyhealth").mkdir(parents=True, exist_ok=True)
(DATA_DIR / "excellent").mkdir(parents=True, exist_ok=True)
(DATA_DIR / "excellent_pharmacy").mkdir(parents=True, exist_ok=True)

# =========================== Centers & Generators =====================
CENTERS = {
    "easyhealth": {
        "key": "easyhealth",
        "name": "Easy Health Medical Clinic (MF8031)",
        "folder_root": DATA_DIR / "easyhealth",
        "src_name": "source.xlsx",  # fallback; auto-picks .xlsb/.xlsx/.xlsm anyway
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
YEARS = [2024, 2025]

# Canonical sheet names expected from generators
SHEET_INS_TOT = "Insurance_Totals"
SHEET_SUMMARY = "Balance_Aging_Summary"
SHEET_DETAIL  = "Balance_Aging_Detail"  # not rendered in the app

# =============================== Helpers ==============================

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


# ===== XLSB/XLSX source helpers =====

def resolve_source_path(folder: Path, preferred: str = "source.xlsx") -> Path:
    candidates = [folder / "source.xlsb", folder / "source.xlsx", folder / "source.xlsm"]
    for p in candidates:
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


# ---------- caching ----------
@st.cache_data(max_entries=6, show_spinner=False)
def get_report_bytes(path: str) -> bytes:
    return Path(path).read_bytes()


@st.cache_data(show_spinner=True)
def load_core_sheets(path: str, _token: float):
    """Load only the two small sheets required for the UI.
    Prefer direct reads by sheet name to keep memory low. If the expected
    sheet names are missing, show the available list in the error.
    """
    ext = Path(path).suffix.lower()
    engine = "pyxlsb" if ext == ".xlsb" else "openpyxl"

    try:
        df_ins = pd.read_excel(path, sheet_name=SHEET_INS_TOT, engine=engine)
        df_sum = pd.read_excel(path, sheet_name=SHEET_SUMMARY, engine=engine)
        return df_ins, df_sum, [SHEET_INS_TOT, SHEET_SUMMARY]
    except Exception as e:
        # Fallback: list available sheets to help debugging
        try:
            names = pd.ExcelFile(path, engine=engine).sheet_names
        except Exception:
            names = []
        raise RuntimeError(f"Required sheets not found or failed to load. Available: {', '.join(names) if names else '(none)'}\nOriginal error: {e}")


# ---------- table & KPI helpers ----------

def trim_empty_rows(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    df2 = df.dropna(how="all")
    if df2.empty:
        return df2
    blank_rows = df2.fillna("").astype(str).apply(lambda row: "".join(row).strip() == "", axis=1)
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


# ---------- admin ----------

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
        # If no password configured, allow manual toggle
        return st.toggle("Admin mode", value=st.session_state.get("is_admin", False))


# ---------- state ----------
for key, default in [
    ("center_key", None),
    ("last_center_key", None),
    ("year", None),
    ("last_year", None),
]:
    if key not in st.session_state:
        st.session_state[key] = default


# ---------- header ----------
st.title("📊 Exclusive Report with Aging — Dashboard")
st.session_state.is_admin = is_admin_mode()

# URL preselect
qs = st.query_params
if st.session_state.center_key is None and qs.get("center"):
    ck_qs = qs.get("center")
    if ck_qs in CENTERS:
        st.session_state.center_key = ck_qs
if st.session_state.year is None and qs.get("year"):
    try:
        st.session_state.year = int(qs.get("year"))
    except Exception:
        pass

# Clear caches when selection changes
if (st.session_state.center_key != st.session_state.last_center_key) or (st.session_state.year != st.session_state.last_year):
    load_core_sheets.clear()
    get_report_bytes.clear()
    st.session_state.last_center_key = st.session_state.center_key
    st.session_state.last_year = st.session_state.year

st.caption(f"Mode: **{'admin' if st.session_state.is_admin else 'view'}** · Center: **{st.session_state.center_key or 'none'}** · Year: **{st.session_state.year or 'none'}**")

# ---------- center select ----------
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

# ---------- year select ----------
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
                """,
                unsafe_allow_html=True,
            )
        else:
            if st.button(str(y), use_container_width=True, key=f"year_btn_{y}"):
                st.session_state.year = y
                st.rerun()

# Auto-pick latest year with a report else fallback
if st.session_state.year is None:
    cfg_tmp = CENTERS[ck]
    found = None
    for y in reversed(YEARS):
        folder_try = (cfg_tmp["folder_root"] / str(y))
        out_try = folder_try / cfg_tmp["out_name"]
        if out_try.exists():
            found = y; break
    st.session_state.year = found or YEARS[-1]
    st.rerun()

# ---------- resolve paths ----------
cfg = CENTERS[st.session_state.center_key]
folder = cfg["folder_root"] / str(st.session_state.year)
folder.mkdir(parents=True, exist_ok=True)

src_path = resolve_source_path(folder, preferred=cfg["src_name"])
out_path = folder / cfg["out_name"]
gen_path = cfg["generator"]

# Keep URL in sync
if (st.query_params.get("center") != st.session_state.center_key) or (st.query_params.get("year") != str(st.session_state.year)):
    st.query_params["center"] = st.session_state.center_key
    st.query_params["year"]   = str(st.session_state.year)

# Audit ribbon (light)
mt = mtime_token(out_path)
built = "—" if not mt else datetime.fromtimestamp(mt).strftime("%Y-%m-%d %H:%M")
st.caption(f"Built: **{built}** · Source: `{src_path}` · Report: `{out_path.name}`")

# ---------- back to center picker ----------
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

# ---------- admin panel ----------
if st.session_state.is_admin:
    st.success("You are in **ADMIN** mode — upload/rebuild is enabled.")
    with st.expander("⬆️ Upload/replace source Excel for this year", expanded=False):
        up = st.file_uploader(
            f"Upload source Excel for {st.session_state.year} (.xlsb/.xlsx/.xlsm)",
            type=["xlsb", "xlsx", "xlsm"],
            key=f"uploader_{st.session_state.center_key}_{st.session_state.year}",
        )
        if up:
            try:
                saved_to = save_uploaded_source(folder, up)
                st.success(f"Saved to {saved_to.name}")
            except Exception as e:
                st.error(str(e))

    if st.button("↻ Rebuild report", use_container_width=True, key=f"rebuild_{ck}_{st.session_state.year}"):
        try:
            if not gen_path.exists():
                st.error(f"Generator not found: {gen_path}")
            elif not src_path.exists():
                st.error(f"No source file found for {st.session_state.year}. Please upload source.xlsb/.xlsx first.")
            else:
                t0 = datetime.now()
                msg = rebuild_report(gen_path, src_path, out_path)
                t1 = datetime.now()
                st.success(f"Report rebuilt successfully in {(t1 - t0).total_seconds():.1f}s.")
                if msg.strip():
                    st.code(msg, language="bash")
            load_core_sheets.clear(); get_report_bytes.clear()
        except Exception as e:
            st.error(str(e))

# ---------- render ----------
token = mtime_token(out_path)
if token == 0.0:
    msg = f"Report not found for {cfg['name']} ({st.session_state.year})."
    if st.session_state.is_admin:
        msg += " (Upload source and click Rebuild.)"
    st.warning(msg)
    st.stop()

try:
    # Load core sheets (only the two small ones)
    totals, summary, _ = load_core_sheets(str(out_path), token)

    # Normalize totals
    totals = totals.copy()
    if "Insurance" not in totals.columns and len(totals.columns) > 0:
        totals = totals.rename(columns={totals.columns[0]: "Insurance"})
    for a, b in [("NetAmount","Net Amount"), ("Net amount","Net Amount"), ("Net","Net Amount")]:
        if a in totals.columns and "Net Amount" not in totals.columns:
            totals = totals.rename(columns={a: "Net Amount"})
    totals = trim_empty_rows(totals)
    totals = drop_empty_insurance(totals, "Insurance")
    totals = ensure_grand_total(totals, "Insurance")

    # Summary
    summary = trim_empty_rows(summary)
    if not summary.empty:
        summary = ensure_grand_total(summary, summary.columns[0])

    # ---------- KPIs (exclude Grand Total row for sums) ----------
    def drop_grand_total(df: pd.DataFrame) -> pd.DataFrame:
        if df is None or df.empty:
            return df
        first_col = df.columns[0]
        return df.loc[~df[first_col].astype(str).str.contains("grand total", case=False, na=False)]

    totals_no_gt = drop_grand_total(totals)
    net = ksum(totals_no_gt, "Net Amount", "NetAmount", "Net")
    paid = ksum(totals_no_gt, "Paid")
    bal  = ksum(totals_no_gt, "Balance")
    rej  = ksum(totals_no_gt, "Rejected", "Rejection")
    acc  = ksum(totals_no_gt, "Accepted")

    # ---------- Tabs ----------
    if ck in ("easyhealth", "excellent"):
        t1, t2, t_doc, t3 = st.tabs([SHEET_INS_TOT, SHEET_SUMMARY, "Doc monthly performance", "Downloads"])
    else:
        t1, t2, t3 = st.tabs([SHEET_INS_TOT, SHEET_SUMMARY, "Downloads"])
        t_doc = None

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
            key=f"dl_csv_totals_{ck}_{st.session_state.year}"
        )

    with t2:
        st.dataframe(summary, use_container_width=True, height=full_height(summary))
        st.download_button(
            "⬇️ Export Summary (CSV)",
            summary.to_csv(index=False).encode("utf-8"),
            file_name=f"{cfg['key']}_{st.session_state.year}_summary.csv",
            use_container_width=True,
            key=f"dl_csv_summary_{ck}_{st.session_state.year}"
        )

    # ---- Doc monthly performance (only Easy Health / Excellent) ----
    if t_doc is not None:
        with t_doc:
            st.caption("Upload an .xlsx with columns: VisitNo, VisitDate, DocName, Item Group, ActivityIns (Month/Year optional).")
            up_perf = st.file_uploader(
                "Upload Excel (.xlsx)", type=["xlsx"],
                key=f"docperf_{ck}_{st.session_state.year}"
            )

            if up_perf is not None:
                try:
                    df_src = load_minimal(up_perf)     # fast, reads only needed cols/sheet
                    result = build_report(df_src)      # builds doctor→month table + totals
                    st.success("Report generated.")
                    st.dataframe(
                        result,
                        use_container_width=True,
                        height=min(800, 120 + 35 * max(1, len(result.index)))
                    )

                    # Download as Excel
                    bio = BytesIO()
                    with pd.ExcelWriter(bio, engine="openpyxl") as w:
                        result.to_excel(w, sheet_name="Doctor_Performance", index=False)
                    bio.seek(0)
                    st.download_button(
                        "⬇️ Download Doc_Performance_By_Month.xlsx",
                        data=bio.getvalue(),
                        file_name=f"{ck}_{st.session_state.year}_Doc_Performance_By_Month.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True,
                        key=f"dl_docperf_{ck}_{st.session_state.year}"
                    )
                except Exception as ex:
                    st.error(str(ex))

    with t3:
        st.markdown("### Report Download")
        st.write("Open the XLSX locally to inspect **Balance_Aging_Detail** if needed.")
        st.download_button(
            "⬇️ Download full report (.xlsx)",
            get_report_bytes(str(out_path)),
            file_name=out_path.name,
            use_container_width=True,
            key=f"dl_xlsx_full_{ck}_{st.session_state.year}"
        )

except Exception as e:
    try:
        ext = Path(str(out_path)).suffix.lower()
        eng = "pyxlsb" if ext == ".xlsb" else "openpyxl"
        names = pd.ExcelFile(str(out_path), engine=eng).sheet_names
    except Exception:
        names = []
    st.error(f"{e}\n\nAvailable sheets: {', '.join(names) if names else '(none)'}")

