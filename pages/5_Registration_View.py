#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Streamlit Page: Registration Summary (View Only) - FIXED Period Selection
"""

import io
import os
import re
import pickle
from datetime import datetime, timedelta
from typing import Dict, Optional, List, Tuple
import pandas as pd
import streamlit as st
from dateutil.relativedelta import relativedelta

# Optional S3
try:
    import boto3
except Exception:
    boto3 = None

# ---------------------------
# Date formatting
# ---------------------------
def fmt_day(ts) -> str:
    try:
        return pd.to_datetime(ts).strftime("%d %b %Y")
    except Exception:
        return str(ts)

def fmt_dt(ts) -> str:
    try:
        return pd.to_datetime(ts).strftime("%d %b %Y %H:%M")
    except Exception:
        return str(ts)

def get_week_range(date_obj) -> Tuple[datetime, datetime]:
    """Get Monday-Sunday week for a given date."""
    dt = pd.to_datetime(date_obj)
    start = dt - timedelta(days=dt.weekday())  # Monday
    end = start + timedelta(days=6)  # Sunday
    return start.date(), end.date()

def get_month_range(date_obj) -> Tuple[datetime, datetime]:
    """Get first-last day of month for a given date."""
    dt = pd.to_datetime(date_obj)
    start = datetime(dt.year, dt.month, 1)
    end = (start + relativedelta(months=1)) - timedelta(days=1)
    return start.date(), end.date()

st.set_page_config(page_title="Registration Summary (View Only)", layout="wide", initial_sidebar_state="collapsed")
st.title("📅 Registration Summary (View Only)")

# ---------------------------
# S3 Helpers
# ---------------------------
def s3_key(*parts: str) -> str:
    return "/".join([p.strip("/").strip() for p in parts if p is not None and str(p).strip() != ""])

def load_secrets() -> Dict[str, str]:
    def get_any(*keys):
        for k in keys:
            if k in st.secrets:
                v = st.secrets.get(k)
                if v is not None and str(v).strip() != "":
                    return str(v).strip()
            v = os.getenv(k)
            if v is not None and str(v).strip() != "":
                return str(v).strip()
        return ""
    return {
        "AWS_ACCESS_KEY_ID": get_any("AWS_ACCESS_KEY_ID"),
        "AWS_SECRET_ACCESS_KEY": get_any("AWS_SECRET_ACCESS_KEY"),
        "AWS_REGION": get_any("AWS_REGION", "AWS_DEFAULT_REGION"),
        "S3_BUCKET_NAME": get_any("S3_BUCKET_NAME", "S3_BUCKET"),
        "S3_BASE_PREFIX": get_any("S3_BASE_PREFIX", "S3_PREFIX"),
    }

def s3_enabled(cfg: Dict[str, str]) -> bool:
    return (
        bool(cfg.get("S3_BUCKET_NAME"))
        and bool(cfg.get("AWS_REGION"))
        and bool(cfg.get("AWS_ACCESS_KEY_ID"))
        and bool(cfg.get("AWS_SECRET_ACCESS_KEY"))
        and boto3 is not None
    )

@st.cache_resource(show_spinner=False)
def s3_client_cached(cfg: Dict[str, str]):
    if not s3_enabled(cfg):
        return None
    return boto3.client(
        "s3",
        region_name=cfg["AWS_REGION"],
        aws_access_key_id=cfg["AWS_ACCESS_KEY_ID"],
        aws_secret_access_key=cfg["AWS_SECRET_ACCESS_KEY"],
    )

def s3_get_bytes(s3, bucket: str, key: str) -> Optional[bytes]:
    try:
        obj = s3.get_object(Bucket=bucket, Key=key)
        return obj["Body"].read()
    except Exception:
        return None

def s3_key_exists(s3, bucket: str, key: str) -> bool:
    try:
        s3.head_object(Bucket=bucket, Key=key)
        return True
    except Exception:
        return False

def s3_list_available_days(s3, bucket: str, prefix: str) -> List[datetime]:
    """List all days that have summary.pkl files."""
    days = []
    try:
        paginator = s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix, Delimiter="/"):
            for obj in page.get("Contents", []):
                if obj["Key"].endswith("summary.pkl"):
                    # Extract date from path: .../2024-01-15/summary.pkl
                    parts = obj["Key"].split("/")
                    for part in parts:
                        try:
                            day = pd.to_datetime(part).normalize()
                            days.append(day)
                            break
                        except:
                            continue
    except Exception:
        pass
    return sorted(set(days))

def history_paths(center: str, base_prefix: str = "") -> Tuple[str, str]:
    root = s3_key(base_prefix, "registration", center)
    return root, s3_key(root, "history.csv")

def resolve_center_root_from_s3(s3, cfg: Dict[str, str], center_key: str) -> Tuple[str, str]:
    bucket = cfg["S3_BUCKET_NAME"]
    prefixes = [
        cfg.get("S3_BASE_PREFIX", "").strip("/"),
        "",
        "streamlit",
        "data"
    ]
    
    for pref in prefixes:
        root, hist_key = history_paths(center_key, pref)
        if s3_key_exists(s3, bucket, hist_key):
            return root, hist_key
    
    root, hist_key = history_paths(center_key, cfg.get("S3_BASE_PREFIX", ""))
    return root, hist_key

def load_history_from_s3(s3, cfg: Dict[str, str], center_key: str) -> Tuple[pd.DataFrame, str]:
    root, hist_key = resolve_center_root_from_s3(s3, cfg, center_key)
    b = s3_get_bytes(s3, cfg["S3_BUCKET_NAME"], hist_key)
    if not b:
        return pd.DataFrame(), root
    try:
        df = pd.read_csv(io.BytesIO(b), parse_dates=["day"])
    except Exception:
        df = pd.read_csv(io.BytesIO(b))
    return df, root

def load_summary_from_s3(s3, cfg: Dict[str, str], root_prefix: str, day_ts: pd.Timestamp) -> Optional[Dict[str, pd.DataFrame]]:
    day_str = pd.to_datetime(day_ts).date().isoformat()
    key = s3_key(root_prefix, day_str, "summary.pkl")
    b = s3_get_bytes(s3, cfg["S3_BUCKET_NAME"], key)
    if not b:
        return None
    try:
        return pickle.loads(b)
    except Exception:
        return None

def load_all_days_in_range(s3, cfg: Dict[str, str], root_prefix: str, start_date: date, end_date: date) -> List[Dict]:
    """Load all daily summaries within a date range."""
    daily_data = []
    current = start_date
    
    while current <= end_date:
        summary = load_summary_from_s3(s3, cfg, root_prefix, pd.Timestamp(current))
        if summary and "KPI" in summary:
            kpi = summary["KPI"].set_index("Metric")["Value"]
            daily_data.append({
                "date": current,
                "total_visits": int(kpi.get("Total Visits", 0)),
                "unique_emr": int(kpi.get("Unique EMR (Patients)", 0)),
                "unique_visitno": int(kpi.get("Unique Visit No", 0)),
                "cash_patients": int(kpi.get("CashOut Patients", 0)),
                "pending_patients": int(kpi.get("Pending Patients", 0)),
                "summary": summary
            })
        current += timedelta(days=1)
    
    return daily_data

# ---------------------------
# Center selection
# ---------------------------
CENTERS = {
    "easyhealth": "Easy Health Medical Clinic (MF8031)",
    "excellent": "Excellent Medical Center (MF4777)",
    "pharmacy": "Excellent Pharmacy (PF3205)",
}

qp_center = (st.query_params.get("center") or "").strip()
center_key = qp_center if qp_center in CENTERS else None

if center_key:
    st.selectbox("Center", [center_key], format_func=lambda k: CENTERS[k], disabled=True, key="center_locked")
else:
    center_key = st.selectbox("Center", options=list(CENTERS.keys()), 
                             format_func=lambda k: CENTERS[k], key="center_pick")

st.caption(f"Center: **{CENTERS.get(center_key, center_key)}**")

# ---------------------------
# S3 setup
# ---------------------------
cfg = load_secrets()
s3_ok = s3_enabled(cfg)
s3 = s3_client_cached(cfg) if s3_ok else None

if not s3_ok:
    st.error("S3 is NOT configured. Cannot load data.")
    st.stop()

# ---------------------------
# Load available days
# ---------------------------
hist, root_prefix = load_history_from_s3(s3, cfg, center_key)

if hist.empty or "day" not in hist.columns:
    st.warning("No saved Daily Report found for this center yet.")
    st.info("Upload data using the Registration Summary (Upload) page first.")
    st.stop()

hist["day"] = pd.to_datetime(hist["day"], errors="coerce").dt.normalize()
hist = hist.dropna(subset=["day"]).sort_values("day")

# Get all available dates that have data
available_dates = s3_list_available_days(s3, cfg["S3_BUCKET_NAME"], root_prefix)
if not available_dates:
    available_dates = list(hist["day"].unique())

if not available_dates:
    st.error("No data found in S3.")
    st.stop()

min_date = min(available_dates).date()
max_date = max(available_dates).date()
latest_date = max_date

# ---------------------------
# FIXED: Period Selector - Simplified
# ---------------------------
st.markdown("---")

# Period type selector
period_type = st.radio(
    "Select Period View:",
    ["Daily", "Weekly", "Monthly"],
    horizontal=True,
    key="period_type"
)

# Date selector - SINGLE DATE PICKER for all modes
selected_date = st.date_input(
    "Select Date",
    value=latest_date,
    min_value=min_date,
    max_value=max_date,
    key="date_selector"
)

# ---------------------------
# Determine period range based on selection
# ---------------------------
if period_type == "Daily":
    period_start = selected_date
    period_end = selected_date
    period_label = fmt_day(selected_date)
    
elif period_type == "Weekly":
    period_start, period_end = get_week_range(selected_date)
    period_label = f"Week: {fmt_day(period_start)} to {fmt_day(period_end)}"
    
else:  # Monthly
    period_start, period_end = get_month_range(selected_date)
    period_label = f"Month: {selected_date.strftime('%B %Y')}"

st.info(f"**Showing {period_type.lower()} data for:** {period_label}")

# ---------------------------
# Load and display data
# ---------------------------
if period_type == "Daily":
    # Load single day
    summary = load_summary_from_s3(s3, cfg, root_prefix, pd.Timestamp(selected_date))
    
    if summary is None:
        st.error(f"No data found for {fmt_day(selected_date)}")
    else:
        # Display KPI cards
        kpi = summary.get("KPI")
        if kpi is not None and not kpi.empty and "Metric" in kpi.columns and "Value" in kpi.columns:
            k = kpi.set_index("Metric")["Value"]
            
            cols = st.columns(6)
            cols[0].metric("Total Visits", int(k.get("Total Visits", 0)))
            cols[1].metric("Unique EMR", int(k.get("Unique EMR (Patients)", 0)))
            cols[2].metric("Unique Visit No", int(k.get("Unique Visit No", 0)))
            cols[3].metric("CashOut", int(k.get("CashOut Patients", 0)))
            cols[4].metric("Pending", int(k.get("Pending Patients", 0)))
            cols[5].metric("Date", fmt_day(selected_date))
        
        # Display tables in columns
        col1, col2 = st.columns(2)
        
        with col1:
            if "Pending Status Wise" in summary:
                st.subheader("Pending Status")
                st.dataframe(summary["Pending Status Wise"], use_container_width=True, hide_index=True)
            
            if "Insurance Wise Visits" in summary:
                st.subheader("Insurance Wise")
                st.dataframe(summary["Insurance Wise Visits"], use_container_width=True, hide_index=True)
        
        with col2:
            if "Employer Wise" in summary:
                st.subheader("Employer Wise")
                st.dataframe(summary["Employer Wise"], use_container_width=True, hide_index=True)
            
            if "Doctor Wise Visits" in summary:
                st.subheader("Doctor Wise")
                st.dataframe(summary["Doctor Wise Visits"], use_container_width=True, hide_index=True)
        
        # Income Analysis
        income_keys = [k for k in summary.keys() if str(k).startswith("Income | ")]
        if income_keys:
            st.markdown("---")
            st.header("Income Analysis")
            
            tabs = st.tabs(["Doctor Wise", "Insurance Wise", "Doctor x Insurance"])
            
            with tabs[0]:
                df_doc = summary.get("Income | Doctor Wise Revenue")
                if df_doc is not None and not df_doc.empty:
                    st.dataframe(df_doc, use_container_width=True, hide_index=True)
                else:
                    st.info("No Doctor Wise revenue data")
            
            with tabs[1]:
                df_ins = summary.get("Income | Insurance Wise Revenue")
                if df_ins is not None and not df_ins.empty:
                    st.dataframe(df_ins, use_container_width=True, hide_index=True)
                else:
                    st.info("No Insurance Wise revenue data")
            
            with tabs[2]:
                df_dx = summary.get("Income | Doctor x Insurance Revenue")
                if df_dx is not None and not df_dx.empty:
                    # Add doctor filter
                    if "Doctor" in df_dx.columns:
                        doctors = sorted([
                            d for d in df_dx["Doctor"].dropna().unique()
                            if str(d).strip().lower() not in ["", "none", "nan", "grand total"]
                        ])
                        if doctors:
                            selected_doctor = st.selectbox("Filter by Doctor:", ["All"] + doctors)
                            if selected_doctor != "All":
                                df_dx = df_dx[df_dx["Doctor"] == selected_doctor]
                    
                    st.dataframe(df_dx, use_container_width=True, hide_index=True)
                else:
                    st.info("No Doctor x Insurance revenue data")

else:
    # Weekly or Monthly - Aggregate data
    with st.spinner(f"Loading {period_type.lower()} data..."):
        daily_data = load_all_days_in_range(s3, cfg, root_prefix, period_start, period_end)
        
        if not daily_data:
            st.warning(f"No data found for {period_label}")
        else:
            # Calculate aggregates
            total_visits = sum(d["total_visits"] for d in daily_data)
            total_cash = sum(d["cash_patients"] for d in daily_data)
            total_pending = sum(d["pending_patients"] for d in daily_data)
            max_unique_emr = max(d["unique_emr"] for d in daily_data) if daily_data else 0
            
            # Display period summary
            st.subheader(f"{period_type} Summary")
            
            cols = st.columns(5)
            cols[0].metric("Period", period_type)
            cols[1].metric("Total Visits", total_visits)
            cols[2].metric("Max Unique EMR", max_unique_emr)
            cols[3].metric("Total CashOut", total_cash)
            cols[4].metric("Total Pending", total_pending)
            
            # Daily breakdown table
            st.subheader(f"Daily Breakdown ({len(daily_data)} days)")
            breakdown_df = pd.DataFrame([
                {
                    "Date": fmt_day(d["date"]),
                    "Visits": d["total_visits"],
                    "Unique EMR": d["unique_emr"],
                    "CashOut": d["cash_patients"],
                    "Pending": d["pending_patients"]
                }
                for d in daily_data
            ])
            st.dataframe(breakdown_df, use_container_width=True, hide_index=True)
            
            # Show first available day's detailed tables
            if daily_data:
                with st.expander("View Sample Day Details", expanded=False):
                    first_day = daily_data[0]
                    st.write(f"**Sample: {fmt_day(first_day['date'])}**")
                    
                    if "Insurance Wise Visits" in first_day["summary"]:
                        st.dataframe(
                            first_day["summary"]["Insurance Wise Visits"],
                            use_container_width=True,
                            hide_index=True
                        )

# ---------------------------
# Accumulated History
# ---------------------------
st.markdown("---")
st.header("📈 Accumulated History")

def add_cumulative(hist_df: pd.DataFrame) -> pd.DataFrame:
    if hist_df.empty:
        return pd.DataFrame()
    
    h = hist_df.sort_values("day").copy()
    
    # Ensure required columns exist
    for col in ["total_visits", "unique_emr", "cash_patients", "pending_patients"]:
        if col not in h.columns:
            h[col] = 0
    
    # Calculate cumulative
    h["cum_total_visits"] = h["total_visits"].cumsum()
    h["cum_unique_emr"] = h["unique_emr"].cumsum()
    h["cum_cash_patients"] = h["cash_patients"].cumsum()
    h["cum_pending_patients"] = h["pending_patients"].cumsum()
    
    return h.sort_values("day", ascending=False).reset_index(drop=True)

acc_df = add_cumulative(hist)

if not acc_df.empty:
    # KPI cards for cumulative totals
    latest = acc_df.iloc[0] if not acc_df.empty else None
    
    st.subheader("Cumulative Totals")
    cols = st.columns(4)
    if latest is not None:
        cols[0].metric("Total Visits", int(latest.get("cum_total_visits", 0)))
        cols[1].metric("Total Unique EMR", int(latest.get("cum_unique_emr", 0)))
        cols[2].metric("Total CashOut", int(latest.get("cum_cash_patients", 0)))
        cols[3].metric("Total Pending", int(latest.get("cum_pending_patients", 0)))
    
    # History table
    st.subheader("Daily History")
    display_cols = ["day", "total_visits", "unique_emr", "cash_patients", "pending_patients"]
    display_df = acc_df[display_cols].copy()
    display_df["day"] = display_df["day"].dt.strftime("%d %b %Y")
    
    st.dataframe(display_df, use_container_width=True, hide_index=True)
else:
    st.info("No historical data available.")

# ---------------------------
# Footer
# ---------------------------
st.markdown("---")
st.caption(f"Data last updated: {max_date.strftime('%d %b %Y')} • Center: {CENTERS.get(center_key, center_key)}")
