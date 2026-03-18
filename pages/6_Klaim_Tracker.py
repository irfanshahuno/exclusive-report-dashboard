import streamlit as st
import pandas as pd
import boto3
import io
import re
import pdfplumber
from collections import defaultdict

st.set_page_config(page_title="Klaim Financial Tracker", layout="wide", page_icon="💰")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
.block-container { padding-top: 1.5rem; }
.kpi-card {
    background: white; border-radius: 12px; padding: 18px 22px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.07);
    border-left: 5px solid #1F3864; height: 100%;
}
.kpi-card.loss   { border-left-color: #e74c3c; }
.kpi-card.gain   { border-left-color: #27ae60; }
.kpi-card.warn   { border-left-color: #f39c12; }
.kpi-card.info   { border-left-color: #2980b9; }
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
</style>
""", unsafe_allow_html=True)

BUCKET         = "emc-rcm-storage-2026"
KLAIM_PREFIX   = "klaim-pdfs/"
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

def read_s3_bytes(key):
    s3 = get_s3()
    return s3.get_object(Bucket=BUCKET, Key=key)["Body"].read()

def upload_s3(key, data, ctype="application/octet-stream"):
    get_s3().put_object(Bucket=BUCKET, Key=key, Body=data, ContentType=ctype)

INSURERS = ['NEXTCARE-AD','DAMAN-AD','FMC-AD','DUBAI-INSCO-AD',
            'ORIENT-AD','QATAR-AD','TAKAFUL-EMARAT-AD']

def parse_klaim_pdf(pdf_bytes):
    claims = []
    meta   = {}
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        p1_text = pdf.pages[0].extract_text() or ""
        ref = re.search(r'(\d{4}/\d{6}/\w+/\d{4})', p1_text)
        meta["rpa_ref"] = ref.group(1) if ref else "UNKNOWN"
        dt = re.search(r'Purchase Date:\s*(\d+ \w+ \d{4})', p1_text)
        meta["deal_date"] = dt.group(1) if dt else ""
        fac = re.search(r'as\s+(EXCELLENT|EASYHEALTHMC|PHARMACY)', p1_text)
        meta["facility"] = fac.group(1) if fac else "EXCELLENT"
        fee = re.search(r'Security registration fee\s+AED\s+([\d,]+)', p1_text)
        meta["fees"] = float(fee.group(1).replace(",","")) if fee else 0.0

        for page in pdf.pages:
            words = page.extract_words()
            rows  = defaultdict(list)
            for w in words:
                rows[round(w['top']/4)*4].append(w)
            for y in sorted(rows):
                line = ' '.join(w['text'] for w in sorted(rows[y], key=lambda w: w['x0']))
                cm   = re.search(r'(MF\d+[-\w]+)', line)
                if not cm:
                    continue
                nums = re.findall(r'\d+\.\d+', line)
                if len(nums) < 3:
                    continue
                ins = next((i for i in INSURERS if i in line), "UNKNOWN")
                dm  = re.search(r'(\d+ \w+ \d{4})', line)
                claims.append({
                    "Claim ID":       cm.group(1),
                    "Insurer":        ins,
                    "Sub Date":       dm.group(1) if dm else "",
                    "Claim Value":    float(nums[0]),
                    "Discount %":     float(nums[1]),
                    "Purchase Price": float(nums[2]),
                    "Discount Loss":  round(float(nums[0]) - float(nums[2]), 2),
                })

    df = pd.DataFrame(claims).drop_duplicates(subset=["Claim ID"])
    meta.update({
        "total_claim_value":    round(df["Claim Value"].sum(), 2),
        "total_purchase_price": round(df["Purchase Price"].sum(), 2),
        "total_discount_loss":  round(df["Discount Loss"].sum(), 2),
        "num_claims":           len(df),
    })
    return df, meta

def rpa_slug(ref):     return ref.replace("/","_")
def rpa_display(slug): return slug.replace("_","/")

@st.cache_data(ttl=300)
def load_all_rpas():
    try:
        keys = [k for k in list_s3_files(KLAIM_PREFIX) if k.lower().endswith(".pdf")]
        all_claims, all_meta = [], []
        for key in keys:
            df, meta = parse_klaim_pdf(read_s3_bytes(key))
            slug = re.sub(r'\.pdf$','', key.split("/")[-1], flags=re.I)
            df["_rpa_slug"] = slug
            df["_facility"] = meta.get("facility","UNKNOWN")
            all_claims.append(df)
            all_meta.append({**meta, "_rpa_slug": slug})
        return (pd.concat(all_claims, ignore_index=True) if all_claims else pd.DataFrame(),
                pd.DataFrame(all_meta) if all_meta else pd.DataFrame())
    except Exception as e:
        st.error(f"Load error: {e}")
        return pd.DataFrame(), pd.DataFrame()

def load_billing(facility, slug):
    try:
        data = read_s3_bytes(f"{BILLING_PREFIX}{facility}/summary/{slug}.xlsx")
        df   = pd.read_excel(io.BytesIO(data))
        df.columns = [c.strip() for c in df.columns]
        return df
    except:
        return None

def kpi(col, label, value, style="", sub=""):
    cc = {"loss":"red","gain":"green","warn":"orange"}.get(style,"")
    with col:
        st.markdown(f"""<div class="kpi-card {style}">
            <div class="kpi-label">{label}</div>
            <div class="kpi-value {cc}">{value}</div>
            <div class="kpi-sub">{sub}</div></div>""", unsafe_allow_html=True)

def fmt(n): return f"AED {n:,.0f}"

# ── Sidebar ───────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### 💰 Klaim Tracker")
    st.markdown("---")
    st.markdown("#### 📤 Upload RPA")
    fac_up  = st.selectbox("Facility", ["EXCELLENT","EASYHEALTHMC","PHARMACY"], key="uf")
    pdf_up  = st.file_uploader("Klaim PDF", type=["pdf"])
    bill_up = st.file_uploader("Billing Summary Excel (optional)", type=["xlsx","xls"])

    if st.button("⬆️ Upload to S3", use_container_width=True):
        if not pdf_up:
            st.error("Upload the PDF first.")
        else:
            with st.spinner("Parsing PDF..."):
                try:
                    pdf_b = pdf_up.read()
                    _, meta = parse_klaim_pdf(pdf_b)
                    slug    = rpa_slug(meta["rpa_ref"])
                    upload_s3(f"{KLAIM_PREFIX}{fac_up}/{slug}.pdf", pdf_b, "application/pdf")
                    if bill_up:
                        upload_s3(f"{BILLING_PREFIX}{fac_up}/summary/{slug}.xlsx", bill_up.read())
                    st.success(f"✅ `{rpa_display(slug)}`\n\n"
                               f"{meta['num_claims']} claims | "
                               f"Value: AED {meta['total_claim_value']:,.0f} | "
                               f"Lost: AED {meta['total_discount_loss']:,.0f}")
                    st.cache_data.clear()
                except Exception as e:
                    st.error(f"Failed: {e}")

    st.markdown("---")
    sel_fac   = st.selectbox("View Facility", ["All","EXCELLENT","EASYHEALTHMC","PHARMACY"], key="vf")
    sel_layer = st.radio("Layer", ["📊 Overall","📋 RPA Level","🔬 Claim Detail"])

# ── Header ────────────────────────────────────────────────────────────────
st.markdown("""
<div style="background:linear-gradient(135deg,#1F3864,#2c5282);
    padding:20px 28px;border-radius:14px;margin-bottom:20px;">
  <h1 style="color:white;margin:0;font-size:24px;font-weight:700;">💰 Klaim Financial Tracker</h1>
  <p style="color:#a0bcd8;margin:4px 0 0 0;font-size:13px;">
    Upload Klaim PDF → auto-extract → track discount loss, fees &amp; net exposure
  </p>
</div>""", unsafe_allow_html=True)

claims_df, meta_df = load_all_rpas()

if claims_df.empty:
    st.info("📭 No data yet. Upload a Klaim PDF using the sidebar.")
    st.stop()

if sel_fac != "All":
    claims_df = claims_df[claims_df["_facility"] == sel_fac]
    if not meta_df.empty and "facility" in meta_df.columns:
        meta_df = meta_df[meta_df["facility"] == sel_fac]

if claims_df.empty:
    st.warning(f"No data for {sel_fac}.")
    st.stop()

# ════════ LAYER 1 — OVERALL ══════════════════════════════════════════════
if "Overall" in sel_layer:
    st.markdown('<div class="section-hdr">📊 Overall Exposure</div>', unsafe_allow_html=True)
    tv   = claims_df["Claim Value"].sum()
    tp   = claims_df["Purchase Price"].sum()
    tl   = claims_df["Discount Loss"].sum()
    tf   = meta_df["fees"].sum() if not meta_df.empty and "fees" in meta_df.columns else 0
    rpas = claims_df["_rpa_slug"].nunique()

    c1,c2,c3,c4,c5,c6 = st.columns(6)
    kpi(c1,"RPA Runs",         f"{rpas}",    "info",  f"{len(claims_df):,} claims")
    kpi(c2,"Total Claim Value",fmt(tv),       "",      "Gross sold to Klaim")
    kpi(c3,"Total Received",   fmt(tp),       "gain",  f"{tp/tv*100:.2f}% of value" if tv else "")
    kpi(c4,"Discount Loss",    fmt(tl),       "loss",  f"{tl/tv*100:.2f}% of value" if tv else "")
    kpi(c5,"Total Fees",       fmt(tf),       "warn",  "Security reg fees")
    kpi(c6,"Net Cost to You",  fmt(tl+tf),    "loss",  "Discount + Fees")
    st.markdown("")

    st.markdown('<div class="section-hdr">🏦 By Insurer</div>', unsafe_allow_html=True)
    ig = claims_df.groupby("Insurer").agg(
        Claims=("Claim ID","count"),
        Value =("Claim Value","sum"),
        Rcvd  =("Purchase Price","sum"),
        Loss  =("Discount Loss","sum"),
        AvgD  =("Discount %","mean"),
    ).reset_index().sort_values("Value", ascending=False)
    ig["Loss%"] = (ig["Loss"]/ig["Value"]*100).round(2).astype(str)+"%"
    ig["AvgD"]  = ig["AvgD"].round(2).astype(str)+"%"
    for c in ["Value","Rcvd","Loss"]:
        ig[c] = ig[c].apply(lambda x: f"{x:,.2f}")
    ig.columns = ["Insurer","Claims","Claim Value (AED)","Received (AED)",
                  "Discount Loss (AED)","Avg Discount %","Loss %"]
    st.dataframe(ig, use_container_width=True, hide_index=True)

    if not meta_df.empty and "deal_date" in meta_df.columns:
        st.markdown('<div class="section-hdr">📅 All RPA Runs</div>', unsafe_allow_html=True)
        h = meta_df[["rpa_ref","deal_date","facility","num_claims",
                     "total_claim_value","total_purchase_price",
                     "total_discount_loss","fees"]].copy()
        h["net_cost"] = h["total_discount_loss"] + h["fees"]
        h = h.sort_values("deal_date", ascending=False)
        for c in ["total_claim_value","total_purchase_price","total_discount_loss","fees","net_cost"]:
            h[c] = h[c].apply(lambda x: f"{x:,.2f}")
        h.columns = ["RPA Ref","Date","Facility","Claims","Claim Value",
                     "Received","Discount Loss","Fees","Net Cost"]
        st.dataframe(h, use_container_width=True, hide_index=True)

# ════════ LAYER 2 — RPA LEVEL ════════════════════════════════════════════
elif "RPA" in sel_layer:
    st.markdown('<div class="section-hdr">📋 RPA Runs</div>', unsafe_allow_html=True)
    search = st.text_input("Search", placeholder="e.g. 008173")

    rg = claims_df.groupby(["_rpa_slug","_facility"]).agg(
        Claims=("Claim ID","count"),
        Value =("Claim Value","sum"),
        Rcvd  =("Purchase Price","sum"),
        Loss  =("Discount Loss","sum"),
        AvgD  =("Discount %","mean"),
        Ins   =("Insurer", lambda x:", ".join(sorted(x.unique()))),
    ).reset_index()

    if not meta_df.empty and "_rpa_slug" in meta_df.columns:
        rg = rg.merge(meta_df[["_rpa_slug","deal_date","fees"]], on="_rpa_slug", how="left")
    else:
        rg["deal_date"] = ""; rg["fees"] = 0

    rg = rg.sort_values("deal_date", ascending=False)
    if search:
        rg = rg[rg["_rpa_slug"].str.contains(search, case=False, na=False)]

    st.markdown(f"**{len(rg)} run(s)**")
    for _, row in rg.iterrows():
        ca, cb = st.columns([5,1])
        with ca:
            st.markdown(f"""
            <div style="background:white;border-radius:10px;padding:14px 18px;
                margin-bottom:8px;box-shadow:0 1px 4px rgba(0,0,0,0.08);
                border-left:4px solid #1F3864;">
              <div style="display:flex;justify-content:space-between;">
                <b style="color:#1F3864;">{rpa_display(row['_rpa_slug'])}</b>
                <span style="color:#888;font-size:12px;">{row['_facility']} · {str(row.get('deal_date',''))[:10]}</span>
              </div>
              <div style="font-size:13px;margin-top:6px;">
                <b>AED {row['Value']:,.0f}</b> &nbsp;·&nbsp;
                <span style="color:#27ae60;">Rcvd AED {row['Rcvd']:,.0f}</span> &nbsp;·&nbsp;
                <span style="color:#e74c3c;">Lost AED {row['Loss']:,.0f}</span> &nbsp;·&nbsp;
                <span style="color:#f39c12;">Fees AED {row['fees']:,.0f}</span>
              </div>
              <div style="font-size:11px;color:#aaa;margin-top:4px;">
                {row['Claims']} claims · {row['AvgD']:.2f}% avg discount · {row['Ins']}
              </div>
            </div>""", unsafe_allow_html=True)
        with cb:
            if st.button("🔍 Drill", key=f"d_{row['_rpa_slug']}"):
                st.session_state["drpa"] = row["_rpa_slug"]
                st.session_state["dfac"] = row["_facility"]
                st.rerun()

    if "drpa" in st.session_state:
        slug = st.session_state["drpa"]
        fac  = st.session_state["dfac"]
        rc   = claims_df[claims_df["_rpa_slug"]==slug].copy()
        rm   = meta_df[meta_df["_rpa_slug"]==slug].iloc[0] if not meta_df.empty and "_rpa_slug" in meta_df.columns and slug in meta_df["_rpa_slug"].values else {}
        st.markdown("---")
        st.markdown(f'<div class="section-hdr">🔍 {rpa_display(slug)}</div>', unsafe_allow_html=True)
        tv=rc["Claim Value"].sum(); tp=rc["Purchase Price"].sum(); tl=rc["Discount Loss"].sum()
        fees = float(rm.get("fees",0)) if hasattr(rm,"get") else 0
        c1,c2,c3,c4,c5 = st.columns(5)
        kpi(c1,"Claims",   f"{len(rc):,}", "info")
        kpi(c2,"Value",    fmt(tv),        "")
        kpi(c3,"Received", fmt(tp),        "gain", f"{tp/tv*100:.2f}%" if tv else "")
        kpi(c4,"Lost",     fmt(tl),        "loss", f"{tl/tv*100:.2f}%" if tv else "")
        kpi(c5,"Fees",     fmt(fees),      "warn")
        st.markdown("")
        ig2 = rc.groupby("Insurer").agg(
            Claims=("Claim ID","count"),
            Value =("Claim Value","sum"),
            Rcvd  =("Purchase Price","sum"),
            Loss  =("Discount Loss","sum"),
            AvgD  =("Discount %","mean"),
        ).reset_index()
        ig2["AvgD"] = ig2["AvgD"].round(2).astype(str)+"%"
        for c in ["Value","Rcvd","Loss"]:
            ig2[c] = ig2[c].apply(lambda x: f"{x:,.2f}")
        ig2.columns = ["Insurer","Claims","Claim Value","Received","Discount Loss","Avg Discount %"]
        st.dataframe(ig2, use_container_width=True, hide_index=True)
        if st.button("❌ Close"):
            del st.session_state["drpa"], st.session_state["dfac"]
            st.rerun()

# ════════ LAYER 3 — CLAIM DETAIL ═════════════════════════════════════════
else:
    st.markdown('<div class="section-hdr">🔬 Claim Detail</div>', unsafe_allow_html=True)
    slugs    = sorted(claims_df["_rpa_slug"].unique().tolist(), reverse=True)
    sel_slug = st.selectbox("Select RPA", slugs, format_func=rpa_display)
    fac      = claims_df[claims_df["_rpa_slug"]==sel_slug]["_facility"].iloc[0]
    rc       = claims_df[claims_df["_rpa_slug"]==sel_slug].copy()
    rm       = meta_df[meta_df["_rpa_slug"]==sel_slug].iloc[0] if not meta_df.empty and "_rpa_slug" in meta_df.columns and sel_slug in meta_df["_rpa_slug"].values else {}

    billing = load_billing(fac, sel_slug)
    if billing is not None:
        b = billing[[c for c in ["UniqueID","DepName","DocName","Status","Balance"] if c in billing.columns]]
        b = b.rename(columns={"UniqueID":"Claim ID","Status":"Billing Status"})
        rc = rc.merge(b, on="Claim ID", how="left")
        st.success("✅ Billing data matched")

    ins_opts = ["All"] + sorted(rc["Insurer"].dropna().unique().tolist())
    sel_ins  = st.selectbox("Filter by Insurer", ins_opts)
    if sel_ins != "All":
        rc = rc[rc["Insurer"]==sel_ins]

    tv=rc["Claim Value"].sum(); tp=rc["Purchase Price"].sum(); tl=rc["Discount Loss"].sum()
    fees = float(rm.get("fees",0)) if hasattr(rm,"get") else 0
    c1,c2,c3,c4,c5 = st.columns(5)
    kpi(c1,"Claims",   f"{len(rc):,}", "info")
    kpi(c2,"Value",    fmt(tv),        "")
    kpi(c3,"Received", fmt(tp),        "gain", f"{tp/tv*100:.2f}%" if tv else "")
    kpi(c4,"Lost",     fmt(tl),        "loss", f"{tl/tv*100:.2f}%" if tv else "")
    kpi(c5,"Fees",     fmt(fees),      "warn")
    st.markdown("")

    show = ["Claim ID","Insurer","Sub Date","Claim Value","Discount %","Purchase Price","Discount Loss"]
    if "Billing Status" in rc.columns: show += ["Billing Status","DepName","DocName"]
    if "Balance" in rc.columns:        show += ["Balance"]
    disp = rc[[c for c in show if c in rc.columns]].copy()
    disp["Discount %"] = disp["Discount %"].apply(lambda x: f"{x:.2f}%")
    for c in ["Claim Value","Purchase Price","Discount Loss"]:
        if c in disp.columns:
            disp[c] = disp[c].apply(lambda x: f"{x:,.2f}")

    st.dataframe(disp, use_container_width=True, hide_index=True, height=500)

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        rc[[c for c in show if c in rc.columns]].to_excel(w, index=False, sheet_name="Claims")
    buf.seek(0)
    st.download_button("⬇️ Download Excel", data=buf,
        file_name=f"Klaim_{sel_slug}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
