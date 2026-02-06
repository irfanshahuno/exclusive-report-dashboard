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
# --------------------
# CPT/ICD helper: safe DF pick + debug
# --------------------
def _pick_first_df(*candidates):
    """Return the first candidate that is a non-empty DataFrame."""
    for x in candidates:
        if isinstance(x, pd.DataFrame) and not x.empty:
            return x
    return pd.DataFrame()

def _summary_keys(dfs):
    try:
        return sorted(list(dfs.keys()))
    except Exception:
        return []

# Optional S3
try:
    import boto3
except Exception:
    boto3 = None



# ---------------------------
# Date formatting (management-friendly)
# ---------------------------
def fmt_day(ts) -> str:
    """Friendly day label with weekday for management views."""
    try:
        return pd.to_datetime(ts).strftime("%A, %d %b %Y")
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


def render_summary(dfs: Dict[str, pd.DataFrame], day_ts: pd.Timestamp, heading: str = "header", label: str = "Current Day"):
    title = f"{label} ({fmt_day(day_ts)})"
    if heading == "subheader":
        st.subheader(title)
    else:
        st.header(title)

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
    # NOTE: Never use `or` between DataFrames (pandas raises: "truth value of a DataFrame is ambiguous").
    # We support BOTH key styles:
    #   New (viewer-style): "CPTICD | ..."
    #   Old (uploader-style): "Doctor x Company | ..." / "CPT -> Top Principal ICD" / "Employer Expiry Tracker"
    def _pick_first_df(keys: List[str]) -> Optional[pd.DataFrame]:
        first_any: Optional[pd.DataFrame] = None
        for kk in keys:
            v = dfs.get(kk)
            if isinstance(v, pd.DataFrame):
                if first_any is None:
                    first_any = v
                if not v.empty:
                    return v
        return first_any

    has_cpticd = any(str(k).startswith("CPTICD | ") for k in dfs.keys()) or any(
        k in dfs for k in [
            "Doctor x Company | Principal DX (Top1)",
            "Doctor x Company | Secondary DX (Top1)",
            "Doctor x Insurance | Principal DX (Counts)",
            "Doctor x Insurance | Secondary DX (Counts)",
            "Doctor x Insurance | Visits",
            "Doctor x Insurance | Principal DX (Top1)",
            "Doctor x Insurance | Secondary DX (Top1)",
            "CPT -> Top Principal ICD",
            "Employer Expiry Tracker",
        ]
    )

    if has_cpticd:
        st.markdown("---")
        st.header("CPT / ICD Analysis")

        # Simplified display (Doctor + Insurance only)
        # Prefer VISIT-LEVEL Principal DX counts (totals intended to match visits)
        df_pri = _pick_first_df([
            "CPTICD | Doctor x Insurance | Principal DX (Counts)",
            "Doctor x Insurance | Principal DX (Counts)",
            # fallback: old Top1 keys
            "CPTICD | Doctor x Insurance | Principal DX (Top1)",
            "CPTICD | Doctor x Company | Principal DX (Top1)",
            "Doctor x Insurance | Principal DX (Top1)",
            "Doctor x Company | Principal DX (Top1)",
        ])
        df_sec = _pick_first_df([
            "CPTICD | Doctor x Insurance | Secondary DX (Counts)",
            "Doctor x Insurance | Secondary DX (Counts)",
            # fallback: old Top1 keys
            "CPTICD | Doctor x Insurance | Secondary DX (Top1)",
            "CPTICD | Doctor x Company | Secondary DX (Top1)",
            "Doctor x Insurance | Secondary DX (Top1)",
            "Doctor x Company | Secondary DX (Top1)",
        ])
        df_cpt_map = _pick_first_df([
            "CPTICD | CPT -> Top Principal ICD",
            "CPT -> Top Principal ICD",
        ])

        tabs = st.tabs(["Doctor x Insurance", "CPT Mapping"])

        def _clean_diag(df: Optional[pd.DataFrame]) -> pd.DataFrame:
            if df is None or df.empty:
                return pd.DataFrame()
            out = df.copy()

            # Drop unnamed/blank columns (common after Excel export)
            bad_cols = []
            for c in list(out.columns):
                sc = str(c).strip()
                if sc == "" or sc.lower().startswith("unnamed"):
                    bad_cols.append(c)
            if bad_cols:
                out = out.drop(columns=bad_cols, errors="ignore")

            # Drop employer/company columns if present
            for drop_c in ["Employer", "Company"]:
                if drop_c in out.columns:
                    out = out.drop(columns=[drop_c])

            # Fix common typo
            if "Insuance" in out.columns and "Insurance" not in out.columns:
                out = out.rename(columns={"Insuance": "Insurance"})

            # Keep only requested columns where available (Doctor/Insurance/ICD/Count/Desc)
            keep = [c for c in ["Doctor", "Insurance", "ICD", "Count", "ICD Description"] if c in out.columns]
            return out[keep] if keep else out

        with tabs[0]:
            st.subheader("Top Diagnosis (Doctor x Insurance)")

            pri_clean = _clean_diag(df_pri)
            sec_clean = _clean_diag(df_sec)

            # --- Filters (Doctor + Insurance) ---
            doctors = []
            ins_list = []
            for _d in [pri_clean, sec_clean]:
                if isinstance(_d, pd.DataFrame) and not _d.empty:
                    if "Doctor" in _d.columns:
                        doctors += _d["Doctor"].dropna().astype(str).tolist()
                    if "Insurance" in _d.columns:
                        ins_list += _d["Insurance"].dropna().astype(str).tolist()

            doctors = sorted({d.strip() for d in doctors if str(d).strip() != ""})
            ins_list = sorted({i.strip() for i in ins_list if str(i).strip() != ""})

            f1, f2 = st.columns(2)
            with f1:
                pick_doc = st.selectbox("Select Doctor", ["All"] + doctors, index=0, key="cpticd_pick_doc")
            with f2:
                pick_ins = st.selectbox("Select Insurance", ["All"] + ins_list, index=0, key="cpticd_pick_ins")

            def _filter_diag(df: pd.DataFrame) -> pd.DataFrame:
                if df is None or df.empty:
                    return pd.DataFrame()
                out = df.copy()
                if pick_doc != "All" and "Doctor" in out.columns:
                    out = out[out["Doctor"].astype(str) == str(pick_doc)]
                if pick_ins != "All" and "Insurance" in out.columns:
                    out = out[out["Insurance"].astype(str) == str(pick_ins)]
                return out

            # --- Principal DX (Counts) with TOTAL + match with visits ---
            pri_show = _filter_diag(pri_clean)

            # Detect if this is visit-level counts table
            is_counts_view = False
            if isinstance(df_pri, pd.DataFrame):
                is_counts_view = any(
                    str(k).strip() in ["CPTICD | Doctor x Insurance | Principal DX (Counts)", "Doctor x Insurance | Principal DX (Counts)"]
                    for k in dfs.keys()
                )

            total_dx = None
            if not pri_show.empty and "Count" in pri_show.columns:
                try:
                    total_dx = int(pd.to_numeric(pri_show["Count"], errors="coerce").fillna(0).sum())
                except Exception:
                    total_dx = None

            # Expected visits from Income Doctor x Insurance table (if available)
            # Expected visits (prefer CPT/ICD visit table; fallback to Income Doctor x Insurance)
            expected_visits = None

            df_vis = dfs.get("Doctor x Insurance | Visits")
            if isinstance(df_vis, pd.DataFrame) and not df_vis.empty and "Visits" in df_vis.columns:
                tmpv = df_vis.copy()
                if pick_doc != "All" and "Doctor" in tmpv.columns:
                    tmpv = tmpv[tmpv["Doctor"].astype(str) == str(pick_doc)]
                if pick_ins != "All" and "Insurance" in tmpv.columns:
                    tmpv = tmpv[tmpv["Insurance"].astype(str) == str(pick_ins)]
                try:
                    expected_visits = int(pd.to_numeric(tmpv["Visits"], errors="coerce").fillna(0).sum())
                except Exception:
                    expected_visits = None

            if expected_visits is None:
                df_income_dx = dfs.get("Income | Doctor x Insurance Revenue")
                if isinstance(df_income_dx, pd.DataFrame) and not df_income_dx.empty and "Total_Visit" in df_income_dx.columns:
                    tmp = df_income_dx.copy()
                    if pick_doc != "All" and "Doctor" in tmp.columns:
                        tmp = tmp[tmp["Doctor"].astype(str) == str(pick_doc)]
                    if pick_ins != "All" and "Insurance" in tmp.columns:
                        tmp = tmp[tmp["Insurance"].astype(str) == str(pick_ins)]
                    # Exclude GRAND TOTAL rows if present
                    for coln in ["Doctor", "Insurance"]:
                        if coln in tmp.columns:
                            tmp = tmp[tmp[coln].astype(str).str.upper() != "GRAND TOTAL"]
                    try:
                        expected_visits = int(pd.to_numeric(tmp["Total_Visit"], errors="coerce").fillna(0).sum())
                    except Exception:
                        expected_visits = None
# Append TOTAL row at end (so user can visually match)
            if not pri_show.empty and total_dx is not None:
                total_row = {c: "" for c in pri_show.columns}
                if "ICD" in pri_show.columns:
                    total_row["ICD"] = "TOTAL"
                elif "Doctor" in pri_show.columns:
                    total_row["Doctor"] = "TOTAL"
                if "Count" in pri_show.columns:
                    total_row["Count"] = total_dx
                pri_show = pd.concat([pri_show, pd.DataFrame([total_row])], ignore_index=True)

            c1, c2 = st.columns(2)
            with c1:
                st.markdown("**Principal DX (Visit-level Counts)**" if is_counts_view else "**Principal DX**")
                # Summary line
                if total_dx is not None:
                    if expected_visits is not None:
                        st.caption(f"Principal DX TOTAL: {total_dx}  |  Visits: {expected_visits}")
                    else:
                        st.caption(f"Principal DX TOTAL: {total_dx}")
                st.dataframe(pri_show, use_container_width=True, hide_index=True)

            with c2:
                st.markdown("**Secondary DX (Counts)**")
                sec_show = _filter_diag(sec_clean)

                total_sec = None
                if not sec_show.empty and "Count" in sec_show.columns:
                    try:
                        total_sec = int(pd.to_numeric(sec_show["Count"], errors="coerce").fillna(0).sum())
                    except Exception:
                        total_sec = None

                if not sec_show.empty and total_sec is not None:
                    total_row = {c: "" for c in sec_show.columns}
                    if "Insurance" in sec_show.columns:
                        total_row["Insurance"] = "TOTAL"
                    if "Count" in sec_show.columns:
                        total_row["Count"] = total_sec
                    sec_show = pd.concat([sec_show, pd.DataFrame([total_row])], ignore_index=True)

                if total_sec is not None:
                    if expected_visits is not None:
                        st.caption(f"Secondary DX TOTAL: {total_sec}  |  Visits: {expected_visits}")
                    else:
                        st.caption(f"Secondary DX TOTAL: {total_sec}")

                st.dataframe(sec_show, use_container_width=True, hide_index=True)
        with tabs[1]:

                    st.subheader("CPT → Most Common Principal ICD")

                    df_cpt = df_cpt_map if isinstance(df_cpt_map, pd.DataFrame) else pd.DataFrame()
                    if df_cpt is None or df_cpt.empty:
                        st.info("No CPT mapping data for this day.")
                    else:
                        # Optional filters
                        if "CPT" in df_cpt.columns:
                            cpt_list = sorted(df_cpt["CPT"].dropna().astype(str).unique().tolist())
                            pick_cpt = st.selectbox("Select CPT", ["All"] + cpt_list, index=0, key="cpticd_pick_cpt")
                        else:
                            pick_cpt = "All"

                        df_show = df_cpt.copy()
                        if pick_cpt != "All" and "CPT" in df_show.columns:
                            df_show = df_show[df_show["CPT"].astype(str) == str(pick_cpt)].copy()

                        st.dataframe(df_show, use_container_width=True, hide_index=True)

    st.subheader("Employer Wise")
    emp_df = dfs.get("Employer Wise", pd.DataFrame()).copy()

    # --- Employer expiry summary (STRICT employer from Registration, expiry from CPT/ICD) ---
    # We expect the uploader to save a tracker table that includes at least:
    #   Employer (from RegistrationList "Employer Name") + Expiry Date (from CPT/ICD file)
    # But to be robust, we also fall back to any table that contains an Employer-like column and an Expiry column.
    def _pick_expiry_df(dfs_dict: dict) -> pd.DataFrame | None:
        # 1) Prefer explicit tracker key
        for k, v in dfs_dict.items():
            if isinstance(v, pd.DataFrame) and "expiry" in str(k).lower() and "tracker" in str(k).lower():
                return v
        # 2) Any key mentioning expiry
        for k, v in dfs_dict.items():
            if isinstance(v, pd.DataFrame) and "expiry" in str(k).lower():
                return v
        # 3) Any DF that has expiry+employer columns
        for _, v in dfs_dict.items():
            if not isinstance(v, pd.DataFrame) or v.empty:
                continue
            cols = [c.lower().strip() for c in v.columns]
            if any("expiry" in c for c in cols) and any(c in ("employer", "employer name") or "employer" in c for c in cols):
                return v
        return None

    df_exp_all = _pick_expiry_df(dfs)

    exp_display_map: dict[str, str] = {}
    exp_top_date_map: dict[str, date | None] = {}
    today = date.today()

    def _norm_emp(x: str) -> str:
        s = str(x or "").strip().upper()
        s = re.sub(r"\s+", " ", s)
        return s

    if df_exp_all is not None and not df_exp_all.empty and not emp_df.empty and "Employer" in emp_df.columns:
        exp = df_exp_all.copy()

        # Detect employer column in tracker (STRICT: should already be Employer from RegistrationList)
        emp_col = None
        for c in exp.columns:
            cl = str(c).strip().lower()
            if cl == "employer" or cl == "employer name" or "employer" in cl:
                emp_col = c
                break

        # Detect expiry column
        exp_col = None
        for c in exp.columns:
            cl = str(c).strip().lower()
            if "expiry" in cl and ("date" in cl or cl == "expiry"):
                exp_col = c
                break
        if exp_col is None:
            # fallback: any column containing 'expiry'
            for c in exp.columns:
                if "expiry" in str(c).strip().lower():
                    exp_col = c
                    break

        if emp_col and exp_col:
            exp[emp_col] = exp[emp_col].astype(str).map(_norm_emp)
            exp["_expiry_date"] = pd.to_datetime(exp[exp_col], errors="coerce").dt.date

            # Option B: base % only on valid (non-null) expiry dates
            for emp in emp_df["Employer"].dropna().astype(str).unique().tolist():
                emp_key = _norm_emp(emp)
                sub = exp.loc[exp[emp_col] == emp_key, "_expiry_date"].dropna()
                if sub.empty:
                    exp_display_map[emp_key] = ""
                    exp_top_date_map[emp_key] = None
                    continue

                vc = sub.value_counts()
                top_date = vc.index[0]
                top_count = int(vc.iloc[0])
                total_valid = int(vc.sum())
                pct = (top_count / total_valid) * 100.0 if total_valid else 0.0

                if pct >= 70.0:
                    display = top_date.strftime("%Y-%m-%d")
                else:
                    display = f"Mixed (Top: {top_date.strftime('%Y-%m-%d')} – {int(round(pct))}%)"

                exp_display_map[emp_key] = display
                exp_top_date_map[emp_key] = top_date
        else:
            # missing columns
            pass

    if emp_df is None or emp_df.empty:
        st.dataframe(emp_df if emp_df is not None else pd.DataFrame(), use_container_width=True, hide_index=True)
    else:
        # Attach Expiry column (string display)
        if "Employer" in emp_df.columns:
            emp_df["Expiry Date"] = emp_df["Employer"].map(lambda e: exp_display_map.get(_norm_emp(e), ""))
        else:
            emp_df["Expiry Date"] = ""

        # Styling bands (today-based):
        #   expired (<0) -> dark red
        #   <=30 -> red
        #   31-60 -> yellow
        #   >60 -> normal
        def _style_exp_cell(emp_val, disp_val):
            if not disp_val:
                return ""
            top_date = exp_top_date_map.get(_norm_emp(emp_val))
            if not top_date:
                return ""
            diff = (top_date - today).days
            if diff < 0:
                return "background-color:#8B0000;color:white;font-weight:700;"
            if diff <= 30:
                return "background-color:red;color:white;font-weight:700;"
            if diff <= 60:
                return "background-color:yellow;color:black;font-weight:700;"
            return ""

        show_df = emp_df.copy()
        sty = show_df.style.apply(
            lambda row: [""] * (len(row) - 1) + [_style_exp_cell(row.get("Employer", ""), row.get("Expiry Date", ""))],
            axis=1,
        )
        st.dataframe(sty, use_container_width=True, hide_index=True)

        # ---- Expiry Detail List (Step 5) + Download ----
        with st.expander("Expiry Detail List (Step 5) — filter & download", expanded=False):
            df_detail = df_exp_all.copy() if df_exp_all is not None else pd.DataFrame()
            if df_detail is None or df_detail.empty:
                st.info("No expiry detail list found for this day/period.")
            else:
                # Normalize column names
                if "Insuance" in df_detail.columns and "Insurance" not in df_detail.columns:
                    df_detail = df_detail.rename(columns={"Insuance": "Insurance"})
                # Expected columns
                # Employer, Insurance, Name, EMR No, Visit ID, Doctor, Expiry Date, Days To Expiry
                # Filters
                f1, f2, f3 = st.columns([2, 2, 2])
                with f1:
                    win = st.selectbox(
                        "Expiry Window",
                        options=["All", "Expired", "Next 30 days", "Next 60 days", "Next 90 days"],
                        key=f"exp_win2_{str(day_ts)}",
                    )
                with f2:
                    ins_opts = []
                    if "Insurance" in df_detail.columns:
                        ins_opts = sorted([x for x in df_detail["Insurance"].dropna().unique() if str(x).strip() not in ["", "nan", "None"]])
                    pick_ins = st.selectbox("Insurance", options=["All"] + ins_opts, key=f"exp_ins2_{str(day_ts)}")
                with f3:
                    emp_opts = []
                    if "Employer" in df_detail.columns:
                        emp_opts = sorted([x for x in df_detail["Employer"].dropna().unique() if str(x).strip() not in ["", "nan", "None"]])
                    pick_emp = st.selectbox("Employer", options=["All"] + emp_opts, key=f"exp_emp2_{str(day_ts)}")

                df_f = df_detail.copy()
                if "Days To Expiry" in df_f.columns:
                    if win == "Expired":
                        df_f = df_f[df_f["Days To Expiry"] < 0]
                    elif win.startswith("Next"):
                        n = int(re.findall(r"\d+", win)[0])
                        df_f = df_f[(df_f["Days To Expiry"] >= 0) & (df_f["Days To Expiry"] <= n)]

                if pick_ins != "All" and "Insurance" in df_f.columns:
                    df_f = df_f[df_f["Insurance"] == pick_ins]
                if pick_emp != "All" and "Employer" in df_f.columns:
                    df_f = df_f[df_f["Employer"] == pick_emp]

                
# ---- Summary counts (on-screen) ----
grp_cols = [c for c in ["Employer", "Insurance"] if c in df_f.columns]
if grp_cols:
    df_counts = (
        df_f.groupby(grp_cols, dropna=False)
        .size()
        .reset_index(name="Count")
        .sort_values("Count", ascending=False)
    )
    # TOTAL row
    total_n = int(df_counts["Count"].sum()) if "Count" in df_counts.columns else 0
    total_row = {c: "" for c in df_counts.columns}
    if "Employer" in total_row:
        total_row["Employer"] = "TOTAL"
    total_row["Count"] = total_n
    df_counts = pd.concat([pd.DataFrame([total_row]), df_counts], ignore_index=True)

    st.caption(f"Showing summary counts for: **{win}** | Rows: {len(df_counts)-1} | TOTAL: {total_n}")
    st.dataframe(df_counts, use_container_width=True, hide_index=True)
else:
    st.info("Expiry list is missing Employer/Insurance columns, so summary counts cannot be built.")
    df_counts = pd.DataFrame()

# ---- Optional detailed list (only when needed) ----
show_details = st.checkbox("Show detailed patient list (only if you need to review before download)", value=False, key=f"exp_show_details_{str(day_ts)}")
if show_details:
    show_cols = [c for c in ["Employer","Insurance","Name","EMR No","Visit ID","Doctor","Expiry Date","Days To Expiry"] if c in df_f.columns]
    st.dataframe(df_f[show_cols] if show_cols else df_f, use_container_width=True, hide_index=True)

# ---- Downloads ----
# Download counts
try:
    import io as _io
    out_counts = _io.BytesIO()
    with pd.ExcelWriter(out_counts, engine="openpyxl") as writer:
        (df_counts if df_counts is not None else pd.DataFrame()).to_excel(writer, index=False, sheet_name="Expiry_Counts")
    st.download_button(
        "Download Counts (Excel)",
        data=out_counts.getvalue(),
        file_name="expiry_counts.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key=f"dl_exp_counts_{str(day_ts)}",
    )
except Exception:
    st.warning("Counts download is unavailable (Excel writer error).")

# Download full list
    # Download full list
    # Download Excel
    try:
        import io as _io
        out = _io.BytesIO()
        with pd.ExcelWriter(out, engine="openpyxl") as writer:
            (df_f[show_cols] if show_cols else df_f).to_excel(writer, index=False, sheet_name="Expiry_List")
        st.download_button(
            "Download Excel",
            data=out.getvalue(),
            file_name="expiry_list.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key=f"dl_exp_{str(day_ts)}_{pick_ins}_{pick_emp}",
        )
    except Exception:
        st.warning("Download is unavailable (Excel writer not found).")

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


def aggregate_income(frames: List[pd.DataFrame]) -> pd.DataFrame:
    """Aggregate Income tables across many days.

    Rule:
    - Sum Consultation/Lab/Procedure/Total_Visit/Total_Amount_* across days (grouped by non-numeric columns)
    - Recompute Avg_Amount_* = Total_Amount_* / Total_Visit
    - Recompute Lab_% = (Lab / Total_Amount_Service) * 100
    - Rebuild GRAND TOTAL row
    """
    frames = [f for f in frames if f is not None and not f.empty]
    if not frames:
        return pd.DataFrame()

    df = pd.concat(frames, ignore_index=True)

    # Remove any TOTAL rows; we rebuild totals after aggregation
    first_col = df.columns[0] if len(df.columns) else None
    if first_col:
        df = df[~df[first_col].astype(str).str.strip().str.upper().isin(["TOTAL", "GRAND TOTAL"])].copy()

    # Identify columns
    avg_cols = [c for c in df.columns if str(c).strip().lower().startswith("avg_") or str(c).strip().lower().startswith("avg ")]
    lab_pct_cols = [c for c in df.columns if str(c).strip().lower() in ["lab_%", "lab%", "lab pct", "lab_pct"]]
    ignore_sum = set(avg_cols + lab_pct_cols)

    num_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    sum_cols = [c for c in num_cols if c not in ignore_sum]

    grp_cols = [c for c in df.columns if c not in num_cols]
    if grp_cols and sum_cols:
        out = df.groupby(grp_cols, dropna=False, as_index=False)[sum_cols].sum()
    else:
        out = df.copy()

    # Normalize expected column names
    # (support both Total_Amount_Insurance and Total_Amount_Insuance)
    if "Total_Amount_Insurance" in out.columns and "Total_Amount_Insuance" not in out.columns:
        out["Total_Amount_Insuance"] = out["Total_Amount_Insurance"]
    if "Avg_Amount_Insurance" in out.columns and "Avg_Amount_Insuance" not in out.columns:
        out["Avg_Amount_Insuance"] = out["Avg_Amount_Insurance"]

    # Recompute averages (strictly by Total_Visit)
    if "Total_Visit" in out.columns:
        denom = out["Total_Visit"].replace(0, pd.NA)
        if "Total_Amount_Service" in out.columns:
            out["Avg_Amount_Service"] = out["Total_Amount_Service"] / denom
        if "Total_Amount_Insuance" in out.columns:
            out["Avg_Amount_Insuance"] = out["Total_Amount_Insuance"] / denom

    # Recompute Lab_% (service basis)
    if "Lab" in out.columns and "Total_Amount_Service" in out.columns:
        denom2 = out["Total_Amount_Service"].replace(0, pd.NA)
        out["Lab_%"] = (out["Lab"] / denom2) * 100

    # Rebuild GRAND TOTAL
    if first_col and any(c in out.columns for c in sum_cols):
        row = {c: "" for c in out.columns}
        row[first_col] = "GRAND TOTAL"
        for c in sum_cols:
            row[c] = float(out[c].sum()) if not out.empty else 0.0
        # Averages for grand total
        if "Total_Visit" in out.columns and row.get("Total_Visit", 0):
            tv = row["Total_Visit"] if row["Total_Visit"] else 0
            try:
                tv = float(tv)
            except Exception:
                tv = 0
            if tv:
                if "Total_Amount_Service" in out.columns:
                    row["Avg_Amount_Service"] = float(row.get("Total_Amount_Service", 0)) / tv
                if "Total_Amount_Insuance" in out.columns:
                    row["Avg_Amount_Insuance"] = float(row.get("Total_Amount_Insuance", 0)) / tv
                if "Lab" in out.columns and "Total_Amount_Service" in out.columns and float(row.get("Total_Amount_Service", 0)) != 0:
                    row["Lab_%"] = (float(row.get("Lab", 0)) / float(row.get("Total_Amount_Service", 0))) * 100
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
        if str(k).startswith("Income | "):
            agg[k] = aggregate_income(frames)
        else:
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
                render_summary(SS["loaded_summary"], picked, heading="header", label="Current Day")
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
            render_summary(SS["loaded_summary"], pd.to_datetime(max(selected)), heading="subheader", label="Latest Saved Day")
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
            SS["loaded_label"] = f"Monthly Summary ({pd.to_datetime(d0).strftime('%B %Y')})"

        if SS.get("loaded_summary") is not None:
            st.header(SS.get("loaded_label", "Monthly Summary"))
            render_summary(SS["loaded_summary"], pd.to_datetime(max(month_days)), heading="subheader", label="Latest Saved Day")
        else:
            st.warning("No summary.pkl files found for that month.")
