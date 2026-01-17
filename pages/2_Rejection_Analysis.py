# pages/2_Rejection_Analysis.py

import boto3
from botocore.exceptions import ClientError
import io
import hashlib
from datetime import datetime

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
# APP
# =========================================
def run_rejection_app():
    st.subheader("Rejection Analysis")
    st.caption("Rule: Paid==0 AND ActivityStatus=='rejected' AND DenialCode not empty")

    # -------------------------------------
    # Auto-detect from dashboard
    # -------------------------------------
    center = st.session_state.get("selected_center")
    year = st.session_state.get("selected_year")

    if center is None or year is None:
        st.warning("Center/Year not detected from dashboard. Please select manually.")

        center = st.selectbox(
            "Center",
            ["excellent", "pharmacy", "easyhealth"],
        )
        year = st.selectbox(
            "Year",
            DEFAULT_YEAR_OPTIONS,
        )

    center = center.lower()
    year = str(year)

    s3_key = f"streamlit/{center}/{year}/{SOURCE_FILENAME}"

    st.write(f"**Center:** {center}")
    st.write(f"**Year:** {year}")
    st.write(f"**Source:** s3://{S3_BUCKET}/{s3_key}")

    if not s3_exists(S3_BUCKET, s3_key):
        st.error("Source file not found in S3. Upload from dashboard first.")
        st.stop()

    input_bytes = load_file_from_s3(S3_BUCKET, s3_key)

    def sha1_short(b):
        return hashlib.sha1(b).hexdigest()[:12]

    run = st.button("Generate Rejection Analysis", type="primary")

    if not run:
        return

    with st.spinner("Building rejection analysis..."):
        df = pd.read_excel(io.BytesIO(input_bytes))
        df.columns = df.columns.str.strip()

        for col in [
            "ActivityIns",
            "actRemitInsShare", "actResub1RemitInsShare",
            "actResub2RemitInsShare", "actResub3RemitInsShare",
            "TKBKAmountAct"
        ]:
            if col not in df.columns:
                df[col] = 0
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

        df["Paid"] = df[
            [
                "actRemitInsShare",
                "actResub1RemitInsShare",
                "actResub2RemitInsShare",
                "actResub3RemitInsShare",
                "TKBKAmountAct",
            ]
        ].sum(axis=1)

        if "DenialCode" not in df.columns:
            df["DenialCode"] = ""

        status = df["ActivityStatus"].astype(str).str.lower()
        rej = df[(df["Paid"] == 0) & (status == "rejected") & (df["DenialCode"] != "")].copy()

        rej["RejectedAmount"] = rej["ActivityIns"]
        rej["RejectedCount"] = 1

        out_buf = io.BytesIO()
        with pd.ExcelWriter(out_buf, engine="openpyxl") as writer:
            rej.to_excel(writer, sheet_name="Rejected_Detail", index=False)

        st.success("Done ✅")

        st.download_button(
            "Download Rejection Analysis Excel",
            data=out_buf.getvalue(),
            file_name=f"Rejection_Analysis_{center}_{year}_{sha1_short(input_bytes)}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

        st.metric("Rejected Rows", len(rej))
        st.dataframe(rej, use_container_width=True)


run_rejection_app()
