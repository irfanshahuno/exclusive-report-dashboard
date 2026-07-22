# Professional Rejection & Resubmission Analysis
# Run: streamlit run Rejection_Analysis_Professional.py

import io
from datetime import datetime as dt

import pandas as pd
import streamlit as st
from openpyxl import load_workbook
from openpyxl.styles import Alignment, Font, PatternFill

st.set_page_config(
    page_title="Rejection & Resubmission Analysis",
    page_icon="📊",
    layout="wide",
)

# =========================================================
# Column mapping
# =========================================================
COL_INITIAL_STATUS = "InitialActivityStatus"
COL_CURRENT_STATUS = "CurrentActivityStatus"
COL_RESUB1_STATUS = "Resub1ActivityStatus"
COL_RESUB2_STATUS = "Resub2ActivityStatus"
COL_RESUB3_STATUS = "Resub3ActivityStatus"

COL_AMOUNT = "ActivityIns"
COL_DENIAL = "DenialCode"
COL_INSURANCE = "Insurance"

PAID_COLS = [
    "actRemitInsShare",
    "actResub1RemitInsShare",
    "actResub2RemitInsShare",
    "actResub3RemitInsShare",
    "TKBKAmountAct",
]

REQUIRED_COLUMNS = [
    COL_INITIAL_STATUS,
    COL_CURRENT_STATUS,
    COL_RESUB1_STATUS,
    COL_AMOUNT,
    COL_DENIAL,
    COL_INSURANCE,
]

# =========================================================
# Styling
# =========================================================
st.markdown(
    """
    <style>
        .block-container {padding-top: 1.5rem; padding-bottom: 2rem;}
        .main-title {font-size: 2rem; font-weight: 750; margin-bottom: 0.15rem;}
        .sub-title {color: #667085; margin-bottom: 1rem;}
        .section-card {
            border: 1px solid #e4e7ec;
            border-radius: 14px;
            padding: 1rem 1.1rem;
            background: white;
            margin-bottom: 0.75rem;
        }
        div[data-testid="stMetric"] {
            border: 1px solid #e4e7ec;
            border-radius: 14px;
            padding: 0.85rem 1rem;
            background: white;
        }
        div[data-testid="stMetricLabel"] {font-weight: 650;}
        .processed-note {
            padding: 0.7rem 0.9rem;
            border-radius: 10px;
            background: #ecfdf3;
            border: 1px solid #abefc6;
            color: #067647;
            margin-bottom: 0.8rem;
        }
    </style>
    """,
    unsafe_allow_html=True,
)

# =========================================================
# Helpers
# =========================================================
def _fmt_aed(value):
    try:
        return f"AED {float(value):,.2f}"
    except Exception:
        return f"AED {value}"


def low(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).str.strip().str.lower()


def is_blank(series: pd.Series) -> pd.Series:
    cleaned = series.fillna("").astype(str).str.strip().str.lower()
    return cleaned.isin(["", "nan", "none", "null"])


def load_and_prepare(file_bytes: bytes) -> pd.DataFrame:
    df = pd.read_excel(io.BytesIO(file_bytes), header=0, engine="openpyxl")
    df.columns = df.columns.astype(str).str.strip()

    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(
            "This Excel does not match the required ClaimComparison layout. "
            f"Missing columns: {', '.join(missing)}"
        )

    # Remove fully blank export rows.
    df = df.dropna(how="all").copy()

    for column in PAID_COLS + [COL_AMOUNT]:
        if column not in df.columns:
            df[column] = 0
        df[column] = pd.to_numeric(df[column], errors="coerce").fillna(0)

    df["Paid"] = df[PAID_COLS].sum(axis=1)

    df[COL_INSURANCE] = df[COL_INSURANCE].fillna("").astype(str).str.strip()
    df.loc[df[COL_INSURANCE].eq(""), COL_INSURANCE] = "Not Available"

    df[COL_DENIAL] = df[COL_DENIAL].fillna("").astype(str).str.strip()
    df.loc[df[COL_DENIAL].eq(""), COL_DENIAL] = "Not Available"

    for column in [COL_RESUB2_STATUS, COL_RESUB3_STATUS]:
        if column not in df.columns:
            df[column] = ""

    df["_init_rej"] = low(df[COL_INITIAL_STATUS]).eq("rejected")
    df["_curr_rej"] = low(df[COL_CURRENT_STATUS]).eq("rejected")
    df["_resubmitted"] = ~is_blank(df[COL_RESUB1_STATUS])

    return df


def lifecycle_summary(df: pd.DataFrame) -> pd.DataFrame:
    init_rej = df["_init_rej"]
    resub = df["_resubmitted"]
    curr_rej = df["_curr_rej"]

    rows = [
        ("Total Activities", len(df), df[COL_AMOUNT].sum()),
        ("Initially Rejected", int(init_rej.sum()), df.loc[init_rej, COL_AMOUNT].sum()),
        ("Resubmitted", int((init_rej & resub).sum()), df.loc[init_rej & resub, COL_AMOUNT].sum()),
        ("Not Resubmitted", int((init_rej & ~resub).sum()), df.loc[init_rej & ~resub, COL_AMOUNT].sum()),
        ("Currently Still Rejected", int(curr_rej.sum()), df.loc[curr_rej, COL_AMOUNT].sum()),
        (
            "Currently Rejected & Unpaid",
            int((curr_rej & df["Paid"].eq(0)).sum()),
            df.loc[curr_rej & df["Paid"].eq(0), COL_AMOUNT].sum(),
        ),
        ("Resubmission 1 Attempts", int((~is_blank(df[COL_RESUB1_STATUS])).sum()), 0),
        ("Resubmission 2 Attempts", int((~is_blank(df[COL_RESUB2_STATUS])).sum()), 0),
        ("Resubmission 3 Attempts", int((~is_blank(df[COL_RESUB3_STATUS])).sum()), 0),
    ]

    out = pd.DataFrame(rows, columns=["Metric", "Count", "Amount"])
    out["Amount"] = pd.to_numeric(out["Amount"], errors="coerce").fillna(0).round(2)
    return out


def by_group(df: pd.DataFrame, group_col: str) -> pd.DataFrame:
    rejected = df.loc[df["_init_rej"]].copy()
    if rejected.empty:
        return pd.DataFrame(
            columns=[
                group_col,
                "Rejected_Count",
                "Rejected_Amount",
                "Resubmitted_Count",
                "Resubmitted_Amount",
                "NotResub_Count",
                "NotResub_Amount",
            ]
        )

    rejected["_resub"] = rejected["_resubmitted"]
    agg = (
        rejected.groupby(group_col, dropna=False)
        .apply(
            lambda x: pd.Series(
                {
                    "Rejected_Count": len(x),
                    "Rejected_Amount": x[COL_AMOUNT].sum(),
                    "Resubmitted_Count": int(x["_resub"].sum()),
                    "Resubmitted_Amount": x.loc[x["_resub"], COL_AMOUNT].sum(),
                    "NotResub_Count": int((~x["_resub"]).sum()),
                    "NotResub_Amount": x.loc[~x["_resub"], COL_AMOUNT].sum(),
                }
            ),
            include_groups=False,
        )
        .reset_index()
        .sort_values("Rejected_Amount", ascending=False)
    )

    for column in ["Rejected_Amount", "Resubmitted_Amount", "NotResub_Amount"]:
        agg[column] = agg[column].round(2)

    total = {
        group_col: "Grand Total",
        "Rejected_Count": agg["Rejected_Count"].sum(),
        "Rejected_Amount": round(agg["Rejected_Amount"].sum(), 2),
        "Resubmitted_Count": agg["Resubmitted_Count"].sum(),
        "Resubmitted_Amount": round(agg["Resubmitted_Amount"].sum(), 2),
        "NotResub_Count": agg["NotResub_Count"].sum(),
        "NotResub_Amount": round(agg["NotResub_Amount"].sum(), 2),
    }
    return pd.concat([agg, pd.DataFrame([total])], ignore_index=True)


def top_denials(df: pd.DataFrame, limit: int = 10) -> pd.DataFrame:
    rejected = df.loc[df["_init_rej"]].copy()
    result = (
        rejected.groupby(COL_DENIAL, dropna=False)
        .agg(
            Rejection_Count=(COL_DENIAL, "size"),
            Rejection_Amount=(COL_AMOUNT, "sum"),
        )
        .reset_index()
        .sort_values(["Rejection_Count", "Rejection_Amount"], ascending=[False, False])
        .head(limit)
    )
    result["Rejection_Amount"] = result["Rejection_Amount"].round(2)
    return result


# -------------------- Excel styling --------------------
HEADER_FILL = PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid")
TOTAL_FILL = PatternFill(start_color="D9EAF7", end_color="D9EAF7", fill_type="solid")


def style_bytes(xlsx_bytes: bytes) -> bytes:
    wb = load_workbook(io.BytesIO(xlsx_bytes))
    for ws in wb.worksheets:
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions

        for c in range(1, ws.max_column + 1):
            cell = ws.cell(row=1, column=c)
            cell.fill = HEADER_FILL
            cell.font = Font(bold=True, color="FFFFFF")
            cell.alignment = Alignment(horizontal="center", vertical="center")
            ws.column_dimensions[cell.column_letter].width = min(
                max(14, len(str(cell.value or "")) + 2), 32
            )

        for r in range(2, ws.max_row + 1):
            first = str(ws.cell(row=r, column=1).value).strip()
            if first in ("Grand Total", "Total Activities"):
                for c in range(1, ws.max_column + 1):
                    ws.cell(row=r, column=c).fill = TOTAL_FILL
                    ws.cell(row=r, column=c).font = Font(bold=True)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def build_report(df: pd.DataFrame) -> bytes:
    summary = lifecycle_summary(df)
    by_ins = by_group(df, COL_INSURANCE)
    by_code = by_group(df, COL_DENIAL)
    top_codes = top_denials(df, 15)

    detail_cols = [
        c
        for c in [
            COL_INSURANCE,
            COL_DENIAL,
            COL_INITIAL_STATUS,
            COL_CURRENT_STATUS,
            COL_AMOUNT,
            "Paid",
        ]
        if c in df.columns
    ]
    not_resub = df[df["_init_rej"] & ~df["_resubmitted"]][detail_cols].copy()

    meta = pd.DataFrame(
        [
            {
                "GeneratedAt": dt.now().strftime("%Y-%m-%d %H:%M:%S"),
                "TotalActivities": len(df),
                "InitiallyRejected": int(df["_init_rej"].sum()),
                "Resubmitted": int((df["_init_rej"] & df["_resubmitted"]).sum()),
                "NotResubmitted": int((df["_init_rej"] & ~df["_resubmitted"]).sum()),
            }
        ]
    )

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        summary.to_excel(writer, sheet_name="Lifecycle_Summary", index=False)
        top_codes.to_excel(writer, sheet_name="Top_Denial_Codes", index=False)
        by_ins.to_excel(writer, sheet_name="By_Insurance", index=False)
        by_code.to_excel(writer, sheet_name="By_DenialCode", index=False)
        not_resub.to_excel(writer, sheet_name="NotResubmitted_Detail", index=False)
        meta.to_excel(writer, sheet_name="Meta", index=False)

    return style_bytes(buf.getvalue())


# =========================================================
# Session state: keep the previous result until Process is clicked again
# =========================================================
for key, default in {
    "analysis_df": None,
    "analysis_summary": None,
    "analysis_by_ins": None,
    "analysis_by_code": None,
    "analysis_top_denials": None,
    "analysis_report": None,
    "processed_filename": None,
    "processed_at": None,
}.items():
    if key not in st.session_state:
        st.session_state[key] = default

# =========================================================
# App header and upload control
# =========================================================
st.markdown('<div class="main-title">Rejection & Resubmission Analysis</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="sub-title">Upload a ClaimComparison Excel file, then click Process File. Previous results remain visible until a new file is processed.</div>',
    unsafe_allow_html=True,
)

with st.container(border=True):
    upload_col, button_col = st.columns([4, 1])
    with upload_col:
        uploaded = st.file_uploader(
            "Upload ClaimComparison Excel (.xlsx)",
            type=["xlsx"],
            help="Selecting a file does not replace the existing report until you click Process File.",
        )
    with button_col:
        st.write("")
        st.write("")
        process_clicked = st.button(
            "Process File",
            type="primary",
            use_container_width=True,
            disabled=uploaded is None,
        )

if process_clicked and uploaded is not None:
    try:
        with st.spinner("Processing rejection data and preparing the report..."):
            processed_df = load_and_prepare(uploaded.getvalue())
            st.session_state.analysis_df = processed_df
            st.session_state.analysis_summary = lifecycle_summary(processed_df)
            st.session_state.analysis_by_ins = by_group(processed_df, COL_INSURANCE)
            st.session_state.analysis_by_code = by_group(processed_df, COL_DENIAL)
            st.session_state.analysis_top_denials = top_denials(processed_df, 10)
            st.session_state.analysis_report = build_report(processed_df)
            st.session_state.processed_filename = uploaded.name
            st.session_state.processed_at = dt.now().strftime("%d %b %Y, %I:%M %p")
        st.success("File processed successfully.")
    except Exception as exc:
        st.error(f"Unable to process this file: {exc}")

# =========================================================
# Results
# =========================================================
if st.session_state.analysis_df is None:
    st.info("Upload the correct ClaimComparison Excel and click **Process File** to create the rejection summary.")
    st.stop()

df = st.session_state.analysis_df
summary = st.session_state.analysis_summary
by_ins = st.session_state.analysis_by_ins
by_code = st.session_state.analysis_by_code
top_codes = st.session_state.analysis_top_denials
report_bytes = st.session_state.analysis_report

st.markdown(
    f'<div class="processed-note"><b>Current report:</b> {st.session_state.processed_filename} &nbsp; | &nbsp; '
    f'<b>Processed:</b> {st.session_state.processed_at}</div>',
    unsafe_allow_html=True,
)

# KPI cards
init_rej_ct = int(df["_init_rej"].sum())
init_rej_amt = float(df.loc[df["_init_rej"], COL_AMOUNT].sum())
resub_ct = int((df["_init_rej"] & df["_resubmitted"]).sum())
notresub_ct = int((df["_init_rej"] & ~df["_resubmitted"]).sum())
notresub_amt = float(df.loc[df["_init_rej"] & ~df["_resubmitted"], COL_AMOUNT].sum())
current_rej_ct = int(df["_curr_rej"].sum())
resub_rate = (resub_ct / init_rej_ct * 100) if init_rej_ct else 0

k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Initially Rejected", f"{init_rej_ct:,}", _fmt_aed(init_rej_amt))
k2.metric("Resubmitted", f"{resub_ct:,}", f"{resub_rate:.1f}% of rejected")
k3.metric("Not Resubmitted", f"{notresub_ct:,}", _fmt_aed(notresub_amt))
k4.metric("Currently Rejected", f"{current_rej_ct:,}")
k5.metric("Total Activities", f"{len(df):,}")

st.write("")

# Top denial codes above the detailed tabs
st.subheader("Most Common Denial Codes")
st.caption("Top initial rejection reasons ranked by count. Amount is based on ActivityIns.")

if top_codes.empty:
    st.info("No initially rejected activities were found.")
else:
    display_top = top_codes.copy()
    display_top.insert(0, "Rank", range(1, len(display_top) + 1))

    left, right = st.columns([1.15, 1])
    with left:
        st.dataframe(
            display_top,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Rank": st.column_config.NumberColumn("#", format="%d"),
                COL_DENIAL: st.column_config.TextColumn("Denial Code"),
                "Rejection_Count": st.column_config.NumberColumn("Count", format="%,d"),
                "Rejection_Amount": st.column_config.NumberColumn("Amount", format="AED %,.2f"),
            },
        )
    with right:
        chart_data = top_codes.set_index(COL_DENIAL)["Rejection_Count"]
        st.bar_chart(chart_data, horizontal=True)

st.write("")

download_col, note_col = st.columns([1, 3])
with download_col:
    st.download_button(
        "Download Full Excel Report",
        data=report_bytes,
        file_name=f"Rejection_Resubmission_Report_{dt.now():%Y%m%d_%H%M}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary",
        use_container_width=True,
    )
with note_col:
    st.caption(
        "The downloadable workbook includes the lifecycle summary, top denial codes, insurance analysis, denial-code analysis, and not-resubmitted detail."
    )

st.divider()

tab1, tab2, tab3, tab4 = st.tabs(
    ["Lifecycle Summary", "By Insurance", "By Denial Code", "Not-Resubmitted Detail"]
)

with tab1:
    st.subheader("Lifecycle Summary")
    st.dataframe(
        summary,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Count": st.column_config.NumberColumn(format="%,d"),
            "Amount": st.column_config.NumberColumn(format="AED %,.2f"),
        },
    )

with tab2:
    st.subheader("Rejected vs Resubmitted by Insurance")
    st.dataframe(
        by_ins,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Rejected_Count": st.column_config.NumberColumn(format="%,d"),
            "Rejected_Amount": st.column_config.NumberColumn(format="AED %,.2f"),
            "Resubmitted_Count": st.column_config.NumberColumn(format="%,d"),
            "Resubmitted_Amount": st.column_config.NumberColumn(format="AED %,.2f"),
            "NotResub_Count": st.column_config.NumberColumn(format="%,d"),
            "NotResub_Amount": st.column_config.NumberColumn(format="AED %,.2f"),
        },
    )

with tab3:
    st.subheader("Rejected vs Resubmitted by Denial Code")
    st.dataframe(
        by_code,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Rejected_Count": st.column_config.NumberColumn(format="%,d"),
            "Rejected_Amount": st.column_config.NumberColumn(format="AED %,.2f"),
            "Resubmitted_Count": st.column_config.NumberColumn(format="%,d"),
            "Resubmitted_Amount": st.column_config.NumberColumn(format="AED %,.2f"),
            "NotResub_Count": st.column_config.NumberColumn(format="%,d"),
            "NotResub_Amount": st.column_config.NumberColumn(format="AED %,.2f"),
        },
    )

with tab4:
    st.subheader("Rejected but Not Resubmitted")
    detail_cols = [
        c
        for c in [
            COL_INSURANCE,
            COL_DENIAL,
            COL_INITIAL_STATUS,
            COL_CURRENT_STATUS,
            COL_AMOUNT,
            "Paid",
        ]
        if c in df.columns
    ]
    nr = df[df["_init_rej"] & ~df["_resubmitted"]][detail_cols].copy()

    ins_opts = ["All"] + sorted(nr[COL_INSURANCE].dropna().astype(str).unique().tolist())
    code_opts = ["All"] + sorted(nr[COL_DENIAL].dropna().astype(str).unique().tolist())

    filter1, filter2 = st.columns(2)
    sel_ins = filter1.selectbox("Insurance", ins_opts)
    sel_code = filter2.selectbox("Denial Code", code_opts)

    filtered = nr.copy()
    if sel_ins != "All":
        filtered = filtered[filtered[COL_INSURANCE] == sel_ins]
    if sel_code != "All":
        filtered = filtered[filtered[COL_DENIAL] == sel_code]

    st.caption(f"{len(filtered):,} activities | {_fmt_aed(filtered[COL_AMOUNT].sum())}")
    st.dataframe(
        filtered,
        use_container_width=True,
        hide_index=True,
        column_config={
            COL_AMOUNT: st.column_config.NumberColumn("Activity Amount", format="AED %,.2f"),
            "Paid": st.column_config.NumberColumn("Paid", format="AED %,.2f"),
        },
    )
