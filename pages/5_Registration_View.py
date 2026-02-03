#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Streamlit Page: Registration Summary (View Only)

Purpose
- Management should ONLY view results (no upload).
- Loads the latest saved summary from S3 created by:
    pages/4_Registration_Summary.py  (Process & Save to S3)

Important
- This viewer MUST read the SAME S3 folder structure as the uploader page:
    registration_summary/<center>/<YYYY-MM-DD>/summary.pkl
    registration_summary/<center>/history.csv

So we intentionally IGNORE any `year=` query param for storage paths, unless you
also change the uploader to save year-wise.
"""

import io
import os
import re
import pickle
from datetime import datetime
from typing import Dict, Optional, List, Tuple

import pandas as pd
import streamlit as st

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
        "S3_BASE_PREFIX": get_any("S3_BASE_PREFIX", "S3_PREFIX"),  # optional (unused by default)
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


def history_paths(center: str, base_prefix: str = "") -> Tuple[str, str]:
    """Return (root_prefix, history_csv_key) for this center.

    Must match uploader page logic:
      <S3_BASE_PREFIX>/registration_summary/<center>/...
    If base_prefix is empty:
      registration_summary/<center>/...
    """
    root = s3_key(base_prefix, "registration_summary", center)
    return root, s3_key(root, "history.csv")


def load_history_from_s3(s3, cfg: Dict[str, str], center_key: str) -> pd.DataFrame:
    root, hist_key = history_paths(center_key, cfg.get('S3_BASE_PREFIX',''))
    b = s3_get_bytes(s3, cfg["S3_BUCKET_NAME"], hist_key)
    if not b:
        return pd.DataFrame()
    try:
        return pd.read_csv(io.BytesIO(b), parse_dates=["day"])
    except Exception:
        # fallback if parse fails
        return pd.read_csv(io.BytesIO(b))


def load_summary_from_s3(s3, cfg: Dict[str, str], center_key: str, day_ts: pd.Timestamp) -> Optional[Dict[str, pd.DataFrame]]:
    root, _ = history_paths(center_key, cfg.get('S3_BASE_PREFIX',''))
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
    h = hist.sort_values("day").copy()
    for c in ["total_visits", "unique_emr", "unique_visitno", "cash_patients", "pending_patients"]:
        if c in h.columns:
            h[c] = h[c].fillna(0).astype(int)
            h[f"cum_{c}"] = h[c].cumsum()
    # show latest first
    return h.sort_values("day", ascending=False).reset_index(drop=True)


def render_summary(dfs: Dict[str, pd.DataFrame], day_ts: pd.Timestamp):
    st.header(f"Current Day ({fmt_day(day_ts)})")

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

    st.subheader("Pending Status Wise")
    st.dataframe(dfs.get("Pending Status Wise", pd.DataFrame()), use_container_width=True, hide_index=True)

    st.subheader("Insurance Wise Visits")
    st.dataframe(dfs.get("Insurance Wise Visits", pd.DataFrame()), use_container_width=True, hide_index=True)

    st.subheader("Employer Wise")
    st.dataframe(dfs.get("Employer Wise", pd.DataFrame()), use_container_width=True, hide_index=True)

    st.subheader("Doctor Wise Visits")
    st.dataframe(dfs.get("Doctor Wise Visits", pd.DataFrame()), use_container_width=True, hide_index=True)


    # -------------------- Income Analysis (Doctor Revenue) --------------------
    income_keys = [k for k in dfs.keys() if str(k).startswith("Income | ")]
    if income_keys:
        st.markdown("---")
        st.header("Income Analysis (Doctor Revenue)")

        df_doc = dfs.get("Income | Doctor Wise Revenue")
        df_ins = dfs.get("Income | Insurance Wise Revenue")
        df_dx  = dfs.get("Income | Doctor x Insurance Revenue")

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

                # Filter: pick doctor first
                if "Doctor" in df_f.columns:
                    doctors = sorted([
                        d for d in df_f["Doctor"].dropna().unique()
                        if str(d).strip().lower() not in ["", "none", "nan"]
                        and str(d).strip().upper() != "GRAND TOTAL"
                    ])
                    if doctors:
                        pick_doc = st.selectbox("Select Doctor", options=doctors, key="income_pick_doc")
                        df_f = df_f[df_f["Doctor"] == pick_doc].copy()

                # Filter: pick insurance (optional)
                if "Insurance" in df_f.columns:
                    ins_list = sorted([
                        i for i in df_f["Insurance"].dropna().unique()
                        if str(i).strip().lower() not in ["", "none", "nan"]
                    ])
                    pick_ins = st.selectbox("Select Insurance", options=["All"] + ins_list, key="income_pick_ins")
                    if pick_ins != "All":
                        df_f = df_f[df_f["Insurance"] == pick_ins].copy()

                st.dataframe(df_f, use_container_width=True, hide_index=True)




# ---------------------------
# Center selection (LOCKED if passed in URL)
# ---------------------------
CENTERS = {
    "easyhealth": "Easy Health Medical Clinic (MF8031)",
    "excellent": "Excellent Medical Center (MF4777)",
    "pharmacy": "Excellent Pharmacy (PF3205)",
}

# Streamlit new API: st.query_params is dict-like
qp_center = (st.query_params.get("center") or "").strip()
center_key = qp_center if qp_center in CENTERS else None

if center_key:
    st.selectbox("Center", [center_key], format_func=lambda k: CENTERS[k], disabled=True, key="center_locked")
else:
    center_key = st.selectbox("Center", options=list(CENTERS.keys()), format_func=lambda k: CENTERS[k], key="center_pick")

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
        st.caption(f"Path used: {(cfg.get('S3_BASE_PREFIX','') + '/' if cfg.get('S3_BASE_PREFIX') else '')}registration_summary/<center>/history.csv")
        if cfg.get("S3_BASE_PREFIX"):
            st.caption(f"S3_BASE_PREFIX is set to '{cfg['S3_BASE_PREFIX']}'. Viewer will load from: {cfg['S3_BASE_PREFIX']}/registration_summary/<center>/...")
    else:
        st.error("S3 is NOT configured on this app, so View page cannot load saved results.")
        st.caption("Expected secrets: S3_BUCKET_NAME (or S3_BUCKET), AWS_REGION (or AWS_DEFAULT_REGION), AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY")

if not s3_ok:
    st.stop()

# ---------------------------
# Load history and auto-show latest result
# ---------------------------
hist = load_history_from_s3(s3, cfg, center_key)

if hist.empty or "day" not in hist.columns:
    root, hist_key = history_paths(center_key, cfg.get('S3_BASE_PREFIX',''))
    st.warning("No saved Daily Report found for this center yet.")
    st.write("✅ To fix:")
    st.markdown(
        "- Open **Registration Summary (Upload)** page\n"
        "- Upload Step 1/2/3\n"
        "- Click **Process & Save to S3**\n"
        "- Then come back here"
    )
    st.caption(f"Expected S3 key: {hist_key}")
    st.stop()

# normalize day
hist["day"] = pd.to_datetime(hist["day"], errors="coerce").dt.normalize()
hist = hist.dropna(subset=["day"]).sort_values("day")

days = list(hist["day"].unique())
latest_day = days[-1]


# pick day UI (LATEST ONLY by default)
latest = max(days)
picked = pd.to_datetime(latest).normalize()

st.caption(f"Showing latest saved day: **{picked.date().strftime('%d %b %Y')}**")

SS = st.session_state
SS.setdefault("loaded_day", None)
SS.setdefault("loaded_summary", None)
SS.setdefault("picked_override", None)

with st.expander("View another day (optional)", expanded=False):
    other = st.date_input(
        "Select a different day",
        value=picked.date(),
        min_value=pd.to_datetime(min(days)).date(),
        max_value=pd.to_datetime(latest).date(),
    )
    if st.button("Load selected day", use_container_width=True):
        SS["picked_override"] = pd.to_datetime(other).normalize()
        SS["loaded_day"] = None
        SS["loaded_summary"] = None
        st.rerun()

if SS.get("picked_override") is not None:
    picked = pd.to_datetime(SS["picked_override"]).normalize()
need_load = (SS["loaded_day"] is None) or (pd.to_datetime(SS["loaded_day"]) != picked)

if need_load:
    loaded = load_summary_from_s3(s3, cfg, center_key, picked)
    if loaded is None:
        st.error("history.csv exists, but summary.pkl is missing for this day.")
        root, _ = history_paths(center_key, cfg.get('S3_BASE_PREFIX',''))
        st.caption(f"Expected: {s3_key(root, picked.date().isoformat(), 'summary.pkl')}")
        SS["loaded_day"] = picked
        SS["loaded_summary"] = None
    else:
        SS["loaded_day"] = picked
        SS["loaded_summary"] = loaded

if SS.get("loaded_summary") is not None:
    render_summary(SS["loaded_summary"], pd.to_datetime(SS["loaded_day"]))

st.header("Accumulated (All Saved Days)")
acc = add_cumulative(hist)
st.dataframe(acc, use_container_width=True, hide_index=True)
