import io
import json
import uuid
from datetime import date

import pandas as pd
import streamlit as st

# S3 required
import boto3


# =========================================================
# Page
# =========================================================
st.set_page_config(page_title="Registration Summary", layout="wide")
st.title("Registration Summary (Registration + CashOut + Pending)")


# =========================================================
# Secrets / S3 must exist
# =========================================================
def get_secret(key: str, default=None):
    try:
        return st.secrets.get(key, default)
    except Exception:
        return default


REQUIRED_KEYS = ["S3_BUCKET_NAME", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_REGION"]

missing = [k for k in REQUIRED_KEYS if not get_secret(k)]
if missing:
    st.error(
        "S3 is required for this page.\n\n"
        f"Missing secrets: {', '.join(missing)}\n\n"
        "Add them in Streamlit Cloud → App → Settings → Secrets:\n"
        "S3_BUCKET_NAME, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION\n\n"
        "Optional: S3_BASE_PREFIX"
    )
    st.stop()

BUCKET = get_secret("S3_BUCKET_NAME")
BASE_PREFIX = get_secret("S3_BASE_PREFIX", "excellent/daily_registration").strip("/")

s3 = boto3.client(
    "s3",
    aws_access_key_id=get_secret("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=get_secret("AWS_SECRET_ACCESS_KEY"),
    region_name=get_secret("AWS_REGION"),
)


# =========================================================
# Helpers
# =========================================================
def s3_put_bytes(key: str, data: bytes):
    s3.upload_fileobj(io.BytesIO(data), BUCKET, key)


def s3_get_bytes(key: str) -> bytes:
    buf = io.BytesIO()
    s3.download_fileobj(BUCKET, key, buf)
    return buf.getvalue()


def s3_list_objects(prefix: str):
    """List all objects for a prefix (handles pagination)."""
    keys = []
    token = None
    while True:
        kwargs = {"Bucket": BUCKET, "Prefix": prefix}
        if token:
            kwargs["ContinuationToken"] = token
        resp = s3.list_objects_v2(**kwargs)
        for obj in resp.get("Contents", []):
            keys.append(obj["Key"])
        if resp.get("IsTruncated"):
            token = resp.get("NextContinuationToken")
        else:
            break
    return keys


def s3_day_prefix(day_str: str):
    return f"{BASE_PREFIX}/{day_str}"


def s3_list_dates():
    keys = s3_list_objects(f"{BASE_PREFIX}/")
    dates = set()
    for k in keys:
        rest = k.replace(f"{BASE_PREFIX}/", "", 1)
        parts = rest.split("/")
        if len(parts) >= 2:
            d = parts[0]
            if len(d) == 10 and d[4] == "-" and d[7] == "-":
                dates.add(d)
    return sorted(dates)


def s3_latest_date():
    ds = s3_list_dates()
    return ds[-1] if ds else None


def norm_cols(df: pd.DataFrame):
    df.columns = [str(c).strip() for c in df.columns]
    return df


def pick_col(df: pd.DataFrame, candidates):
    cols = {str(c).strip().lower(): c for c in df.columns}
    for cand in candidates:
        key = str(cand).strip().lower()
        if key in cols:
            return cols[key]
    return None


def read_excel_find_header(file_bytes: bytes, required_col="EMRNo", max_header_rows=10):
    """
    For .xls files with title rows above headers.
    Try header=0..max_header_rows until required_col exists.
    """
    last_cols = None
    for h in range(max_header_rows + 1):
        df = pd.read_excel(io.BytesIO(file_bytes), header=h)
        df = norm_cols(df)
        last_cols = list(df.columns)
        if required_col in df.columns:
            return df, h
    return None, last_cols


def validate_registration_excel(file_bytes: bytes):
    df = pd.read_excel(io.BytesIO(file_bytes))
    df = norm_cols(df)
    emr = pick_col(df, ["EMR No", "EMRNo"])
    if not emr:
        return False, f"Registration file must contain 'EMR No' or 'EMRNo'. Found: {list(df.columns)}"
    return True, ""


def validate_cashout_or_pending(file_bytes: bytes):
    df, last_cols = read_excel_find_header(file_bytes, required_col="EMRNo", max_header_rows=10)
    if df is None:
        return False, f"File must contain 'EMRNo'. Header row not found. Columns seen: {last_cols}"
    return True, ""


def count_cashout_or_pending(file_bytes: bytes) -> int:
    df, _ = read_excel_find_header(file_bytes, required_col="EMRNo", max_header_rows=10)
    if df is None or df.empty:
        return 0
    return int(df["EMRNo"].nunique())


def safe_value_counts(df: pd.DataFrame, col: str):
    if not col or col not in df.columns:
        return pd.DataFrame(columns=["Value", "Count"])
    s = df[col].fillna("").astype(str)
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
            margin:10px 0 6px 0;">
            {text}
        </div>
        """,
        unsafe_allow_html=True,
    )


def df_to_excel_bytes(df: pd.DataFrame, sheet_name="data") -> bytes:
    out = io.BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name=sheet_name[:31])
    return out.getvalue()


def load_summary_df():
    ds = s3_list_dates()
    rows = []
    for d in ds:
        key = f"{s3_day_prefix(d)}/summary.json"
        try:
            obj = json.loads(s3_get_bytes(key).decode("utf-8"))
            rows.append(obj)
        except Exception:
            pass
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["day"] = pd.to_datetime(df["day"])
    df = df.sort_values("day")
    return df


# =========================================================
# Session State
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
    reset_cash()


def reset_cash():
    st.session_state.cash_bytes = None
    st.session_state.cash_name = ""
    reset_pending()


def reset_pending():
    st.session_state.pend_bytes = None
    st.session_state.pend_name = ""
    st.session_state.result = None


# =========================================================
# Load from S3 (Latest / Specific Day)
# =========================================================
st.subheader("Load from S3")

available_dates = s3_list_dates()
latest = available_dates[-1] if available_dates else None

c1, c2, c3 = st.columns([2, 2, 2])
with c1:
    chosen_date = st.selectbox(
        "Select Day",
        options=available_dates if available_dates else ["(no saved days yet)"],
        index=len(available_dates) - 1 if available_dates else 0,
        disabled=not available_dates,
    )

with c2:
    if st.button("📥 Load Selected Day", use_container_width=True, disabled=not available_dates):
        dayp = s3_day_prefix(chosen_date)
        st.session_state.reg_bytes = s3_get_bytes(f"{dayp}/registration.xlsx")
        st.session_state.cash_bytes = s3_get_bytes(f"{dayp}/cashout.xls")
        st.session_state.pend_bytes = s3_get_bytes(f"{dayp}/pending.xls")
        st.session_state.reg_name = "registration.xlsx"
        st.session_state.cash_name = "cashout.xls"
        st.session_state.pend_name = "pending.xls"
        st.session_state.result = None
        st.rerun()

with c3:
    if st.button("⏮ Load Latest", use_container_width=True, disabled=not latest):
        dayp = s3_day_prefix(latest)
        st.session_state.reg_bytes = s3_get_bytes(f"{dayp}/registration.xlsx")
        st.session_state.cash_bytes = s3_get_bytes(f"{dayp}/cashout.xls")
        st.session_state.pend_bytes = s3_get_bytes(f"{dayp}/pending.xls")
        st.session_state.reg_name = "registration.xlsx"
        st.session_state.cash_name = "cashout.xls"
        st.session_state.pend_name = "pending.xls"
        st.session_state.result = None
        st.rerun()

st.divider()


# =========================================================
# Upload section (Step by step)
# =========================================================
st.subheader("Step 1 → Step 2 → Step 3 Upload (then Process)")


# Step 1
a, b = st.columns([6, 2])
with a:
    st.markdown("### 1) RegistrationList.xlsx")
    reg_upl = st.file_uploader("Upload Registration file", type=["xlsx"], key="upl_reg")
with b:
    st.markdown("### ")
    st.button("🗑️ Delete Step 1", use_container_width=True, on_click=reset_reg)

if reg_upl is not None:
    reg_bytes = reg_upl.getvalue()
    ok, msg = validate_registration_excel(reg_bytes)
    if not ok:
        st.error(f"Step 1 error: {msg}")
        reset_reg()
    else:
        st.session_state.reg_bytes = reg_bytes
        st.session_state.reg_name = reg_upl.name
        st.success(f"Step 1 uploaded ✅ ({reg_upl.name})")

st.divider()


# Step 2
step2_enabled = st.session_state.reg_bytes is not None
a, b = st.columns([6, 2])
with a:
    st.markdown("### 2) PatientCashOutList (.xls / .xlsx) — Only for Count")
    cash_upl = st.file_uploader(
        "Upload CashOut file", type=["xls", "xlsx"], key="upl_cash", disabled=not step2_enabled
    )
with b:
    st.markdown("### ")
    st.button("🗑️ Delete Step 2", use_container_width=True, on_click=reset_cash, disabled=not step2_enabled)

if not step2_enabled:
    st.info("Upload Step 1 first to enable Step 2.")

if cash_upl is not None:
    cash_bytes = cash_upl.getvalue()
    ok, msg = validate_cashout_or_pending(cash_bytes)
    if not ok:
        st.error(f"Step 2 error: {msg}")
        reset_cash()
    else:
        st.session_state.cash_bytes = cash_bytes
        st.session_state.cash_name = cash_upl.name
        st.success(f"Step 2 uploaded ✅ ({cash_upl.name})")

st.divider()


# Step 3
step3_enabled = st.session_state.reg_bytes is not None and st.session_state.cash_bytes is not None
a, b = st.columns([6, 2])
with a:
    st.markdown("### 3) Pending file (.xls / .xlsx) — Only for Count")
    pend_upl = st.file_uploader(
        "Upload Pending file", type=["xls", "xlsx"], key="upl_pend", disabled=not step3_enabled
    )
with b:
    st.markdown("### ")
    st.button("🗑️ Delete Step 3", use_container_width=True, on_click=reset_pending, disabled=not step3_enabled)

if not step3_enabled:
    st.info("Upload Step 1 and Step 2 first to enable Step 3.")

if pend_upl is not None:
    pend_bytes = pend_upl.getvalue()
    ok, msg = validate_cashout_or_pending(pend_bytes)
    if not ok:
        st.error(f"Step 3 error: {msg}")
        reset_pending()
    else:
        st.session_state.pend_bytes = pend_bytes
        st.session_state.pend_name = pend_upl.name
        st.success(f"Step 3 uploaded ✅ ({pend_upl.name})")

st.divider()


# =========================================================
# Day selection for saving
# =========================================================
save_day = st.date_input("Save as Day (for S3)", value=date.today())
save_day_str = save_day.strftime("%Y-%m-%d")


# =========================================================
# Process
# =========================================================
all_ready = (
    st.session_state.reg_bytes is not None
    and st.session_state.cash_bytes is not None
    and st.session_state.pend_bytes is not None
)

c1, c2 = st.columns([2, 6])
with c1:
    process = st.button("✅ Process + Save to S3", type="primary", use_container_width=True, disabled=not all_ready)
with c2:
    if not all_ready:
        st.warning("Complete Step 1 → Step 2 → Step 3 to enable Process.")
    else:
        st.success("All files ready. Click Process.")

if process:
    run_id = str(uuid.uuid4())[:8]
    dayp = s3_day_prefix(save_day_str)

    # save raw uploads
    s3_put_bytes(f"{dayp}/registration.xlsx", st.session_state.reg_bytes)
    # keep extension stable for loading
    s3_put_bytes(f"{dayp}/cashout.xls", st.session_state.cash_bytes)
    s3_put_bytes(f"{dayp}/pending.xls", st.session_state.pend_bytes)

    # read registration for summary blocks
    reg_df = pd.read_excel(io.BytesIO(st.session_state.reg_bytes))
    reg_df = norm_cols(reg_df)

    # Columns (registration only)
    col_emr = pick_col(reg_df, ["EMR No", "EMRNo"])
    col_visitno = pick_col(reg_df, ["Visit No", "VisitNo", "Visit Number", "VisitNumber"])
    col_doctor = pick_col(reg_df, ["Doctor", "Doctor Name", "Physician", "Provider"])
    col_ins = pick_col(reg_df, ["Insurance", "Payer", "TPA", "Insurance Company"])
    col_employer = pick_col(reg_df, ["Employer", "Employer Name", "Company", "Company Name", "Sponsor", "Sponsor Name"])
    col_billtype = pick_col(reg_df, ["Bill Type", "BillType"])
    col_visittype = pick_col(reg_df, ["Visit Type", "VisitType", "Purpose"])
    col_status = pick_col(reg_df, ["Status", "Visit Status"])
    col_reguser = pick_col(reg_df, ["Reg:User", "Reg User", "Registered By", "Registration User"])
    col_regdate = pick_col(reg_df, ["Reg Date", "Registration Date", "Visit Date", "Date"])

    # KPIs (registration only)
    total_visits = int(len(reg_df))
    unique_emr = int(reg_df[col_emr].nunique()) if col_emr else 0
    unique_visitno = int(reg_df[col_visitno].nunique()) if col_visitno else total_visits

    # CashOut/Pending counts only
    cash_patients = count_cashout_or_pending(st.session_state.cash_bytes)
    pending_patients = count_cashout_or_pending(st.session_state.pend_bytes)

    # Tables (registration only)
    doctor_tbl = safe_value_counts(reg_df, col_doctor)
    ins_tbl = safe_value_counts(reg_df, col_ins)
    employer_tbl = safe_value_counts(reg_df, col_employer)
    bill_tbl = safe_value_counts(reg_df, col_billtype)
    visit_type_tbl = safe_value_counts(reg_df, col_visittype)
    status_tbl = safe_value_counts(reg_df, col_status)
    reg_user_tbl = safe_value_counts(reg_df, col_reguser)

    # Reg Date wise (Daily)
    if col_regdate and col_regdate in reg_df.columns:
        tmp = reg_df.copy()
        tmp[col_regdate] = pd.to_datetime(tmp[col_regdate], errors="coerce").dt.date
        reg_date_tbl = tmp[col_regdate].value_counts().sort_index().reset_index()
        reg_date_tbl.columns = ["Reg Date", "Count"]
    else:
        reg_date_tbl = pd.DataFrame(columns=["Reg Date", "Count"])

    # Save summary.json for accumulative
    summary_obj = {
        "day": save_day_str,
        "total_visits": total_visits,
        "unique_emr": unique_emr,
        "unique_visitno": unique_visitno,
        "cash_patients": cash_patients,
        "pending_patients": pending_patients,
        "run_id": run_id,
    }
    s3_put_bytes(f"{dayp}/summary.json", json.dumps(summary_obj).encode("utf-8"))

    # Store result for display + downloads
    st.session_state.result = {
        "day": save_day_str,
        "reg_df": reg_df,  # keep in memory for downloads
        "cols": {
            "col_doctor": col_doctor,
            "col_ins": col_ins,
            "col_employer": col_employer,
            "col_billtype": col_billtype,
            "col_visittype": col_visittype,
            "col_status": col_status,
            "col_reguser": col_reguser,
            "col_regdate": col_regdate,
        },
        "kpis": {
            "total_visits": total_visits,
            "unique_emr": unique_emr,
            "unique_visitno": unique_visitno,
            "cash_patients": cash_patients,
            "pending_patients": pending_patients,
        },
        "tables": {
            "doctor_tbl": doctor_tbl,
            "ins_tbl": ins_tbl,
            "employer_tbl": employer_tbl,
            "bill_tbl": bill_tbl,
            "visit_type_tbl": visit_type_tbl,
            "status_tbl": status_tbl,
            "reg_user_tbl": reg_user_tbl,
            "reg_date_tbl": reg_date_tbl,
        },
        "s3_saved": {
            "registration": f"{dayp}/registration.xlsx",
            "cashout": f"{dayp}/cashout.xls",
            "pending": f"{dayp}/pending.xls",
            "summary": f"{dayp}/summary.json",
        },
    }

    st.success(f"Processed & saved to S3 ✅ (Day: {save_day_str})")

st.divider()


# =========================================================
# Accumulative view (All days from S3)
# =========================================================
st.subheader("Accumulated (All Saved Days)")

sum_df = load_summary_df()
if sum_df.empty:
    st.info("No saved days yet. Process and save first.")
else:
    sum_df["cum_total_visits"] = sum_df["total_visits"].cumsum()
    sum_df["cum_unique_emr"] = sum_df["unique_emr"].cumsum()
    sum_df["cum_cash_patients"] = sum_df["cash_patients"].cumsum()
    sum_df["cum_pending_patients"] = sum_df["pending_patients"].cumsum()

    a, b, c, d = st.columns(4)
    a.metric("Cumulative Visits", int(sum_df["cum_total_visits"].iloc[-1]))
    b.metric("Cumulative Unique EMR", int(sum_df["cum_unique_emr"].iloc[-1]))
    c.metric("Cumulative CashOut", int(sum_df["cum_cash_patients"].iloc[-1]))
    d.metric("Cumulative Pending", int(sum_df["cum_pending_patients"].iloc[-1]))

    st.dataframe(sum_df, use_container_width=True)

st.divider()


# =========================================================
# Display Excel-style summary + Downloads (A)
# =========================================================
if st.session_state.result:
    res = st.session_state.result
    reg_df = res["reg_df"]
    cols = res["cols"]
    t = res["tables"]
    k = res["kpis"]
    day_str = res["day"]

    st.markdown("## Registration Summary")

    # Top KPI row
    x, y, z = st.columns(3)
    with x:
        st.metric("Total Visits", k["total_visits"])
    with y:
        st.metric("Unique EMR (Patients)", k["unique_emr"])
    with z:
        st.metric("Unique Visit No", k["unique_visitno"])

    # CashOut + Pending
    p1, p2, p3, p4 = st.columns([1, 2, 2, 1])
    with p2:
        st.metric("CashOut Patients", k["cash_patients"])
    with p3:
        st.metric("Pending Patients", k["pending_patients"])

    # -------- Doctor + Insurance
    l, r = st.columns(2)
    with l:
        style_block_title("Doctor Wise Visits")
        st.dataframe(t["doctor_tbl"], use_container_width=True, height=320)
        col_doctor = cols["col_doctor"]
        if col_doctor and not t["doctor_tbl"].empty:
            options = [str(x) for x in t["doctor_tbl"]["Value"].tolist() if str(x).strip() != ""]
            pick = st.selectbox("Download by Doctor", options=options, key="dl_doctor")
            filt = reg_df[reg_df[col_doctor].fillna("").astype(str) == str(pick)]
            st.download_button(
                "⬇ Download Doctor Visits (Excel)",
                data=df_to_excel_bytes(filt, "doctor"),
                file_name=f"doctor_{pick}_{day_str}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )

    with r:
        style_block_title("Insurance Wise Visits")
        st.dataframe(t["ins_tbl"], use_container_width=True, height=320)
        col_ins = cols["col_ins"]
        if col_ins and not t["ins_tbl"].empty:
            options = [str(x) for x in t["ins_tbl"]["Value"].tolist() if str(x).strip() != ""]
            pick = st.selectbox("Download by Insurance", options=options, key="dl_ins")
            filt = reg_df[reg_df[col_ins].fillna("").astype(str) == str(pick)]
            st.download_button(
                "⬇ Download Insurance Visits (Excel)",
                data=df_to_excel_bytes(filt, "insurance"),
                file_name=f"insurance_{pick}_{day_str}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )

    # -------- Employer Wise
    style_block_title("Employer Wise")
    st.dataframe(t["employer_tbl"], use_container_width=True, height=380)
    col_employer = cols["col_employer"]
    if col_employer and not t["employer_tbl"].empty:
        options = [str(x) for x in t["employer_tbl"]["Value"].tolist() if str(x).strip() != ""]
        pick = st.selectbox("Download by Employer", options=options, key="dl_employer")
        filt = reg_df[reg_df[col_employer].fillna("").astype(str) == str(pick)]
        st.download_button(
            "⬇ Download Employer Visits (Excel)",
            data=df_to_excel_bytes(filt, "employer"),
            file_name=f"employer_{pick}_{day_str}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )

    # -------- Bill Type + Visit Type
    l, r = st.columns(2)
    with l:
        style_block_title("Bill Type (Insurance/Cash)")
        st.dataframe(t["bill_tbl"], use_container_width=True, height=260)
        col_bill = cols["col_billtype"]
        if col_bill and not t["bill_tbl"].empty:
            options = [str(x) for x in t["bill_tbl"]["Value"].tolist() if str(x).strip() != ""]
            pick = st.selectbox("Download by Bill Type", options=options, key="dl_bill")
            filt = reg_df[reg_df[col_bill].fillna("").astype(str) == str(pick)]
            st.download_button(
                "⬇ Download Bill Type (Excel)",
                data=df_to_excel_bytes(filt, "billtype"),
                file_name=f"billtype_{pick}_{day_str}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )

    with r:
        style_block_title("Visit Type (Consult/Follow-up)")
        st.dataframe(t["visit_type_tbl"], use_container_width=True, height=260)
        col_vt = cols["col_visittype"]
        if col_vt and not t["visit_type_tbl"].empty:
            options = [str(x) for x in t["visit_type_tbl"]["Value"].tolist() if str(x).strip() != ""]
            pick = st.selectbox("Download by Visit Type", options=options, key="dl_vt")
            filt = reg_df[reg_df[col_vt].fillna("").astype(str) == str(pick)]
            st.download_button(
                "⬇ Download Visit Type (Excel)",
                data=df_to_excel_bytes(filt, "visittype"),
                file_name=f"visittype_{pick}_{day_str}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )

    # -------- Status + Reg User
    l, r = st.columns(2)
    with l:
        style_block_title("Status Wise")
        st.dataframe(t["status_tbl"], use_container_width=True, height=260)
        col_st = cols["col_status"]
        if col_st and not t["status_tbl"].empty:
            options = [str(x) for x in t["status_tbl"]["Value"].tolist() if str(x).strip() != ""]
            pick = st.selectbox("Download by Status", options=options, key="dl_status")
            filt = reg_df[reg_df[col_st].fillna("").astype(str) == str(pick)]
            st.download_button(
                "⬇ Download Status (Excel)",
                data=df_to_excel_bytes(filt, "status"),
                file_name=f"status_{pick}_{day_str}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )

    with r:
        style_block_title("Registration User Wise")
        st.dataframe(t["reg_user_tbl"], use_container_width=True, height=260)
        col_ru = cols["col_reguser"]
        if col_ru and not t["reg_user_tbl"].empty:
            options = [str(x) for x in t["reg_user_tbl"]["Value"].tolist() if str(x).strip() != ""]
            pick = st.selectbox("Download by Registration User", options=options, key="dl_reguser")
            filt = reg_df[reg_df[col_ru].fillna("").astype(str) == str(pick)]
            st.download_button(
                "⬇ Download Reg User (Excel)",
                data=df_to_excel_bytes(filt, "reguser"),
                file_name=f"reguser_{pick}_{day_str}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )

    # -------- Reg Date Wise
    style_block_title("Reg Date Wise (Daily)")
    st.dataframe(t["reg_date_tbl"], use_container_width=True, height=240)
    col_rd = cols["col_regdate"]
    if col_rd:
        # normalize date for filtering
        tmp = reg_df.copy()
        tmp[col_rd] = pd.to_datetime(tmp[col_rd], errors="coerce").dt.date
        date_opts = [d for d in tmp[col_rd].dropna().unique().tolist()]
        date_opts = sorted(date_opts)
        if date_opts:
            pick_d = st.selectbox("Download by Reg Date", options=date_opts, key="dl_regdate")
            filt = tmp[tmp[col_rd] == pick_d].drop(columns=[col_rd]).copy()
            # keep original column too (optional)
            filt.insert(0, "Reg Date", pick_d)
            st.download_button(
                "⬇ Download Reg Date Visits (Excel)",
                data=df_to_excel_bytes(filt, "regdate"),
                file_name=f"regdate_{pick_d}_{day_str}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )

    # S3 saved paths
    st.caption("Saved in S3:")
    st.code("\n".join([f"{k}: {v}" for k, v in res["s3_saved"].items()]))

    if st.button("🔄 Reset All", use_container_width=True):
        reset_all()
        st.rerun()
