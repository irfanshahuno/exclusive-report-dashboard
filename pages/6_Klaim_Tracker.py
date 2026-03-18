import streamlit as st
import pandas as pd
import boto3
import io
import re
from datetime import datetime

st.set_page_config(page_title="Klaim Financial Tracker", layout="wide", page_icon="💰")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
.block-container { padding-top: 1.5rem; }

.kpi-card {
    background: white;
    border-radius: 12px;
    padding: 18px 22px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.07);
    border-left: 5px solid #1F3864;
    height: 100%;
}
.kpi-card.loss  { border-left-color: #e74c3c; }
.kpi-card.gain  { border-left-color: #27ae60; }
.kpi-card.warn  { border-left-color: #f39c12; }
.kpi-card.info  { border-left-color: #2980b9; }
.kpi-card.purple{ border-left-color: #8e44ad; }

.kpi-label { font-size: 11px; color: #888; font-weight: 600; text-transform: uppercase; letter-spacing: 0.6px; margin-bottom: 4px; }
.kpi-value { font-size: 22px; font-weight: 700; color: #1F3864; }
.kpi-value.red    { color: #e74c3c; }
.kpi-value.green  { color: #27ae60; }
.kpi-value.orange { color: #f39c12; }
.kpi-sub { font-size: 11px; color: #aaa; margin-top: 2px; }

.section-hdr {
    font-size: 15px; font-weight: 700; color: #1F3864;
    border-bottom: 2px solid #e8edf3;
    padding-bottom: 6px; margin: 20px 0 12px 0;
}
.rpa-card {
    background: white; border-radius: 10px;
    padding: 14px 18px; margin-bottom: 8px;
    box-shadow: 0 1px 4px rgba(0,0,0,0.08);
    border-left: 4px solid #1F3864;
    cursor: pointer;
}
.rpa-card:hover { border-left-color: #ED7D31; }
.tag {
    display:inline-block; padding:2px 10px; border-radius:20px;
    font-size:11px; font-weight:600;
}
.tag-pending  { background:#fff3cd; color:#856404; }
.tag-paid     { background:#d1e7dd; color:#0a3622; }
.tag-denied   { background:#f8d7da; color:#842029; }
</style>
""", unsafe_allow_html=True)

# ── AWS ─────────────────────────────────────────────────────────────────
BUCKET = "emc-rcm-storage-2026"
KLAIM_PREFIX   = "klaim-data/"
BILLING_PREFIX = "billing-data/"

@st.cache_resource
def get_s3():
    return boto3.client(
        "s3",
        aws_access_key_id=st.secrets["AWS_ACCESS_KEY_ID"],
        aws_secret_access_key=st.secrets["AWS_SECRET_ACCESS_KEY"],
        region_name=st.secrets.get("AWS_DEFAULT_REGION", "me-south-1")
    )

def list_s3_files(prefix):
    s3 = get_s3()
    resp = s3.list_objects_v2(Bucket=BUCKET, Prefix=prefix)
    return [o["Key"] for o in resp.get("Contents", [])]

def read_s3_csv(key):
    s3 = get_s3()
    obj = s3.get_object(Bucket=BUCKET, Key=key)
    return pd.read_csv(io.BytesIO(obj["Body"].read()))

def read_s3_excel(key):
    s3 = get_s3()
    obj = s3.get_object(Bucket=BUCKET, Key=key)
    df = pd.read_excel(io.BytesIO(obj["Body"].read()))
    df.columns = [c.strip() for c in df.columns]
    return df

def upload_s3(key, data_bytes, content_type="application/octet-stream"):
    s3 = get_s3()
    s3.put_object(Bucket=BUCKET, Key=key, Body=data_bytes, ContentType=content_type)

# ── Extract RPA ref from filename ────────────────────────────────────────
def extract_rpa_ref(filename):
    """Extract RPA reference like 2603_008173_EXCELLENT_0145 from filename"""
    base = filename.split("/")[-1]
    # Try pattern NNNN_NNNNNN_WORD_NNNN
    m = re.search(r'(\d{4}_\d{6}_[A-Z]+_\d{4})', base, re.IGNORECASE)
    if m:
        return m.group(1).upper()
    # Fallback: strip extension
    return re.sub(r'\.(csv|xlsx)$', '', base, flags=re.IGNORECASE)

def rpa_ref_to_slash(ref):
    """Convert 2603_008173_EXCELLENT_0145 -> 2603/008173/EXCELLENT/0145"""
    return ref.replace("_", "/")

# ── Financial calculations ────────────────────────────────────────────────
def calc_financials(klaim_df):
    """Compute key financial columns from Klaim file"""
    df = klaim_df.copy()
    df["Claim net"]                   = pd.to_numeric(df["Claim net"], errors="coerce").fillna(0)
    df["Paid by insurance"]           = pd.to_numeric(df["Paid by insurance"], errors="coerce").fillna(0)
    df["Denied by insurance"]         = pd.to_numeric(df["Denied by insurance"], errors="coerce").fillna(0)
    df["Pending insurance response"]  = pd.to_numeric(df["Pending insurance response"], errors="coerce").fillna(0)
    df["Pending reconciliation"]      = pd.to_numeric(df["Pending reconciliation"], errors="coerce").fillna(0)
    return df

def merge_with_billing(klaim_df, billing_df):
    """Merge Klaim claims with billing summary on Claim ID / UniqueID"""
    billing_cols = ["UniqueID","Insurance","DepName","DocName","SubDate","Status",
                    "SubInsShare","Balance","Month","Year","Facility Name"]
    billing_cols = [c for c in billing_cols if c in billing_df.columns]
    b = billing_df[billing_cols].copy()
    b = b.rename(columns={
        "UniqueID": "Claim ID",
        "Insurance": "Billing Insurance",
        "Status": "Billing Status",
        "SubInsShare": "Billed Amount",
        "SubDate": "Sub Date",
    })
    merged = klaim_df.merge(b, on="Claim ID", how="left")
    return merged

# ── KPI card helper ───────────────────────────────────────────────────────
def kpi(col, label, value, style="", sub=""):
    with col:
        st.markdown(f"""
        <div class="kpi-card {style}">
            <div class="kpi-label">{label}</div>
            <div class="kpi-value {'red' if style=='loss' else 'green' if style=='gain' else 'orange' if style=='warn' else ''}">{value}</div>
            <div class="kpi-sub">{sub}</div>
        </div>""", unsafe_allow_html=True)

def fmt(n): return f"AED {n:,.0f}"
def pct(n): return f"{n:.1f}%"

# ════════════════════════════════════════════════════════════════════════
# UPLOAD SECTION (sidebar)
# ════════════════════════════════════════════════════════════════════════
with st.sidebar:
    st.markdown("### 💰 Klaim Financial Tracker")
    st.markdown("---")
    st.markdown("#### 📤 Upload New RPA Files")

    facility_up = st.selectbox("Facility", ["EXCELLENT", "EASYHEALTHMC", "PHARMACY"], key="up_fac")
    klaim_file  = st.file_uploader("Klaim CSV file", type=["csv"], key="klaim_up")
    billing_sum = st.file_uploader("Billing Summary Excel", type=["xlsx","xls"], key="bill_sum_up")
    billing_det = st.file_uploader("Billing Detail Excel", type=["xlsx","xls"], key="bill_det_up")

    if st.button("⬆️ Upload to S3", use_container_width=True):
        if not klaim_file:
            st.error("Please upload at least the Klaim CSV file.")
        else:
            try:
                # Extract RPA ref from klaim filename
                rpa_ref = extract_rpa_ref(klaim_file.name)
                fac = facility_up

                # Upload Klaim file
                k_key = f"{KLAIM_PREFIX}{fac}/{rpa_ref}.csv"
                upload_s3(k_key, klaim_file.read(), "text/csv")

                if billing_sum:
                    bs_key = f"{BILLING_PREFIX}{fac}/summary/{rpa_ref}.xlsx"
                    upload_s3(bs_key, billing_sum.read())

                if billing_det:
                    bd_key = f"{BILLING_PREFIX}{fac}/detail/{rpa_ref}.xlsx"
                    upload_s3(bd_key, billing_det.read())

                st.success(f"✅ Uploaded RPA `{rpa_ref}`")
                st.cache_data.clear()
            except Exception as e:
                st.error(f"Upload failed: {e}")

    st.markdown("---")
    st.markdown("#### 🔍 Filter View")
    selected_facility = st.selectbox("View Facility", ["All", "EXCELLENT", "EASYHEALTHMC", "PHARMACY"], key="view_fac")
    selected_layer    = st.radio("Layer", ["📊 Overall", "📋 RPA Level", "🔬 Claim Detail"], key="layer")

# ════════════════════════════════════════════════════════════════════════
# LOAD ALL KLAIM DATA
# ════════════════════════════════════════════════════════════════════════
@st.cache_data(ttl=300)
def load_all_klaim():
    try:
        keys = list_s3_files(KLAIM_PREFIX)
        keys = [k for k in keys if k.endswith(".csv")]
        frames = []
        for key in keys:
            df = read_s3_csv(key)
            df = calc_financials(df)
            # Extract facility and RPA ref from path
            parts = key.replace(KLAIM_PREFIX, "").split("/")
            df["_facility"] = parts[0] if len(parts) > 1 else "UNKNOWN"
            df["_rpa_ref"]  = extract_rpa_ref(key)
            df["_s3_key"]   = key
            frames.append(df)
        if frames:
            return pd.concat(frames, ignore_index=True)
        return pd.DataFrame()
    except Exception as e:
        st.error(f"Error loading data: {e}")
        return pd.DataFrame()

@st.cache_data(ttl=300)
def load_billing_summary(facility, rpa_ref):
    key = f"{BILLING_PREFIX}{facility}/summary/{rpa_ref}.xlsx"
    try:
        return read_s3_excel(key)
    except:
        return None

# ── Header ───────────────────────────────────────────────────────────────
st.markdown("""
<div style="background:linear-gradient(135deg,#1F3864 0%,#2c5282 100%);
            padding:20px 28px;border-radius:14px;margin-bottom:20px;
            display:flex;align-items:center;gap:12px;">
    <div>
        <h1 style="color:white;margin:0;font-size:24px;font-weight:700;">💰 Klaim Financial Tracker</h1>
        <p style="color:#a0bcd8;margin:4px 0 0 0;font-size:13px;">
            Track your financial exposure — discounts, rejections, and net position across all RPA runs
        </p>
    </div>
</div>
""", unsafe_allow_html=True)

all_data = load_all_klaim()

if all_data.empty:
    st.info("📭 No data loaded yet. Upload your first Klaim CSV and billing files using the sidebar.")
    st.stop()

# Apply facility filter
if selected_facility != "All":
    view_data = all_data[all_data["_facility"] == selected_facility].copy()
else:
    view_data = all_data.copy()

if view_data.empty:
    st.warning(f"No data found for facility: {selected_facility}")
    st.stop()

# ════════════════════════════════════════════════════════════════════════
# LAYER 1 — OVERALL
# ════════════════════════════════════════════════════════════════════════
if "Overall" in selected_layer:
    st.markdown('<div class="section-hdr">📊 Overall Exposure to Klaim</div>', unsafe_allow_html=True)

    total_claims   = len(view_data)
    total_value    = view_data["Claim net"].sum()
    total_paid     = view_data["Paid by insurance"].sum()
    total_denied   = view_data["Denied by insurance"].sum()
    total_pending  = view_data["Pending insurance response"].sum() + view_data["Pending reconciliation"].sum()
    total_rpas     = view_data["_rpa_ref"].nunique()

    # Discount loss = what Klaim kept (Claim net - what insurance eventually pays back)
    # Since funds_received = sale_price - fees, and sale_price = claim_net * (1 - discount%)
    # We approximate discount as claims still pending + difference on paid
    # Best approximation from available data:
    recovered      = total_paid  # insurance paid Klaim (Klaim passes this to you minus their cut already taken at sale)
    denial_loss    = total_denied
    pending_amt    = total_pending

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    kpi(c1, "Total RPA Runs",       f"{total_rpas}",       "info",   f"{total_claims:,} claims")
    kpi(c2, "Total Claim Value",     fmt(total_value),      "",       "Gross sent to Klaim")
    kpi(c3, "Paid by Insurance",     fmt(total_paid),       "gain",   f"{total_paid/total_value*100:.1f}% of total" if total_value else "")
    kpi(c4, "Denied by Insurance",   fmt(total_denied),     "loss",   f"{total_denied/total_value*100:.1f}% of total" if total_value else "")
    kpi(c5, "Pending Response",      fmt(total_pending),    "warn",   "Awaiting insurer decision")
    kpi(c6, "Pending Reconciliation",fmt(view_data["Pending reconciliation"].sum()), "purple", "Klaim processing")

    st.markdown("")

    # Breakdown by facility
    st.markdown('<div class="section-hdr">🏥 Breakdown by Facility</div>', unsafe_allow_html=True)
    fac_grp = view_data.groupby("_facility").agg(
        RPAs        =("_rpa_ref","nunique"),
        Claims      =("Claim ID","count"),
        Total_Value =("Claim net","sum"),
        Paid        =("Paid by insurance","sum"),
        Denied      =("Denied by insurance","sum"),
        Pending     =("Pending insurance response","sum"),
    ).reset_index()
    fac_grp["Denial Rate"] = (fac_grp["Denied"] / fac_grp["Total_Value"] * 100).round(1).astype(str) + "%"
    fac_grp.columns = ["Facility","RPAs","Claims","Total Value (AED)","Paid (AED)","Denied (AED)","Pending (AED)","Denial Rate"]
    for col in ["Total Value (AED)","Paid (AED)","Denied (AED)","Pending (AED)"]:
        fac_grp[col] = fac_grp[col].apply(lambda x: f"{x:,.0f}")
    st.dataframe(fac_grp, use_container_width=True, hide_index=True)

    # Breakdown by Payer
    st.markdown('<div class="section-hdr">🏦 Breakdown by Payer / Insurer</div>', unsafe_allow_html=True)
    pay_grp = view_data.groupby("Payer").agg(
        Claims      =("Claim ID","count"),
        Total_Value =("Claim net","sum"),
        Paid        =("Paid by insurance","sum"),
        Denied      =("Denied by insurance","sum"),
        Pending     =("Pending insurance response","sum"),
    ).reset_index().sort_values("Total_Value", ascending=False)
    pay_grp["Denial Rate"] = (pay_grp["Denied"] / pay_grp["Total_Value"] * 100).round(1).astype(str) + "%"
    pay_grp.columns = ["Payer","Claims","Total Value (AED)","Paid (AED)","Denied (AED)","Pending (AED)","Denial Rate"]
    for col in ["Total Value (AED)","Paid (AED)","Denied (AED)","Pending (AED)"]:
        pay_grp[col] = pay_grp[col].apply(lambda x: f"{x:,.0f}")
    st.dataframe(pay_grp, use_container_width=True, hide_index=True)

    # Monthly trend
    st.markdown('<div class="section-hdr">📅 Monthly Trend</div>', unsafe_allow_html=True)
    if "Deal date" in view_data.columns:
        view_data["_month"] = pd.to_datetime(view_data["Deal date"], errors="coerce").dt.to_period("M").astype(str)
        trend = view_data.groupby("_month").agg(
            Claims=("Claim ID","count"),
            Value =("Claim net","sum"),
            Paid  =("Paid by insurance","sum"),
            Denied=("Denied by insurance","sum"),
        ).reset_index()
        trend.columns = ["Month","Claims","Claim Value (AED)","Paid (AED)","Denied (AED)"]
        st.dataframe(trend, use_container_width=True, hide_index=True)

# ════════════════════════════════════════════════════════════════════════
# LAYER 2 — RPA LEVEL
# ════════════════════════════════════════════════════════════════════════
elif "RPA" in selected_layer:
    st.markdown('<div class="section-hdr">📋 RPA Runs</div>', unsafe_allow_html=True)

    # Filters
    fc1, fc2, fc3 = st.columns(3)
    if "Deal date" in view_data.columns:
        view_data["_deal_date"] = pd.to_datetime(view_data["Deal date"], errors="coerce")
        months = ["All"] + sorted(view_data["_deal_date"].dt.to_period("M").astype(str).dropna().unique().tolist(), reverse=True)
        sel_month = fc1.selectbox("Month", months)
        if sel_month != "All":
            view_data = view_data[view_data["_deal_date"].dt.to_period("M").astype(str) == sel_month]

    search = fc2.text_input("Search RPA reference", placeholder="e.g. 008173")

    # Build RPA summary table
    rpa_grp = view_data.groupby(["_rpa_ref","_facility"]).agg(
        Deal_Date   =("Deal date","first"),
        Claims      =("Claim ID","count"),
        Total_Value =("Claim net","sum"),
        Paid        =("Paid by insurance","sum"),
        Denied      =("Denied by insurance","sum"),
        Pending     =("Pending insurance response","sum"),
        Payers      =("Payer", lambda x: ", ".join(sorted(x.unique()))),
    ).reset_index().sort_values("Deal_Date", ascending=False)

    if search:
        rpa_grp = rpa_grp[rpa_grp["_rpa_ref"].str.contains(search, case=False, na=False)]

    st.markdown(f"**{len(rpa_grp)} RPA run(s) found**")

    sel_rpa = None
    for _, row in rpa_grp.iterrows():
        denial_pct = row["Denied"] / row["Total_Value"] * 100 if row["Total_Value"] else 0
        paid_pct   = row["Paid"]   / row["Total_Value"] * 100 if row["Total_Value"] else 0
        ref_display = rpa_ref_to_slash(row["_rpa_ref"])
        date_str = str(row["Deal_Date"])[:10] if pd.notna(row["Deal_Date"]) else "—"

        col_a, col_b = st.columns([5,1])
        with col_a:
            st.markdown(f"""
            <div class="rpa-card">
                <div style="display:flex;justify-content:space-between;align-items:center;">
                    <div>
                        <span style="font-weight:700;color:#1F3864;font-size:14px;">{ref_display}</span>
                        <span style="margin-left:10px;font-size:12px;color:#888;">{row['_facility']} · {date_str}</span>
                    </div>
                    <div style="text-align:right;font-size:13px;">
                        <b>AED {row['Total_Value']:,.0f}</b> &nbsp;|&nbsp;
                        {row['Claims']} claims &nbsp;|&nbsp;
                        <span style="color:#27ae60;">Paid: {paid_pct:.1f}%</span> &nbsp;
                        <span style="color:#e74c3c;">Denied: {denial_pct:.1f}%</span>
                    </div>
                </div>
                <div style="font-size:11px;color:#aaa;margin-top:4px;">Payers: {row['Payers']}</div>
            </div>
            """, unsafe_allow_html=True)
        with col_b:
            if st.button("🔍 Drill In", key=f"drill_{row['_rpa_ref']}"):
                st.session_state["drill_rpa"]      = row["_rpa_ref"]
                st.session_state["drill_facility"] = row["_facility"]
                st.rerun()

    # ── Drill-in modal ────────────────────────────────────────────────
    if "drill_rpa" in st.session_state:
        rpa  = st.session_state["drill_rpa"]
        fac  = st.session_state["drill_facility"]
        rpa_data = view_data[view_data["_rpa_ref"] == rpa].copy()

        st.markdown("---")
        st.markdown(f'<div class="section-hdr">🔍 RPA Detail: {rpa_ref_to_slash(rpa)}</div>', unsafe_allow_html=True)

        # Try load billing summary for this RPA
        billing = load_billing_summary(fac, rpa)
        if billing is not None:
            rpa_data = merge_with_billing(rpa_data, billing)

        tv = rpa_data["Claim net"].sum()
        c1,c2,c3,c4,c5 = st.columns(5)
        kpi(c1, "Claims",          f"{len(rpa_data):,}",                  "info")
        kpi(c2, "Total Value",     fmt(tv),                                "")
        kpi(c3, "Paid",            fmt(rpa_data["Paid by insurance"].sum()),"gain", f"{rpa_data['Paid by insurance'].sum()/tv*100:.1f}%" if tv else "")
        kpi(c4, "Denied",          fmt(rpa_data["Denied by insurance"].sum()),"loss", f"{rpa_data['Denied by insurance'].sum()/tv*100:.1f}%" if tv else "")
        kpi(c5, "Pending",         fmt(rpa_data["Pending insurance response"].sum()),"warn")

        st.markdown("")

        # Payer breakdown
        pb = rpa_data.groupby("Payer").agg(
            Claims=("Claim ID","count"),
            Value =("Claim net","sum"),
            Paid  =("Paid by insurance","sum"),
            Denied=("Denied by insurance","sum"),
            Pending=("Pending insurance response","sum"),
        ).reset_index()
        for col in ["Value","Paid","Denied","Pending"]:
            pb[col] = pb[col].apply(lambda x: f"{x:,.2f}")
        pb.columns = ["Payer","Claims","Claim Net (AED)","Paid (AED)","Denied (AED)","Pending (AED)"]
        st.dataframe(pb, use_container_width=True, hide_index=True)

        if st.button("❌ Close Detail"):
            del st.session_state["drill_rpa"]
            del st.session_state["drill_facility"]
            st.rerun()

# ════════════════════════════════════════════════════════════════════════
# LAYER 3 — CLAIM DETAIL
# ════════════════════════════════════════════════════════════════════════
elif "Claim" in selected_layer:
    st.markdown('<div class="section-hdr">🔬 Claim-Level Detail</div>', unsafe_allow_html=True)

    # RPA selector
    rpa_options = sorted(view_data["_rpa_ref"].unique().tolist(), reverse=True)
    rpa_labels  = {r: rpa_ref_to_slash(r) for r in rpa_options}
    sel_rpa_key = st.selectbox("Select RPA Run", rpa_options, format_func=lambda x: rpa_labels[x])

    sel_fac = view_data[view_data["_rpa_ref"] == sel_rpa_key]["_facility"].iloc[0]
    rpa_claims = view_data[view_data["_rpa_ref"] == sel_rpa_key].copy()

    # Try load billing
    billing = load_billing_summary(sel_fac, sel_rpa_key)
    if billing is not None:
        rpa_claims = merge_with_billing(rpa_claims, billing)
        st.success(f"✅ Billing data matched — {len(rpa_claims)} claims reconciled")
    else:
        st.info("ℹ️ No billing summary file found for this RPA. Upload one via the sidebar.")

    # Status filter
    statuses = ["All"] + rpa_claims["Status"].dropna().unique().tolist()
    sel_status = st.selectbox("Filter by Status", statuses)
    if sel_status != "All":
        rpa_claims = rpa_claims[rpa_claims["Status"] == sel_status]

    payer_filter = ["All"] + sorted(rpa_claims["Payer"].dropna().unique().tolist())
    sel_payer = st.selectbox("Filter by Payer", payer_filter)
    if sel_payer != "All":
        rpa_claims = rpa_claims[rpa_claims["Payer"] == sel_payer]

    # KPIs
    tv = rpa_claims["Claim net"].sum()
    c1,c2,c3,c4,c5 = st.columns(5)
    kpi(c1, "Claims Shown",    f"{len(rpa_claims):,}",                      "info")
    kpi(c2, "Claim Net",       fmt(tv),                                      "")
    kpi(c3, "Paid",            fmt(rpa_claims["Paid by insurance"].sum()),    "gain")
    kpi(c4, "Denied",          fmt(rpa_claims["Denied by insurance"].sum()),  "loss")
    kpi(c5, "Pending",         fmt(rpa_claims["Pending insurance response"].sum()), "warn")
    st.markdown("")

    # Build display table
    display_cols = ["Claim ID","Payer","Claim net","Status",
                    "Paid by insurance","Denied by insurance",
                    "Pending insurance response","Pending reconciliation",
                    "Submission Date","Encounter Date"]
    if "Billing Insurance" in rpa_claims.columns:
        display_cols = ["Claim ID","Payer","Billing Insurance","Claim net","Status",
                        "Paid by insurance","Denied by insurance",
                        "Pending insurance response","DepName","DocName",
                        "Sub Date","Submission Date"]

    disp = rpa_claims[[c for c in display_cols if c in rpa_claims.columns]].copy()

    # Color rows by status
    def color_row(row):
        s = str(row.get("Status",""))
        if "Denied" in s or "denied" in s.lower():
            return ["background-color:#fff0f0"]*len(row)
        elif "Paid" in s or "paid" in s.lower():
            return ["background-color:#f0fff4"]*len(row)
        elif "Pending" in s:
            return ["background-color:#fffbf0"]*len(row)
        return [""]*len(row)

    styled = disp.style.apply(color_row, axis=1)
    st.dataframe(styled, use_container_width=True, hide_index=True, height=500)

    # Download
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        disp.to_excel(writer, index=False, sheet_name="Claim Detail")
    buf.seek(0)
    st.download_button(
        "⬇️ Download This RPA Claims as Excel",
        data=buf,
        file_name=f"Klaim_{sel_rpa_key}_claims.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
