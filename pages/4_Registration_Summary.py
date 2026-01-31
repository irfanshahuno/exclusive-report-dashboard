import os, io, uuid, tempfile
import pandas as pd
import streamlit as st
import boto3

st.set_page_config(page_title="Registration Summary", layout="wide")
st.title("Registration Summary (Registration + CashOut + Pending)")

# -----------------------
# S3 settings from secrets
# -----------------------
S3_BUCKET = st.secrets.get("S3_BUCKET_NAME", "")
S3_PREFIX = st.secrets.get("S3_BASE_PREFIX", "excellent")
AWS_REGION = st.secrets.get("AWS_REGION", "me-central-1")

if not S3_BUCKET:
    st.error("Missing S3_BUCKET_NAME in secrets. Add it in .streamlit/secrets.toml")
    st.stop()

def s3_client():
    return boto3.client(
        "s3",
        region_name=AWS_REGION,
        aws_access_key_id=st.secrets.get("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=st.secrets.get("AWS_SECRET_ACCESS_KEY"),
    )

def upload_fileobj_to_s3(s3, file_obj, key: str):
    file_obj.seek(0)
    s3.upload_fileobj(file_obj, S3_BUCKET, key)

def read_excel_patient_count(file_bytes: bytes, col_name: str = "EMRNo") -> int:
    df = pd.read_excel(io.BytesIO(file_bytes))
    if col_name not in df.columns:
        # try flexible match
        cols = {c.strip().lower(): c for c in df.columns}
        if col_name.strip().lower() in cols:
            col_name = cols[col_name.strip().lower()]
        else:
            raise ValueError(f"Column '{col_name}' not found. Available: {list(df.columns)}")
    # You said no duplicates, still safe to use nunique()
    return int(df[col_name].nunique())

# -----------------------
# Upload UI
# -----------------------
c1, c2, c3 = st.columns(3)
with c1:
    reg_file = st.file_uploader("1) RegistrationList.xlsx", type=["xlsx"])
with c2:
    cash_file = st.file_uploader("2) PatientCashOutList (.xls/.xlsx)", type=["xls", "xlsx"])
with c3:
    pending_file = st.file_uploader("3) Pending CashOut (.xls/.xlsx)", type=["xls", "xlsx"])

run_id = str(uuid.uuid4())[:8]
st.caption(f"Run ID: {run_id}")

# -----------------------
# Action
# -----------------------
if st.button("Upload to S3 & Show KPIs", type="primary", disabled=not (reg_file and cash_file and pending_file)):
    s3 = s3_client()

    # Read bytes
    reg_bytes = reg_file.getvalue()
    cash_bytes = cash_file.getvalue()
    pending_bytes = pending_file.getvalue()

    # Upload originals to S3
    reg_key = f"{S3_PREFIX}/uploads/registration/{run_id}_{reg_file.name}"
    cash_key = f"{S3_PREFIX}/uploads/cashout/{run_id}_{cash_file.name}"
    pend_key = f"{S3_PREFIX}/uploads/pending/{run_id}_{pending_file.name}"

    upload_fileobj_to_s3(s3, io.BytesIO(reg_bytes), reg_key)
    upload_fileobj_to_s3(s3, io.BytesIO(cash_bytes), cash_key)
    upload_fileobj_to_s3(s3, io.BytesIO(pending_bytes), pend_key)

    # Compute KPIs:
    # - Registration patient count: from RegistrationList.xlsx (usually EMR No column)
    # - CashOut patient count: from PatientCashOutList (EMRNo)
    # - Pending patient count: from Pending file (EMRNo)
    try:
        reg_df = pd.read_excel(io.BytesIO(reg_bytes))
        # Registration column in your script is "EMR No" (with space). We'll handle both.
        reg_col = "EMR No" if "EMR No" in reg_df.columns else ("EMRNo" if "EMRNo" in reg_df.columns else None)
        if not reg_col:
            st.error(f"Registration file must contain 'EMR No' or 'EMRNo'. Found: {list(reg_df.columns)}")
            st.stop()
        reg_patients = int(reg_df[reg_col].nunique())

        cash_patients = read_excel_patient_count(cash_bytes, "EMRNo")
        pending_patients = read_excel_patient_count(pending_bytes, "EMRNo")

    except Exception as e:
        st.error(f"Failed to read files / count patients: {e}")
        st.stop()

    # Show KPI cards
    k1, k2, k3 = st.columns(3)
    k1.metric("Registered Patients", reg_patients)
    k2.metric("CashOut Patients", cash_patients)
    k3.metric("Pending Patients", pending_patients)

    st.success("Uploaded to S3 and KPIs calculated ✅")

    st.write("S3 saved paths:")
    st.code("\n".join([reg_key, cash_key, pend_key]))
