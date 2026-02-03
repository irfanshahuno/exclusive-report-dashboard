#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Streamlit Page: Registration Summary (View Only) - FINAL

Purpose
- Management view-only page
- Loads latest saved summary from S3 (created by the uploader page)
- Expected structure:
    registration_summary/<center>/<YYYY-MM-DD>/summary.pkl
    registration_summary/<center>/history.csv
"""

import io
import os
import pickle
from datetime import datetime
from typing import Dict, Optional, Tuple

import pandas as pd
import streamlit as st

# Optional S3
try:
    import boto3
except Exception:
    boto3 = None


# ────────────────────────────────────────────────
# Date formatting helpers
# ────────────────────────────────────────────────
def fmt_day(ts) -> str:
    try:
        return pd.to_datetime(ts).strftime("%d %b %Y")
    except:
        return str(ts)


def fmt_dt(ts) -> str:
    try:
        return pd.to_datetime(ts).strftime("%d %b %Y %H:%M")
    except:
        return str(ts)


st.set_page_config(
    page_title="Registration Summary (View Only)",
    layout="wide",
    initial_sidebar_state="collapsed"
)

st.title("📅 Registration Summary (View Only)")


# ────────────────────────────────────────────────
# S3 helpers
# ────────────────────────────────────────────────
def s3_key(*parts: str) -> str:
    return "/".join(p.strip("/") for p in parts if p and str(p).strip())


def load_secrets() -> Dict[str, str]:
    def get_any(*keys):
        for k in keys:
            v = st.secrets.get(k) or os.getenv(k)
            if v and str(v).strip():
                return str(v).strip()
        return ""

    return {
        "AWS_ACCESS_KEY_ID": get_any("AWS_ACCESS_KEY_ID"),
        "AWS_SECRET_ACCESS_KEY": get_any("AWS_SECRET_ACCESS_KEY"),
        "AWS_REGION": get_any("AWS_REGION", "AWS_DEFAULT_REGION"),
        "S3_BUCKET_NAME": get_any("S3_BUCKET_NAME", "S3_BUCKET"),
        "S3_BASE_PREFIX": get_any("S3_BASE_PREFIX", "S3_PREFIX"),  # optional
    }


def s3_enabled(cfg: Dict[str, str]) -> bool:
    required = ["S3_BUCKET_NAME", "AWS_REGION", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"]
    return all(cfg.get(k) for k in required) and boto3 is not None


@st.cache_resource(show_spinner=False)
def get_s3_client(cfg: Dict[str, str]):
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


def history_paths(center: str, base_prefix: str = "") -> Tuple[str, str]:
    root = s3_key(base_prefix, "registration_summary", center)
    return root, s3_key(root, "history.csv")


def load_history(s3, cfg, center_key: str) -> pd.DataFrame:
    root, hist_key = history_paths(center_key, cfg.get('S3_BASE_PREFIX', ''))
    b = s3_get_bytes(s3, cfg["S3_BUCKET_NAME"], hist_key)
    if not b:
        return pd.DataFrame()
    try:
        return pd.read_csv(io.BytesIO(b), parse_dates=["day"])
    except:
        return pd.DataFrame()


def load_summary(s3, cfg, center_key: str, day_ts: pd.Timestamp) -> Optional[Dict[str, pd.DataFrame]]:
    root, _ = history_paths(center_key, cfg.get('S3_BASE_PREFIX', ''))
    day_str = pd.to_datetime(day_ts).date().isoformat()
    key = s3_key(root, day_str, "summary.pkl")
    b = s3_get_bytes(s3, cfg["S3_BUCKET_NAME"], key)
    if not b:
        return None
    try:
        return pickle.loads(b)
    except:
        return None


def add_cumulative(hist: pd.DataFrame) -> pd.DataFrame:
    if hist.empty:
        return pd.DataFrame()
    h = hist.sort_values("day").copy()
    for c in ["total_visits", "unique_emr", "unique_visitno", "cash_patients", "pending_patients"]:
        if c in h.columns:
            h[c] = h[c].fillna(0).astype(int)
            h[f"cum_{c}"] = h[c].cumsum()
    return h.sort_values("day", ascending=False).reset_index(drop=True)


# ────────────────────────────────────────────────
# Center selection
# ────────────────────────────────────────────────
CENTERS = {
    "easyhealth": "Easy Health Medical Clinic (MF8031)",
    "excellent":  "Excellent Medical Center (MF4777)",
    "pharmacy":   "Excellent Pharmacy (PF3205)",
}

qp_center = (st.query_params.get("center") or "").strip().lower()
center_key = qp_center if qp_center in CENTERS else None

if center_key:
    st.selectbox("Center", [center_key], format_func=lambda k: CENTERS[k], disabled=True)
else:
    center_key = st.selectbox(
        "Center",
        options=list(CENTERS.keys()),
        format_func=lambda k: CENTERS[k],
        index=0
    )

st.caption(f"**Selected center:** {CENTERS.get(center_key, center_key)}")


# ────────────────────────────────────────────────
# S3 configuration check
# ────────────────────────────────────────────────
cfg = load_secrets()
s3_ok = s3_enabled(cfg)
s3 = get_s3_client(cfg) if s3_ok else None

with st.expander("S3 Connection Status", expanded=not s3_ok):
    if s3_ok:
        prefix = cfg.get('S3_BASE_PREFIX', '')
        full_prefix = f"{prefix}/" if prefix else ""
        st.success(f"**S3 is configured** • Bucket: `{cfg['S3_BUCKET_NAME']}` • Region: `{cfg['AWS_REGION']}`")
        st.caption(f"Reading from: `{full_prefix}registration_summary/{center_key}/…`")
    else:
        st.error("**S3 is NOT configured** → cannot load reports")
        st.markdown("""
        Required secrets / environment variables:
        - `AWS_ACCESS_KEY_ID`
        - `AWS_SECRET_ACCESS_KEY`
        - `AWS_REGION`
        - `S3_BUCKET_NAME`
        """)
        st.stop()


# ────────────────────────────────────────────────
# Load history & show latest day automatically
# ────────────────────────────────────────────────
hist = load_history(s3, cfg, center_key)

if hist.empty or "day" not in hist.columns:
    root, hist_key = history_paths(center_key, cfg.get('S3_BASE_PREFIX', ''))
    st.warning("No daily reports found for this center yet.")
    st.info("Expected location:")
    st.code(hist_key, language="text")
    st.markdown("""
    **Next steps:**
    1. Go to the **Registration Summary (Upload)** page
    2. Upload files and click **Process & Save to S3**
    3. Return here to view results
    """)
    st.stop()

# Normalize & sort days
hist["day"] = pd.to_datetime(hist["day"], errors="coerce").dt.normalize()
hist = hist.dropna(subset=["day"]).sort_values("day")

days = hist["day"].unique()
latest_day = days[-1]
picked_day = pd.to_datetime(latest_day).normalize()

st.caption(f"**Showing latest available day:** {fmt_day(picked_day)}")

# Session state for selected day
ss = st.session_state
ss.setdefault("selected_day", picked_day)
ss.setdefault("loaded_day", None)
ss.setdefault("loaded_summary", None)

with st.expander("View a different day", expanded=False):
    chosen_date = st.date_input(
        "Select date",
        value=picked_day.date(),
        min_value=pd.to_datetime(days.min()).date(),
        max_value=pd.to_datetime(days.max()).date(),
    )
    if st.button("Load this day", use_container_width=True):
        ss["selected_day"] = pd.to_datetime(chosen_date)
        ss["loaded_day"] = None
        ss["loaded_summary"] = None
        st.rerun()

# Decide which day to show
target_day = ss["selected_day"]

# Load summary if needed
if ss["loaded_day"] != target_day:
    summary = load_summary(s3, cfg, center_key, target_day)
    ss["loaded_day"] = target_day
    ss["loaded_summary"] = summary

# ────────────────────────────────────────────────
# Render daily summary
# ────────────────────────────────────────────────
if ss["loaded_summary"]:
    dfs = ss["loaded_summary"]
    day_str = fmt_day(target_day)

    st.header(f"Daily Summary – {day_str}")

    kpi = dfs.get("KPI")
    if kpi is not None and not kpi.empty and "Metric" in kpi.columns and "Value" in kpi.columns:
        k = kpi.set_index("Metric")["Value"]
        cols = st.columns(4)
        cols[0].metric("Total Visits", int(k.get("Total Visits", 0)))
        cols[1].metric("Unique EMR (Patients)", int(k.get("Unique EMR (Patients)", 0)))
        cols[2].metric("Unique Visit No", int(k.get("Unique Visit No", 0)))
        cols[3].metric("CashOut Patients", int(k.get("CashOut Patients", 0)))

        cols = st.columns(2)
        cols[0].metric("Pending Patients", int(k.get("Pending Patients", 0)))
        cols[1].metric("Generated", fmt_dt(datetime.now()))

    st.subheader("Pending Status Wise")
    st.dataframe(dfs.get("Pending Status Wise", pd.DataFrame()), use_container_width=True, hide_index=True)

    st.subheader("Insurance Wise Visits")
    st.dataframe(dfs.get("Insurance Wise Visits", pd.DataFrame()), use_container_width=True, hide_index=True)

    st.subheader("Employer Wise")
    st.dataframe(dfs.get("Employer Wise", pd.DataFrame()), use_container_width=True, hide_index=True)

    st.subheader("Doctor Wise Visits")
    st.dataframe(dfs.get("Doctor Wise Visits", pd.DataFrame()), use_container_width=True, hide_index=True)

    # Income Analysis
    income_tabs = [k for k in dfs if str(k).startswith("Income | ")]
    if income_tabs:
        st.markdown("---")
        st.header("Income Analysis (Doctor Revenue)")

        tab_names = ["Doctor Wise", "Insurance Wise", "Doctor × Insurance"]
        tabs = st.tabs(tab_names)

        with tabs[0]:
            df = dfs.get("Income | Doctor Wise Revenue")
            if df is not None and not df.empty:
                st.dataframe(df, use_container_width=True, hide_index=True)
            else:
                st.info("No doctor-wise revenue data")

        with tabs[1]:
            df = dfs.get("Income | Insurance Wise Revenue")
            if df is not None and not df.empty:
                st.dataframe(df, use_container_width=True, hide_index=True)
            else:
                st.info("No insurance-wise revenue data")

        with tabs[2]:
            df = dfs.get("Income | Doctor x Insurance Revenue")
            if df is not None and not df.empty:
                df_f = df.copy()

                doctors = sorted(df_f["Doctor"].dropna().unique())
                doctors = [d for d in doctors if str(d).strip().lower() not in ["", "none", "nan", "grand total"]]

                if doctors:
                    doc = st.selectbox("Doctor", options=doctors, key="inc_doc")
                    df_f = df_f[df_f["Doctor"] == doc]

                    insurances = ["All"] + sorted(df_f["Insurance"].dropna().unique())
                    ins = st.selectbox("Insurance", options=insurances, key="inc_ins")
                    if ins != "All":
                        df_f = df_f[df_f["Insurance"] == ins]

                st.dataframe(df_f, use_container_width=True, hide_index=True)
            else:
                st.info("No doctor × insurance revenue data")

else:
    st.error(f"No summary found for {fmt_day(target_day)}")
    root, _ = history_paths(center_key, cfg.get('S3_BASE_PREFIX', ''))
    st.caption(f"Expected path: `{root}/{target_day.date().isoformat()}/summary.pkl`")


# ────────────────────────────────────────────────
# Accumulated history
# ────────────────────────────────────────────────
st.header("Accumulated – All Saved Days")
acc = add_cumulative(hist)
st.dataframe(acc, use_container_width=True, hide_index=True)
