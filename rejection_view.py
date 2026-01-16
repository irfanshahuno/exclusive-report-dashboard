# rejection_view.py
# ✅ Loaded ONLY when user clicks Rejected KPI (speed)

from pathlib import Path
import pandas as pd
import streamlit as st


SHEET_DETAIL = "Balance_Aging_Detail"


def _mtime_token(p: Path) -> float:
    try:
        return p.stat().st_mtime
    except FileNotFoundError:
        return 0.0


@st.cache_data(show_spinner=True)
def _load_detail(path: str, token: float) -> pd.DataFrame:
    """
    Load Balance_Aging_Detail only when needed.
    token is mtime -> cache invalidation automatically.
    """
    ext = Path(path).suffix.lower()
    engine = "pyxlsb" if ext == ".xlsb" else "openpyxl"
    df = pd.read_excel(path, sheet_name=SHEET_DETAIL, engine=engine)
    return df


def _safe_str_series(s):
    return s.astype(str).fillna("").str.strip()


def render_rejection_page(center_key: str, year: int, centers: dict):
    """
    Called from exclusive_dashboard.py:
        render_rejection_page(center_key=ck, year=yy, centers=CENTERS)
    """
    cfg = centers[center_key]
    base_folder = Path(cfg["folder_root"]) / str(year)
    report_path = base_folder / cfg["out_name"]

    st.title("❌ Rejection Analysis")
    st.caption(f"Center: **{cfg['name']}**  ·  Year: **{year}**")

    if not report_path.exists():
        st.warning(f"Report not found: {report_path.name} (Year {year}).")
        st.stop()

    token = _mtime_token(report_path)
    if token == 0.0:
        st.warning("Report file is missing or unreadable.")
        st.stop()

    # Load detail sheet
    try:
        df = _load_detail(str(report_path), token)
    except Exception as e:
        # show available sheets (helpful error)
        try:
            ext = report_path.suffix.lower()
            engine = "pyxlsb" if ext == ".xlsb" else "openpyxl"
            names = pd.ExcelFile(str(report_path), engine=engine).sheet_names
        except Exception:
            names = []
        st.error(f"Cannot open `{SHEET_DETAIL}`.\n\nError: {e}\n\nAvailable sheets: {', '.join(names) if names else '(none)'}")
        st.stop()

    if df is None or df.empty:
        st.info("Balance_Aging_Detail is empty.")
        st.stop()

    # Try to detect common useful columns (we don't assume exact headers)
    cols = list(df.columns)

    # Candidate columns
    cand_ins = next((c for c in cols if str(c).strip().lower() in ["insurance", "payer", "tpa"]), None)
    cand_status = next((c for c in cols if "status" in str(c).strip().lower()), None)
    cand_reason = next((c for c in cols if "reason" in str(c).strip().lower() or "remark" in str(c).strip().lower()), None)
    cand_code = next((c for c in cols if "code" in str(c).strip().lower()), None)

    # Sidebar filters
    st.markdown("### Filters")

    f1, f2, f3 = st.columns(3)

    # Insurance filter
    if cand_ins:
        ins_list = sorted([x for x in _safe_str_series(df[cand_ins]).unique().tolist() if x and x.lower() not in ["nan", "none"]])
        with f1:
            ins_choice = st.selectbox("Insurance", ["All"] + ins_list, index=0)
    else:
        ins_choice = "All"
        with f1:
            st.caption("Insurance column not detected")

    # Status filter (if exists)
    if cand_status:
        st_list = sorted([x for x in _safe_str_series(df[cand_status]).unique().tolist() if x and x.lower() not in ["nan", "none"]])
        with f2:
            status_choice = st.selectbox("Status", ["All"] + st_list, index=0)
    else:
        status_choice = "All"
        with f2:
            st.caption("Status column not detected")

    # Search in reason/code
    with f3:
        q = st.text_input("Search (reason/code/text)", value="").strip()

    view = df.copy()

    if cand_ins and ins_choice != "All":
        view = view.loc[_safe_str_series(view[cand_ins]) == ins_choice]

    if cand_status and status_choice != "All":
        view = view.loc[_safe_str_series(view[cand_status]) == status_choice]

    if q:
        mask = None
        # search across a few likely text columns
        search_cols = []
        if cand_reason: search_cols.append(cand_reason)
        if cand_code: search_cols.append(cand_code)
        if cand_status: search_cols.append(cand_status)
        if cand_ins: search_cols.append(cand_ins)

        # plus: any object columns (limit to avoid heavy)
        for c in view.columns:
            if len(search_cols) >= 8:
                break
            if c in search_cols:
                continue
            if view[c].dtype == object:
                search_cols.append(c)

        for c in search_cols:
            s = _safe_str_series(view[c]).str.lower()
            m = s.str.contains(q.lower(), na=False)
            mask = m if mask is None else (mask | m)

        if mask is not None:
            view = view.loc[mask]

    # Simple KPIs
    st.markdown("### Summary")
    c1, c2 = st.columns(2)
    with c1:
        st.metric("Rows (filtered)", f"{len(view):,}")
    with c2:
        st.metric("Rows (total)", f"{len(df):,}")

    st.markdown("### Detail (Filtered)")
    st.dataframe(view, use_container_width=True, height=650)

    st.markdown("---")
    st.download_button(
        "⬇️ Download filtered rejection detail (CSV)",
        view.to_csv(index=False).encode("utf-8"),
        file_name=f"{center_key}_{year}_rejection_detail_filtered.csv",
        use_container_width=True,
        key=f"dl_rej_detail_{center_key}_{year}",
    )

    with st.expander("⬇️ Download full report (XLSX)", expanded=False):
        st.download_button(
            "Download full report",
            report_path.read_bytes(),
            file_name=report_path.name,
            use_container_width=True,
            key=f"dl_full_report_from_rej_{center_key}_{year}",
        )
