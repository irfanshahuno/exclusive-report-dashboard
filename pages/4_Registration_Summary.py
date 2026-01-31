import io
import os
import uuid
import tempfile
import pandas as pd
import streamlit as st

# Optional S3
try:
    import boto3
except Exception:
    boto3 = None


st.set_page_config(page_title="Registration Summary", layout="wide")
st.title("Registration Summary (Registration + CashOut + Pending)")


# =========================================================
# Helpers
# =========================================================
def get_secret(key: str, default=None):
    # Works in Streamlit Cloud + local secrets.toml
    try:
        return st.secrets.get(key, default)
    except Exception:
        return default


def s3_is_configured():
    bucket = get_secret("S3_BUCKET_NAME", "")
    ak = get_secret("AWS_ACCESS_KEY_ID", "")
    sk = get_secret("AWS_SECRET_ACCESS_KEY", "")
    rg = get_secret("AWS_REGION", "")
    return bool(bucket and ak and sk and rg and boto3 is not None)


def make_s3_client():
    return boto3.client(
        "s3",
        aws_access_key_id=get_secret("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=get_secret("AWS_SECRET_ACCESS_KEY"),
        region_name=get_secret("AWS_REGION"),
    )


def upload_bytes_to_s3(s3, bucket: str, key: str, data: bytes):
    s3.upload_fileobj(io.BytesIO(data), bucket, key)


def normalize_cols(df: pd.DataFrame):
    df.columns = [str(c).strip() for c in df.columns]
    return df


def has_col(df: pd.DataFrame, col: str):
    return col in df.columns


def validate_registration_excel(file_bytes: bytes):
    """
    Registration file: must contain EMR No (your registration file uses 'EMR No').
    We'll accept 'EMR No' or 'EMRNo'.
    """
    df = pd.read_excel(io.BytesIO(file_bytes))
    df = normalize_cols(df)
    if not (has_col(df, "EMR No") or has_col(df, "EMRNo")):
        return False, f"Registration file must contain 'EMR No' or 'EMRNo'. Found: {list(df.columns)}"
    return True, ""


def validate_cashout_excel(file_bytes: bytes):
    """
    CashOut files: must contain EMRNo (you confirmed).
    """
    df = pd.read_excel(io.BytesIO(file_bytes))
    df = normalize_cols(df)
    if not has_col(df, "EMRNo"):
        return False, f"CashOut file must contain 'EMRNo'. Found: {list(df.columns)}"
    return True, ""


def count_patients_registration(file_bytes: bytes) -> int:
    df = pd.read_excel(io.BytesIO(file_bytes))
    df = normalize_cols(df)
    col = "EMR No" if has_col(df, "EMR No") else "EMRNo"
    return int(df[col].nunique())


def count_patients_cashout(file_bytes: bytes) -> int:
    df = pd.read_excel(io.BytesIO(file_bytes))
    df = normalize_cols(df)
    if df.empty:
        return 0
    return int(df["EMRNo"].nunique())


# =========================================================
# State (for “delete uploaded file”)
# =========================================================
if "reg_bytes" not in st.session_state:
    st.session_state.reg_bytes = None
if "cash_bytes" not in st.session_state:
    st.session_state.cash_bytes = None
if "pend_bytes" not in st.session_state:
    st.session_state.pend_bytes = None

if "reg_name" not in st.session_state:
    st.session_state.reg_name = ""
if "cash_name" not in st.session_state:
    st.session_state.cash_name = ""
if "pend_name" not in st.session_state:
    st.session_state.pend_name = ""

if "last_result" not in st.session_state:
    st.session_state.last_result = None


def reset_reg():
    st.session_state.reg_bytes = None
    st.session_state.reg_name = ""
    # also reset downstream (sequence)
    reset_cash()
    reset_pending()


def reset_cash():
    st.session_state.cash_bytes = None
    st.session_state.cash_name = ""
    reset_pending()


def reset_pending():
    st.session_state.pend_bytes = None
    st.session_state.pend_name = ""


# =========================================================
# S3 status (do NOT block UI)
# =========================================================
with st.expander("Storage Status (S3)", expanded=False):
    if s3_is_configured():
        st.success("S3 is configured ✅ (uploads will be saved)")
        st.write("Bucket:", get_secret("S3_BUCKET_NAME"))
        st.write("Prefix:", get_secret("S3_BASE_PREFIX", "excellent"))
        st.write("Region:", get_secret("AWS_REGION"))
    else:
        st.warning(
            "S3 is NOT configured. Uploaders will work and KPIs will display, "
            "but files will NOT be saved to S3.\n\n"
            "To enable S3, add these in Streamlit Secrets:\n"
            "S3_BUCKET_NAME, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION"
        )


# =========================================================
# Step-by-step upload UI
# =========================================================
st.subheader("Step 1 → Step 2 → Step 3 Upload")

# STEP 1
left1, right1 = st.columns([6, 2])
with left1:
    st.markdown("### 1) RegistrationList.xlsx")
    reg_upl = st.file_uploader(
        "Upload Registration file",
        type=["xlsx"],
        key="upl_reg",
        help="Must contain 'EMR No' (or EMRNo).",
        disabled=False,
    )
with right1:
    st.markdown("### ")
    st.button("🗑️ Delete Step 1", use_container_width=True, on_click=reset_reg)

if reg_upl is not None:
    reg_bytes = reg_upl.getvalue()
    ok, msg = validate_registration_excel(reg_bytes)
    if not ok:
        st.error(f"Step 1 error: {msg}")
        st.session_state.reg_bytes = None
        st.session_state.reg_name = ""
    else:
        st.session_state.reg_bytes = reg_bytes
        st.session_state.reg_name = reg_upl.name
        st.success(f"Step 1 uploaded ✅ ({reg_upl.name})")

st.divider()

# STEP 2 (only enabled if step 1 is valid)
step2_enabled = st.session_state.reg_bytes is not None

left2, right2 = st.columns([6, 2])
with left2:
    st.markdown("### 2) PatientCashOutList (.xls / .xlsx)")
    cash_upl = st.file_uploader(
        "Upload CashOut file",
        type=["xls", "xlsx"],
        key="upl_cash",
        help="Must contain 'EMRNo'.",
        disabled=not step2_enabled,
    )
with right2:
    st.markdown("### ")
    st.button("🗑️ Delete Step 2", use_container_width=True, on_click=reset_cash, disabled=not step2_enabled)

if not step2_enabled:
    st.info("Upload Step 1 first to enable Step 2.")

if cash_upl is not None:
    if not step2_enabled:
        st.error("Step 2 is locked. Upload Step 1 first.")
    else:
        cash_bytes = cash_upl.getvalue()
        ok, msg = validate_cashout_excel(cash_bytes)
        if not ok:
            st.error(f"Step 2 error: {msg}")
            st.session_state.cash_bytes = None
            st.session_state.cash_name = ""
        else:
            st.session_state.cash_bytes = cash_bytes
            st.session_state.cash_name = cash_upl.name
            st.success(f"Step 2 uploaded ✅ ({cash_upl.name})")

st.divider()

# STEP 3 (only enabled if step 1 & 2 valid)
step3_enabled = st.session_state.reg_bytes is not None and st.session_state.cash_bytes is not None

left3, right3 = st.columns([6, 2])
with left3:
    st.markdown("### 3) Pending file (PatientCashOutList (1).xls)")
    pend_upl = st.file_uploader(
        "Upload Pending file",
        type=["xls", "xlsx"],
        key="upl_pend",
        help="Must contain 'EMRNo'. Can be empty (0 pending).",
        disabled=not step3_enabled,
    )
with right3:
    st.markdown("### ")
    st.button("🗑️ Delete Step 3", use_container_width=True, on_click=reset_pending, disabled=not step3_enabled)

if not step3_enabled:
    st.info("Upload Step 1 and Step 2 first to enable Step 3.")

if pend_upl is not None:
    if not step3_enabled:
        st.error("Step 3 is locked. Upload Step 1 and Step 2 first.")
    else:
        pend_bytes = pend_upl.getvalue()
        ok, msg = validate_cashout_excel(pend_bytes)
        if not ok:
            st.error(f"Step 3 error: {msg}")
            st.session_state.pend_bytes = None
            st.session_state.pend_name = ""
        else:
            st.session_state.pend_bytes = pend_bytes
            st.session_state.pend_name = pend_upl.name
            st.success(f"Step 3 uploaded ✅ ({pend_upl.name})")

st.divider()

# =========================================================
# Process button (enabled only if all 3 are uploaded valid)
# =========================================================
all_ready = (
    st.session_state.reg_bytes is not None
    and st.session_state.cash_bytes is not None
    and st.session_state.pend_bytes is not None
)

colp1, colp2 = st.columns([2, 6])
with colp1:
    process = st.button("✅ Process", type="primary", use_container_width=True, disabled=not all_ready)
with colp2:
    if not all_ready:
        st.warning("Complete Step 1 → Step 2 → Step 3 to enable Process.")
    else:
        st.success("All files ready. Click Process.")

# =========================================================
# When Process is clicked: compute + upload to S3 (optional)
# =========================================================
if process:
    run_id = str(uuid.uuid4())[:8]

    reg_patients = count_patients_registration(st.session_state.reg_bytes)
    cash_patients = count_patients_cashout(st.session_state.cash_bytes)
    pending_patients = count_patients_cashout(st.session_state.pend_bytes)

    # Save to S3 (optional)
    s3_keys = None
    if s3_is_configured():
        s3 = make_s3_client()
        bucket = get_secret("S3_BUCKET_NAME")
        prefix = get_secret("S3_BASE_PREFIX", "excellent")

        reg_key = f"{prefix}/uploads/registration/{run_id}_{st.session_state.reg_name}"
        cash_key = f"{prefix}/uploads/cashout/{run_id}_{st.session_state.cash_name}"
        pend_key = f"{prefix}/uploads/pending/{run_id}_{st.session_state.pend_name}"

        upload_bytes_to_s3(s3, bucket, reg_key, st.session_state.reg_bytes)
        upload_bytes_to_s3(s3, bucket, cash_key, st.session_state.cash_bytes)
        upload_bytes_to_s3(s3, bucket, pend_key, st.session_state.pend_bytes)

        s3_keys = [reg_key, cash_key, pend_key]

    # Store result in session
    st.session_state.last_result = {
        "reg_patients": reg_patients,
        "cash_patients": cash_patients,
        "pending_patients": pending_patients,
        "s3_keys": s3_keys,
    }

    st.success("Processed successfully ✅")


# =========================================================
# Display summary (KPIs + optional details)
# =========================================================
if st.session_state.last_result:
    res = st.session_state.last_result

    st.subheader("Summary")

    k1, k2, k3 = st.columns(3)
    k1.metric("Registered Patients", res["reg_patients"])
    k2.metric("CashOut Patients", res["cash_patients"])
    k3.metric("Pending Patients", res["pending_patients"])

    if res.get("s3_keys"):
        st.caption("Saved to S3:")
        st.code("\n".join(res["s3_keys"]))

    # Optional: show small previews
    with st.expander("Preview (first 10 rows)", expanded=False):
        reg_df = pd.read_excel(io.BytesIO(st.session_state.reg_bytes))
        cash_df = pd.read_excel(io.BytesIO(st.session_state.cash_bytes))
        pend_df = pd.read_excel(io.BytesIO(st.session_state.pend_bytes))

        st.write("Registration preview")
        st.dataframe(reg_df.head(10), use_container_width=True)

        st.write("CashOut preview")
        st.dataframe(cash_df.head(10), use_container_width=True)

        st.write("Pending preview")
        st.dataframe(pend_df.head(10), use_container_width=True)

    # One-click reset
    if st.button("🔄 Reset All", use_container_width=True):
        reset_reg()
        st.session_state.last_result = None
        st.rerun()
