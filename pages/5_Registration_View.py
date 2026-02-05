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
        a, b, c = st.columns(3)
        a.metric("Total Visits", int(k.get("Total Visits", 0)))
        b.metric("New Patients", int(k.get("New Patients", 0)))
        c.metric("Established Patients", int(k.get("Established Patients", 0)))

        d, e, f = st.columns(3)
        d.metric("Follow Up", int(k.get("Follow Up", 0)))
        e.metric("Unclassified Visits", int(k.get("Unclassified Visits", 0)))
        f.metric("Pending Patients", int(k.get("Pending Patients", 0)))
        st.caption(f"Generated: **{fmt_dt(datetime.now())}**")
    else:
        st.info("KPI is not available for this day.")

    st.subheader("Pending Status Wise")
    st.dataframe(dfs.get("Pending Status Wise", pd.DataFrame()), use_container_width=True, hide_index=True)

    st.subheader("Insurance Wise Visits")
    st.dataframe(dfs.get("Insurance Wise Visits", pd.DataFrame()), use_container_width=True, hide_index=True)

    st.subheader("Doctor Wise Visits")
    st.dataframe(dfs.get("Doctor Wise Visits", pd.DataFrame()), use_container_width=True, hide_index=True)


    # -------------------- Income Analysis (Doctor Revenue) -------------------- (Doctor Revenue) --------------------
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



    

    # -------------------- CPT / ICD Analysis --------------------
    cpticd_keys = [k for k in dfs.keys() if str(k).startswith("CPTICD | ")]
    if cpticd_keys:
        st.markdown("---")
        st.header("CPT / ICD Analysis")

        # Pick known tables
        df_docco_pri = dfs.get("CPTICD | Doctor x Company | Principal DX (Top1)")
        df_docco_sec = dfs.get("CPTICD | Doctor x Company | Secondary DX (Top1)")
        df_cpt_map    = dfs.get("CPTICD | CPT -> Top Principal ICD")
        df_exp        = dfs.get("CPTICD | Employer Expiry Tracker")
        df_doc_pri    = dfs.get("CPTICD | Doctor | Principal DX (Top1)")
        df_doc_sec    = dfs.get("CPTICD | Doctor | Secondary DX (Top1)")
        df_co_pri     = dfs.get("CPTICD | Company | Principal DX (Top1)")
        df_co_sec     = dfs.get("CPTICD | Company | Secondary DX (Top1)")

        tabs = st.tabs(["Doctor x Company", "CPT Mapping", "Employer Expiry", "Doctor Wise", "Company Wise"])

        with tabs[0]:
            st.subheader("Top Diagnosis (Doctor x Company)")
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("**Principal DX (Top 1)**")
                st.dataframe(df_docco_pri if df_docco_pri is not None else pd.DataFrame(), use_container_width=True, hide_index=True)
            with c2:
                st.markdown("**Secondary DX (Top 1)**")
                st.dataframe(df_docco_sec if df_docco_sec is not None else pd.DataFrame(), use_container_width=True, hide_index=True)

        with tabs[1]:
            st.subheader("CPT → Most Common Principal ICD")
            st.dataframe(df_cpt_map if df_cpt_map is not None else pd.DataFrame(), use_container_width=True, hide_index=True)

        with tabs[2]:
            st.subheader("Employer Employee Expiry Tracker")
            if df_exp is None or df_exp.empty:
                st.info("No expiry data found in the uploaded CPT/ICD report.")
            else:
                # Filters
                df_f = df_exp.copy()
                # choose window
                win = st.selectbox("Expiry Window", options=["All", "Expired", "Next 30 days", "Next 60 days", "Next 90 days"], key=f"exp_win_{str(day_ts)}")
                if "Days To Expiry" in df_f.columns:
                    if win == "Expired":
                        df_f = df_f[df_f["Days To Expiry"] < 0]
                    elif win.startswith("Next"):
                        n = int(re.findall(r"\d+", win)[0])
                        df_f = df_f[(df_f["Days To Expiry"] >= 0) & (df_f["Days To Expiry"] <= n)]
                # company filter
                if "Company" in df_f.columns:
                    comps = sorted([c for c in df_f["Company"].dropna().unique() if str(c).strip() not in ["", "nan", "None"]])
                    pick_c = st.selectbox("Company", options=["All"] + comps, key=f"exp_comp_{str(day_ts)}")
                    if pick_c != "All":
                        df_f = df_f[df_f["Company"] == pick_c]
                st.dataframe(df_f, use_container_width=True, hide_index=True)

        with tabs[3]:
            st.subheader("Top Diagnosis (Doctor)")
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("**Principal DX (Top 1)**")
                st.dataframe(df_doc_pri if df_doc_pri is not None else pd.DataFrame(), use_container_width=True, hide_index=True)
            with c2:
                st.markdown("**Secondary DX (Top 1)**")
                st.dataframe(df_doc_sec if df_doc_sec is not None else pd.DataFrame(), use_container_width=True, hide_index=True)

        with tabs[4]:
            st.subheader("Top Diagnosis (Company)")
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("**Principal DX (Top 1)**")
                st.dataframe(df_co_pri if df_co_pri is not None else pd.DataFrame(), use_container_width=True, hide_index=True)
            with c2:
                st.markdown("**Secondary DX (Top 1)**")
                st.dataframe(df_co_sec if df_co_sec is not None else pd.DataFrame(), use_container_width=True, hide_index=True)
    st.subheader("Employer Wise")
    emp_df = dfs.get("Employer Wise", pd.DataFrame()).copy()

    # Add dominant Expiry Date per Employer from CPT/ICD report (Option B: only non-null expiry dates)
    df_exp_all = dfs.get("CPTICD | Employer Expiry Tracker")
    exp_map = {}
    today = date.today()

    def _norm_txt(x: str) -> str:
        s = str(x or "").strip().upper()
        s = re.sub(r"\s+", " ", s)
        return s

    # Basic aliases/prefix merges (same idea as Employer Wise)
    PREFIX_ALIAS = [
        ("ARCO", "ARCO"),
        ("EXEED", "EXCEED"),
        ("EXCEED", "EXCEED"),
        ("QUMRA", "QAMRA"),
        ("QAMARA", "QAMRA"),
        ("QAMRA", "QAMRA"),
    ]

    def _map_company_to_employer(company: str) -> str:
        c = _norm_txt(company)
        for pfx, canon in PREFIX_ALIAS:
            if c.startswith(pfx):
                return canon
        return c  # fallback (still useful)

    if df_exp_all is not None and not df_exp_all.empty and "Company" in df_exp_all.columns:
        exp = df_exp_all.copy()
        # Parse expiry date
        if "Expiry Date" in exp.columns:
            exp["_expiry_date"] = pd.to_datetime(exp["Expiry Date"], errors="coerce").dt.date
        elif "Expiry" in exp.columns:
            exp["_expiry_date"] = pd.to_datetime(exp["Expiry"], errors="coerce").dt.date
        else:
            exp["_expiry_date"] = pd.NaT

        exp["Employer"] = exp["Company"].map(_map_company_to_employer)

        # For each employer present in Employer Wise table, pick dominant expiry date (>=70%) among non-null dates
        if not emp_df.empty and "Employer" in emp_df.columns:
            for emp in emp_df["Employer"].dropna().astype(str).unique().tolist():
                emp_key = _norm_txt(emp)
                dates = exp.loc[exp["Employer"] == emp_key, "_expiry_date"].dropna()
                if len(dates) == 0:
                    continue
                vc = dates.value_counts()
                top_date = vc.index[0]
                pct = float(vc.iloc[0]) / float(len(dates))
                if pct >= 0.70:
                    exp_map[emp_key] = top_date
                else:
                    exp_map[emp_key] = "Mixed"

    if emp_df is None or emp_df.empty:
        st.dataframe(emp_df if emp_df is not None else pd.DataFrame(), use_container_width=True, hide_index=True)
    else:
        # Attach Expiry column
        if "Employer" in emp_df.columns:
            emp_df["Expiry Date"] = emp_df["Employer"].map(lambda e: exp_map.get(_norm_txt(e), ""))
        else:
            emp_df["Expiry Date"] = ""

        # Styling: turn red if expiry is within 30 days (or already expired)
        def _style_exp(v):
            if isinstance(v, date):
                d = (v - today).days
                if d <= 30:
                    return "color: red; font-weight: 700;"
            return ""

        show_df = emp_df.copy()
        sty = show_df.style.applymap(_style_exp, subset=["Expiry Date"])
        st.dataframe(sty, use_container_width=True, hide_index=True)


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


def _snap_to_saved(chosen: pd.Timestamp, saved: List[pd.Timestamp]) -> Tuple[pd.Timestamp, bool]:
    """Return (snapped_day, was_snapped). Picks the nearest saved day <= chosen, else the earliest."""
    if not saved:
        return chosen, False
    chosen = pd.to_datetime(chosen).normalize()
    saved_sorted = sorted(pd.to_datetime(saved).tolist())
    if chosen in saved_sorted:
        return chosen, False
    earlier = [d for d in saved_sorted if d <= chosen]
    if earlier:
        return earlier[-1], True
    return saved_sorted[0], True


min_day = pd.to_datetime(min(days)).normalize()
max_day = pd.to_datetime(max(days)).normalize()

if mode == "Daily":
    chosen = st.date_input(
        "Select day",
        value=max_day.date(),
        min_value=min_day.date(),
        max_value=max_day.date(),
    )
    picked, snapped = _snap_to_saved(pd.to_datetime(chosen), days)
    if snapped:
        st.info(f"No saved data for **{pd.to_datetime(chosen).strftime('%d %b %Y')}**. Showing nearest saved day: **{fmt_day(picked)}**")

    cache_key = f"daily:{picked.date().isoformat()}"
    if SS.get("loaded_key") != cache_key:
        SS["loaded_summary"] = load_summary_from_s3(s3, cfg, root_prefix, picked)
        SS["loaded_key"] = cache_key
        SS["loaded_label"] = f"Current Day ({fmt_day(picked)})"

    if SS.get("loaded_summary") is not None:
        render_summary(SS["loaded_summary"], picked)
    else:
        st.error("summary.pkl is missing for this day.")
        st.caption(f"Expected: {s3_key(root_prefix, picked.date().isoformat(), 'summary.pkl')}")

elif mode == "Weekly":
    c1, c2 = st.columns(2)
    with c1:
        s_in = st.date_input("Week Start", value=max_day.date(), min_value=min_day.date(), max_value=max_day.date(), key="wk_start")
    with c2:
        e_in = st.date_input("Week End", value=max_day.date(), min_value=min_day.date(), max_value=max_day.date(), key="wk_end")

    start_d, s_snap = _snap_to_saved(pd.to_datetime(s_in), days)
    end_d, e_snap = _snap_to_saved(pd.to_datetime(e_in), days)
    if start_d > end_d:
        start_d, end_d = end_d, start_d

    selected = [d for d in days if (d >= start_d) and (d <= end_d)]
    st.caption(f"Selected range: **{start_d.date().isoformat()} → {end_d.date().isoformat()}**  (saved days: {len(selected)})")

    if not selected:
        st.warning("No saved days found in this range.")
    else:
        cache_key = f"range:{start_d.date().isoformat()}:{end_d.date().isoformat()}"
        if SS.get("loaded_key") != cache_key:
            SS["loaded_summary"] = load_and_aggregate(selected)
            SS["loaded_key"] = cache_key
            SS["loaded_label"] = f"Weekly Summary ({start_d.date().isoformat()} → {end_d.date().isoformat()})"

        if SS.get("loaded_summary") is not None:
            st.header(SS.get("loaded_label", "Weekly Summary"))
            render_summary(SS["loaded_summary"], pd.to_datetime(max(selected)))
        else:
            st.warning("No summary.pkl files found in this range.")

else:  # Monthly
    chosen = st.date_input(
        "Select any date in the month",
        value=max_day.date(),
        min_value=min_day.date(),
        max_value=max_day.date(),
        key="mo_pick",
    )
    d0 = pd.to_datetime(chosen).normalize()
    month_days = days_in_month(d0)

    if not month_days:
        st.warning("No saved days found for that month.")
    else:
        sel_month = d0.strftime("%Y-%m")
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
        else:
            st.warning("No summary.pkl files found for that month.")
