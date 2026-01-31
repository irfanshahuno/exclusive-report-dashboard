import io
import uuid
import pandas as pd
import streamlit as st

# Optional S3 (do not block UI if not installed)
try:
    import boto3
except Exception:
    boto3 = None


# ---------------- Page ----------------
st.set_page_config(page_title="Registration Summary", layout="wide")
st.title("Registration Summary (Registration + CashOut + Pending)")


# =========================================================
# Helpers
# =========================================================
def get_secret(key: str, default=None):
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


def norm_cols(df: pd.DataFrame):
    df.columns = [str(c).strip() for c in df.columns]
    return df


def read_excel_find_header(file_bytes: bytes, required_col="EMRNo", max_header_rows=10):
    """
    Many .xls exports have a title row above actual headers.
    Try header rows 0..max_header_rows until required_col exists.
    """
    last_cols = None
    for h in range(max_header_rows + 1):
        df = pd.read_excel(io.BytesIO(file_bytes), header=h)
        df = norm_cols(df)
        last_cols = list(df.columns)
        if required_col in df.columns:
            return df, h
    return None, last_cols


def pick_col(df: pd.DataFrame, candidates):
    """
    Return first matching column from candidates (case-insensitive + trimmed)
    """
    cols = {str(c).strip().lower(): c for c in df.columns}
    for cand in candidates:
        key = str(cand).strip().lower()
        if key in cols:
            return cols[key]
    return None


def safe_value_counts(df: pd.DataFrame, col: str, drop_blank=False):
    if col is None or col not in df.columns:
        return pd.DataFrame(columns=["Value", "Count"])
    s = df[col].astype(str).fillna("")
    if drop_blank:
        s = s[s.str.strip() != ""]
    out = s.value_counts(dropna=False).reset_index()
    out.columns = ["Value", "Count"]
    return out


def style_block_title(text: str):
    st.markdown(
        f"""
        <div style="
            background:#f6e9bf;
            padding:10px 12px;
            border-radius:10px;
            font-weight:700;
            margin-bottom:6px;">
            {text}
        </div>
        """,
        unsafe_allow_html=True,
    )


def validate_registration_excel(file_bytes: bytes):
    df = pd.read_excel(io.BytesIO(file_bytes))
    df = norm_cols(df)
    emr_col = pick_col(df, ["EMR No", "EMRNo"])
    visit_col = pick_col(df, ["Visit No", "VisitNo", "Visit Number", "VisitNumber"])
    if not emr_col:
        return False, f"Registration file must contain 'EMR No' or 'EMRNo'. Found: {list(df.columns)}"
    if not visit_col:
        # visit no not mandatory, but your top KPI uses it; warn only
        return True, ""
    return True, ""


def validate_cashout_excel(file_bytes: bytes):
    df, last_cols = read_excel_find_header(file_bytes, required_col="EMRNo", max_header_rows=10)
    if df is None:
        return False, f"CashOut file must contain 'EMRNo'. Header row not found. Columns seen: {last_cols}"
    return True, ""


def count_cashout_patients(file_bytes: bytes) -> int:
    df, _ = read_excel_find_header(file_bytes, required_col="EMRNo", max_header_rows=10)
    if df is None or df.empty:
        return 0
    return int(df["EMRNo"].nunique())


# =========================================================
# State
# =========================================================
for k in ["reg_bytes", "cash_bytes", "pend_bytes", "reg_name", "cash_name", "pend_name", "result"]:
    if k not in st.session_state:
        st.session_state[k] = None if k.endswith("_bytes") or k == "result" else ""


def reset_all():
    st.session_state.reg_bytes = None
    st.session_state.cash_bytes = None
    st.session_state.pend_bytes = None
    st.session_state.reg_name = ""
    st.session_state.cash_name = ""
    st.session_state.pend_name = ""
    st.session_state.result = None


def reset_reg():
    st.session_state.reg_bytes = None
    st.session_state.reg_name = ""
    st.session_state.cash_bytes = None
    st.session_state.cash_name = ""
    st.session_state.pend_bytes = None
    st.session_state.pend_name = ""
    st.session_state.result = None


def reset_cash():
    st.session_state.cash_bytes = None
    st.session_state.cash_name = ""
    st.session_state.pend_bytes = None
    st.session_state.pend_name = ""
    st.session_state.result = None


def reset_pending():
    st.session_state.pend_bytes = None
    st.session_state.pend_name = ""
    st.session_state.result = None


# =========================================================
# S3 status (do not block UI)
# =========================================================
with st.expander("Storage Status (S3)", expanded=False):
    if s3_is_configured():
        st.success("S3 is configured ✅ (uploads will be saved)")
        st.write("Bucket:", get_secret("S3_BUCKET_NAME"))
        st.write("Prefix:", get_secret("S3_BASE_PREFIX", "excellent"))
        st.write("Region:", get_secret("AWS_REGION"))
    else:
        st.warning(
            "S3 is NOT configured. Uploaders will work and summary will display, "
            "but files will NOT be saved to S3."
        )

st.subheader("Step 1 → Step 2 → Step 3 Upload")


# =========================================================
# Step 1
# =========================================================
c1, c2 = st.columns([6, 2])
with c1:
    st.markdown("### 1) RegistrationList.xlsx")
    reg_upl = st.file_uploader("Upload Registration file", type=["xlsx"], key="upl_reg")
with c2:
    st.markdown("### ")
    st.button("🗑️ Delete Step 1", use_container_width=True, on_click=reset_reg)

if reg_upl is not None:
    b = reg_upl.getvalue()
    ok, msg = validate_registration_excel(b)
    if not ok:
        st.error(f"Step 1 error: {msg}")
        st.session_state.reg_bytes = None
        st.session_state.reg_name = ""
    else:
        st.session_state.reg_bytes = b
        st.session_state.reg_name = reg_upl.name
        st.success(f"Step 1 uploaded ✅ ({reg_upl.name})")

st.divider()


# =========================================================
# Step 2
# =========================================================
step2_enabled = st.session_state.reg_bytes is not None

c1, c2 = st.columns([6, 2])
with c1:
    st.markdown("### 2) PatientCashOutList (.xls / .xlsx)")
    cash_upl = st.file_uploader(
        "Upload CashOut file", type=["xls", "xlsx"], key="upl_cash", disabled=not step2_enabled
    )
with c2:
    st.markdown("### ")
    st.button("🗑️ Delete Step 2", use_container_width=True, on_click=reset_cash, disabled=not step2_enabled)

if not step2_enabled:
    st.info("Upload Step 1 first to enable Step 2.")

if cash_upl is not None:
    if not step2_enabled:
        st.error("Step 2 is locked. Upload Step 1 first.")
    else:
        b = cash_upl.getvalue()
        ok, msg = validate_cashout_excel(b)
        if not ok:
            st.error(f"Step 2 error: {msg}")
            st.session_state.cash_bytes = None
            st.session_state.cash_name = ""
        else:
            st.session_state.cash_bytes = b
            st.session_state.cash_name = cash_upl.name
            st.success(f"Step 2 uploaded ✅ ({cash_upl.name})")

st.divider()


# =========================================================
# Step 3
# =========================================================
step3_enabled = st.session_state.reg_bytes is not None and st.session_state.cash_bytes is not None

c1, c2 = st.columns([6, 2])
with c1:
    st.markdown("### 3) Pending file (PatientCashOutList (1).xls)")
    pend_upl = st.file_uploader(
        "Upload Pending file", type=["xls", "xlsx"], key="upl_pend", disabled=not step3_enabled
    )
with c2:
    st.markdown("### ")
    st.button("🗑️ Delete Step 3", use_container_width=True, on_click=reset_pending, disabled=not step3_enabled)

if not step3_enabled:
    st.info("Upload Step 1 and Step 2 first to enable Step 3.")

if pend_upl is not None:
    if not step3_enabled:
        st.error("Step 3 is locked. Upload Step 1 and Step 2 first.")
    else:
        b = pend_upl.getvalue()
        ok, msg = validate_cashout_excel(b)
        if not ok:
            st.error(f"Step 3 error: {msg}")
            st.session_state.pend_bytes = None
            st.session_state.pend_name = ""
        else:
            st.session_state.pend_bytes = b
            st.session_state.pend_name = pend_upl.name
            st.success(f"Step 3 uploaded ✅ ({pend_upl.name})")

st.divider()


# =========================================================
# Process
# =========================================================
all_ready = (
    st.session_state.reg_bytes is not None
    and st.session_state.cash_bytes is not None
    and st.session_state.pend_bytes is not None
)

p1, p2 = st.columns([2, 6])
with p1:
    process = st.button("✅ Process", type="primary", use_container_width=True, disabled=not all_ready)
with p2:
    if not all_ready:
        st.warning("Complete Step 1 → Step 2 → Step 3 to enable Process.")
    else:
        st.success("All files ready. Click Process.")

if process:
    run_id = str(uuid.uuid4())[:8]

    # --- read registration
    reg_df = pd.read_excel(io.BytesIO(st.session_state.reg_bytes))
    reg_df = norm_cols(reg_df)

    # Column mapping (auto)
    col_emr = pick_col(reg_df, ["EMR No", "EMRNo"])
    col_visitno = pick_col(reg_df, ["Visit No", "VisitNo", "Visit Number", "VisitNumber"])
    col_doctor = pick_col(reg_df, ["Doctor", "Doctor Name", "Physician", "Provider"])
    col_ins = pick_col(reg_df, ["Insurance", "Payer", "TPA", "Insurance Company"])
    col_billtype = pick_col(reg_df, ["Bill Type", "BillType"])
    col_visittype = pick_col(reg_df, ["Visit Type", "VisitType", "Purpose"])
    col_status = pick_col(reg_df, ["Status", "Visit Status"])
    col_reguser = pick_col(reg_df, ["Reg:User", "Reg User", "Registered By", "Registration User"])
    col_regdate = pick_col(reg_df, ["Reg Date", "Registration Date", "Visit Date", "Date"])

    # KPIs
    total_visits = int(len(reg_df))
    unique_emr = int(reg_df[col_emr].nunique()) if col_emr else 0
    unique_visitno = int(reg_df[col_visitno].nunique()) if col_visitno else total_visits

    # CashOut / Pending
    cash_patients = count_cashout_patients(st.session_state.cash_bytes)
    pending_patients = count_cashout_patients(st.session_state.pend_bytes)

    # Blocks
    doctor_tbl = safe_value_counts(reg_df, col_doctor)
    ins_tbl = safe_value_counts(reg_df, col_ins)
    bill_tbl = safe_value_counts(reg_df, col_billtype)
    visit_type_tbl = safe_value_counts(reg_df, col_visittype)
    status_tbl = safe_value_counts(reg_df, col_status)
    reg_user_tbl = safe_value_counts(reg_df, col_reguser)

    # Reg Date wise
    if col_regdate and col_regdate in reg_df.columns:
        tmp = reg_df.copy()
        tmp[col_regdate] = pd.to_datetime(tmp[col_regdate], errors="coerce").dt.date
        reg_date_tbl = tmp[col_regdate].value_counts().sort_index().reset_index()
        reg_date_tbl.columns = ["Reg Date", "Count"]
    else:
        reg_date_tbl = pd.DataFrame(columns=["Reg Date", "Count"])

    # optional S3 upload of 3 originals
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

    st.session_state.result = {
        "kpis": {
            "total_visits": total_visits,
            "unique_emr": unique_emr,
            "unique_visitno": unique_visitno,
            "cash_patients": cash_patients,
            "pending_patients": pending_patients,
        },
        "doctor_tbl": doctor_tbl,
        "ins_tbl": ins_tbl,
        "bill_tbl": bill_tbl,
        "visit_type_tbl": visit_type_tbl,
        "status_tbl": status_tbl,
        "reg_user_tbl": reg_user_tbl,
        "reg_date_tbl": reg_date_tbl,
        "s3_keys": s3_keys,
    }

    st.success("Processed successfully ✅")


# =========================================================
# Display like Excel layout
# =========================================================
if st.session_state.result:
    res = st.session_state.result
    k = res["kpis"]

    st.markdown("## Registration Summary")

    # --- Top KPI row like Excel (3 blocks)
    a, b, c = st.columns(3)
    with a:
        st.metric("Total Visits", k["total_visits"])
    with b:
        st.metric("Unique EMR (Patients)", k["unique_emr"])
    with c:
        st.metric("Unique Visit No", k["unique_visitno"])

    st.write("")

    # --- CashOut + Pending (center like your sheet)
    x1, x2, x3, x4 = st.columns([1, 2, 2, 1])
    with x2:
        st.metric("CashOut Patients", k["cash_patients"])
    with x3:
        st.metric("Pending Patients", k["pending_patients"])

    st.write("")

    # --- Doctor Wise + Insurance Wise
    l, r = st.columns(2)
    with l:
        style_block_title("Doctor Wise Visits")
        st.dataframe(res["doctor_tbl"], use_container_width=True, height=320)
    with r:
        style_block_title("Insurance Wise Visits")
        st.dataframe(res["ins_tbl"], use_container_width=True, height=320)

    st.write("")

    # --- Bill Type + Visit Type
    l, r = st.columns(2)
    with l:
        style_block_title("Bill Type (Insurance/Cash)")
        st.dataframe(res["bill_tbl"], use_container_width=True, height=260)
    with r:
        style_block_title("Visit Type (Consult/Follow-up)")
        st.dataframe(res["visit_type_tbl"], use_container_width=True, height=260)

    st.write("")

    # --- Status Wise + Registration User Wise
    l, r = st.columns(2)
    with l:
        style_block_title("Status Wise")
        st.dataframe(res["status_tbl"], use_container_width=True, height=260)
    with r:
        style_block_title("Registration User Wise")
        st.dataframe(res["reg_user_tbl"], use_container_width=True, height=260)

    st.write("")

    # --- Reg Date Wise (Daily)
    style_block_title("Reg Date Wise (Daily)")
    st.dataframe(res["reg_date_tbl"], use_container_width=True, height=220)

    # --- S3 paths
    if res.get("s3_keys"):
        st.caption("Saved to S3:")
        st.code("\n".join(res["s3_keys"]))

    st.write("")
    if st.button("🔄 Reset All", use_container_width=True):
        reset_all()
        st.rerun()
