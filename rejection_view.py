# rejection_view.py
# Rejection Analysis page (called from exclusive_dashboard.py only when ?view=rejection)
# ✅ No code runs at import-time
# ✅ Has "Back" button that returns to dashboard
# ✅ Does NOT re-check password (dashboard already handled it)

import streamlit as st
import pandas as pd
from pathlib import Path


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


def render_rejection_page(center_key: str, year: int, centers: dict):
    st.markdown("## ❌ Rejection Analysis")

    # Back button (removes view=rejection)
    if st.button("⬅ Back to Dashboard", use_container_width=True):
        try:
            if "view" in st.query_params:
                del st.query_params["view"]
        except Exception:
            pass
        st.rerun()

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

    # Try to load rejection sheet(s) if they exist
    sheet_candidates = [
        "Rejection_Analysis",
        "Rejection Analysis",
        "Rejected_Analysis",
        "Rejected Analysis",
        "Rejections",
        "Rejected",
        "Insurance_Totals",  # fallback
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

    # column detection
    col_ins = _pick_col(df, ["Insurance", "Payer", "Insurer", "TPA", "Company"])
    col_plan = _pick_col(df, ["Plan", "Plan Name", "Policy", "Network Plan"])
    col_code = _pick_col(df, ["Rejection Code", "Code", "Denial Code", "Reject Code"])
    col_reason = _pick_col(df, ["Rejection Reason", "Reason", "Denial Reason", "Reject Reason", "Comment", "Remarks"])
    col_amount = _pick_col(df, ["Rejected Amount", "Rejected", "Rejection Amount", "Amount"])
    col_count = _pick_col(df, ["Count", "Rejected Count", "Claims", "No of Claims", "Total Claims"])

    c1, c2, c3, c4 = st.columns(4)

    def _vals(colname):
        if not colname:
            return None
        vals = (
            df[colname]
            .dropna()
            .astype(str)
            .str.strip()
        )
        vals = sorted([v for v in vals.unique().tolist() if v and v.lower() not in ("grand total", "total")])
        return ["All"] + vals

    with c1:
        sel_ins = st.selectbox("Insurance", _vals(col_ins) or ["All"], index=0)
    with c2:
        sel_plan = st.selectbox("Plan", _vals(col_plan) or ["All"], index=0)
    with c3:
        sel_code = st.selectbox("Rejection Code", _vals(col_code) or ["All"], index=0)
    with c4:
        reason_search = st.text_input("Search reason text", value="", placeholder="type words...")

    view = df.copy()
    if col_ins and sel_ins != "All":
        view = view[view[col_ins].astype(str).str.strip() == sel_ins]
    if col_plan and sel_plan != "All":
        view = view[view[col_plan].astype(str).str.strip() == sel_plan]
    if col_code and sel_code != "All":
        view = view[view[col_code].astype(str).str.strip() == sel_code]
    if reason_search and col_reason:
        view = view[view[col_reason].astype(str).str.contains(reason_search, case=False, na=False)]

    k1, k2, k3 = st.columns(3)
    total_amt = _to_num(view[col_amount]).sum() if col_amount else 0.0
    total_cnt = _to_num(view[col_count]).sum() if col_count else float(len(view))

    with k1:
        st.metric("Rejected Amount", f"{total_amt:,.2f}")
    with k2:
        st.metric("Rejected Count", f"{int(total_cnt):,}")
    with k3:
        st.metric("Rows", f"{len(view):,}")

    st.write("---")

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

    st.download_button(
        "⬇️ Download current filtered rejection rows (CSV)",
        view.to_csv(index=False).encode("utf-8"),
        file_name=f"{center_key}_{year}_rejection_filtered.csv",
        use_container_width=True,
        key=f"dl_rej_{center_key}_{year}",
    )
