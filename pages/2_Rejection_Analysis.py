# Rejection_Resubmission_Analysis.py
# Upload the ClaimComparison Excel -> get Rejection vs Resubmission lifecycle results.
#
# Run:  streamlit run Rejection_Resubmission_Analysis.py

import io
from datetime import datetime as dt

import pandas as pd
import streamlit as st
from openpyxl import load_workbook
from openpyxl.styles import PatternFill, Font, Alignment

st.set_page_config(page_title="Rejection & Resubmission Analysis", layout="wide")

# =========================================================
# Column mapping  (new ClaimComparison layout)
# =========================================================
COL_INITIAL_STATUS = "InitialActivityStatus"   # status at first submission
COL_CURRENT_STATUS = "CurrentActivityStatus"   # latest status (still open?)
COL_RESUB1_STATUS  = "Resub1ActivityStatus"    # presence => was resubmitted
COL_RESUB2_STATUS  = "Resub2ActivityStatus"
COL_RESUB3_STATUS  = "Resub3ActivityStatus"

COL_AMOUNT    = "ActivityIns"
COL_DENIAL    = "DenialCode"
COL_INSURANCE = "Insurance"

PAID_COLS = [
    "actRemitInsShare",
    "actResub1RemitInsShare",
    "actResub2RemitInsShare",
    "actResub3RemitInsShare",
    "TKBKAmountAct",
]

# date columns to try, in priority order, for aging
DATE_CANDS = ["SubDate", "VisitDate", "ActivityStart"]

# =========================================================
# Helpers
# =========================================================
def _fmt_aed(x):
    try:
        return f"AED {float(x):,.2f}"
    except Exception:
        return f"AED {x}"

def low(series: pd.Series) -> pd.Series:
    # fillna BEFORE astype(str): Arrow string dtype keeps NaN through astype(str)
    return series.fillna("").astype(str).str.strip().str.lower()

def is_blank(series: pd.Series) -> pd.Series:
    s = series.fillna("").astype(str).str.strip().str.lower()
    return s.isin(["", "nan", "none", "null"])

def load_and_prepare(file_bytes: bytes) -> pd.DataFrame:
    df = pd.read_excel(io.BytesIO(file_bytes), header=0, engine="openpyxl")
    # strip the leading/trailing spaces present in this export's headers
    df.columns = df.columns.astype(str).str.strip()

    # numeric coercion
    for c in PAID_COLS + [COL_AMOUNT]:
        if c not in df.columns:
            df[c] = 0
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
    df["Paid"] = df[PAID_COLS].sum(axis=1)

    # insurance / denial cleanup
    if COL_INSURANCE not in df.columns:
        df[COL_INSURANCE] = "Not Available"
    df[COL_INSURANCE] = df[COL_INSURANCE].astype(str).str.strip()
    df.loc[df[COL_INSURANCE].eq(""), COL_INSURANCE] = "Not Available"

    if COL_DENIAL not in df.columns:
        df[COL_DENIAL] = ""
    df[COL_DENIAL] = df[COL_DENIAL].astype(str).str.strip()

    # ensure status columns exist
    for c in [COL_INITIAL_STATUS, COL_CURRENT_STATUS, COL_RESUB1_STATUS,
              COL_RESUB2_STATUS, COL_RESUB3_STATUS]:
        if c not in df.columns:
            df[c] = ""

    # lifecycle flags
    df["_init_rej"]    = low(df[COL_INITIAL_STATUS]).eq("rejected")
    df["_curr_rej"]    = low(df[COL_CURRENT_STATUS]).eq("rejected")
    df["_resubmitted"] = ~is_blank(df[COL_RESUB1_STATUS])

    return df

def lifecycle_summary(df: pd.DataFrame) -> pd.DataFrame:
    init_rej = df["_init_rej"]
    resub    = df["_resubmitted"]
    curr_rej = df["_curr_rej"]

    rows = [
        ("Total Activities",            len(df),                      df[COL_AMOUNT].sum()),
        ("Initially Rejected",          int(init_rej.sum()),          df.loc[init_rej, COL_AMOUNT].sum()),
        ("  -> Resubmitted",            int((init_rej & resub).sum()),df.loc[init_rej & resub, COL_AMOUNT].sum()),
        ("  -> NOT Resubmitted",        int((init_rej & ~resub).sum()),df.loc[init_rej & ~resub, COL_AMOUNT].sum()),
        ("Currently Still Rejected",    int(curr_rej.sum()),          df.loc[curr_rej, COL_AMOUNT].sum()),
        ("Currently Rejected & Unpaid", int((curr_rej & (df["Paid"] == 0)).sum()),
                                        df.loc[curr_rej & (df["Paid"] == 0), COL_AMOUNT].sum()),
        ("Resub-1 Attempts",            int((~is_blank(df[COL_RESUB1_STATUS])).sum()), 0),
        ("Resub-2 Attempts",            int((~is_blank(df[COL_RESUB2_STATUS])).sum()), 0),
        ("Resub-3 Attempts",            int((~is_blank(df[COL_RESUB3_STATUS])).sum()), 0),
    ]
    out = pd.DataFrame(rows, columns=["Metric", "Count", "Amount"])
    out["Amount"] = pd.to_numeric(out["Amount"], errors="coerce").fillna(0).round(2)
    return out

def by_group(df: pd.DataFrame, group_col: str) -> pd.DataFrame:
    init_rej = df["_init_rej"]
    g = df.loc[init_rej].copy()
    if g.empty:
        return pd.DataFrame(columns=[group_col, "Rejected_Count", "Rejected_Amount",
                                     "Resubmitted_Count", "Resubmitted_Amount",
                                     "NotResub_Count", "NotResub_Amount"])
    g["_resub"] = g["_resubmitted"]
    agg = g.groupby(group_col, dropna=False).apply(
        lambda x: pd.Series({
            "Rejected_Count":     len(x),
            "Rejected_Amount":    x[COL_AMOUNT].sum(),
            "Resubmitted_Count":  int(x["_resub"].sum()),
            "Resubmitted_Amount": x.loc[x["_resub"], COL_AMOUNT].sum(),
            "NotResub_Count":     int((~x["_resub"]).sum()),
            "NotResub_Amount":    x.loc[~x["_resub"], COL_AMOUNT].sum(),
        }), include_groups=False
    ).reset_index().sort_values("Rejected_Amount", ascending=False)

    for c in ["Rejected_Amount", "Resubmitted_Amount", "NotResub_Amount"]:
        agg[c] = agg[c].round(2)

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

# -------------------- excel styling --------------------
HEADER_FILL = PatternFill(start_color="BDD7EE", end_color="BDD7EE", fill_type="solid")
TOTAL_FILL  = PatternFill(start_color="FCE4D6", end_color="FCE4D6", fill_type="solid")

def style_bytes(xlsx_bytes: bytes) -> bytes:
    wb = load_workbook(io.BytesIO(xlsx_bytes))
    for ws in wb.worksheets:
        for c in range(1, ws.max_column + 1):
            cell = ws.cell(row=1, column=c)
            cell.fill = HEADER_FILL
            cell.font = Font(bold=True)
            cell.alignment = Alignment(horizontal="center", vertical="center")
        for r in range(2, ws.max_row + 1):
            if str(ws.cell(row=r, column=1).value).strip() in ("Grand Total", "Total Activities"):
                for c in range(1, ws.max_column + 1):
                    ws.cell(row=r, column=c).fill = TOTAL_FILL
                    ws.cell(row=r, column=c).font = Font(bold=True)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()

def build_report(df: pd.DataFrame) -> bytes:
    summary = lifecycle_summary(df)
    by_ins  = by_group(df, COL_INSURANCE)
    by_code = by_group(df, COL_DENIAL)

    # detail of the unworked inventory (rejected, not resubmitted)
    detail_cols = [c for c in [COL_INSURANCE, COL_DENIAL, COL_INITIAL_STATUS,
                               COL_CURRENT_STATUS, COL_AMOUNT, "Paid"] if c in df.columns]
    not_resub = df[df["_init_rej"] & ~df["_resubmitted"]][detail_cols].copy()

    meta = pd.DataFrame([{
        "GeneratedAt": dt.now().strftime("%Y-%m-%d %H:%M:%S"),
        "TotalActivities": len(df),
        "InitiallyRejected": int(df["_init_rej"].sum()),
        "Resubmitted": int((df["_init_rej"] & df["_resubmitted"]).sum()),
        "NotResubmitted": int((df["_init_rej"] & ~df["_resubmitted"]).sum()),
        "StatusColumns": f"{COL_INITIAL_STATUS} / {COL_CURRENT_STATUS} / {COL_RESUB1_STATUS}",
    }])

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        summary.to_excel(w, sheet_name="Lifecycle_Summary", index=False)
        by_ins.to_excel(w, sheet_name="By_Insurance", index=False)
        by_code.to_excel(w, sheet_name="By_DenialCode", index=False)
        not_resub.to_excel(w, sheet_name="NotResubmitted_Detail", index=False)
        meta.to_excel(w, sheet_name="Meta", index=False)
    return style_bytes(buf.getvalue())

# =========================================================
# APP
# =========================================================
st.markdown("## Rejection & Resubmission Analysis")
st.caption(
    "Initially Rejected = InitialActivityStatus == 'rejected'  |  "
    "Resubmitted = Resub1ActivityStatus not blank  |  "
    "Still Open = CurrentActivityStatus == 'rejected'"
)

uploaded = st.file_uploader("Upload ClaimComparison Excel (.xlsx)", type=["xlsx"])

if uploaded is None:
    st.info("Upload the activity Excel to begin.")
    st.stop()

with st.spinner("Reading and analyzing..."):
    df = load_and_prepare(uploaded.getvalue())
    summary = lifecycle_summary(df)
    by_ins  = by_group(df, COL_INSURANCE)
    by_code = by_group(df, COL_DENIAL)
    report_bytes = build_report(df)

# ---- KPI cards ----
init_rej_ct  = int(df["_init_rej"].sum())
init_rej_amt = float(df.loc[df["_init_rej"], COL_AMOUNT].sum())
resub_ct     = int((df["_init_rej"] & df["_resubmitted"]).sum())
notresub_ct  = int((df["_init_rej"] & ~df["_resubmitted"]).sum())
notresub_amt = float(df.loc[df["_init_rej"] & ~df["_resubmitted"], COL_AMOUNT].sum())
resub_rate   = (resub_ct / init_rej_ct * 100) if init_rej_ct else 0

c1, c2, c3, c4 = st.columns(4)
c1.metric("Initially Rejected", f"{init_rej_ct:,}", _fmt_aed(init_rej_amt))
c2.metric("Resubmitted", f"{resub_ct:,}", f"{resub_rate:.1f}% of rejected")
c3.metric("Not Resubmitted", f"{notresub_ct:,}", _fmt_aed(notresub_amt))
c4.metric("Total Activities", f"{len(df):,}", "")

st.download_button(
    "Download Full Report (Excel)",
    data=report_bytes,
    file_name=f"Rejection_Resubmission_Report_{dt.now():%Y%m%d_%H%M}.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
)

st.divider()

tab1, tab2, tab3, tab4 = st.tabs(
    ["Lifecycle Summary", "By Insurance", "By Denial Code", "Not-Resubmitted Detail"]
)

with tab1:
    st.subheader("Lifecycle Summary")
    st.dataframe(summary, use_container_width=True)

with tab2:
    st.subheader("Rejected vs Resubmitted — by Insurance")
    st.dataframe(by_ins, use_container_width=True)

with tab3:
    st.subheader("Rejected vs Resubmitted — by Denial Code")
    st.dataframe(by_code, use_container_width=True)

with tab4:
    st.subheader("Rejected but NOT Resubmitted (unworked inventory)")
    detail_cols = [c for c in [COL_INSURANCE, COL_DENIAL, COL_INITIAL_STATUS,
                               COL_CURRENT_STATUS, COL_AMOUNT, "Paid"] if c in df.columns]
    nr = df[df["_init_rej"] & ~df["_resubmitted"]][detail_cols]
    ins_opts  = ["All"] + sorted(nr[COL_INSURANCE].dropna().unique().tolist()) if COL_INSURANCE in nr else ["All"]
    code_opts = ["All"] + sorted(nr[COL_DENIAL].dropna().unique().tolist()) if COL_DENIAL in nr else ["All"]
    fc1, fc2 = st.columns(2)
    sel_ins  = fc1.selectbox("Insurance", ins_opts)
    sel_code = fc2.selectbox("Denial Code", code_opts)
    f = nr.copy()
    if sel_ins != "All":
        f = f[f[COL_INSURANCE] == sel_ins]
    if sel_code != "All":
        f = f[f[COL_DENIAL] == sel_code]
    st.caption(f"{len(f):,} rows  |  {_fmt_aed(f[COL_AMOUNT].sum())}")
    st.dataframe(f, use_container_width=True)
