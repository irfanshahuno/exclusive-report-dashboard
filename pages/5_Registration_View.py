#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Streamlit Page: Registration Summary - VIEW ONLY (from S3)

- No uploads
- Loads history.csv + summary.pkl from S3
- Shows KPI + key tables
- Works with query params:
    ?center=excellent
    ?center=easyhealth
    ?center=pharmacy

S3 structure expected (same as your admin page):
  registration_summary/<center>/history.csv
  registration_summary/<center>/<YYYY-MM-DD>/summary.pkl
"""

import io
import os
import pickle
from datetime import datetime
from typing import Dict, Optional, List

import pandas as pd
import streamlit as st

# Optional S3
try:
    import boto3
except Exception:
    boto3 = None

st.set_page_config(
    page_title="Registration Summary (View)",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.title("📅 Registration Summary (View Only)")

# ---------------------------
# Centers
# ---------------------------
CENTERS = {
    "easyhealth": "Easy Health Medical Clinic (MF8031)",
    "excellent": "Excellent Medical Center (MF4777)",
    "pharmacy": "Excellent Pharmacy (PF3205)",
}

# ---------------------------
# Secrets / env loader
# ---------------------------
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
        # NOTE: your admin page intentionally saves at top-level "registration_summary/..."
        "S3_BASE_PREFIX": get_any("S3_BASE_PREFIX", "S3_PREFIX"),
    }

def s3_enabled(cfg: Dict[str, str]) -> bool:
    return (
        boto3 is not None
        and bool(cfg.get("S3_BUCKET_NAME"))
        and bool(cfg.get("AWS_REGION"))
        and bool(cfg.get("AWS_ACCESS_KEY_ID"))
        and bool(cfg.get("AWS_SECRET_ACCESS_KEY"))
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

def s3_key(*parts: str) -> str:
    return "/".join([p.strip("/").strip() for p in parts if p is not None and str(p).strip() != ""])

def s3_get_bytes(s3, bucket: str, key: str) -> Optional[bytes]:
    try:
        obj = s3.get_object(Bucket=bucket, Key=key)
        return obj["Body"].read()
    except Exception:
        return None

def history_paths(center: str):
    # same as your admin page
    root = s3_key("registration_summary", center)
    return root, s3_key(root, "history.csv")

def load_history_from_s3(s3, cfg: Dict[str, str], center: str) -> pd.DataFrame:
    _, hist_key = history_paths(center)
    b = s3_get_bytes(s3, cfg["S3_BUCKET_NAME"], hist_key)
    if not b:
        return pd.DataFrame()
    try:
        return pd.read_csv(io.BytesIO(b), parse_dates=["day"])
    except Exception:
        return pd.DataFrame()

def load_summary_from_s3(s3, cfg: Dict[str, str], center: str, day_ts: pd.Timestamp):
    root, _ = history_paths(center)
    day_str = pd.to_datetime(day_ts).date().isoformat()
    key = s3_key(root, day_str, "summary.pkl")
    b = s3_get_bytes(s3, cfg["S3_BUCKET_NAME"], key)
    if not b:
        return None
    try:
        return pickle.loads(b)
    except Exception:
        return None

def add_cumulative(hist: pd.DataFrame) -> pd.DataFrame:
    if hist is None or hist.empty:
        return pd.DataFrame()

    h = hist.copy()
    h["day"] = pd.to_datetime(h["day"]).dt.normalize()
    h = h.sort_values("day").copy()

    for c in ["total_visits", "unique_emr", "unique_visitno", "cash_patients", "pending_patients"]:
        if c not in h.columns:
            h[c] = 0
        h[c] = pd.to_numeric(h[c], errors="coerce").fillna(0).astype(int)
        h[f"cum_{c}"] = h[c].cumsum()

    cols = [
        "day",
        "total_visits", "unique_emr", "unique_visitno", "cash_patients", "pending_patients",
        "cum_total_visits", "cum_unique_emr", "cum_unique_visitno", "cum_cash_patients", "cum_pending_patients",
    ]
    cols = [c for c in cols if c in h.columns]
    # newest first
    return h[cols].sort_values("day", ascending=False).reset_index(drop=True)

def render_summary(dfs: Dict[str, pd.DataFrame], day_ts: pd.Timestamp):
    st.header(f"Current Day ({day_ts.date().isoformat()})")

    # KPI cards
    kpi = dfs.get("KPI")
    if kpi is not None and not kpi.empty and "Metric" in kpi.columns and "Value" in kpi.columns:
        k = kpi.set_index("Metric")["Value"]
        a, b, c, d = st.columns(4)
        a.metric("Total Visits", int(float(k.get("Total Visits", 0) or 0)))
        b.metric("Unique EMR (Patients)", int(float(k.get("Unique EMR (Patients)", 0) or 0)))
        c.metric("Unique Visit No", int(float(k.get("Unique Visit No", 0) or 0)))
        d.metric("CashOut Patients", int(float(k.get("CashOut Patients", 0) or 0)))
        e, f = st.columns(2)
        e.metric("Pending Patients", int(float(k.get("Pending Patients", 0) or 0)))
        f.metric("Loaded", datetime.now().strftime("%Y-%m-%d %H:%M"))
    else:
        st.info("KPI not available in this saved summary.")

    # Order you wanted (Pending Status -> Insurance -> Employer -> Doctor)
    st.subheader("Pending Status Wise")
    st.dataframe(dfs.get("Pending Status Wise", pd.DataFrame()), use_container_width=True, hide_index=True)

    st.subheader("Insurance Wise Visits")
    st.dataframe(dfs.get("Insurance Wise Visits", pd.DataFrame()), use_container_width=True, hide_index=True)

    st.subheader("Employer Wise")
    st.dataframe(dfs.get("Employer Wise", pd.DataFrame()), use_container_width=True, hide_index=True)

    st.subheader("Doctor Wise Visits")
    st.dataframe(dfs.get("Doctor Wise Visits", pd.DataFrame()), use_container_width=True, hide_index=True)

    st.markdown("---")
    st.header("Accumulated (All Saved Days)")
    st.session_state["_last_hist_render"] = True  # marker

# ---------------------------
# Read center from session/query
# ---------------------------
center_key = (
    st.session_state.get("center_key")
    or st.query_params.get("center")
    or None
)

if center_key not in CENTERS:
    # only show selector if not provided
    center_key = st.selectbox(
        "Center",
        options=list(CENTERS.keys()),
        format_func=lambda k: CENTERS[k],
    )

st.caption(f"Center: **{CENTERS.get(center_key, center_key)}**")

# ---------------------------
# S3 connect
# ---------------------------
cfg = load_secrets()
s3_ok = s3_enabled(cfg)
s3 = s3_client_cached(cfg) if s3_ok else None

with st.expander("Storage Status (S3)", expanded=False):
    if s3_ok:
        st.success(f"S3 OK ✅  Bucket: {cfg['S3_BUCKET_NAME']}  Region: {cfg['AWS_REGION']}")
    else:
        st.error("S3 is NOT configured. Add secrets: AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION, S3_BUCKET_NAME.")

if not s3_ok:
    st.stop()

# ---------------------------
# Load history + allow pick day
# ---------------------------
hist = load_history_from_s3(s3, cfg, center_key)
if hist.empty:
    st.warning("No history.csv found yet for this center. First run 'Process & Save to S3' in the admin page.")
    st.stop()

hist["day"] = pd.to_datetime(hist["day"]).dt.normalize()
days = sorted(hist["day"].unique())
days_ui = list(reversed(days))  # newest first

picked = st.selectbox(
    "Select day to view",
    options=days_ui,
    format_func=lambda x: pd.to_datetime(x).date().isoformat(),
)

dfs = load_summary_from_s3(s3, cfg, center_key, pd.to_datetime(picked))
if not dfs:
    st.warning("summary.pkl not found for this day. (Maybe only history.csv exists.)")
    st.stop()

render_summary(dfs, pd.to_datetime(picked))

# show accumulated table under
acc = add_cumulative(hist)
st.dataframe(acc, use_container_width=True, hide_index=True)
