#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Streamlit Page: Registration Summary (View Only) - ENHANCED with Period Aggregation

New Features:
1. Period Selector: Daily, Weekly, Monthly views
2. Auto-aggregation: Weekly (Mon-Sun) and Monthly summaries from daily data
3. Period comparison: vs previous period
4. Period breakdown: Shows daily data within selected period
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
# Date formatting (management-friendly)
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

def get_week_range(date_str: str) -> Tuple[datetime, datetime]:
    """Get Monday-Sunday week for a given date."""
    dt = pd.to_datetime(date_str)
    start = dt - timedelta(days=dt.weekday())  # Monday
    end = start + timedelta(days=6)  # Sunday
    return start, end

def get_month_range(date_str: str) -> Tuple[datetime, datetime]:
    """Get first-last day of month for a given date."""
    dt = pd.to_datetime(date_str)
    start = datetime(dt.year, dt.month, 1)
    end = (start + relativedelta(months=1)) - timedelta(days=1)
    return start, end

st.set_page_config(page_title="Registration Summary (View Only)", layout="wide", initial_sidebar_state="collapsed")
st.title("📅 Registration Summary (View Only)")

# ---------------------------
# Helpers
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

def s3_list_days_in_range(s3, bucket: str, prefix: str, start_date: datetime, end_date: datetime) -> List[datetime]:
    """List all daily summary files within a date range."""
    days = []
    try:
        # List all objects under the center prefix
        paginator = s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                # Extract date from path like: registration/center/2024-01-15/summary.pkl
                parts = key.split("/")
                for part in parts:
                    try:
                        day = pd.to_datetime(part).normalize()
                        if start_date <= day <= end_date:
                            days.append(day)
                            break
                    except:
                        continue
    except Exception:
        pass
    return sorted(set(days))

def history_paths(center: str, base_prefix: str = "") -> Tuple[str, str]:
    """Return (root_prefix, history_csv_key) for this center."""
    root = s3_key(base_prefix, "registration", center)
    return root, s3_key(root, "history.csv")

def resolve_center_root_from_s3(s3, cfg: Dict[str, str], center_key: str) -> Tuple[str, str]:
    """Return (root_prefix, history_csv_key) that actually exists in S3."""
    bucket = cfg["S3_BUCKET_NAME"]
    # Try multiple prefix patterns
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
    
    # Return default
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
    """Load daily summary from S3."""
    day_str = pd.to_datetime(day_ts).date().isoformat()
    key = s3_key(root_prefix, day_str, "summary.pkl")
    b = s3_get_bytes(s3, cfg["S3_BUCKET_NAME"], key)
    if not b:
        return None
    try:
        return pickle.loads(b)
    except Exception:
        return None

def aggregate_period_summary(s3, cfg: Dict[str, str], root_prefix: str, period_type: str, selected_date: datetime) -> Dict:
    """
    Aggregate daily summaries for a period (week/month).
    Returns aggregated metrics and list of daily summaries.
    """
    if period_type == "weekly":
        start_date, end_date = get_week_range(selected_date)
        period_label = f"{start_date.strftime('%d %b')} - {end_date.strftime('%d %b %Y')}"
    elif period_type == "monthly":
        start_date, end_date = get_month_range(selected_date)
        period_label = selected_date.strftime("%B %Y")
    else:  # daily
        return {"period_label": fmt_day(selected_date), "daily_summaries": []}
    
    # Get all days in the period
    days_in_period = s3_list_days_in_range(s3, cfg["S3_BUCKET_NAME"], root_prefix, start_date, end_date)
    
    daily_summaries = []
    aggregated_kpis = {
        "total_visits": 0,
        "unique_emr": set(),
        "unique_visitno": 0,
        "cash_patients": 0,
        "pending_patients": 0,
    }
    
    # Load and aggregate each day's summary
    for day in days_in_period:
        summary = load_summary_from_s3(s3, cfg, root_prefix, day)
        if summary and "KPI" in summary:
            kpi = summary["KPI"].set_index("Metric")["Value"]
            daily_summaries.append({
                "date": day.date(),
                "total_visits": int(kpi.get("Total Visits", 0)),
                "unique_emr": int(kpi.get("Unique EMR (Patients)", 0)),
                "cash_patients": int(kpi.get("CashOut Patients", 0)),
                "pending_patients": int(kpi.get("Pending Patients", 0)),
                "summary": summary
            })
            
            # Aggregate
            aggregated_kpis["total_visits"] += int(kpi.get("Total Visits", 0))
            aggregated_kpis["cash_patients"] += int(kpi.get("CashOut Patients", 0))
            aggregated_kpis["pending_patients"] += int(kpi.get("Pending Patients", 0))
            aggregated_kpis["unique_visitno"] += int(kpi.get("Unique Visit No", 0))
            
            # For unique EMR, we need to track across days
            # This is simplified - in production, you'd need to track actual EMR numbers
            aggregated_kpis["unique_emr"].add(int(kpi.get("Unique EMR (Patients)", 0)))
    
    # For unique EMR, use max as approximation (or implement proper deduplication)
    unique_emr_approx = max(aggregated_kpis["unique_emr"]) if aggregated_kpis["unique_emr"] else 0
    
    return {
        "period_label": period_label,
        "start_date": start_date,
        "end_date": end_date,
        "daily_summaries": daily_summaries,
        "aggregated": {
            "Total Visits": aggregated_kpis["total_visits"],
            "Unique EMR (Patients)": unique_emr_approx,
            "Unique Visit No": aggregated_kpis["unique_visitno"],
            "CashOut Patients": aggregated_kpis["cash_patients"],
            "Pending Patients": aggregated_kpis["pending_patients"],
        }
    }

def render_daily_summary(dfs: Dict[str, pd.DataFrame], day_ts: pd.Timestamp):
    """Render single day summary."""
    st.header(f"Daily Summary ({fmt_day(day_ts)})")
    
    kpi = dfs.get("KPI")
    if kpi is not None and not kpi.empty and "Metric" in kpi.columns and "Value" in kpi.columns:
        k = kpi.set_index("Metric")["Value"]
        a, b, c, d = st.columns(4)
        a.metric("Total Visits", int(k.get("Total Visits", 0)))
        b.metric("Unique EMR (Patients)", int(k.get("Unique EMR (Patients)", 0)))
        c.metric("Unique Visit No", int(k.get("Unique Visit No", 0)))
        d.metric("CashOut Patients", int(k.get("CashOut Patients", 0)))
        
        e, f = st.columns(2)
        e.metric("Pending Patients", int(k.get("Pending Patients", 0)))
        f.metric("Generated", fmt_dt(datetime.now()))
    else:
        st.info("KPI is not available for this day.")
    
    # Display detailed tables
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("Pending Status Wise")
        st.dataframe(dfs.get("Pending Status Wise", pd.DataFrame()), 
                    use_container_width=True, hide_index=True)
        
        st.subheader("Insurance Wise Visits")
        st.dataframe(dfs.get("Insurance Wise Visits", pd.DataFrame()), 
                    use_container_width=True, hide_index=True)
    
    with col2:
        st.subheader("Employer Wise")
        st.dataframe(dfs.get("Employer Wise", pd.DataFrame()), 
                    use_container_width=True, hide_index=True)
        
        st.subheader("Doctor Wise Visits")
        st.dataframe(dfs.get("Doctor Wise Visits", pd.DataFrame()), 
                    use_container_width=True, hide_index=True)

def render_period_summary(period_data: Dict, period_type: str):
    """Render weekly/monthly aggregated summary."""
    st.header(f"{period_type.title()} Summary ({period_data['period_label']})")
    
    # Period KPI cards
    agg = period_data["aggregated"]
    a, b, c, d = st.columns(4)
    a.metric("Total Visits", agg["Total Visits"])
    b.metric("Unique EMR (Patients)", agg["Unique EMR (Patients)"])
    c.metric("Unique Visit No", agg["Unique Visit No"])
    d.metric("CashOut Patients", agg["CashOut Patients"])
    
    e, f = st.columns(2)
    e.metric("Pending Patients", agg["Pending Patients"])
    f.metric("Days in Period", len(period_data["daily_summaries"]))
    
    # Daily breakdown within period
    if period_data["daily_summaries"]:
        st.subheader(f"Daily Breakdown ({period_type})")
        daily_df = pd.DataFrame(period_data["daily_summaries"])
        daily_df["date"] = pd.to_datetime(daily_df["date"]).dt.strftime("%d %b")
        st.dataframe(daily_df[["date", "total_visits", "unique_emr", "cash_patients", "pending_patients"]], 
                    use_container_width=True, hide_index=True)
    
    # Show first day's detailed tables as sample
    if period_data["daily_summaries"]:
        first_day = period_data["daily_summaries"][0]
        with st.expander("View Sample Day Details", expanded=False):
            render_daily_summary(first_day["summary"], first_day["date"])

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
# S3 status
# ---------------------------
cfg = load_secrets()
s3_ok = s3_enabled(cfg)
s3 = s3_client_cached(cfg) if s3_ok else None

with st.expander("Storage Status (S3)", expanded=False):
    if s3_ok:
        st.success(f"S3 is configured ✅  Bucket: {cfg['S3_BUCKET_NAME']}  Region: {cfg['AWS_REGION']}")
    else:
        st.error("S3 is NOT configured on this app, so View page cannot load saved results.")
        st.caption("Expected secrets: S3_BUCKET_NAME (or S3_BUCKET), AWS_REGION (or AWS_DEFAULT_REGION), AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY")

if not s3_ok:
    st.stop()

# ---------------------------
# Load history
# ---------------------------
hist, root_prefix = load_history_from_s3(s3, cfg, center_key)

if hist.empty or "day" not in hist.columns:
    st.warning("No saved Daily Report found for this center yet.")
    st.write("✅ To fix:")
    st.markdown(
        "- Open **Registration Summary (Upload)** page\n"
        "- Upload Step 1/2/3\n"
        "- Click **Process & Save to S3**\n"
        "- Then come back here"
    )
    st.stop()

hist["day"] = pd.to_datetime(hist["day"], errors="coerce").dt.normalize()
hist = hist.dropna(subset=["day"]).sort_values("day")
days = list(hist["day"].unique())
latest_day = days[-1] if days else datetime.now()

# ---------------------------
# NEW: Period Selector
# ---------------------------
st.markdown("---")
col1, col2, col3 = st.columns([1, 2, 1])

with col1:
    period_type = st.selectbox(
        "Period View",
        ["daily", "weekly", "monthly"],
        format_func=lambda x: x.title(),
        key="period_type"
    )

with col2:
    if period_type == "daily":
        selected_date = st.date_input(
            "Select Date",
            value=latest_day.date(),
            min_value=pd.to_datetime(min(days)).date() if days else latest_day.date(),
            max_value=pd.to_datetime(latest_day).date(),
            key="date_picker"
        )
        selected_date = pd.to_datetime(selected_date)
        
    elif period_type == "weekly":
        # Show week selector
        week_options = []
        for day in days:
            start, end = get_week_range(day)
            week_label = f"Week {start.strftime('%U')}: {start.strftime('%d %b')} - {end.strftime('%d %b %Y')}"
            if week_label not in [w[1] for w in week_options]:
                week_options.append((start, week_label))
        
        if week_options:
            week_options.sort(reverse=True)  # Show latest first
            week_labels = [w[1] for w in week_options]
            selected_week = st.selectbox("Select Week", options=week_labels, key="week_picker")
            selected_date = next(w[0] for w in week_options if w[1] == selected_week)
        else:
            selected_date = latest_day
            st.info("No weekly data available")
            
    else:  # monthly
        month_options = []
        for day in days:
            month_label = day.strftime("%B %Y")
            if month_label not in [m[1] for m in month_options]:
                month_options.append((day, month_label))
        
        if month_options:
            month_options.sort(reverse=True)
            month_labels = [m[1] for m in month_options]
            selected_month = st.selectbox("Select Month", options=month_labels, key="month_picker")
            selected_date = next(m[0] for m in month_options if m[1] == selected_month)
        else:
            selected_date = latest_day
            st.info("No monthly data available")

with col3:
    if period_type != "daily":
        st.metric("Period Type", period_type.title())

# ---------------------------
# Load and display data
# ---------------------------
SS = st.session_state
cache_key = f"{center_key}_{period_type}_{selected_date.date().isoformat()}"

if period_type == "daily":
    # Load single day summary
    summary = load_summary_from_s3(s3, cfg, root_prefix, selected_date)
    if summary is None:
        st.error(f"No data found for {fmt_day(selected_date)}")
        st.caption(f"Expected S3 key: {s3_key(root_prefix, selected_date.date().isoformat(), 'summary.pkl')}")
    else:
        render_daily_summary(summary, selected_date)
else:
    # Aggregate period data
    with st.spinner(f"Aggregating {period_type} data..."):
        period_data = aggregate_period_summary(s3, cfg, root_prefix, period_type, selected_date)
        render_period_summary(period_data, period_type)

# ---------------------------
# Income Analysis (if available for the period)
# ---------------------------
if period_type == "daily":
    summary = load_summary_from_s3(s3, cfg, root_prefix, selected_date)
    if summary:
        income_keys = [k for k in summary.keys() if str(k).startswith("Income | ")]
        if income_keys:
            st.markdown("---")
            st.header("Income Analysis (Doctor Revenue)")
            
            df_doc = summary.get("Income | Doctor Wise Revenue")
            df_ins = summary.get("Income | Insurance Wise Revenue")
            df_dx  = summary.get("Income | Doctor x Insurance Revenue")
            
            tabs = st.tabs(["Doctor Wise", "Insurance Wise", "Doctor x Insurance"])
            
            with tabs[0]:
                if df_doc is None or df_doc.empty:
                    st.info("No Doctor Wise revenue data for this day.")
                else:
                    st.dataframe(df_doc, use_container_width=True, hide_index=True)
            
            with tabs[1]:
                if df_ins is None or df_ins.empty:
                    st.info("No Insurance Wise revenue data for this day.")
                else:
                    st.dataframe(df_ins, use_container_width=True, hide_index=True)
            
            with tabs[2]:
                if df_dx is None or df_dx.empty:
                    st.info("No Doctor x Insurance revenue data for this day.")
                else:
                    df_f = df_dx.copy()
                    if "Doctor" in df_f.columns:
                        doctors = sorted([
                            d for d in df_f["Doctor"].dropna().unique()
                            if str(d).strip().lower() not in ["", "none", "nan"]
                            and str(d).strip().upper() != "GRAND TOTAL"
                        ])
                        if doctors:
                            pick_doc = st.selectbox("Select Doctor", options=doctors, 
                                                   key=f"income_pick_doc_{selected_date.date()}")
                            df_f = df_f[df_f["Doctor"] == pick_doc].copy()
                    
                    st.dataframe(df_f, use_container_width=True, hide_index=True)

# ---------------------------
# Accumulated History
# ---------------------------
st.markdown("---")
st.header("Accumulated History (All Days)")

def add_cumulative(hist: pd.DataFrame) -> pd.DataFrame:
    if hist is None or hist.empty:
        return pd.DataFrame()
    h = hist.sort_values("day").copy()
    for c in ["total_visits", "unique_emr", "unique_visitno", "cash_patients", "pending_patients"]:
        if c in h.columns:
            h[c] = h[c].fillna(0).astype(int)
            h[f"cum_{c}"] = h[c].cumsum()
    return h.sort_values("day", ascending=False).reset_index(drop=True)

acc = add_cumulative(hist)

# Display with tabs for different views
tab1, tab2 = st.tabs(["Table View", "Chart View"])

with tab1:
    st.dataframe(acc, use_container_width=True, hide_index=True)

with tab2:
    if not acc.empty:
        import matplotlib.pyplot as plt
        
        fig, axes = plt.subplots(2, 2, figsize=(12, 8))
        fig.suptitle('Registration Trends', fontsize=16)
        
        # Plot 1: Daily Visits
        axes[0, 0].plot(acc['day'], acc['total_visits'], marker='o', linewidth=2)
        axes[0, 0].set_title('Daily Visits')
        axes[0, 0].set_xlabel('Date')
        axes[0, 0].set_ylabel('Visits')
        axes[0, 0].grid(True, alpha=0.3)
        axes[0, 0].tick_params(axis='x', rotation=45)
        
        # Plot 2: Cumulative Visits
        axes[0, 1].plot(acc['day'], acc['cum_total_visits'], marker='s', linewidth=2, color='green')
        axes[0, 1].set_title('Cumulative Visits')
        axes[0, 1].set_xlabel('Date')
        axes[0, 1].set_ylabel('Total Visits')
        axes[0, 1].grid(True, alpha=0.3)
        axes[0, 1].tick_params(axis='x', rotation=45)
        
        # Plot 3: Unique Patients
        axes[1, 0].bar(acc['day'], acc['unique_emr'], alpha=0.7)
        axes[1, 0].set_title('Unique Patients per Day')
        axes[1, 0].set_xlabel('Date')
        axes[1, 0].set_ylabel('Patients')
        axes[1, 0].grid(True, alpha=0.3)
        axes[1, 0].tick_params(axis='x', rotation=45)
        
        # Plot 4: CashOut Patients
        axes[1, 1].plot(acc['day'], acc['cash_patients'], marker='^', linewidth=2, color='orange')
        axes[1, 1].set_title('CashOut Patients')
        axes[1, 1].set_xlabel('Date')
        axes[1, 1].set_ylabel('Patients')
        axes[1, 1].grid(True, alpha=0.3)
        axes[1, 1].tick_params(axis='x', rotation=45)
        
        plt.tight_layout()
        st.pyplot(fig)
    else:
        st.info("No data available for charts.")

# ---------------------------
# Download Options
# ---------------------------
st.markdown("---")
st.header("Download Reports")

col1, col2 = st.columns(2)

with col1:
    if st.button("📥 Download Current View", use_container_width=True):
        if period_type == "daily":
            summary = load_summary_from_s3(s3, cfg, root_prefix, selected_date)
            if summary:
                # Create Excel with all tables
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    for sheet_name, df in summary.items():
                        if isinstance(df, pd.DataFrame):
                            df.to_excel(writer, sheet_name=sheet_name[:31], index=False)
                st.download_button(
                    label="Click to download Excel",
                    data=output.getvalue(),
                    file_name=f"Registration_Summary_{selected_date.date().isoformat()}.xlsx",
                    mime="application/vnd.openxlmformats-officedocument.spreadsheetml.sheet"
                )

with col2:
    if st.button("📈 Download Trend Report", use_container_width=True):
        if not acc.empty:
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                acc.to_excel(writer, sheet_name="Trend_Data", index=False)
            st.download_button(
                label="Click to download Trend Report",
                data=output.getvalue(),
                file_name=f"Registration_Trend_{center_key}_{datetime.now().date().isoformat()}.xlsx",
                mime="application/vnd.openxlmformats-officedocument.spreadsheetml.sheet"
            )

st.caption("💡 Tip: Use 'View another day' option to explore historical data")
