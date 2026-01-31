import io
import re
import hashlib
from datetime import datetime, date

import pandas as pd
import streamlit as st

# Optional (only used if S3 is configured)
import boto3
from botocore.exceptions import ClientError

st.set_page_config(page_title="Registration Summary", layout="wide")
st.title("Registration Summary (Registration + CashOut + Pending)")

# =========================
# Helpers
# =========================
def _sha1_bytes(b: bytes) -> str:
    return hashlib.sha1(b).hexdigest()[:8]

def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(s).strip().lower())

def find_emr_column(df: pd.DataFrame):
    # Accept many variants
    candidates = {"emrno", "emr", "emrnumber", "mrn", "medicalrecordno", "medicalrecordnumber", "patientid"}
    for c in df.columns:
        if _norm(c) in candidates:
            return c
    # If columns are weird, try to detect a header row in first 10 rows:
    # Sometimes first row is a title like "EXCELLENT MEDICAL CENTER" and real header is next row.
    # We'll scan first 10 rows and if any row contains "EMR", treat it as header.
    for i in range(min(10, len(df))):
        row = df.iloc[i].astype(str).tolist()
        row_norm = [_norm(x) for x in row]
        if any(x in candidates for x in row_norm):
            # rebuild with that row as header
            new_header = df.iloc[i].astype(str).tolist()
            df2 = df.iloc[i + 1 :].copy()
            df2.columns = new_header
            df2 = df2.reset_index(drop=True)
            for c in df2.columns:
                if _norm(c) in candidates:
                    return c, df2
    return None

def try_read_excel(uploaded_file):
    # Works for .xls/.xlsx
    # Try default, then fallback to header=None if headers are broken
    try:
        return pd.read_excel(uploaded_file)
    except Exception:
        uploaded_file.seek(0)
        return pd.read_excel(uploaded_file, header=None)

def safe_sheet_name(name: str) -> str:
    # Excel sheet name max 31 chars
    name = re.sub(r"[\[\]\*\?:/\\]", "-", name)
    return name[:31]

def to_excel_bytes(sheets: dict[str, pd.DataFrame]) -> bytes:
    bio = io.BytesIO()
    with pd.ExcelWriter(bio, engine="openpyxl") as writer:
        for sheet, df in sheets.items():
            if df is None:
                continue
            df.to_excel(writer, sheet_name=safe_sheet_name(sheet), index=False)
    return bio.getvalue()

# =========================
# S3 Secrets (accept both naming styles)
# =========================
def get_secret(*names, default=None):
    for n in names:
        if n in st.secrets:
            return st.secrets.get(n)
    return default

AWS_KEY = get_secret("AWS_ACCESS_KEY_ID")
AWS_SECRET = get_secret("AWS_SECRET_ACCESS_KEY")
AWS_REGION = get_secret("AWS_REGION", "AWS_DEFAULT_REGION")
S3_BUCKET = get_secret("S3_BUCKET_NAME", "S3_BUCKET")
S3_PREFIX = get_secret("S3_BASE_PREFIX", default="streamlit")

S3_OK = all([AWS_KEY, AWS_SECRET, AWS_REGION, S3_BUCKET])

def s3_client():
    return boto3.client(
        "s3",
        aws_access_key_id=AWS_KEY,
        aws_secret_access_key=AWS_SECRET,
        region_name=AWS_REGION,
    )

def s3_key(*parts):
    # store inside streamlit/registration/...
    return "/".join([S3_PREFIX.strip("/"), "registration", *[p.strip("/") for p in parts]])

def s3_put_bytes(key: str, b: bytes):
    c = s3_client()
    c.put_object(Bucket=S3_BUCKET, Key=key, Body=b)

def s3_get_bytes(key: str) -> bytes | None:
    c = s3_client()
    try:
        obj = c.get_object(Bucket=S3_BUCKET, Key=key)
        return obj["Body"].read()
    except ClientError:
        return None

def s3_list(prefix: str):
    c = s3_client()
    out = []
    token = None
    while True:
        kwargs = {"Bucket": S3_BUCKET, "Prefix": prefix}
        if token:
            kwargs["ContinuationToken"] = token
        resp = c.list_objects_v2(**kwargs)
        for it in resp.get("Contents", []):
            out.append(it["Key"])
        if resp.get("IsTruncated"):
            token = resp.get("NextContinuationToken")
        else:
            break
    return out

with st.expander("Storage Status (S3)", expanded=False):
    if S3_OK:
        st.success(f"S3 configured ✅  Bucket: {S3_BUCKET} | Region: {AWS_REGION} | Prefix: {S3_PREFIX}")
    else:
        st.warning("S3 is NOT configured. Uploaders will work and summary will display, but files will NOT be saved to S3.")

# =========================
# Session state
# =========================
for k in ["reg_file", "cash_file", "pend_file"]:
    if k not in st.session_state:
        st.session_state[k] = None

# =========================
# Step 0: day picker (fallback only)
# =========================
st.caption("✅ Day is read from Registration file (if date column exists). Date picker is used only if file has no date column.")
manual_day = st.date_input("Manual Day (fallback only)", value=date.today())

# =========================
# Step 1: Registration file
# =========================
st.subheader("1) RegistrationList (.xls / .xlsx)")
c1, c2 = st.columns([4, 1])
with c1:
    reg = st.file_uploader("Upload Registration file", type=["xls", "xlsx"], key="u_reg")
with c2:
    if st.button("🗑️ Delete Step 1", use_container_width=True):
        st.session_state["reg_file"] = None
        st.session_state["cash_file"] = None
        st.session_state["pend_file"] = None
        st.rerun()

if reg is not None:
    st.session_state["reg_file"] = reg

if st.session_state["reg_file"] is None:
    st.info("Please upload Registration file (Step 1).")
    st.stop()

# =========================
# Step 2: CashOut file
# =========================
st.subheader("2) PatientCashOutList (.xls / .xlsx)")
c1, c2 = st.columns([4, 1])
with c1:
    cash = st.file_uploader("Upload CashOut file", type=["xls", "xlsx"], key="u_cash")
with c2:
    if st.button("🗑️ Delete Step 2", use_container_width=True):
        st.session_state["cash_file"] = None
        st.session_state["pend_file"] = None
        st.rerun()

if cash is not None:
    st.session_state["cash_file"] = cash

if st.session_state["cash_file"] is None:
    st.warning("Upload CashOut file (Step 2) to continue.")
    st.stop()

# =========================
# Step 3: Pending file
# =========================
st.subheader("3) Pending file (.xls / .xlsx)")
c1, c2 = st.columns([4, 1])
with c1:
    pend = st.file_uploader("Upload Pending file", type=["xls", "xlsx"], key="u_pend")
with c2:
    if st.button("🗑️ Delete Step 3", use_container_width=True):
        st.session_state["pend_file"] = None
        st.rerun()

if pend is not None:
    st.session_state["pend_file"] = pend

if st.session_state["pend_file"] is None:
    st.warning("Upload Pending file (Step 3) to continue.")
    st.stop()

# =========================
# Read + validate EMR from Cash/Pending
# =========================
def read_emr_list(uploaded) -> pd.Series:
    df = try_read_excel(uploaded)
    if isinstance(find_emr_column(df), tuple):
        emr_col, df2 = find_emr_column(df)
        df = df2
    else:
        emr_col = find_emr_column(df)

    if emr_col is None:
        raise ValueError(f"File must contain EMR column (EMRNo / EMR No / MRN etc). Found columns: {list(df.columns)}")

    s = df[emr_col].dropna().astype(str).str.strip()
    s = s[s != ""]
    return s

# =========================
# Registration processing (tables come ONLY from registration)
# =========================
def process_registration(reg_file):
    df = pd.read_excel(reg_file)

    # Guess date column
    date_candidates = ["regdate", "registrationdate", "date", "visitdate", "createddate"]
    date_col = None
    for c in df.columns:
        if _norm(c) in date_candidates:
            date_col = c
            break

    if date_col:
        day_val = pd.to_datetime(df[date_col], errors="coerce").dropna()
        if len(day_val) > 0:
            day = day_val.dt.date.mode().iloc[0]
        else:
            day = manual_day
    else:
        day = manual_day

    # EMR / Visit no
    emr_col = None
    visit_col = None
    for c in df.columns:
        if _norm(c) in {"emrno", "emr", "mrn"}:
            emr_col = c
        if _norm(c) in {"visitno", "visit", "visitnumber"}:
            visit_col = c

    total_visits = len(df)
    unique_emr = df[emr_col].nunique() if emr_col else None
    unique_visit = df[visit_col].nunique() if visit_col else None

    # Doctor-wise
    doctor_col = None
    for c in df.columns:
        if _norm(c) in {"doctor", "doctorname", "physician"}:
            doctor_col = c
            break
    doctor_wise = (
        df.groupby(doctor_col).size().reset_index(name="Count").rename(columns={doctor_col: "Value"})
        if doctor_col else pd.DataFrame(columns=["Value", "Count"])
    )

    # Insurance-wise
    ins_col = None
    for c in df.columns:
        if _norm(c) in {"insurance", "payer", "tpainsurance", "insurancename"}:
            ins_col = c
            break
    insurance_wise = (
        df.groupby(ins_col).size().reset_index(name="Count").rename(columns={ins_col: "Value"})
        if ins_col else pd.DataFrame(columns=["Value", "Count"])
    )

    # Employer-wise
    emp_col = None
    for c in df.columns:
        if _norm(c) in {"employer", "company", "employername"}:
            emp_col = c
            break
    employer_wise = (
        df.groupby(emp_col).size().reset_index(name="Count").rename(columns={emp_col: "Value"})
        if emp_col else pd.DataFrame(columns=["Value", "Count"])
    )

    # Bill type (Insurance/Cash)
    bill_col = None
    for c in df.columns:
        if _norm(c) in {"billtype", "billingtype", "paymenttype"}:
            bill_col = c
            break
    bill_type = (
        df.groupby(bill_col).size().reset_index(name="Count").rename(columns={bill_col: "Value"})
        if bill_col else pd.DataFrame(columns=["Value", "Count"])
    )

    # Visit type
    vtype_col = None
    for c in df.columns:
        if _norm(c) in {"visittype", "appointmenttype", "type"}:
            vtype_col = c
            break
    visit_type = (
        df.groupby(vtype_col).size().reset_index(name="Count").rename(columns={vtype_col: "Value"})
        if vtype_col else pd.DataFrame(columns=["Value", "Count"])
    )

    # Registration user wise
    user_col = None
    for c in df.columns:
        if _norm(c) in {"user", "createdby", "registrationuser"}:
            user_col = c
            break
    reg_user = (
        df.groupby(user_col).size().reset_index(name="Count").rename(columns={user_col: "Value"})
        if user_col else pd.DataFrame(columns=["Value", "Count"])
    )

    # Status wise
    status_col = None
    for c in df.columns:
        if _norm(c) in {"status"}:
            status_col = c
            break
    status_wise = (
        df.groupby(status_col).size().reset_index(name="Count").rename(columns={status_col: "Value"})
        if status_col else pd.DataFrame(columns=["Value", "Count"])
    )

    return {
        "day": pd.to_datetime(day),
        "df": df,
        "total_visits": int(total_visits),
        "unique_emr": int(unique_emr) if unique_emr is not None else None,
        "unique_visit": int(unique_visit) if unique_visit is not None else None,
        "doctor_wise": doctor_wise.sort_values("Count", ascending=False),
        "insurance_wise": insurance_wise.sort_values("Count", ascending=False),
        "employer_wise": employer_wise.sort_values("Count", ascending=False),
        "bill_type": bill_type.sort_values("Count", ascending=False),
        "visit_type": visit_type.sort_values("Count", ascending=False),
        "reg_user": reg_user.sort_values("Count", ascending=False),
        "status_wise": status_wise.sort_values("Count", ascending=False),
    }

# =========================
# Process button
# =========================
st.divider()
process_and_save = st.checkbox("Process & Save to S3", value=True if S3_OK else False)

if st.button("✅ Process", type="primary", use_container_width=True):
    # read
    reg_res = process_registration(st.session_state["reg_file"])
    cash_emr = read_emr_list(st.session_state["cash_file"])
    pend_emr = read_emr_list(st.session_state["pend_file"])

    cash_count = int(cash_emr.nunique())
    pend_count = int(pend_emr.nunique())

    # CURRENT DAY section
    st.subheader("Current Day")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total Visits", reg_res["total_visits"])
    m2.metric("Unique EMR (Patients)", reg_res["unique_emr"] if reg_res["unique_emr"] is not None else 0)
    m3.metric("CashOut Patients", cash_count)
    m4.metric("Pending Patients", pend_count)

    # Display tables (from Registration only)
    left, right = st.columns(2)
    with left:
        st.markdown("### Doctor Wise Visits")
        st.dataframe(reg_res["doctor_wise"], use_container_width=True)
        st.markdown("### Bill Type (Insurance/Cash)")
        st.dataframe(reg_res["bill_type"], use_container_width=True)
        st.markdown("### Status Wise")
        st.dataframe(reg_res["status_wise"], use_container_width=True)

    with right:
        st.markdown("### Insurance Wise Visits")
        st.dataframe(reg_res["insurance_wise"], use_container_width=True)
        st.markdown("### Visit Type (Consult/Follow-up)")
        st.dataframe(reg_res["visit_type"], use_container_width=True)
        st.markdown("### Employer Wise")
        st.dataframe(reg_res["employer_wise"], use_container_width=True)

    st.markdown("### Registration User Wise")
    st.dataframe(reg_res["reg_user"], use_container_width=True)

    # Download filtered lists (simple)
    st.divider()
    st.subheader("Download Lists (from Registration file)")
    df_reg = reg_res["df"]

    # try infer insurance column for filtering
    ins_col = None
    for c in df_reg.columns:
        if _norm(c) in {"insurance", "payer", "tpainsurance", "insurancename"}:
            ins_col = c
            break

    bill_col = None
    for c in df_reg.columns:
        if _norm(c) in {"billtype", "billingtype", "paymenttype"}:
            bill_col = c
            break

    cA, cB = st.columns(2)
    with cA:
        if ins_col:
            ins_values = sorted([x for x in df_reg[ins_col].dropna().astype(str).unique().tolist() if x.strip() != ""])
            pick_ins = st.selectbox("Insurance", ["(select)"] + ins_values)
            if pick_ins != "(select)":
                dfi = df_reg[df_reg[ins_col].astype(str) == pick_ins].copy()
                st.download_button(
                    f"⬇️ Download Insurance: {pick_ins}",
                    data=to_excel_bytes({"Insurance_List": dfi}),
                    file_name=f"registration_insurance_{_norm(pick_ins)[:20]}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
        else:
            st.info("Insurance column not found in Registration file.")

    with cB:
        if bill_col:
            bill_values = sorted([x for x in df_reg[bill_col].dropna().astype(str).unique().tolist() if x.strip() != ""])
            pick_bill = st.selectbox("Bill Type", ["(select)"] + bill_values)
            if pick_bill != "(select)":
                dfb = df_reg[df_reg[bill_col].astype(str) == pick_bill].copy()
                st.download_button(
                    f"⬇️ Download Bill Type: {pick_bill}",
                    data=to_excel_bytes({"BillType_List": dfb}),
                    file_name=f"registration_billtype_{_norm(pick_bill)[:20]}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
        else:
            st.info("Bill Type column not found in Registration file.")

    # =========================
    # Save to S3 + Accumulate
    # =========================
    day_str = pd.to_datetime(reg_res["day"]).strftime("%Y-%m-%d")
    run_id = _sha1_bytes((day_str + str(datetime.utcnow())).encode())

    # Summary row (day-based; if you upload old file, it saves to that day)
    row = {
        "day": pd.to_datetime(reg_res["day"]),
        "total_visits": reg_res["total_visits"],
        "unique_emr": reg_res["unique_emr"] or 0,
        "unique_visitno": reg_res["unique_visit"] or 0,
        "cash_patients": cash_count,
        "pending_patients": pend_count,
        "run_id": run_id,
        "created_utc": datetime.utcnow(),
    }

    if S3_OK and process_and_save:
        # store uploaded files with clear names (not only date folder)
        reg_bytes = st.session_state["reg_file"].getvalue()
        cash_bytes = st.session_state["cash_file"].getvalue()
        pend_bytes = st.session_state["pend_file"].getvalue()

        s3_put_bytes(s3_key(day_str, f"registration_{run_id}.xlsx"), reg_bytes)
        s3_put_bytes(s3_key(day_str, f"cashout_{run_id}.xls"), cash_bytes)
        s3_put_bytes(s3_key(day_str, f"pending_{run_id}.xls"), pend_bytes)

        # also store a snapshot export of tables
        export_book = to_excel_bytes({
            "DoctorWise": reg_res["doctor_wise"],
            "InsuranceWise": reg_res["insurance_wise"],
            "EmployerWise": reg_res["employer_wise"],
            "BillType": reg_res["bill_type"],
            "VisitType": reg_res["visit_type"],
            "RegUserWise": reg_res["reg_user"],
            "StatusWise": reg_res["status_wise"],
        })
        s3_put_bytes(s3_key(day_str, f"summary_tables_{run_id}.xlsx"), export_book)

        # accumulate into one history csv in S3
        history_key = s3_key("history.csv")
        old = s3_get_bytes(history_key)
        if old:
            hist = pd.read_csv(io.BytesIO(old))
            # ensure datetime
            hist["day"] = pd.to_datetime(hist["day"], errors="coerce")
        else:
            hist = pd.DataFrame(columns=list(row.keys()))

        hist_new = pd.concat([hist, pd.DataFrame([row])], ignore_index=True)
        # If same day uploaded again, keep latest by created_utc
        hist_new["created_utc"] = pd.to_datetime(hist_new["created_utc"], errors="coerce")
        hist_new = hist_new.sort_values(["day", "created_utc"]).drop_duplicates(subset=["day"], keep="last")
        hist_new = hist_new.sort_values("day")

        s3_put_bytes(history_key, hist_new.to_csv(index=False).encode("utf-8"))
        st.success(f"Saved to S3 ✅  Day: {day_str}")

        # =========================
        # Accumulated view (all saved days)
        # =========================
        st.divider()
        st.subheader("Accumulated (All Saved Days)")
        cum = hist_new.copy()
        cum["cum_total_visits"] = cum["total_visits"].cumsum()
        cum["cum_unique_emr"] = cum["unique_emr"].cumsum()
        cum["cum_cash_patients"] = cum["cash_patients"].cumsum()
        cum["cum_pending_patients"] = cum["pending_patients"].cumsum()

        cm1, cm2, cm3, cm4 = st.columns(4)
        cm1.metric("Cumulative Visits", int(cum["cum_total_visits"].iloc[-1]) if len(cum) else 0)
        cm2.metric("Cumulative Unique EMR", int(cum["cum_unique_emr"].iloc[-1]) if len(cum) else 0)
        cm3.metric("Cumulative CashOut", int(cum["cum_cash_patients"].iloc[-1]) if len(cum) else 0)
        cm4.metric("Cumulative Pending", int(cum["cum_pending_patients"].iloc[-1]) if len(cum) else 0)

        st.dataframe(cum, use_container_width=True)

    else:
        st.warning("Processed locally. S3 save is OFF or not configured.")

