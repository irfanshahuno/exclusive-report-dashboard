#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Streamlit Page: Registration Summary (View Only)

What this page does:
- Shows ONLY saved results from S3 (no uploads, no processing).
- Auto-picks Center from URL query param:
    ?center=excellent   OR ?center=easyhealth OR ?center=pharmacy
- Auto-picks Day from S3 history.csv (newest day by default).
- Shows the same "Current Day" tables + "Accumulated" section.

Works with the S3 structure used by your Registration Summary uploader:
  registration_summary/<center>/<YYYY-MM-DD>/{summary.pkl, registration.xlsx, cashout.xlsx, pending.xlsx}
  registration_summary/<center>/history.csv
"""

import io
import os
import re
import pickle
from datetime import datetime, date
from typing import Dict, Tuple, Optional, List

import pandas as pd
import streamlit as st

# Optional S3
try:
    import boto3
    from botocore.exceptions import ClientError
except Exception:
    boto3 = None
    ClientError = Exception


# ---------------------------
# Page config
# ---------------------------
st.set_page_config(page_title="Registration Summary (View Only)", layout="wide", initial_sidebar_state="collapsed")
st.title("🗓️ Registration Summary (View Only)")


# ---------------------------
# Centers
# ---------------------------
CENTERS = {
    "easyhealth": "Easy Health Medical Clinic (MF8031)",
    "excellent": "Excellent Medical Center (MF4777)",
    "pharmacy": "Excellent Pharmacy (PF3205)",
}


# ---------------------------
# S3 helpers (same logic as your uploader page)
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
        "S3_BASE_PREFIX": get_any("S3_BASE_PREFIX", "S3_PREFIX"),
    }


def s3_enabled(cfg: Dict[str, str]) -> bool:
    return bool(cfg.get("S3_BUCKET_NAME")) and bool(cfg.get("AWS_REGION")) and bool(cfg.get("AWS_ACCESS_KEY_ID")) and bool(cfg.get("AWS_SECRET_ACCESS_KEY")) and boto3 is not None


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


def history_paths(center: str) -> Tuple[str, str]:
    # IMPORTANT: keep same root used by uploader page
    root = s3_key("registration_summary", center)
    return root, s3_key(root, "history.csv")


def load_history_from_s3(s3, cfg: Dict[str, str], center_key: str) -> pd.DataFrame:
    root, hist_key = history_paths(center_key)
    b = s3_get_bytes(s3, cfg["S3_BUCKET_NAME"], hist_key)
    if not b:
        return pd.DataFrame()
    return pd.read_csv(io.BytesIO(b), parse_dates=["day"])


def load_summary_from_s3(s3, cfg: Dict[str, str], center_key: str, day_ts: pd.Timestamp) -> Optional[Dict[str, pd.DataFrame]]:
    root, _ = history_paths(center_key)
    day_str = pd.to_datetime(day_ts).date().isoformat()
    key = s3_key(root, day_str, "summary.pkl")
    b = s3_get_bytes(s3, cfg["S3_BUCKET_NAME"], key)
    if not b:
        return None
    try:
        return pickle.loads(b)
    except Exception:
        return None


# ---------------------------
# UI helpers
# ---------------------------
def add_cumulative(hist: pd.DataFrame) -> pd.DataFrame:
    if hist is None or hist.empty:
        return pd.DataFrame()
    h = hist.sort_values("day").copy()
    for c in ["total_visits", "unique_emr", "unique_visitno", "cash_patients", "pending_patients"]:
        if c in h.columns:
            h[c] = h[c].fillna(0).astype(int)
            h[f"cum_{c}"] = h[c].cumsum()
    cols = [
        "day", "total_visits", "unique_emr", "unique_visitno", "cash_patients", "pending_patients",
        "cum_total_visits", "cum_unique_emr", "cum_unique_visitno", "cum_cash_patients", "cum_pending_patients",
    ]
    cols = [c for c in cols if c in h.columns]
    return h[cols].sort_values("day", ascending=False).reset_index(drop=True)


def render_summary(dfs: Dict[str, pd.DataFrame], day_ts: pd.Timestamp):
    st.header(f"Current Day ({day_ts.date().isoformat()})")

    kpi = dfs.get("KPI")
    if kpi is not None and not kpi.empty and {"Metric", "Value"}.issubset(set(kpi.columns)):
        k = kpi.set_index("Metric")["Value"]
        a, b, c, d = st.columns(4)
        a.metric("Total Visits", int(k.get("Total Visits", 0)))
        b.metric("Unique EMR (Patients)", int(k.get("Unique EMR (Patients)", 0)))
        c.metric("Unique Visit No", int(k.get("Unique Visit No", 0)))
        d.metric("CashOut Patients", int(k.get("CashOut Patients", 0)))
        e, f = st.columns(2)
        e.metric("Pending Patients", int(k.get("Pending Patients", 0)))
        f.metric("Generated", datetime.now().strftime("%Y-%m-%d %H:%M"))
    else:
        st.info("KPI is not available for this day.")

    def show_table(title: str, key: str):
        st.subheader(title)
        if key in dfs and isinstance(dfs[key], pd.DataFrame):
            st.dataframe(dfs[key], use_container_width=True, hide_index=True)
        else:
            st.info(f"{title} is not available for this saved day.")

    show_table("Pending Status Wise", "Pending Status Wise")
    show_table("Insurance Wise Visits", "Insurance Wise Visits")
    show_table("Employer Wise", "Employer Wise")
    show_table("Doctor Wise Visits", "Doctor Wise Visits")

    st.markdown("---")
    st.header("Accumulated (All Saved Days)")
    if st.session_state.get("_hist") is None or st.session_state["_hist"].empty:
        st.info("No saved history found yet.")
    else:
        acc = add_cumulative(st.session_state["_hist"])
        latest = acc.sort_values("day").iloc[-1]
        a, b, c, d = st.columns(4)
        a.metric("Cumulative Visits", int(latest.get("cum_total_visits", 0)))
        b.metric("Cumulative Unique EMR", int(latest.get("cum_unique_emr", 0)))
        c.metric("Cumulative CashOut", int(latest.get("cum_cash_patients", 0)))
        d.metric("Cumulative Pending", int(latest.get("cum_pending_patients", 0)))
        st.dataframe(acc, use_container_width=True, hide_index=True)


# ---------------------------
# Center selection (AUTO from URL)
# ---------------------------
qp_center = st.query_params.get("center")
center_from_url = qp_center if qp_center in CENTERS else None

# If URL provided, we lock the center (so it does NOT show wrong name by mistake)
if center_from_url:
    center_key = center_from_url
    st.session_state["center_key"] = center_key
    st.selectbox(
        "Center",
        options=list(CENTERS.keys()),
        index=list(CENTERS.keys()).index(center_key),
        format_func=lambda k: CENTERS[k],
        disabled=True,
        key="center_locked",
    )
else:
    # Normal selectable
    center_key = st.session_state.get("center_key") or "easyhealth"
    if center_key not in CENTERS:
        center_key = "easyhealth"
    center_key = st.selectbox("Center", options=list(CENTERS.keys()), index=list(CENTERS.keys()).index(center_key), format_func=lambda k: CENTERS[k])
    st.session_state["center_key"] = center_key

st.caption(f"Center: **{CENTERS[center_key]}**")


# ---------------------------
# Load from S3
# ---------------------------
cfg = load_secrets()
s3_ok = s3_enabled(cfg)
s3 = s3_client_cached(cfg) if s3_ok else None

with st.expander("Storage Status (S3)", expanded=False):
    if s3_ok:
        st.success(f"S3 is configured ✅  Bucket: {cfg['S3_BUCKET_NAME']}  Region: {cfg['AWS_REGION']}")
        st.caption(f"Base prefix: {cfg.get('S3_BASE_PREFIX') or '(none)'}")
    else:
        st.error("S3 is NOT configured in secrets/env. View-only page cannot load saved results.")

if not s3_ok:
    st.stop()

hist = load_history_from_s3(s3, cfg, center_key)
st.session_state["_hist"] = hist

if hist.empty:
    st.warning("No history.csv found yet for this center in S3.")
    st.stop()

days = sorted(pd.to_datetime(hist["day"]).dt.normalize().unique())
days_ui = list(reversed(days))  # newest first

# Auto-select the newest day by default
default_day = days_ui[0]
picked = st.selectbox(
    "Select saved day",
    options=days_ui,
    index=0,
    format_func=lambda x: pd.to_datetime(x).date().isoformat(),
)

dfs = load_summary_from_s3(s3, cfg, center_key, pd.to_datetime(picked))
if not dfs:
    st.warning("No saved summary.pkl found for that day.")
    st.stop()

render_summary(dfs, pd.to_datetime(picked))
