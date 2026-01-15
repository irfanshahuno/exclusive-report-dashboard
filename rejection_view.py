import pandas as pd
import streamlit as st
from pathlib import Path

SHEET_DETAIL = "Balance_Aging_Detail"

@st.cache_data(show_spinner=False)
def _load_detail(report_path: str, token: float) -> pd.DataFrame:
    ext = Path(report_path).suffix.lower()
    engine = "pyxlsb" if ext == ".xlsb" else "openpyxl"
    df = pd.read_excel(report_path, sheet_name=SHEET_DETAIL, engine=engine)
    return df

def _safe_num(x):
    try:
        return float(pd.to_numeric(x, errors="coerce").fillna(0).sum())
    except Exception:
        return 0.0

def render_rejection_page(center_key: str, year: int, report_path: str, center_name: str, built_text: str, back_center: str):
    st.markdown(f"# ❌ Rejection Analysis — {center_name}")
    st.caption(f"Year: **{year}** · Built: **{built_text}** · Report: `{Path(report_path).name}`")

    # Back button: remove view param only (keep center/year)
    c1, c2 = st.columns([1, 3])
    with c1:
        if st.button("⬅ Back", use_container_width=True, key="rej_back_btn"):
            try:
                if "view" in st.query_params:
                    del st.query_params["view"]
            except Exception:
                pass
            st.rerun()
    with c2:
        st.write("")

    rp = Path(report_path)
    if not rp.exists():
        st.warning("Report file not found for this year/center.")
        return

    # ✅ FAST MODE: do NOT load detail unless user asks
    st.markdown("### Downloads")
    st.download_button(
        "⬇️ Download full report (.xlsx)",
        rp.read_bytes(),
        file_name=rp.name,
        use_container_width=True,
        key=f"rej_dl_full_{center_key}_{year}",
    )

    st.markdown("---")
    st.markdown("### View (optional)")
    st.info("To keep dashboard fast, the detail table loads only when you click **Load Detail Table**.")

    load_now = st.button("📄 Load Detail Table", use_container_width=True, key=f"rej_load_{center_key}_{year}")
    if not load_now:
        st.stop()

    token = rp.stat().st_mtime
    try:
        df = _load_detail(str(rp), token)
    except Exception as e:
        st.error(f"Could not load `{SHEET_DETAIL}` sheet: {e}")
        st.stop()

    if df is None or df.empty:
        st.warning("Detail sheet is empty.")
        st.stop()

    # Try to detect column names
    cols = {c.lower().strip(): c for c in df.columns}

    paid_col = cols.get("paid")
    status_col = cols.get("activitystatus") or cols.get("status")
    denial_col = cols.get("denialcode") or cols.get("denial code") or cols.get("denial_code")
    ins_col = cols.get("insurance") or cols.get("payer") or cols.get("insurer")
    amt_col = cols.get("net amount") or cols.get("netamount") or cols.get("amount") or cols.get("claimamount")

    # Build rejection rule like your screenshot: Paid=0 AND status=rejected AND denialcode not empty
    dff = df.copy()

    if paid_col:
        dff[paid_col] = pd.to_numeric(dff[paid_col], errors="coerce").fillna(0)

    if status_col:
        dff[status_col] = dff[status_col].astype(str)

    if denial_col:
        dff[denial_col] = dff[denial_col].astype(str)

    mask = pd.Series(True, index=dff.index)

    if paid_col:
        mask &= (dff[paid_col] == 0)

    if status_col:
        mask &= dff[status_col].str.lower().str.contains("reject")

    if denial_col:
        mask &= dff[denial_col].str.strip().ne("") & ~dff[denial_col].str.lower().isin(["nan", "none", "null"])

    rej = dff.loc[mask].copy()

    # KPIs
    if amt_col and amt_col in rej.columns:
        rej_amt = _safe_num(rej[amt_col])
    else:
        rej_amt = 0.0

    rej_cnt = len(rej)

    top_denial = "—"
    if denial_col and denial_col in rej.columns and rej_cnt > 0:
        top_denial = (
            rej[denial_col]
            .astype(str)
            .value_counts()
            .head(1)
            .index[0]
        )

    k1, k2, k3 = st.columns(3)
    k1.metric("Rejected Amount", f"{rej_amt:,.2f}")
    k2.metric("Rejected Count", f"{rej_cnt:,}")
    k3.metric("Top Denial Code", top_denial)

    st.markdown("---")

    # Filters
    f1, f2 = st.columns(2)
    ins_choice = "All"
    denial_choice = "All"

    if ins_col and ins_col in rej.columns:
        ins_list = sorted([x for x in rej[ins_col].dropna().astype(str).unique().tolist() if x.strip() != ""])
        with f1:
            ins_choice = st.selectbox("Insurance", ["All"] + ins_list, index=0)

    if denial_col and denial_col in rej.columns:
        denial_list = sorted([x for x in rej[denial_col].dropna().astype(str).unique().tolist() if x.strip() != ""])
        with f2:
            denial_choice = st.selectbox("Denial Code", ["All"] + denial_list, index=0)

    view = rej
    if ins_col and ins_choice != "All":
        view = view.loc[view[ins_col].astype(str) == ins_choice]
    if denial_col and denial_choice != "All":
        view = view.loc[view[denial_col].astype(str) == denial_choice]

    st.markdown("### Rejected Detail")
    st.dataframe(view, use_container_width=True, height=650)

    st.download_button(
        "⬇️ Export current view (CSV)",
        view.to_csv(index=False).encode("utf-8"),
        file_name=f"{center_key}_{year}_rejection_view.csv",
        use_container_width=True,
        key=f"rej_dl_view_{center_key}_{year}",
    )
