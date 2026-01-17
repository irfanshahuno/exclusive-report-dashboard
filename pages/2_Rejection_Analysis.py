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
# REJECTION ANALYSIS ENGINE (from your script)
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
    # Rule:
    # Paid == 0 AND ActivityStatus == 'rejected' AND DenialCode not empty
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
    in_buf = io.BytesIO(xlsx_bytes)
    wb = load_workbook(in_buf)

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

def build_rejection_workbook_bytes(input_bytes: bytes, input_name: str = "source.xlsx") -> tuple[bytes, dict]:
    df = pd.read_excel(io.BytesIO(input_bytes), engine="openpyxl")
    df.columns = df.columns.str.strip()

    df = ensure_numeric(df)
    df = compute_paid(df)
    df = normalize_denial_code(df)
    df = ensure_insurance_column(df)
    df = add_refdate_and_aging(df)

    rejected_df = build_rejected_df(df)

    # outputs even if empty
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

    rejected_detail = rejected_df.copy()

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
        rejected_detail.to_excel(writer, sheet_name="Rejected_Detail", index=False)
        meta.to_excel(writer, sheet_name="Meta", index=False)

    styled_bytes = apply_styling_to_bytes(out_buf.getvalue())

    stats = {
        "rejected_rows": int(len(rejected_df)),
        "sha1": sha1_short_bytes(input_bytes),
    }
    return styled_bytes, stats

# =========================================
# APP
# =========================================
def run_rejection_app():
    st.subheader("Rejection Analysis")
    st.caption("Rule: Paid==0 AND ActivityStatus=='rejected' AND DenialCode not empty")

    # Auto-detect from dashboard
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

    run = st.button("Generate Rejection Analysis", type="primary")
    if not run:
        return

    with st.spinner("Building rejection analysis (pivots + aging + formatting)..."):
        out_xlsx_bytes, stats = build_rejection_workbook_bytes(
            input_bytes=input_bytes,
            input_name=SOURCE_FILENAME,
        )

    st.success("Done ✅")

    st.download_button(
        "Download Rejection Analysis Excel",
        data=out_xlsx_bytes,
        file_name=f"Rejection_Analysis_{center}_{year}_{stats['sha1']}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    st.metric("Rejected Rows", stats["rejected_rows"])
        # ---- Read all sheets from the generated workbook (in memory) ----
    xls = pd.ExcelFile(io.BytesIO(out_xlsx_bytes), engine="openpyxl")

    df_by_ins = pd.read_excel(xls, sheet_name="Rejected_By_Insurance")
    df_by_code = pd.read_excel(xls, sheet_name="Rejected_By_DenialCode")
    df_ins_x_code = pd.read_excel(xls, sheet_name="Rejected_Ins_x_DenialCode")
    df_aging = pd.read_excel(xls, sheet_name="Rejected_Aging_Summary")
    df_detail = pd.read_excel(xls, sheet_name="Rejected_Detail")

    # ---- Tabs ----
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

    # ----- Load ONLY required columns (prevents crash) -----
    wanted_cols = [
        "Insurance",
        "DenialCode",
        "ActivityStatus",
        "ActivityIns",
        "Paid",
        "RefDate",
        "DaysDiff",
        "AgingBucket",
    ]

    # read header only
    detail_header = pd.read_excel(
        xls,
        sheet_name="Rejected_Detail",
        nrows=0,
        engine="openpyxl",
    ).columns.tolist()

    usecols = [c for c in wanted_cols if c in detail_header]
    if "Insurance" not in usecols:
        usecols.append("Insurance")
    if "DenialCode" not in usecols:
        usecols.append("DenialCode")

    PREVIEW_ROWS = 2000

    df_detail_small = pd.read_excel(
        xls,
        sheet_name="Rejected_Detail",
        usecols=usecols,
        nrows=PREVIEW_ROWS,
        engine="openpyxl",
    )

    # ----- Filters -----
    ins_list = sorted(
        [x for x in df_detail_small["Insurance"].dropna().unique().tolist() if str(x).strip() != ""]
    )
    code_list = sorted(
        [x for x in df_detail_small["DenialCode"].dropna().unique().tolist() if str(x).strip() != ""]
    )

    c1, c2, c3 = st.columns([1, 1, 1])

    with c1:
        sel_ins = st.selectbox("Insurance", ["All"] + ins_list)

    with c2:
        sel_code = st.selectbox("Denial Code", ["All"] + code_list)

    with c3:
        show_top = st.number_input(
            "Preview rows",
            min_value=50,
            max_value=2000,
            value=500,
            step=50,
        )

    # ----- Apply filters to preview -----
    filt = df_detail_small.copy()

    if sel_ins != "All":
        filt = filt[filt["Insurance"].astype(str) == str(sel_ins)]

    if sel_code != "All":
        filt = filt[filt["DenialCode"].astype(str) == str(sel_code)]

    st.caption(
        f"Previewing {min(len(filt), int(show_top))} rows "
        f"(from first {PREVIEW_ROWS} only)."
    )

    st.dataframe(filt.head(int(show_top)), use_container_width=True)

    st.divider()
    st.write("### Download filtered rejected detail")

    if st.button("Build & Download Filtered Excel", type="primary"):
        with st.spinner("Preparing filtered file..."):

            df_full = pd.read_excel(
                pd.ExcelFile(io.BytesIO(out_xlsx_bytes), engine="openpyxl"),
                sheet_name="Rejected_Detail",
                engine="openpyxl",
            )

            if sel_ins != "All":
                df_full = df_full[df_full["Insurance"].astype(str) == str(sel_ins)]

            if sel_code != "All":
                df_full = df_full[df_full["DenialCode"].astype(str) == str(sel_code)]

            buf = io.BytesIO()
            with pd.ExcelWriter(buf, engine="openpyxl") as writer:
                df_full.to_excel(
                    writer,
                    sheet_name="Rejected_Detail_Filtered",
                    index=False,
                )

            st.download_button(
                "Download Filtered Excel",
                data=buf.getvalue(),
                file_name=f"Rejected_Detail_{center}_{year}_{sel_ins}_{sel_code}.xlsx"
                .replace(" ", "_")
                .replace("/", "_"),
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

            st.success(f"Rows exported: {len(df_full)}")


        with c1:
            sel_ins = st.selectbox("Insurance", ["All"] + ins_list, index=0)

        with c2:
            sel_code = st.selectbox("Denial Code", ["All"] + code_list, index=0)

        with c3:
            show_top = st.number_input("Preview rows", min_value=50, max_value=2000, value=500, step=50)

        # Apply filter to preview sample
        filt = df_detail_small.copy()
        if sel_ins != "All":
            filt = filt[filt["Insurance"].astype(str) == str(sel_ins)]
        if sel_code != "All":
            filt = filt[filt["DenialCode"].astype(str) == str(sel_code)]

        st.caption(
            f"Previewing up to {int(show_top)} rows (from first {PREVIEW_ROWS} rows only). "
            f"Use download for full filtered output."
        )
        st.dataframe(filt.head(int(show_top)), use_container_width=True)

        # ----- FULL filtered download (reads full detail but NOT displayed) -----
        st.divider()
        st.write("### Download filtered detail")

        # Button to build filtered excel on-demand (so it doesn't crash UI)
        if st.button("Build & Download Filtered Detail Excel", type="primary"):
            with st.spinner("Preparing filtered detail Excel..."):
                # Read FULL detail sheet (but don't render it)
                df_full_detail = pd.read_excel(
                    pd.ExcelFile(io.BytesIO(out_xlsx_bytes), engine="openpyxl"),
                    sheet_name="Rejected_Detail",
                    engine="openpyxl",
                )

                if sel_ins != "All":
                    df_full_detail = df_full_detail[df_full_detail["Insurance"].astype(str) == str(sel_ins)]

                if sel_code != "All":
                    df_full_detail = df_full_detail[df_full_detail["DenialCode"].astype(str) == str(sel_code)]

                # Write only filtered detail into a small workbook
                dl_buf = io.BytesIO()
                with pd.ExcelWriter(dl_buf, engine="openpyxl") as writer:
                    df_full_detail.to_excel(writer, sheet_name="Rejected_Detail_Filtered", index=False)

                st.download_button(
                    "Download Filtered Detail Excel",
                    data=dl_buf.getvalue(),
                    file_name=f"Rejected_Detail_{center}_{year}_{sel_ins}_{sel_code}_{stats['sha1']}.xlsx"
                        .replace(" ", "_")
                        .replace("/", "_")
                        .replace("\\", "_")
                        .replace(":", "_"),
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )

                st.success(f"Filtered rows: {len(df_full_detail)} ✅")


        with c1:
            sel_ins = st.selectbox("Insurance", ["All"] + ins_list, index=0)

        with c2:
            sel_code = st.selectbox("Denial Code", ["All"] + code_list, index=0)

        with c3:
            show_top = st.number_input("Rows to show", min_value=50, max_value=5000, value=500, step=50)

        filt = df_detail.copy()

        if sel_ins != "All":
            filt = filt[filt["Insurance"].astype(str) == str(sel_ins)]

        if sel_code != "All":
            filt = filt[filt["DenialCode"].astype(str) == str(sel_code)]

        st.caption(f"Showing {min(len(filt), int(show_top))} of {len(filt)} rejected rows after filters.")
        st.dataframe(filt.head(int(show_top)), use_container_width=True)


    # Optional: show detail table (can be heavy on big files)
    with st.expander("Preview Rejected Detail (may be large)", expanded=False):
        df_preview = pd.read_excel(io.BytesIO(out_xlsx_bytes), sheet_name="Rejected_Detail", engine="openpyxl")
        st.dataframe(df_preview, use_container_width=True)

run_rejection_app()
