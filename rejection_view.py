# rejection_view.py
# Rejection Analysis page (called from exclusive_dashboard.py only when ?view=rejection)
# ✅ Fixes NameError + avoids running at import-time
# ✅ No password re-check, no redirect to view mode
# ✅ Works with Streamlit query params coming from main dashboard

import streamlit as st
import pandas as pd
from pathlib import Path


def _safe_int(x, default=None):
    try:
        return int(x)
    except Exception:
        return default


def _read_excel(path: Path, sheet: str):
    ext = path.suffix.lower()
    engine = "pyxlsb" if ext == ".xlsb" else "openpyxl"
    return pd.read_excel(str(path), sheet_name=sheet, engine=engine)


def _pick_col(df, candidates):
    for c in candidates:
        if c in df.columns:
            return c
    return None


def _to_num(s):
    return pd.to_numeric(s, errors="coerce").fillna(0)


def render_rejection_page(center_key: str, year: int, centers: dict, base_dir=None, data_dir=None):
    """
    Required by exclusive_dashboard.py:
      render_rejection_page(center_key=..., year=..., centers=..., base_dir=..., data_dir=...)
    """
    st.markdown("## ❌ Rejection Analysis")

    if center_key not in centers:
        st.error("Invalid center key.")
        return

    cfg = centers[center_key]
    folder = Path(cfg["folder_root"]) / str(year)
    report_path = folder / cfg["out_name"]

    st.caption(f"Center: **{cfg['name']}**  ·  Year: **{year}**")
    st.write("---")

    if not report_path.exists():
        st.warning(f"No report found for this center/year:\n\n{report_path}")
        return

    # Try to load a rejection-related sheet (you can adjust sheet names here if your file differs)
    sheet_candidates = [
        "Rejection_Analysis",
        "Rejection Analysis",
        "Rejected_Analysis",
        "Rejected Analysis",
        "Rejections",
        "Rejected",
        "Insurance_Totals",  # fallback (will still show rejected totals if available)
    ]

    df = None
    used_sheet = None
    last_err = None
    for s in sheet_candidates:
        try:
            df = _read_excel(report_path, s)
            used_sheet = s
            break
        except Exception as e:
            last_err = e

    if df is None:
        st.error("Could not find any rejection sheet in the report.")
        st.write("Tried sheets:", sheet_candidates)
        st.write("Last error:", last_err)
        # show available sheets for debugging
        try:
            ext = report_path.suffix.lower()
            engine = "pyxlsb" if ext == ".xlsb" else "openpyxl"
            names = pd.ExcelFile(str(report_path), engine=engine).sheet_names
            st.info("Available sheets: " + ", ".join(names))
        except Exception:
            pass
        return

    df = df.dropna(how="all")
    df.columns = [str(c).strip() for c in df.columns]

    st.caption(f"Loaded sheet: **{used_sheet}**")
    st.write("")

    # ====== Smart column detection (works with different file formats) ======
    col_ins = _pick_col(df, ["Insurance", "Payer", "Insurer", "TPA", "Company"])
    col_plan = _pick_col(df, ["Plan", "Plan Name", "Policy", "Network Plan"])
    col_code = _pick_col(df, ["Rejection Code", "Code", "Denial Code", "Reject Code"])
    col_reason = _pick_col(df, ["Rejection Reason", "Reason", "Denial Reason", "Reject Reason", "Comment", "Remarks"])
    col_amount = _pick_col(df, ["Rejected Amount", "Rejected", "Rejection Amount", "Amount", "Net Amount", "NetAmount"])
    col_count = _pick_col(df, ["Count", "Rejected Count", "Claims", "No of Claims", "Total Claims"])

    # If fallback is Insurance_Totals, we might only have totals columns
    # We will still show it, but disable deep filters if columns missing.
    filters = st.columns(4)

    def _make_filter(colname):
        if not colname:
            return None, None
        vals = (
            df[colname]
            .dropna()
            .astype(str)
            .str.strip()
            .replace({"nan": ""})
        )
        vals = sorted([v for v in vals.unique().tolist() if v and v.lower() not in ("grand total", "total")])
        return colname, ["All"] + vals

    f_ins = _make_filter(col_ins)
    f_plan = _make_filter(col_plan)
    f_code = _make_filter(col_code)
    # reason can be huge — we'll do a text search instead
    reason_search = None

    with filters[0]:
        sel_ins = None
        if f_ins:
            sel_ins = st.selectbox("Insurance", f_ins[1], index=0)
    with filters[1]:
        sel_plan = None
        if f_plan:
            sel_plan = st.selectbox("Plan", f_plan[1], index=0)
    with filters[2]:
        sel_code = None
        if f_code:
            sel_code = st.selectbox("Rejection Code", f_code[1], index=0)
    with filters[3]:
        reason_search = st.text_input("Search reason text", value="", placeholder="type words...")

    view = df.copy()

    if col_ins and sel_ins and sel_ins != "All":
        view = view[view[col_ins].astype(str).str.strip() == sel_ins]
    if col_plan and sel_plan and sel_plan != "All":
        view = view[view[col_plan].astype(str).str.strip() == sel_plan]
    if col_code and sel_code and sel_code != "All":
        view = view[view[col_code].astype(str).str.strip() == sel_code]
    if reason_search and col_reason:
        view = view[view[col_reason].astype(str).str.contains(reason_search, case=False, na=False)]

    # ====== KPIs ======
    k1, k2, k3 = st.columns(3)

    total_amt = _to_num(view[col_amount]).sum() if col_amount else 0
    total_cnt = _to_num(view[col_count]).sum() if col_count else len(view)

    with k1:
        st.metric("Rejected Amount", f"{total_amt:,.2f}")
    with k2:
        st.metric("Rejected Count", f"{int(total_cnt):,}")
    with k3:
        st.metric("Rows", f"{len(view):,}")

    st.write("---")

    # ====== Top tables ======
    if col_reason:
        st.subheader("Top Rejection Reasons")
        grp_cols = [col_reason]
        if col_code:
            grp_cols = [col_code, col_reason]

        agg = view.groupby(grp_cols, dropna=False).agg(
            Amount=(col_amount, lambda s: _to_num(s).sum()) if col_amount else ("__dummy__", "size"),
            Count=(col_count, lambda s: _to_num(s).sum()) if col_count else ("__dummy__", "size"),
        ).reset_index()

        if "Amount" in agg.columns:
            agg = agg.sort_values("Amount", ascending=False)
        else:
            agg = agg.sort_values("Count", ascending=False)

        st.dataframe(agg.head(50), use_container_width=True)

    if col_ins:
        st.subheader("Insurance Summary")
        agg2 = view.groupby([col_ins], dropna=False).agg(
            Amount=(col_amount, lambda s: _to_num(s).sum()) if col_amount else ("__dummy__", "size"),
            Count=(col_count, lambda s: _to_num(s).sum()) if col_count else ("__dummy__", "size"),
        ).reset_index()
        if "Amount" in agg2.columns:
            agg2 = agg2.sort_values("Amount", ascending=False)
        else:
            agg2 = agg2.sort_values("Count", ascending=False)
        st.dataframe(agg2, use_container_width=True)

    st.subheader("Detailed Rows")
    st.dataframe(view, use_container_width=True, height=650)

    # ====== Download ======
    st.download_button(
        "⬇️ Download current filtered rejection rows (CSV)",
        view.to_csv(index=False).encode("utf-8"),
        file_name=f"{center_key}_{year}_rejection_filtered.csv",
        use_container_width=True,
        key=f"dl_rej_{center_key}_{year}",
    )
