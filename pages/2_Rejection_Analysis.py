# pages/2_Rejection_Analysis.py

import boto3
from botocore.exceptions import ClientError
import io
import hashlib
from datetime import datetime as dt

import pandas as pd
import streamlit as st
from openpyxl import load_workbook
from openpyxl.styles import PatternFill, Font, Alignment

# =========================================
# CONFIG
# =========================================
S3_BUCKET = "emc-rcm-storage-2026"
SOURCE_FILENAME = "source.xlsx"
DEFAULT_YEAR_OPTIONS = ["2024", "2025", "2026"]

# =========================================
# S3 HELPERS
# =========================================
def s3_client():
    return boto3.client("s3")

def s3_exists(bucket, key):
    try:
        s3_client().head_object(Bucket=bucket, Key=key)
        return True
    except ClientError:
        return False

def load_file_from_s3(bucket, key):
    obj = s3_client().get_object(Bucket=bucket, Key=key)
    return obj["Body"].read()

# =========================================
# REJECTION ANALYSIS ENGINE
# =========================================
def sha1_short_bytes(b: bytes) -> str:
    return hashlib.sha1(b).hexdigest()[:12]

def ensure_numeric(df: pd.DataFrame) -> pd.DataFrame:
    num_cols = [
        "ActivityIns",
        "actRemitInsShare", "actResub1RemitInsShare",
        "actResub2RemitInsShare", "actResub3RemitInsShare",
        "TKBKAmountAct",
    ]
    for c in num_cols:
        if c not in df.columns:
            df[c] = 0
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
    return df

def compute_paid(df: pd.DataFrame) -> pd.DataFrame:
    df["Paid"] = df[
        [
            "actRemitInsShare", "actResub1RemitInsShare",
            "actResub2RemitInsShare", "actResub3RemitInsShare",
            "TKBKAmountAct",
        ]
    ].sum(axis=1)
    return df

def ensure_insurance_column(df: pd.DataFrame) -> pd.DataFrame:
    insurance_col = next(
        (c for c in ["Insurance", "PayerName", "Insurer", "Plan"] if c in df.columns),
        "Insurance",
    )
    if insurance_col not in df.columns:
        df["Insurance"] = "Not Available"
    elif insurance_col != "Insurance":
        df["Insurance"] = df[insurance_col]
    return df

def add_refdate_and_aging(df: pd.DataFrame) -> pd.DataFrame:
    date_candidates = [c for c in ["SubmissionDate", "ClaimDate", "VisitDate"] if c in df.columns]
    if date_candidates:
        for c in date_candidates:
            df[c] = pd.to_datetime(df[c], errors="coerce", dayfirst=True)
        df["RefDate"] = df[date_candidates].bfill(axis=1).iloc[:, 0]
    else:
        df["RefDate"] = pd.NaT

    today = pd.Timestamp(dt.today().date())
    df["DaysDiff"] = (today - df["RefDate"]).dt.days

    bins = [-1, 30, 45, 60, 90, float("inf")]
    labels = ["0–30 Days", "31–45 Days", "46–60 Days", "61–90 Days", ">90 Days"]
    df["AgingBucket"] = pd.cut(df["DaysDiff"], bins=bins, labels=labels)
    return df

def normalize_denial_code(df: pd.DataFrame) -> pd.DataFrame:
    if "DenialCode" not in df.columns:
        df["DenialCode"] = ""
    df["DenialCode"] = df["DenialCode"].astype(str).fillna("").str.strip()
    df.loc[df["DenialCode"].str.lower().isin(["nan", "none", "null"]), "DenialCode"] = ""
    return df

def build_rejected_df(df: pd.DataFrame) -> pd.DataFrame:
    if "ActivityStatus" not in df.columns:
        return df.iloc[0:0].copy()

    status = df["ActivityStatus"].astype(str).fillna("").str.strip().str.lower()
    mask = (df["Paid"] == 0) & (status == "rejected") & (df["DenialCode"] != "")
    rej = df.loc[mask].copy()
    rej["RejectedAmount"] = rej["ActivityIns"]
    rej["RejectedCount"] = 1
    return rej

def pivot_by_insurance(rej: pd.DataFrame) -> pd.DataFrame:
    out = (
        rej.groupby("Insurance", dropna=False)[["RejectedAmount", "RejectedCount"]]
          .sum()
          .reset_index()
    )
    total_row = {
        "Insurance": "Grand Total",
        "RejectedAmount": out["RejectedAmount"].sum(),
        "RejectedCount": int(out["RejectedCount"].sum()),
    }
    return pd.concat([out, pd.DataFrame([total_row])], ignore_index=True)

def pivot_by_denialcode(rej: pd.DataFrame) -> pd.DataFrame:
    out = (
        rej.groupby("DenialCode", dropna=False)[["RejectedAmount", "RejectedCount"]]
          .sum()
          .reset_index()
          .sort_values("RejectedAmount", ascending=False)
    )
    total_row = {
        "DenialCode": "Grand Total",
        "RejectedAmount": out["RejectedAmount"].sum(),
        "RejectedCount": int(out["RejectedCount"].sum()),
    }
    return pd.concat([out, pd.DataFrame([total_row])], ignore_index=True)

def pivot_insurance_x_denialcode(rej: pd.DataFrame) -> pd.DataFrame:
    pv = pd.pivot_table(
        rej,
        index="Insurance",
        columns="DenialCode",
        values="RejectedAmount",
        aggfunc="sum",
        fill_value=0,
        observed=False,
    )
    pv["Grand Total"] = pv.sum(axis=1)
    pv.loc["Grand Total"] = pv.sum(axis=0)
    pv.reset_index(inplace=True)
    return pv

def pivot_rejection_aging(rej: pd.DataFrame) -> pd.DataFrame:
    labels = ["0–30 Days", "31–45 Days", "46–60 Days", "61–90 Days", ">90 Days"]
    pv = pd.pivot_table(
        rej,
        index="Insurance",
        columns="AgingBucket",
        values="RejectedAmount",
        aggfunc="sum",
        fill_value=0,
        observed=False,
    ).reindex(columns=labels)
    pv["Grand Total"] = pv.sum(axis=1)
    pv.loc["Grand Total"] = pv.sum(axis=0)
    pv.reset_index(inplace=True)
    return pv

# -------------------- styling --------------------
HEADER_FILL = PatternFill(start_color="BDD7EE", end_color="BDD7EE", fill_type="solid")
TOTAL_FILL  = PatternFill(start_color="FCE4D6", end_color="FCE4D6", fill_type="solid")

def style_headers(ws):
    for c in range(1, ws.max_column + 1):
        cell = ws.cell(row=1, column=c)
        cell.fill = HEADER_FILL
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal="center", vertical="center")

def highlight_grand_total_rows(ws, label_col=1, label_value="Grand Total"):
    for r in range(2, ws.max_row + 1):
        if ws.cell(row=r, column=label_col).value == label_value:
            for c in range(1, ws.max_column + 1):
                cell = ws.cell(row=r, column=c)
                cell.fill = TOTAL_FILL
                cell.font = Font(bold=True)

def highlight_last_col(ws):
    last_col = ws.max_column
    for r in range(1, ws.max_row + 1):
        cell = ws.cell(row=r, column=last_col)
        cell.fill = TOTAL_FILL
        cell.font = Font(bold=True)

def apply_styling_to_bytes(xlsx_bytes: bytes) -> bytes:
    wb = load_workbook(io.BytesIO(xlsx_bytes))
    for ws in wb.worksheets:
        style_headers(ws)
        if ws.title in [
            "Rejected_By_Insurance",
            "Rejected_By_DenialCode",
            "Rejected_Ins_x_DenialCode",
            "Rejected_Aging_Summary",
        ]:
            highlight_grand_total_rows(ws, label_col=1, label_value="Grand Total")
            if ws.title in ["Rejected_Ins_x_DenialCode", "Rejected_Aging_Summary"]:
                highlight_last_col(ws)

    out_buf = io.BytesIO()
    wb.save(out_buf)
    return out_buf.getvalue()

def build_rejection_workbook_bytes(input_bytes: bytes, input_name: str = "source.xlsx"):
    df = pd.read_excel(io.BytesIO(input_bytes), engine="openpyxl")
    df.columns = df.columns.str.strip()

    df = ensure_numeric(df)
    df = compute_paid(df)
    df = normalize_denial_code(df)
    df = ensure_insurance_column(df)
    df = add_refdate_and_aging(df)

    rejected_df = build_rejected_df(df)

    by_ins = pivot_by_insurance(rejected_df) if len(rejected_df) else pd.DataFrame(
        [{"Insurance": "Grand Total", "RejectedAmount": 0.0, "RejectedCount": 0}]
    )
    by_code = pivot_by_denialcode(rejected_df) if len(rejected_df) else pd.DataFrame(
        [{"DenialCode": "Grand Total", "RejectedAmount": 0.0, "RejectedCount": 0}]
    )
    ins_x_code = pivot_insurance_x_denialcode(rejected_df) if len(rejected_df) else pd.DataFrame(
        [{"Insurance": "Grand Total", "Grand Total": 0.0}]
    )
    aging_sum = pivot_rejection_aging(rejected_df) if len(rejected_df) else pd.DataFrame(
        [{"Insurance": "Grand Total", "Grand Total": 0.0}]
    )

    meta = pd.DataFrame([{
        "InputFile": input_name,
        "InputSHA1": sha1_short_bytes(input_bytes),
        "GeneratedAt": dt.now().strftime("%Y-%m-%d %H:%M:%S"),
        "RejectedRule": "Paid==0 AND lower(ActivityStatus)=='rejected' AND DenialCode not empty",
        "RejectedRows": int(len(rejected_df)),
    }])

    out_buf = io.BytesIO()
    with pd.ExcelWriter(out_buf, engine="openpyxl") as writer:
        by_ins.to_excel(writer, sheet_name="Rejected_By_Insurance", index=False)
        by_code.to_excel(writer, sheet_name="Rejected_By_DenialCode", index=False)
        ins_x_code.to_excel(writer, sheet_name="Rejected_Ins_x_DenialCode", index=False)
        aging_sum.to_excel(writer, sheet_name="Rejected_Aging_Summary", index=False)
        rejected_df.to_excel(writer, sheet_name="Rejected_Detail", index=False)
        meta.to_excel(writer, sheet_name="Meta", index=False)

    styled = apply_styling_to_bytes(out_buf.getvalue())

    stats = {"rejected_rows": int(len(rejected_df)), "sha1": sha1_short_bytes(input_bytes)}
    return styled, stats

# =========================================
# APP
# =========================================
def run_rejection_app():
    st.subheader("Rejection Analysis")
    st.caption("Rule: Paid==0 AND ActivityStatus=='rejected' AND DenialCode not empty")

    center = st.session_state.get("selected_center")
    year = st.session_state.get("selected_year")

    if center is None or year is None:
        st.warning("Center/Year not detected from dashboard. Please select manually.")
        center = st.selectbox("Center", ["excellent", "pharmacy", "easyhealth"])
        year = st.selectbox("Year", DEFAULT_YEAR_OPTIONS)

    center = str(center).lower()
    year = str(year)

    s3_key = f"streamlit/{center}/{year}/{SOURCE_FILENAME}"

    st.write(f"**Center:** {center}")
    st.write(f"**Year:** {year}")
    st.write(f"**Source:** s3://{S3_BUCKET}/{s3_key}")

    if not s3_exists(S3_BUCKET, s3_key):
        st.error("Source file not found in S3. Upload from dashboard first.")
        st.stop()

    input_bytes = load_file_from_s3(S3_BUCKET, s3_key)

    # ---------- Session state keys ----------
    if "rej_out_xlsx_bytes" not in st.session_state:
        st.session_state.rej_out_xlsx_bytes = None
    if "rej_stats" not in st.session_state:
        st.session_state.rej_stats = None
    if "rej_source_sha1" not in st.session_state:
        st.session_state.rej_source_sha1 = None

    current_sha1 = sha1_short_bytes(input_bytes)

    # If source changed (new upload/year/center), reset old output
    if st.session_state.rej_source_sha1 != current_sha1:
        st.session_state.rej_out_xlsx_bytes = None
        st.session_state.rej_stats = None
        st.session_state.rej_source_sha1 = current_sha1

    gen_col1, gen_col2 = st.columns([1, 1])
    with gen_col1:
        generate = st.button("Generate Rejection Analysis", type="primary")
    with gen_col2:
        if st.session_state.rej_out_xlsx_bytes is not None:
            if st.button("Clear Result"):
                st.session_state.rej_out_xlsx_bytes = None
                st.session_state.rej_stats = None

    if generate:
        with st.spinner("Building rejection analysis (pivots + aging + formatting)..."):
            out_xlsx_bytes, stats = build_rejection_workbook_bytes(input_bytes, SOURCE_FILENAME)

        st.session_state.rej_out_xlsx_bytes = out_xlsx_bytes
        st.session_state.rej_stats = stats
        st.success("Done ✅")

    if st.session_state.rej_out_xlsx_bytes is None:
        st.info("Click **Generate Rejection Analysis** to view tables and filters.")
        st.stop()

    # Use stored output from session (survives filter changes)
    out_xlsx_bytes = st.session_state.rej_out_xlsx_bytes
    stats = st.session_state.rej_stats

    st.download_button(
        "Download Rejection Analysis Excel",
        data=out_xlsx_bytes,
        file_name=f"Rejection_Analysis_{center}_{year}_{stats['sha1']}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    st.metric("Rejected Rows", stats["rejected_rows"])

    # Read summary sheets (LIGHT)
    xls = pd.ExcelFile(io.BytesIO(out_xlsx_bytes), engine="openpyxl")
    df_by_ins = pd.read_excel(xls, sheet_name="Rejected_By_Insurance")
    df_by_code = pd.read_excel(xls, sheet_name="Rejected_By_DenialCode")
    df_ins_x_code = pd.read_excel(xls, sheet_name="Rejected_Ins_x_DenialCode")
    df_aging = pd.read_excel(xls, sheet_name="Rejected_Aging_Summary")

    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "By Insurance",
        "By Denial Code",
        "Insurance × Denial",
        "Aging Summary",
        "Rejected Detail (Filters)"
    ])

    with tab1:
        st.subheader("Rejected by Insurance")
        st.dataframe(df_by_ins, use_container_width=True)

    with tab2:
        st.subheader("Rejected by Denial Code")
        st.dataframe(df_by_code, use_container_width=True)

    with tab3:
        st.subheader("Insurance × Denial Code (Amounts)")
        st.dataframe(df_ins_x_code, use_container_width=True)

    with tab4:
        st.subheader("Rejected Aging Summary")
        st.dataframe(df_aging, use_container_width=True)

    with tab5:
        st.subheader("Rejected Detail (Filter + Download)")

        # Preview only (safe)
        detail_header = pd.read_excel(
            xls,
            sheet_name="Rejected_Detail",
            nrows=0,
            engine="openpyxl"
        ).columns.tolist()

        must_cols = ["Insurance", "DenialCode", "ActivityIns", "Paid", "AgingBucket"]
        usecols = [c for c in must_cols if c in detail_header]
        PREVIEW_ROWS = 2000

        df_small = pd.read_excel(
            xls,
            sheet_name="Rejected_Detail",
            usecols=usecols,
            nrows=PREVIEW_ROWS,
            engine="openpyxl"
        )

        ins_list = sorted(df_small["Insurance"].dropna().astype(str).unique().tolist())
        code_list = sorted(df_small["DenialCode"].dropna().astype(str).unique().tolist())

        c1, c2, c3 = st.columns([1, 1, 1])
        with c1:
            sel_ins = st.selectbox("Insurance", ["All"] + ins_list, key="rej_sel_ins")
        with c2:
            sel_code = st.selectbox("Denial Code", ["All"] + code_list, key="rej_sel_code")
        with c3:
            show_top = st.number_input("Preview rows", 50, 2000, 500, 50, key="rej_preview_rows")

        view = df_small.copy()
        if sel_ins != "All":
            view = view[view["Insurance"].astype(str) == sel_ins]
        if sel_code != "All":
            view = view[view["DenialCode"].astype(str) == sel_code]

        st.caption(f"Preview (from first {PREVIEW_ROWS} rows only). Use download for full filtered data.")
        st.dataframe(view.head(int(show_top)), use_container_width=True)

        st.divider()

        if st.button("Build & Download Filtered Detail Excel", type="primary", key="rej_build_download"):
            with st.spinner("Preparing filtered detail..."):
                df_full = pd.read_excel(
                    pd.ExcelFile(io.BytesIO(out_xlsx_bytes), engine="openpyxl"),
                    sheet_name="Rejected_Detail",
                    engine="openpyxl",
                )
                if sel_ins != "All":
                    df_full = df_full[df_full["Insurance"].astype(str) == sel_ins]
                if sel_code != "All":
                    df_full = df_full[df_full["DenialCode"].astype(str) == sel_code]

                buf = io.BytesIO()
                with pd.ExcelWriter(buf, engine="openpyxl") as writer:
                    df_full.to_excel(writer, sheet_name="Rejected_Detail_Filtered", index=False)

                safe_name = (
                    f"Rejected_Detail_{center}_{year}_{sel_ins}_{sel_code}_{stats['sha1']}.xlsx"
                    .replace(" ", "_").replace("/", "_").replace("\\", "_").replace(":", "_")
                )

                st.download_button(
                    "Download Filtered Detail Excel",
                    data=buf.getvalue(),
                    file_name=safe_name,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key="rej_download_filtered",
                )

                st.success(f"Rows exported: {len(df_full)} ✅")

run_rejection_app()
