#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import io
import os
import pickle
from datetime import datetime
from typing import Dict, Optional, Tuple

import pandas as pd
import streamlit as st

try:
    import boto3
except Exception:
    boto3 = None

st.set_page_config(page_title="Registration Summary (View Only)", layout="wide", initial_sidebar_state="collapsed")
st.title("📅 Registration Summary (View Only)")

# ---------------- Date Formatting ----------------
def fmt_day(ts):
    try:
        return pd.to_datetime(ts).strftime("%d %b %Y")
    except:
        return str(ts)

def fmt_dt(ts):
    try:
        return pd.to_datetime(ts).strftime("%d %b %Y %H:%M")
    except:
        return str(ts)

# ---------------- Helpers ----------------
def s3_key(*parts):
    return "/".join([p.strip("/") for p in parts if p])

def load_secrets():
    def get_any(*keys):
        for k in keys:
            if k in st.secrets:
                return str(st.secrets.get(k))
            v = os.getenv(k)
            if v:
                return str(v)
        return ""

    return {
        "AWS_ACCESS_KEY_ID": get_any("AWS_ACCESS_KEY_ID"),
        "AWS_SECRET_ACCESS_KEY": get_any("AWS_SECRET_ACCESS_KEY"),
        "AWS_REGION": get_any("AWS_REGION","AWS_DEFAULT_REGION"),
        "S3_BUCKET_NAME": get_any("S3_BUCKET_NAME","S3_BUCKET"),
        "S3_BASE_PREFIX": get_any("S3_BASE_PREFIX","S3_PREFIX"),
    }

def s3_enabled(cfg):
    return all([
        cfg["AWS_ACCESS_KEY_ID"],
        cfg["AWS_SECRET_ACCESS_KEY"],
        cfg["AWS_REGION"],
        cfg["S3_BUCKET_NAME"],
        boto3 is not None
    ])

@st.cache_resource
def s3_client_cached(cfg):
    if not s3_enabled(cfg):
        return None
    return boto3.client(
        "s3",
        region_name=cfg["AWS_REGION"],
        aws_access_key_id=cfg["AWS_ACCESS_KEY_ID"],
        aws_secret_access_key=cfg["AWS_SECRET_ACCESS_KEY"],
    )

def s3_get_bytes(s3, bucket, key):
    try:
        obj = s3.get_object(Bucket=bucket, Key=key)
        return obj["Body"].read()
    except:
        return None

def history_paths(center, prefix=""):
    root = s3_key(prefix, "registration_summary", center)
    return root, s3_key(root, "history.csv")

def load_history_from_s3(s3, cfg, center):
    root, hist_key = history_paths(center, cfg.get("S3_BASE_PREFIX",""))
    b = s3_get_bytes(s3, cfg["S3_BUCKET_NAME"], hist_key)
    if not b:
        return pd.DataFrame()
    return pd.read_csv(io.BytesIO(b), parse_dates=["day"])

def load_summary_from_s3(s3, cfg, center, day_ts):
    root,_ = history_paths(center, cfg.get("S3_BASE_PREFIX",""))
    key = s3_key(root, pd.to_datetime(day_ts).date().isoformat(), "summary.pkl")
    b = s3_get_bytes(s3, cfg["S3_BUCKET_NAME"], key)
    if not b:
        return None
    return pickle.loads(b)

def add_cumulative(hist):
    if hist.empty:
        return pd.DataFrame()
    h = hist.sort_values("day").copy()
    for c in ["total_visits","unique_emr","unique_visitno","cash_patients","pending_patients"]:
        if c in h.columns:
            h[c] = h[c].fillna(0).astype(int)
            h[f"cum_{c}"] = h[c].cumsum()
    return h.sort_values("day", ascending=False)

# ---------------- Center Selection ----------------
CENTERS = {
    "easyhealth":"Easy Health Medical Clinic (MF8031)",
    "excellent":"Excellent Medical Center (MF4777)",
    "pharmacy":"Excellent Pharmacy (PF3205)"
}

qp_center = (st.query_params.get("center") or "").strip()
center_key = qp_center if qp_center in CENTERS else st.selectbox("Center", list(CENTERS.keys()))

st.caption(f"Center: **{CENTERS.get(center_key)}**")

# ---------------- S3 Status ----------------
cfg = load_secrets()
s3_ok = s3_enabled(cfg)
s3 = s3_client_cached(cfg) if s3_ok else None

if not s3_ok:
    st.error("S3 NOT Configured")
    st.stop()

# ---------------- Load History ----------------
hist = load_history_from_s3(s3, cfg, center_key)

if hist.empty:
    st.warning("No saved Daily Report found")
    st.stop()

hist["day"] = pd.to_datetime(hist["day"]).dt.normalize()
hist = hist.sort_values("day")

latest = hist["day"].max()
st.caption(f"Showing latest saved day: {fmt_day(latest)}")

dfs = load_summary_from_s3(s3, cfg, center_key, latest)

if dfs is None:
    st.error("Summary missing")
    st.stop()

# ---------------- KPI ----------------
kpi = dfs.get("KPI")
if kpi is not None:
    k = kpi.set_index("Metric")["Value"]
    a,b,c,d = st.columns(4)
    a.metric("Total Visits", int(k.get("Total Visits",0)))
    b.metric("Unique EMR", int(k.get("Unique EMR (Patients)",0)))
    c.metric("Unique Visit No", int(k.get("Unique Visit No",0)))
    d.metric("CashOut", int(k.get("CashOut Patients",0)))

# ---------------- Tables ----------------
def show(name):
    df = dfs.get(name)
    if df is not None:
        st.subheader(name)
        st.dataframe(df, use_container_width=True)

show("Pending Status Wise")
show("Insurance Wise Visits")
show("Employer Wise")
show("Doctor Wise Visits")

# ---------------- Income Analysis ----------------
income_keys = [k for k in dfs.keys() if str(k).startswith("Income | ")]

if income_keys:
    st.header("💰 Income Analysis")

    tab1,tab2,tab3 = st.tabs(["Doctor Wise","Insurance Wise","Doctor x Insurance"])

    with tab1:
        df = dfs.get("Income | Doctor Wise Revenue")
        if df is not None:
            st.dataframe(df,use_container_width=True)

    with tab2:
        df = dfs.get("Income | Insurance Wise Revenue")
        if df is not None:
            st.dataframe(df,use_container_width=True)

    with tab3:
        df = dfs.get("Income | Doctor x Insurance Revenue")
        if df is not None and not df.empty:

            doctors = sorted([
                d for d in df["Doctor"].dropna().unique()
                if str(d).strip().upper()!="GRAND TOTAL"
            ])

            doc = st.selectbox("Select Doctor", doctors, key=f"doc_{latest}")

            filtered = df[df["Doctor"]==doc].copy()

            ins_list = ["All"] + sorted([
                i for i in filtered["Insurance"].dropna().unique()
                if str(i).strip().upper()!="GRAND TOTAL"
            ])

            ins = st.selectbox("Select Insurance", ins_list, key=f"ins_{latest}")

            if ins!="All":
                filtered = filtered[filtered["Insurance"]==ins]

            st.dataframe(filtered,use_container_width=True)

# ---------------- Accumulated ----------------
st.header("Accumulated")
acc = add_cumulative(hist)
st.dataframe(acc,use_container_width=True)
