#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import io
import pickle
from datetime import datetime
from typing import Dict, Optional

import pandas as pd
import streamlit as st

# Optional S3
try:
    import boto3
except Exception:
    boto3 = None

st.set_page_config(page_title="Registration Summary (View)", layout="wide")

st.title("📅 Registration Summary (View Only)")

# ---------------------------
# Secrets loader
# ---------------------------
def load_secrets():
    def get_any(*keys):
        for k in keys:
            if k in st.secrets:
                return st.secrets.get(k)
        return ""

    return {
        "AWS_ACCESS_KEY_ID": get_any("AWS_ACCESS_KEY_ID"),
        "AWS_SECRET_ACCESS_KEY": get_any("AWS_SECRET_ACCESS_KEY"),
        "AWS_REGION": get_any("AWS_REGION", "AWS_DEFAULT_REGION"),
        "S3_BUCKET_NAME": get_any("S3_BUCKET_NAME", "S3_BUCKET"),
        "S3_BASE_PREFIX": get_any("S3_BASE_PREFIX"),
    }


def s3_enabled(cfg):
    return (
        cfg["AWS_ACCESS_KEY_ID"]
        and cfg["AWS_SECRET_ACCESS_KEY"]
        and cfg["AWS_REGION"]
        and cfg["S3_BUCKET_NAME"]
        and boto3 is not None
    )


cfg = load_secrets()

# ---------------------------
# S3 client
# ---------------------------
@st.cache_resource
def s3_client():
    if not s3_enabled(cfg):
        return None

    return boto3.client(
        "s3",
        region_name=cfg["AWS_REGION"],
        aws_access_key_id=cfg["AWS_ACCESS_KEY_ID"],
        aws_secret_access_key=cfg["AWS_SECRET_ACCESS_KEY"],
    )


s3 = s3_client()

# ---------------------------
# Path helper
# ---------------------------
def history_paths(center: str):
    prefix = cfg.get("S3_BASE_PREFIX", "")
    parts = [p.strip("/") for p in [prefix, "registration_summary", center] if p]
    root = "/".join(parts)
    return root, f"{root}/history.csv"


# ---------------------------
# Load history
# ---------------------------
def load_history(center):
    if not s3:
        return pd.DataFrame()

    _, hist_key = history_paths(center)

    try:
        obj = s3.get_object(Bucket=cfg["S3_BUCKET_NAME"], Key=hist_key)
        return pd.read_csv(io.BytesIO(obj["Body"].read()), parse_dates=["day"])
    except Exception:
        return pd.DataFrame()


# ---------------------------
# Load summary
# ---------------------------
def load_summary(center, day):
    if not s3:
        return None

    root, _ = history_paths(center)
    key = f"{root}/{day}/summary.pkl"

    try:
        obj = s3.get_object(Bucket=cfg["S3_BUCKET_NAME"], Key=key)
        return pickle.loads(obj["Body"].read())
    except Exception:
        return None


# ---------------------------
# UI
# ---------------------------
CENTERS = {
    "excellent": "Excellent Medical Center (MF4777)",
    "easyhealth": "Easy Health Medical Clinic",
    "pharmacy": "Excellent Pharmacy",
}

center_key = st.selectbox(
    "Center",
    list(CENTERS.keys()),
    format_func=lambda x: CENTERS[x],
)

history = load_history(center_key)

if history.empty:
    st.warning("No saved Daily Report found for this center yet.")
    st.stop()

selected_day = st.selectbox(
    "Select Day",
    sorted(history["day"].dt.date.astype(str).unique(), reverse=True),
)

dfs = load_summary(center_key, selected_day)

if dfs is None:
    st.warning("Summary not found.")
    st.stop()

# ---------------------------
# KPI
# ---------------------------
kpi = dfs.get("KPI")
if kpi is not None:
    st.subheader("KPI")
    st.dataframe(kpi, use_container_width=True)

# ---------------------------
# Normal tables
# ---------------------------
for name in [
    "Pending Status Wise",
    "Insurance Wise Visits",
    "Employer Wise",
    "Doctor Wise Visits",
]:
    df = dfs.get(name)
    if df is not None:
        st.subheader(name)
        st.dataframe(df, use_container_width=True)

# ---------------------------
# Income Analysis
# ---------------------------
income_keys = [k for k in dfs.keys() if str(k).startswith("Income | ")]

if income_keys:

    st.header("💰 Income Analysis (Doctor Revenue)")

    tab1, tab2, tab3 = st.tabs(
        ["Doctor Wise", "Insurance Wise", "Doctor x Insurance"]
    )

    with tab1:
        df_dw = dfs.get("Income | Doctor Wise Revenue")
        if df_dw is not None:
            st.dataframe(df_dw, use_container_width=True)

    with tab2:
        df_ins = dfs.get("Income | Insurance Wise Revenue")
        if df_ins is not None:
            st.dataframe(df_ins, use_container_width=True)

    with tab3:
        df_dx = dfs.get("Income | Doctor x Insurance Revenue")

        if df_dx is not None and not df_dx.empty:

            doctors = sorted(df_dx["Doctor"].dropna().unique())
            pick_doc = st.selectbox("Select Doctor", doctors)

            filtered = df_dx[df_dx["Doctor"] == pick_doc]

            ins_list = ["All"] + sorted(filtered["Insurance"].dropna().unique())
            pick_ins = st.selectbox("Select Insurance", ins_list)

            if pick_ins != "All":
                filtered = filtered[filtered["Insurance"] == pick_ins]

            st.dataframe(filtered, use_container_width=True)

# ---------------------------
# Footer
# ---------------------------
st.caption(f"Loaded summary for {selected_day}")
