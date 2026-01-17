# pages/2_Rejection_Analysis.py

import boto3
import io
import hashlib
from datetime import datetime as dt
import pandas as pd
import streamlit as st
from botocore.exceptions import ClientError

# =====================================================
# CONFIG
# =====================================================
S3_BUCKET = "emc-rcm-storage-2026"
SOURCE_FILENAME = "source.xlsx"
YEARS = ["2024", "2025", "2026"]

# =====================================================
# S3
# =====================================================
def s3_client():
    return boto3.client("s3")

def s3_exists(bucket, key):
    try:
        s3_client().head_object(Bucket=bucket, Key=key)
        return True
    except ClientError:
        return False

def load_s3(bucket, key):
    return s3_client().get_object(Bucket=bucket, Key=key)["Body"].read()

# =====================================================
# REJECTION ENGINE (UNCHANGED LOGIC)
# =====================================================
def sha1_short(b: bytes):
    return hashlib.sha1(b).hexdigest()[:10]

def build_rejection(df):
    df.columns = df.columns.str.strip()

    num_cols = [
        "ActivityIns",
        "actRemitInsShare", "actResub1RemitInsShare",
        "actResub2RemitInsShare", "actResub3RemitInsShare",
        "TKBKAmountAct"
    ]
    for c in num_cols:
        if c not in df.columns:
            df[c] = 0
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)

    df["Paid"] = df[num_cols].sum(axis=1)

    if "DenialCode" not in df.columns:
        df["DenialCode"] = ""

    status = df.get("ActivityStatus", "").astype(str).str.lower()
    df["Insurance"] = df.get("Insurance", df.get("PayerName", "Unknown"))

    rejected = df[
        (df["Paid"] == 0) &
        (status == "rejected") &
        (df["DenialCode"].astype(str).str.strip() != "")
    ].copy()

    rejected["RejectedAmount"] = rejected["ActivityIns"]
    return rejected

# =====================================================
# UI CARD
# =====================================================
def kpi(title, value, sub=""):
    st.markdown(
        f"""
        <div style="
            background:#ffffff;
            padding:22px;
            border-radius:16px;
            border:1px solid #e6ecf5;
            box-shadow:0 2px 10px rgba(0,0,0,0.03);
        ">
            <div style="color:#6b7a99;font-size:14px">{title}</div>
            <div style="font-size:32px;font-weight:700;margin-top:6px">{value}</div>
            <div style="color:#9aa6bf;font-size:13px;margin-top:6px">{sub}</div>
        </div>
        """,
        unsafe_allow_html=True
    )

# =====================================================
# APP
# =====================================================
def run():

    st.markdown("## Rejection Analysis")
    st.caption("Rule: Paid = 0 AND ActivityStatus = rejected AND DenialCode not empty")

    # -------------------------------------------------
    # SESSION STORAGE
    # -------------------------------------------------
    if "rej_result" not in st.session_state:
        st.session_state.rej_result = None

    # -------------------------------------------------
    # LAYOUT
    # -------------------------------------------------
    left, right = st.columns([1.2, 4])

    # =======================
    # LEFT PANEL
    # =======================
    with left:
        st.subheader("Controls")

        center = st.selectbox("Center", ["excellent", "pharmacy", "easyhealth"])
        year = st.selectbox("Year", YEARS)

        s3_key = f"streamlit/{center}/{year}/{SOURCE_FILENAME}"

        if st.button("Generate Rejection Analysis", type="primary"):
            if not s3_exists(S3_BUCKET, s3_key):
                st.error("Source file not found in S3")
            else:
                with st.spinner("Processing rejection analysis..."):
                    raw = load_s3(S3_BUCKET, s3_key)
                    df = pd.read_excel(io.BytesIO(raw))
                    rej = build_rejection(df)

                    st.session_state.rej_result = {
                        "df": rej,
                        "sha": sha1_short(raw)
                    }

                st.success("Done ✅")

        if st.button("Clear Result"):
            st.session_state.rej_result = None
            st.experimental_rerun()

    # =======================
    # RIGHT PANEL
    # =======================
    with right:

        if st.session_state.rej_result is None:
            st.info("Generate rejection analysis to view KPIs.")
            return

        df = st.session_state.rej_result["df"]

        # KPIs
        total_rows = len(df)
        total_amt = df["RejectedAmount"].sum()

        by_ins = df.groupby("Insurance")["RejectedAmount"].sum().sort_values(ascending=False)
        top3_ins = by_ins.head(3)

        by_dx = (
            df.groupby(["Insurance", "DenialCode"])["RejectedAmount"]
            .sum()
            .sort_values(ascending=False)
            .head(3)
        )

        c1, c2, c3 = st.columns(3)
        with c1:
            kpi("Rejected Rows", f"{total_rows:,}", "Paid=0 + rejected + denial")
        with c2:
            kpi("Total Rejected Amount", f"AED {total_amt:,.2f}", "All insurers")
        with c3:
            kpi("Total Rejected Claims", f"{total_rows:,}", "Activities")

        st.markdown("### Top 3 Insurance by Rejected Amount")

        cols = st.columns(3)
        for i, (ins, amt) in enumerate(top3_ins.items()):
            with cols[i]:
                kpi(ins, f"AED {amt:,.2f}")

        st.markdown("### Top 3 Denial (Insurance + Code)")

        cols = st.columns(3)
        for i, ((ins, code), amt) in enumerate(by_dx.items()):
            with cols[i]:
                kpi(
                    ins,
                    code,
                    f"AED {amt:,.2f}"
                )

        st.divider()

        tab1, tab2 = st.tabs(["By Insurance", "Rejected Detail"])

        with tab1:
            st.dataframe(by_ins.reset_index(name="Rejected Amount"), use_container_width=True)

        with tab2:
            st.dataframe(df.head(2000), use_container_width=True)


run()
