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
# PAGE CONFIG (wide + clean)
# =========================================
st.set_page_config(page_title="Rejection Analysis", layout="wide")

# ✅ Light-Red + Smaller Buttons (CSS only)
st.markdown(
    """
    <style>
      .block-container {max-width: 100% !important; padding-top: 1.0rem; padding-left: 1.2rem; padding-right: 1.2rem;}

      .card{
        background:#ffffff;
        border:1px solid #fde2e2;
        border-left:3px solid #fb7185;
        border-radius:14px;
        padding:12px 14px 10px 14px;
        box-shadow:0 2px 14px rgba(0,0,0,0.04);
      }
      .card-title{
        color:#b42318;
        font-size:13px;
        font-weight:800;
        letter-spacing:0.2px;
        margin-bottom:6px;
      }
      .card-value{
        color:#0f172a;
        font-size:24px;
        font-weight:900;
        line-height:1.15;
      }
      .card-sub{
        color:#64748b;
        font-size:12px;
        margin-top:6px;
      }

      h3{
        font-size:26px!important;
        font-weight:800!important;
        margin-top:22px!important;
        margin-bottom:10px!important;
        color:#0f172a;
      }

      div[data-testid="stDataFrame"] {border: 1px solid #edf2fa; border-radius: 14px; overflow:hidden;}

      /* Buttons */
      div.stButton > button,
      div.stDownloadButton > button{
        background: #f87171 !important;
        color: #ffffff !important;
        border: 1px solid #fecaca !important;
        border-radius: 12px !important;

        padding: 0.35rem 0.80rem !important;
        font-size: 0.88rem !important;
        font-weight: 700 !important;
        min-height: 2.25rem !important;

        box-shadow: 0 6px 18px rgba(239,68,68,0.18) !important;
      }
      div.stButton > button:hover,
      div.stDownloadButton > button:hover{
        background: #ef4444 !important;
        border-color: #fca5a5 !important;
        transform: translateY(-1px);
      }
      div.stButton > button:active,
      div.stDownloadButton > button:active{
        transform: translateY(0px);
      }
    </style>
    """,
    unsafe_allow_html=True
)

# =========================================
# CONFIG
# =========================================
S3_BUCKET = "emc-rcm-storage-2026"
SOURCE_FILENAME = "source.xlsx"
DEFAULT_YEAR_OPTIONS = ["2024", "2025", "2026"]

# =========================================
# CACHE KEY (per center+year)
# =========================================
def _rej_cache_key(center: str, year: str) -> str:
    return f"rej::{center}::{year}"

# =========================================
# CENTER NORMALIZATION
# =========================================
CENTER_ALIASES = {
    "excellent medical center": "excellent",
    "excellent pharmacy": "pharmacy",
    "easyhealth clinic": "easyhealth",
    "easy health medical clinic": "easyhealth",
    "easy health clinic": "easyhealth",
    "easyhealth": "easyhealth",
    "excellent": "excellent",
    "pharmacy": "pharmacy",
}

def normalize_center_for_s3(center_value: str) -> str:
    c = str(center_value).strip().lower()
    c = " ".join(c.split())
    return CENTER_ALIASES.get(c, c)

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
# SAFE CHUNK READER (prevents FULL crash)
# =========================================
def read_excel_sheet_in_chunks(xlsx_bytes: bytes, sheet_name: str, chunk_size: int = 50000):
    """
    Stream big excel sheet safely using openpyxl (no pandas full load).
    Yields DataFrames chunk by chunk.
    """
    wb = load_workbook(io.BytesIO(xlsx_bytes), read_only=True, data_only=True)
    ws = wb[sheet_name]

    rows = ws.iter_rows(values_only=True)
    headers = next(rows)
    headers = [str(h).strip() if h is not None else "" for h in headers]

    batch = []
    for r in rows:
        batch.append(r)
        if len(batch) >= chunk_size:
            yield pd.DataFrame(batch, columns=headers)
            batch = []

    if batch:
        yield pd.DataFrame(batch, columns=headers)

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
    df["Insurance"] = df["Insurance"].astype(str).fillna("").str.strip()
    df.loc[df["Insurance"].eq(""), "Insurance"] = "Not Available"
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
          .sort_values("RejectedAmount", ascending=False)
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

# -------------------- excel styling --------------------
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

def build_rejection_workbook_bytes(input_bytes: bytes, input_name: str = "source.xlsx") -> tuple[bytes, dict]:
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
# UI HELPERS
# =========================================
def _card(title: str, value: str, sub: str = ""):
    st.markdown(
        f"""
        <div class="card">
          <div class="card-title">{title}</div>
          <div class="card-value">{value}</div>
          <div class="card-sub">{sub}</div>
        </div>
        """,
        unsafe_allow_html=True
    )

def _fmt_aed(x):
    try:
        return f"AED {float(x):,.2f}"
    except Exception:
        return f"AED {x}"

def _detect_amount_col(df: pd.DataFrame) -> str | None:
    for c in ["RejectedAmount", "ActivityIns"]:
        if c in df.columns:
            return c
    return None

# =========================================
# APP
# =========================================
def run_rejection_app():
    st.markdown("## Rejection Analysis")
    st.caption("Rule: Paid==0 AND ActivityStatus=='rejected' AND DenialCode not empty")

    if "rej_result" not in st.session_state:
        st.session_state.rej_result = None
    if "rej_cache" not in st.session_state:
        st.session_state.rej_cache = {}

    detected_center = st.session_state.get("selected_center")
    detected_year = st.session_state.get("selected_year")

    # ---- Sidebar controls (TRUE LEFT) ----
    with st.sidebar:
        st.subheader("Controls")

        if detected_center is None or detected_year is None:
            st.warning("Center/Year not detected. Select manually.")
            center = st.selectbox(
                "Center",
                ["Excellent Medical Center", "Excellent Pharmacy", "Easyhealth Clinic"],
                key="rej_center_manual"
            )
            year = st.selectbox("Year", DEFAULT_YEAR_OPTIONS, key="rej_year_manual")
        else:
            center = str(detected_center).lower()
            year = str(detected_year)

            st.success("Detected from dashboard ✅")
            st.selectbox(
                "Center",
                ["excellent", "pharmacy", "easyhealth"],
                index=["excellent", "pharmacy", "easyhealth"].index(center),
                disabled=True
            )
            st.selectbox(
                "Year",
                DEFAULT_YEAR_OPTIONS,
                index=DEFAULT_YEAR_OPTIONS.index(year),
                disabled=True
            )

        center_raw = center
        center = normalize_center_for_s3(center_raw)
        year = str(year)

        s3_key = f"streamlit/{center}/{year}/{SOURCE_FILENAME}"
        cache_key = _rej_cache_key(center, year)

        # ✅ Auto-load cached result for this center/year if available
        if cache_key in st.session_state.rej_cache and st.session_state.rej_result is None:
            st.session_state.rej_result = st.session_state.rej_cache[cache_key]

        st.write("**Source**")
        st.code(f"s3://{S3_BUCKET}/{s3_key}", language="text")

        cA, cB = st.columns(2)
        with cA:
            generate = st.button("Generate", type="primary", use_container_width=True)
        with cB:
            clear = st.button("Clear", use_container_width=True)

        if clear:
            if cache_key in st.session_state.rej_cache:
                del st.session_state.rej_cache[cache_key]
            st.session_state.rej_result = None
            st.rerun()

        # ---- Generate only on click ----
        if generate:
            if not s3_exists(S3_BUCKET, s3_key):
                st.error("Source file not found in S3. Upload from dashboard first.")
                st.stop()

            with st.spinner("Building rejection analysis..."):
                input_bytes = load_file_from_s3(S3_BUCKET, s3_key)
                out_xlsx_bytes, stats = build_rejection_workbook_bytes(input_bytes, SOURCE_FILENAME)

                xls = pd.ExcelFile(io.BytesIO(out_xlsx_bytes), engine="openpyxl")
                df_by_ins = pd.read_excel(xls, sheet_name="Rejected_By_Insurance")
                df_by_code = pd.read_excel(xls, sheet_name="Rejected_By_DenialCode")
                df_ins_x_code = pd.read_excel(xls, sheet_name="Rejected_Ins_x_DenialCode")
                df_aging = pd.read_excel(xls, sheet_name="Rejected_Aging_Summary")

                # light preview for filters
                PREVIEW_ROWS = 2000
                detail_header = pd.read_excel(xls, sheet_name="Rejected_Detail", nrows=0).columns.tolist()
                wanted_cols = ["Insurance", "DenialCode", "ActivityStatus", "ActivityIns", "Paid", "AgingBucket", "DaysDiff", "RefDate", "RejectedAmount"]
                usecols = [c for c in wanted_cols if c in detail_header]
                df_preview = pd.read_excel(xls, sheet_name="Rejected_Detail", usecols=usecols, nrows=PREVIEW_ROWS)

                result_obj = {
                    "center": center,
                    "year": year,
                    "s3_key": s3_key,
                    "out_bytes": out_xlsx_bytes,
                    "stats": stats,
                    "df_by_ins": df_by_ins,
                    "df_by_code": df_by_code,
                    "df_ins_x_code": df_ins_x_code,
                    "df_aging": df_aging,
                    "df_preview": df_preview,
                    "preview_rows": PREVIEW_ROWS,
                }

                st.session_state.rej_result = result_obj
                st.session_state.rej_cache[cache_key] = result_obj

            st.success("Done ✅")

    if st.session_state.rej_result is None:
        st.info("Generate to view KPIs + tables.")
        return

    R = st.session_state.rej_result
    out_xlsx_bytes = R["out_bytes"]
    stats = R["stats"]

    df_by_ins = R["df_by_ins"]
    df_by_code = R["df_by_code"]
    df_ins_x_code = R["df_ins_x_code"]
    df_aging = R["df_aging"]
    df_preview = R["df_preview"]
    PREVIEW_ROWS = R["preview_rows"]

    st.download_button(
        "Download Rejection Analysis Excel",
        data=out_xlsx_bytes,
        file_name=f"Rejection_Analysis_{R['center']}_{R['year']}_{stats['sha1']}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    df_by_ins_nogt = df_by_ins[df_by_ins["Insurance"] != "Grand Total"].copy()
    total_amount = float(pd.to_numeric(df_by_ins_nogt["RejectedAmount"], errors="coerce").fillna(0).sum())
    total_claims = int(pd.to_numeric(df_by_ins_nogt["RejectedCount"], errors="coerce").fillna(0).sum())

    c1, c2, c3 = st.columns(3)
    with c1:
        _card("Rejected Rows", f"{int(stats['rejected_rows']):,}", "Paid=0 + Status=rejected + DenialCode not empty")
    with c2:
        _card("Total Rejected Amount", _fmt_aed(total_amount), "All insurers (excluding Grand Total row)")
    with c3:
        _card("Total Rejected Claims", f"{total_claims:,}", "Count of rejected activities")

    st.divider()

    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "By Insurance",
        "By Denial Code",
        "Insurance × Denial",
        "Aging Summary",
        "Rejected Detail (Filter + Download)"
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

        ins_list = sorted([x for x in df_preview["Insurance"].dropna().unique().tolist() if str(x).strip() != ""]) if "Insurance" in df_preview.columns else []
        code_list = sorted([x for x in df_preview["DenialCode"].dropna().unique().tolist() if str(x).strip() != ""]) if "DenialCode" in df_preview.columns else []

        c1, c2, c3 = st.columns([1, 1, 1])
        with c1:
            sel_ins = st.selectbox("Insurance", ["All"] + ins_list, key="rej_filter_ins")
        with c2:
            sel_code = st.selectbox("Denial Code", ["All"] + code_list, key="rej_filter_code")
        with c3:
            show_top = st.number_input("Preview rows", min_value=50, max_value=2000, value=500, step=50, key="rej_preview_rows")

        filt = df_preview.copy()
        if sel_ins != "All" and "Insurance" in filt.columns:
            filt = filt[filt["Insurance"].astype(str) == str(sel_ins)]
        if sel_code != "All" and "DenialCode" in filt.columns:
            filt = filt[filt["DenialCode"].astype(str) == str(sel_code)]

        amt_col_prev = _detect_amount_col(filt)
        total_count_preview = int(len(filt))
        total_amount_preview = float(pd.to_numeric(filt[amt_col_prev], errors="coerce").fillna(0).sum()) if amt_col_prev else 0.0

        m1, m2 = st.columns(2)
        with m1:
            st.metric("Selected (Preview) Count", f"{total_count_preview:,}")
        with m2:
            st.metric("Selected (Preview) Amount", _fmt_aed(total_amount_preview))

        st.caption(f"Preview (from first {PREVIEW_ROWS} rows only). Use Download for FULL filtered output.")
        st.dataframe(filt.head(int(show_top)), use_container_width=True)

        st.divider()
        st.write("### Download FULL filtered rejected detail (No crash)")
        if st.button("Build & Download Filtered Detail Excel", type="primary", key="rej_dl_btn"):
            with st.spinner("Reading FULL detail safely (chunked) and preparing filtered file..."):

                filtered_parts = []
                total_count_full = 0
                total_amount_full = 0.0
                amt_col_full = None

                for chunk in read_excel_sheet_in_chunks(out_xlsx_bytes, "Rejected_Detail", chunk_size=40000):
                    if sel_ins != "All" and "Insurance" in chunk.columns:
                        chunk = chunk[chunk["Insurance"].astype(str) == str(sel_ins)]
                    if sel_code != "All" and "DenialCode" in chunk.columns:
                        chunk = chunk[chunk["DenialCode"].astype(str) == str(sel_code)]

                    if len(chunk) == 0:
                        continue

                    if amt_col_full is None:
                        amt_col_full = _detect_amount_col(chunk)

                    total_count_full += int(len(chunk))
                    if amt_col_full and amt_col_full in chunk.columns:
                        total_amount_full += float(pd.to_numeric(chunk[amt_col_full], errors="coerce").fillna(0).sum())

                    filtered_parts.append(chunk)

                if total_count_full == 0:
                    st.warning("No rows found for this filter (FULL file).")
                    st.stop()

                df_full_filtered = pd.concat(filtered_parts, ignore_index=True)

                buf = io.BytesIO()
                with pd.ExcelWriter(buf, engine="openpyxl") as writer:
                    df_full_filtered.to_excel(writer, sheet_name="Rejected_Detail_Filtered", index=False)

                safe_name = f"Rejected_Detail_{R['center']}_{R['year']}_{sel_ins}_{sel_code}_{stats['sha1']}.xlsx"
                safe_name = (safe_name.replace(" ", "_")
                                     .replace("/", "_")
                                     .replace("\\", "_")
                                     .replace(":", "_"))

                st.download_button(
                    "Download Filtered Detail Excel",
                    data=buf.getvalue(),
                    file_name=safe_name,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )

                st.success(f"FULL Filtered ✅ Count: {total_count_full:,} | Amount: {_fmt_aed(total_amount_full)}")

run_rejection_app()
