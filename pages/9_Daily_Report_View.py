#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import io
import os
import re
import json
import pickle
from datetime import datetime
from typing import Dict, Tuple, Optional, List

import pandas as pd
import streamlit as st

# Optional S3
try:
    import boto3
except Exception:
    boto3 = None

st.set_page_config(page_title="Daily Report (View)", layout="wide", initial_sidebar_state="collapsed")
st.title("📅 Daily Report")
st.caption("Management view — result only (loads latest saved summary from S3)")

# ---------------------------
# Centers
# ---------------------------
CENTERS = {
    "easyhealth": "Easy Health Medical Clinic (MF8031)",
    "excellent": "Excellent Medical Center (MF4777)",
    "pharmacy": "Excellent Pharmacy (PF3205)",
}

# ---------------------------
# Helpers (same style as your upload page)
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


def history_paths(center: str) -> Tuple[str, str]:
    # same as upload page
    root = s3_key("registration_summary", center)
    return root, s3_key(root, "history.csv")


def load_history_from_s3(s3, cfg, center: str) -> pd.DataFrame:
    root, hist_key = history_paths(center)
    b = s3_get_bytes(s3, cfg["S3_BUCKET_NAME"], hist_key)
    if not b:
        return pd.DataFrame()
    return pd.read_csv(io.BytesIO(b), parse_dates=["day"])


def load_summary_from_s3(s3, cfg, center: str, day_ts: pd.Timestamp) -> Optional[Dict[str, pd.DataFrame]]:
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


def excel_bytes_from_dfs(dfs: Dict[str, pd.DataFrame]) -> bytes:
    bio = io.BytesIO()
    with pd.ExcelWriter(bio, engine="openpyxl") as writer:
        for name, df in dfs.items():
            df.to_excel(writer, sheet_name=str(name)[:31], index=False)
    bio.seek(0)
    return bio.read()


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
        "cum_total_visits", "cum_unique_emr", "cum_unique_visitno", "cum_cash_patients", "cum_pending_patients"
    ]
    cols = [c for c in cols if c in h.columns]
    out = h[cols].sort_values("day", ascending=False).reset_index(drop=True)
    return out


def render_summary_view(dfs: Dict[str, pd.DataFrame], day_ts: pd.Timestamp, center_key: str):
    st.header(f"{CENTERS.get(center_key, center_key)} — Current Day ({day_ts.date().isoformat()})")

    # KPI cards
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
        f.metric("Loaded", datetime.now().strftime("%Y-%m-%d %H:%M"))
    else:
        st.info("KPI is not available in this saved summary.")

    # Tables (same order you used)
    st.subheader("Pending Status Wise")
    if "Pending Status Wise" in dfs:
        st.dataframe(dfs["Pending Status Wise"], use_container_width=True, hide_index=True)
    else:
        st.info("Pending Status Wise is not available for this saved summary.")

    st.subheader("Insurance Wise Visits")
    if "Insurance Wise Visits" in dfs:
        st.dataframe(dfs["Insurance Wise Visits"], use_container_width=True, hide_index=True)

    st.subheader("Employer Wise")
    if "Employer Wise" in dfs:
        st.dataframe(dfs["Employer Wise"], use_container_width=True, hide_index=True)

    st.subheader("Doctor Wise Visits")
    if "Doctor Wise Visits" in dfs:
        st.dataframe(dfs["Doctor Wise Visits"], use_container_width=True, hide_index=True)

    # Download whole summary (management can download if needed)
    st.markdown("---")
    st.download_button(
        "⬇️ Download Summary Excel",
        data=excel_bytes_from_dfs({k: dfs[k] for k in dfs.keys()}),
        file_name=f"Daily_Report_{center_key}_{day_ts.date().isoformat()}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True
    )

    # Note: Row-level downloads depend on raw uploaded DFs (SS['reg_df'], etc.)
    # In view mode we don't have them, so we intentionally remove those sections.


# ---------------------------
# 1) Get center from URL/session (NO selector)
# ---------------------------
center_key = st.session_state.get("center_key") or st.query_params.get("center") or None
if center_key:
    center_key = str(center_key).strip().lower()

if center_key not in CENTERS:
    st.error("Center not found in URL/session. Please open Daily Report from the main dashboard center button.")
    st.caption("Expected URL like:  .../9_Daily_Report_View?center=excellent")
    st.stop()

# ---------------------------
# 2) S3 connect
# ---------------------------
cfg = load_secrets()
if not s3_enabled(cfg):
    st.error("S3 is not configured. This view page needs S3 to load saved results.")
    st.stop()

s3 = s3_client_cached(cfg)
if s3 is None:
    st.error("Could not initialize S3 client.")
    st.stop()

# ---------------------------
# 3) Load latest day from history.csv (auto)
# ---------------------------
hist = load_history_from_s3(s3, cfg, center_key)
if hist.empty:
    st.warning("No saved history found yet for this center. Reception must upload & save first.")
    st.stop()

hist["day"] = pd.to_datetime(hist["day"], errors="coerce").dt.normalize()
hist = hist.dropna(subset=["day"])
if hist.empty:
    st.warning("history.csv exists but has no valid 'day' values.")
    st.stop()

latest_day = hist["day"].max()
dfs = load_summary_from_s3(s3, cfg, center_key, latest_day)
if not dfs:
    st.warning(f"Found history, but summary.pkl not found for latest day: {latest_day.date().isoformat()}")
    st.stop()

# ---------------------------
# 4) Render current + accumulated
# ---------------------------
render_summary_view(dfs, latest_day, center_key)

st.header("Accumulated (All Saved Days)")
acc = add_cumulative(hist)
if acc.empty:
    st.info("No accumulated data available.")
else:
    latest = acc.sort_values("day").iloc[0]  # acc already desc, but safe
    a, b, c, d = st.columns(4)
    a.metric("Cumulative Visits", int(latest.get("cum_total_visits", 0)))
    b.metric("Cumulative Unique EMR", int(latest.get("cum_unique_emr", 0)))
    c.metric("Cumulative CashOut", int(latest.get("cum_cash_patients", 0)))
    d.metric("Cumulative Pending", int(latest.get("cum_pending_patients", 0)))
    st.dataframe(acc, use_container_width=True, hide_index=True)

