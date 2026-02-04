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
    registration/<center>/<YYYY-MM-DD>/summary.pkl
    registration/<center>/history.csv

So we intentionally IGNORE any `year=` query param for storage paths, unless you
also change the uploader to save year-wise.
"""

import io
import os
import re
import pickle
from datetime import datetime, date
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


def s3_key_exists(s3, bucket: str, key: str) -> bool:
    try:
        s3.head_object(Bucket=bucket, Key=key)
        return True
    except Exception:
        return False


def candidate_base_prefixes(cfg: Dict[str, str]) -> List[str]:
    """Try a few likely prefixes so the viewer works even if uploader/viewer prefixes differ."""
    prefs: List[str] = []
    p = (cfg.get("S3_BASE_PREFIX") or "").strip().strip("/")
    if p:
        prefs.append(p)
    # common fallbacks
    prefs.append("")  # root of bucket
    if "streamlit" not in prefs:
        prefs.append("streamlit")
    # de-dup while preserving order
    out: List[str] = []
    for x in prefs:
        x = (x or "").strip().strip("/")
        if x not in out:
            out.append(x)
    return out


def history_paths(center: str, base_prefix: str = "") -> Tuple[str, str]:
    """Return (root_prefix, history_csv_key) for this center.

    Expected uploader layout (based on your S3 screenshots):
      <base_prefix>/registration/<center>/history.csv
      <base_prefix>/registration/<center>/<YYYY-MM-DD>/summary.pkl
    """
    root = s3_key(base_prefix, "registration", center)
    return root, s3_key(root, "history.csv")


def resolve_center_root_from_s3(s3, cfg: Dict[str, str], center_key: str) -> Tuple[str, str]:
    """Return (root_prefix, history_csv_key) that actually exists in S3."""
    bucket = cfg["S3_BUCKET_NAME"]
    for pref in candidate_base_prefixes(cfg):
        root, hist_key = history_paths(center_key, pref)
        if s3_key_exists(s3, bucket, hist_key):
            return root, hist_key
    # default to the configured prefix path (even if missing), for clearer error messages
    root, hist_key = history_paths(center_key, (cfg.get("S3_BASE_PREFIX") or ""))
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


def load_summary_from_s3(
    s3,
    cfg: Dict[str, str],
    root_prefix: str,
    day_ts: pd.Timestamp
) -> Optional[Dict[str, pd.DataFrame]]:
    day_str = pd.to_datetime(day_ts).date().isoformat()
    key = s3_key(root_prefix, day_str, "summary.pkl")
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
                        pick_doc = st.selectbox("Select Doctor", options=doctors, key=f"income_pick_doc_{str(day_ts)}")
                        df_f = df_f[df_f["Doctor"] == pick_doc].copy()

                # Filter: pick insurance (optional)
                if "Insurance" in df_f.columns:
                    ins_list = sorted([
                        i for i in df_f["Insurance"].dropna().unique()
                        if str(i).strip().lower() not in ["", "none", "nan"] and str(i).strip().upper() != "GRAND TOTAL"
                    ])
                    pick_ins = st.selectbox("Select Insurance", options=["All"] + ins_list, key=f"income_pick_ins_{str(day_ts)}")
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
        prefs = candidate_base_prefixes(cfg)
        st.caption('Viewer will look for: ' + '  |  '.join([((p + '/') if p else '') + 'registration/<center>/history.csv' for p in prefs]))
    else:
        st.error("S3 is NOT configured on this app, so View page cannot load saved results.")
        st.caption("Expected secrets: S3_BUCKET_NAME (or S3_BUCKET), AWS_REGION (or AWS_DEFAULT_REGION), AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY")

if not s3_ok:
    st.stop()

# ---------------------------
# Load history and auto-show latest result
# ---------------------------
hist, root_prefix = load_history_from_s3(s3, cfg, center_key)

if hist.empty or "day" not in hist.columns:
    hist_key = s3_key(root_prefix, 'history.csv')
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


# ---------------------------
# View mode: Daily / Weekly / Monthly
# ---------------------------
st.markdown("---")
mode = st.radio("View Mode", options=["Daily", "Weekly", "Monthly"], horizontal=True, index=0)

SS = st.session_state
SS.setdefault("loaded_key", None)      # cache key (string) for loaded period
SS.setdefault("loaded_summary", None)  # dict of dfs
SS.setdefault("loaded_label", None)    # title label

def days_in_week(any_day: pd.Timestamp) -> List[pd.Timestamp]:
    d = pd.to_datetime(any_day).normalize()
    start = d - pd.Timedelta(days=int(d.weekday()))  # Monday
    end = start + pd.Timedelta(days=6)
    return [x for x in days if (x >= start) and (x <= end)]

def days_in_month(any_day: pd.Timestamp) -> List[pd.Timestamp]:
    d = pd.to_datetime(any_day).normalize()
    start = d.replace(day=1)
    # next month
    if start.month == 12:
        nxt = start.replace(year=start.year+1, month=1, day=1)
    else:
        nxt = start.replace(month=start.month+1, day=1)
    end = nxt - pd.Timedelta(days=1)
    return [x for x in days if (x >= start) and (x <= end)]

def aggregate_tables(frames: List[pd.DataFrame]) -> pd.DataFrame:
    frames = [f for f in frames if f is not None and not f.empty]
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)

    # Keep only real rows (drop total/grand total rows; we'll rebuild totals)
    def _is_total_row(x):
        s = str(x).strip().upper()
        return s in ["TOTAL", "GRAND TOTAL"]
    first_col = df.columns[0] if len(df.columns) else None
    if first_col:
        df = df[~df[first_col].astype(str).map(_is_total_row)].copy()

    # Group by non-numeric columns, sum numeric
    num_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    grp_cols = [c for c in df.columns if c not in num_cols]
    if num_cols and grp_cols:
        out = df.groupby(grp_cols, dropna=False, as_index=False)[num_cols].sum()
    elif "Count" in df.columns:
        grp_cols = [c for c in df.columns if c != "Count"]
        out = df.groupby(grp_cols, dropna=False, as_index=False)["Count"].sum()
    else:
        out = df

    # Re-add TOTAL / GRAND TOTAL
    if "Count" in out.columns and first_col:
        total = int(out["Count"].sum()) if not out.empty else 0
        out.loc[len(out)] = {first_col: "TOTAL", "Count": total}
    else:
        # If there is any numeric column, add GRAND TOTAL
        if num_cols and first_col:
            row = {c: "" for c in out.columns}
            row[first_col] = "GRAND TOTAL"
            for c in num_cols:
                row[c] = float(out[c].sum()) if not out.empty else 0.0
            out.loc[len(out)] = row

    return out

def load_and_aggregate(day_list: List[pd.Timestamp]) -> Optional[Dict[str, pd.DataFrame]]:
    if not day_list:
        return None
    loaded = []
    for d in day_list:
        dfs = load_summary_from_s3(s3, cfg, root_prefix, d)
        if dfs is not None:
            loaded.append(dfs)

    if not loaded:
        return None

    keys = sorted(set().union(*[set(x.keys()) for x in loaded]))
    agg: Dict[str, pd.DataFrame] = {}

    # KPI: sum across days (note: unique patients across a period is approximate because we only have daily aggregates)
    kpi_rows = []
    for d in loaded:
        k = d.get("KPI")
        if k is not None and not k.empty and "Metric" in k.columns and "Value" in k.columns:
            kpi_rows.append(k)
    if kpi_rows:
        kk = pd.concat(kpi_rows, ignore_index=True)
        kk["Value"] = pd.to_numeric(kk["Value"], errors="coerce").fillna(0)
        kpi_sum = kk.groupby("Metric", as_index=False)["Value"].sum()
        agg["KPI"] = kpi_sum

    for k in keys:
        if k == "KPI":
            continue
        frames = [d.get(k) for d in loaded if isinstance(d.get(k), pd.DataFrame)]
        agg[k] = aggregate_tables(frames)

    return agg

if mode == "Daily":
    latest = max(days)
    picked = pd.to_datetime(latest).normalize()

    c1, c2 = st.columns([3, 1])
    with c1:
        st.caption(f"Showing latest saved day: **{picked.date().strftime('%d %b %Y')}**")
    with c2:
        if st.button("Today", use_container_width=True):
            today = pd.to_datetime(date.today()).normalize()
            if today in days:
                SS["loaded_key"] = None
                SS["loaded_summary"] = None
                SS["loaded_label"] = None
                SS["picked_override"] = today
            else:
                SS["picked_override"] = picked
            st.rerun()

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
            SS["loaded_key"] = None
            SS["loaded_summary"] = None
            SS["loaded_label"] = None
            st.rerun()

    if SS.get("picked_override") is not None:
        picked = pd.to_datetime(SS["picked_override"]).normalize()

    cache_key = f"daily:{picked.date().isoformat()}"
    if SS.get("loaded_key") != cache_key:
        loaded = load_summary_from_s3(s3, cfg, root_prefix, picked)
        SS["loaded_key"] = cache_key
        SS["loaded_summary"] = loaded
        SS["loaded_label"] = f"Current Day ({fmt_day(picked)})"

    if SS.get("loaded_summary") is not None:
        render_summary(SS["loaded_summary"], picked)
    else:
        st.error("summary.pkl is missing for this day.")
        st.caption(f"Expected: {s3_key(root_prefix, picked.date().isoformat(), 'summary.pkl')}")

elif mode == "Weekly":
    base = pd.to_datetime(latest_day).normalize()
    pick = st.date_input("Pick any date in the week", value=base.date())
    d0 = pd.to_datetime(pick).normalize()
    week_days = days_in_week(d0)

    if not week_days:
        st.warning("No saved days found for that week.")
    else:
        start_w = min(week_days).date().isoformat()
        end_w = max(week_days).date().isoformat()
        st.caption(f"Week range: **{start_w} → {end_w}**  (saved days: {len(week_days)})")

        cache_key = f"week:{start_w}:{end_w}"
        if SS.get("loaded_key") != cache_key:
            SS["loaded_summary"] = load_and_aggregate(week_days)
            SS["loaded_key"] = cache_key
            SS["loaded_label"] = f"Weekly Summary ({start_w} → {end_w})"

        if SS.get("loaded_summary") is not None:
            st.header(SS.get("loaded_label", "Weekly Summary"))
            render_summary(SS["loaded_summary"], pd.to_datetime(max(week_days)))
            st.info("Note: 'Unique EMR' for week is an approximate sum of daily unique EMR counts.")
        else:
            st.warning("No summary.pkl files found for that week.")

else:  # Monthly
    base = pd.to_datetime(latest_day).normalize()
    # Build available months from history
    months = sorted({pd.to_datetime(d).strftime("%Y-%m") for d in days})
    default_m = pd.to_datetime(base).strftime("%Y-%m")
    sel_month = st.selectbox("Select Month", options=months, index=months.index(default_m) if default_m in months else len(months)-1)
    d0 = pd.to_datetime(sel_month + "-01").normalize()
    month_days = days_in_month(d0)

    if not month_days:
        st.warning("No saved days found for that month.")
    else:
        start_m = min(month_days).date().isoformat()
        end_m = max(month_days).date().isoformat()
        st.caption(f"Month range: **{start_m} → {end_m}**  (saved days: {len(month_days)})")

        cache_key = f"month:{sel_month}"
        if SS.get("loaded_key") != cache_key:
            SS["loaded_summary"] = load_and_aggregate(month_days)
            SS["loaded_key"] = cache_key
            SS["loaded_label"] = f"Monthly Summary ({sel_month})"

        if SS.get("loaded_summary") is not None:
            st.header(SS.get("loaded_label", "Monthly Summary"))
            render_summary(SS["loaded_summary"], pd.to_datetime(max(month_days)))
            st.info("Note: 'Unique EMR' for month is an approximate sum of daily unique EMR counts.")
        else:
            st.warning("No summary.pkl files found for that month.")

st.header("Accumulated (All Saved Days)")
acc = add_cumulative(hist)
st.dataframe(acc, use_container_width=True, hide_index=True)
