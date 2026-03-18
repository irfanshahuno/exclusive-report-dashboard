
import io
import re
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
import streamlit as st


st.set_page_config(page_title="Klaim Exposure Tracker", layout="wide")


# ---------------------------
# Helpers
# ---------------------------
def clean_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    return df


def to_numeric(series: pd.Series) -> pd.Series:
    if series is None:
        return pd.Series(dtype="float64")
    return pd.to_numeric(
        series.astype(str)
        .str.replace(",", "", regex=False)
        .str.replace("AED", "", regex=False)
        .str.strip()
        .replace({"nan": np.nan, "None": np.nan, "": np.nan}),
        errors="coerce",
    )


def pick_col(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    cols = {c.lower(): c for c in df.columns}
    for cand in candidates:
        if cand.lower() in cols:
            return cols[cand.lower()]
    for cand in candidates:
        for c in df.columns:
            if cand.lower() == c.lower().strip():
                return c
    return None


def read_any(uploaded_file) -> pd.DataFrame:
    name = uploaded_file.name.lower()
    if name.endswith(".csv"):
        try:
            return pd.read_csv(uploaded_file)
        except UnicodeDecodeError:
            uploaded_file.seek(0)
            return pd.read_csv(uploaded_file, encoding="latin1")
    return pd.read_excel(uploaded_file)


def normalize_status(s: str) -> str:
    text = str(s).strip().lower()
    if not text or text == "nan":
        return "Unknown"
    if "takeback" in text or "rejected" in text or "denied" in text:
        return "Rejected / TakeBack"
    if text.startswith("submitted"):
        return "Submitted / Pending"
    if "accepted" in text or "paid" in text or "remit" in text:
        return "Paid / Accepted"
    if "pending" in text:
        return "Submitted / Pending"
    return str(s).strip()


def fmt(x) -> str:
    try:
        if pd.isna(x):
            return "-"
        return f"{float(x):,.2f}"
    except Exception:
        return str(x)


# ---------------------------
# Standardizers
# ---------------------------
def standardize_klaim(df: pd.DataFrame) -> pd.DataFrame:
    df = clean_columns(df)
    out = pd.DataFrame()

    # Flexible mapping for common Klaim exports
    claim_col = pick_col(df, ["Claim ID", "Claim Id", "ClaimID", "Receivable ID"])
    payer_col = pick_col(df, ["Payer", "Insurance", "Payer name"])
    claim_net_col = pick_col(df, ["Claim net", "Claim Net", "Net", "Value", "Claim amount"])
    deal_ref_col = pick_col(df, ["Deal reference", "Deal Reference", "RPA", "Deal no", "Deal number"])
    deal_date_col = pick_col(df, ["Deal date", "Deal Date", "Transaction date"])
    status_col = pick_col(df, ["Status", "Claim status"])
    paid_col = pick_col(df, ["Paid by insurance", "Paid", "Paid amount"])
    denied_col = pick_col(df, ["Denied by insurance", "Denied", "Rejected amount"])
    pending_col = pick_col(df, ["Pending insurance response", "Pending", "Outstanding"])

    if claim_col is None:
        raise ValueError("Klaim file: could not find Claim ID column.")

    out["claim_id"] = df[claim_col].astype(str).str.strip()
    out["payer"] = df[payer_col].astype(str).str.strip() if payer_col else ""
    out["claim_net"] = to_numeric(df[claim_net_col]) if claim_net_col else np.nan
    out["deal_reference"] = df[deal_ref_col].astype(str).str.strip() if deal_ref_col else "Unknown RPA"
    out["deal_date"] = pd.to_datetime(df[deal_date_col], errors="coerce") if deal_date_col else pd.NaT
    out["klaim_status_raw"] = df[status_col].astype(str).str.strip() if status_col else ""
    out["klaim_paid_by_insurance"] = to_numeric(df[paid_col]) if paid_col else 0.0
    out["klaim_denied_by_insurance"] = to_numeric(df[denied_col]) if denied_col else 0.0
    out["klaim_pending_insurance"] = to_numeric(df[pending_col]) if pending_col else 0.0

    out = out.dropna(subset=["claim_id"])
    out = out[out["claim_id"].astype(str).str.strip() != ""]
    return out


def standardize_summary(df: pd.DataFrame) -> pd.DataFrame:
    df = clean_columns(df)
    out = pd.DataFrame()

    claim_col = pick_col(df, ["UniqueID", "Claim ID", "ClaimID"])
    if claim_col is None:
        raise ValueError("Billing summary file: could not find UniqueID / Claim ID column.")

    out["claim_id"] = df[claim_col].astype(str).str.strip()
    out["visit_no"] = df[pick_col(df, ["VisitNo", "Visit No"])] if pick_col(df, ["VisitNo", "Visit No"]) else ""
    out["visit_date"] = pd.to_datetime(df[pick_col(df, ["VisitDate", "Visit Date"])], errors="coerce") if pick_col(df, ["VisitDate", "Visit Date"]) else pd.NaT
    out["insurance"] = df[pick_col(df, ["Insurance"])] if pick_col(df, ["Insurance"]) else ""
    out["status_raw"] = df[pick_col(df, ["Status"])] if pick_col(df, ["Status"]) else ""
    out["sub_ins_share"] = to_numeric(df[pick_col(df, ["SubInsShare"])]) if pick_col(df, ["SubInsShare"]) else 0.0
    out["remit_ins_share"] = to_numeric(df[pick_col(df, ["RemitInsShare"])]) if pick_col(df, ["RemitInsShare"]) else 0.0
    out["takeback"] = to_numeric(df[pick_col(df, ["TakeBack"])]) if pick_col(df, ["TakeBack"]) else 0.0
    out["balance"] = to_numeric(df[pick_col(df, ["Balance"])]) if pick_col(df, ["Balance"]) else 0.0
    out["month"] = df[pick_col(df, ["Month"])] if pick_col(df, ["Month"]) else ""
    out["year"] = to_numeric(df[pick_col(df, ["Year"])]) if pick_col(df, ["Year"]) else np.nan
    out["employer"] = df[pick_col(df, ["EmployerName", "Employer Name"])] if pick_col(df, ["EmployerName", "Employer Name"]) else ""
    out["facility_name"] = df[pick_col(df, ["Facility Name", "FacilityName"])] if pick_col(df, ["Facility Name", "FacilityName"]) else ""

    out["status_group"] = out["status_raw"].apply(normalize_status)
    out = out.dropna(subset=["claim_id"])
    out = out[out["claim_id"].astype(str).str.strip() != ""]
    return out


def standardize_detail(df: pd.DataFrame) -> pd.DataFrame:
    df = clean_columns(df)
    out = pd.DataFrame()

    claim_col = pick_col(df, ["UniqueID", "Claim ID", "ClaimID"])
    if claim_col is None:
        raise ValueError("Billing detail file: could not find UniqueID / Claim ID column.")

    out["claim_id"] = df[claim_col].astype(str).str.strip()
    out["visit_no"] = df[pick_col(df, ["VisitNo", "Visit No"])] if pick_col(df, ["VisitNo", "Visit No"]) else ""
    out["insurance"] = df[pick_col(df, ["Insurance"])] if pick_col(df, ["Insurance"]) else ""
    out["status_raw"] = df[pick_col(df, ["Status"])] if pick_col(df, ["Status"]) else ""
    out["activity_status"] = df[pick_col(df, ["ActivityStatus", "Activity Status"])] if pick_col(df, ["ActivityStatus", "Activity Status"]) else ""
    out["code"] = df[pick_col(df, ["Code", "CPT", "Activity Code"])] if pick_col(df, ["Code", "CPT", "Activity Code"]) else ""
    out["description"] = df[pick_col(df, ["Description"])] if pick_col(df, ["Description"]) else ""
    out["act_id"] = df[pick_col(df, ["ActID", "Act Id"])] if pick_col(df, ["ActID", "Act Id"]) else ""
    out["activity_ins"] = to_numeric(df[pick_col(df, ["ActivityIns"])]) if pick_col(df, ["ActivityIns"]) else 0.0
    out["act_remit_ins_share"] = to_numeric(df[pick_col(df, ["actRemitInsShare", "ActRemitInsShare"])]) if pick_col(df, ["actRemitInsShare", "ActRemitInsShare"]) else 0.0
    out["tkbk_amount_act"] = to_numeric(df[pick_col(df, ["TKBKAmountAct"])]) if pick_col(df, ["TKBKAmountAct"]) else 0.0
    out["denial_code"] = df[pick_col(df, ["DenialCode"])] if pick_col(df, ["DenialCode"]) else ""
    out["item_group"] = df[pick_col(df, ["Item Group", "Item Group "])] if pick_col(df, ["Item Group", "Item Group "]) else ""
    out = out.dropna(subset=["claim_id"])
    out = out[out["claim_id"].astype(str).str.strip() != ""]
    return out


# ---------------------------
# Main calculations
# ---------------------------
def allocate_rpa_financials(
    klaim_df: pd.DataFrame,
    rpa_summary_df: pd.DataFrame,
) -> pd.DataFrame:
    df = klaim_df.copy()

    if rpa_summary_df.empty:
        df["rpa_total_value"] = np.nan
        df["rpa_funds_received"] = np.nan
        df["rpa_fees"] = np.nan
        df["rpa_sale_price"] = np.nan
        df["alloc_received"] = np.nan
        df["alloc_fee"] = np.nan
        df["alloc_discount_loss"] = np.nan
        return df

    merged = df.merge(rpa_summary_df, on="deal_reference", how="left")
    merged["rpa_total_value"] = to_numeric(merged["rpa_total_value"])
    merged["rpa_sale_price"] = to_numeric(merged["rpa_sale_price"])
    merged["rpa_funds_received"] = to_numeric(merged["rpa_funds_received"])
    merged["rpa_fees"] = to_numeric(merged["rpa_fees"])

    ratio = np.where(
        merged["rpa_total_value"].fillna(0) > 0,
        merged["claim_net"].fillna(0) / merged["rpa_total_value"].fillna(0),
        np.nan,
    )

    merged["alloc_received"] = merged["rpa_funds_received"] * ratio
    merged["alloc_fee"] = merged["rpa_fees"] * ratio
    merged["alloc_discount_loss"] = merged["claim_net"] - merged["alloc_received"]
    return merged


def build_master(klaim_df: pd.DataFrame, summary_df: pd.DataFrame, detail_df: Optional[pd.DataFrame], rpa_summary_df: pd.DataFrame) -> pd.DataFrame:
    klaim_fin = allocate_rpa_financials(klaim_df, rpa_summary_df)
    master = klaim_fin.merge(summary_df, on="claim_id", how="left", suffixes=("_klaim", "_billing"))

    # truth from billing file
    master["paid_truth"] = master["remit_ins_share"].fillna(0)
    master["rejected_truth"] = master["takeback"].fillna(0)
    master["pending_truth"] = master["balance"].fillna(0)
    master["current_status_truth"] = master["status_group"].fillna("Not Found In Billing")

    # convenience metrics
    master["matched_in_billing"] = np.where(master["status_raw"].notna(), "Matched", "Not Matched")
    master["expected_chargeback_risk"] = master["rejected_truth"]
    master["net_cash_position"] = master["alloc_received"] - master["expected_chargeback_risk"]
    master["economic_cost"] = (master["claim_net"] - master["alloc_received"]).fillna(0) + master["expected_chargeback_risk"].fillna(0)

    if detail_df is not None and not detail_df.empty:
        detail_agg = (
            detail_df.groupby("claim_id", as_index=False)
            .agg(
                activity_rows=("claim_id", "size"),
                detail_activity_ins=("activity_ins", "sum"),
                detail_paid=("act_remit_ins_share", "sum"),
                detail_takeback=("tkbk_amount_act", "sum"),
            )
        )
        master = master.merge(detail_agg, on="claim_id", how="left")
    else:
        master["activity_rows"] = np.nan
        master["detail_activity_ins"] = np.nan
        master["detail_paid"] = np.nan
        master["detail_takeback"] = np.nan

    return master


def to_excel_bytes(sheets: Dict[str, pd.DataFrame]) -> bytes:
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        for sheet_name, df in sheets.items():
            safe_name = re.sub(r"[\\/*?:\[\]]", "", sheet_name)[:31]
            df.to_excel(writer, index=False, sheet_name=safe_name)
    output.seek(0)
    return output.getvalue()


# ---------------------------
# UI
# ---------------------------
st.title("Klaim Exposure Tracker")
st.caption("Klaim file = sold claims | Billing summary = truth | Billing detail = drill-down")

with st.sidebar:
    st.header("Upload Files")

    klaim_file = st.file_uploader("Klaim CSV/Excel", type=["csv", "xlsx", "xls"], key="klaim")
    summary_file = st.file_uploader("Billing Summary Excel", type=["xlsx", "xls", "csv"], key="summary")
    detail_file = st.file_uploader("Billing Detail Excel (optional)", type=["xlsx", "xls", "csv"], key="detail")

    st.markdown("---")
    st.subheader("RPA financial input")
    st.caption("Enter one row per RPA if you want funds received / fees / allocated cost.")
    sample_rpa = pd.DataFrame(
        {
            "deal_reference": ["2603/008173/EXCELLENT/0145"],
            "rpa_total_value": [35208],
            "rpa_sale_price": [33728],
            "rpa_fees": [185],
            "rpa_funds_received": [33543],
        }
    )
    rpa_summary_input = st.data_editor(
        sample_rpa,
        num_rows="dynamic",
        use_container_width=True,
        key="rpa_editor",
    )

if not klaim_file or not summary_file:
    st.info("Upload at least Klaim file and Billing Summary file to start.")
    st.stop()

try:
    klaim_raw = read_any(klaim_file)
    summary_raw = read_any(summary_file)
    detail_raw = read_any(detail_file) if detail_file else pd.DataFrame()

    klaim_std = standardize_klaim(klaim_raw)
    summary_std = standardize_summary(summary_raw)
    detail_std = standardize_detail(detail_raw) if not detail_raw.empty else pd.DataFrame()

    rpa_summary_df = clean_columns(pd.DataFrame(rpa_summary_input))
    master = build_master(klaim_std, summary_std, detail_std, rpa_summary_df)

except Exception as e:
    st.error(f"Error while processing files: {e}")
    st.stop()

# Filters
st.subheader("Filters")
f1, f2, f3, f4 = st.columns(4)

rpas = ["All"] + sorted([str(x) for x in master["deal_reference"].dropna().unique()])
statuses = ["All"] + sorted([str(x) for x in master["current_status_truth"].dropna().unique()])
insurances = ["All"] + sorted([str(x) for x in master["insurance"].dropna().unique()])
match_opts = ["All", "Matched", "Not Matched"]

selected_rpa = f1.selectbox("RPA", rpas)
selected_status = f2.selectbox("Billing Status", statuses)
selected_ins = f3.selectbox("Insurance", insurances)
selected_match = f4.selectbox("Match Status", match_opts)

filtered = master.copy()
if selected_rpa != "All":
    filtered = filtered[filtered["deal_reference"].astype(str) == selected_rpa]
if selected_status != "All":
    filtered = filtered[filtered["current_status_truth"].astype(str) == selected_status]
if selected_ins != "All":
    filtered = filtered[filtered["insurance"].astype(str) == selected_ins]
if selected_match != "All":
    filtered = filtered[filtered["matched_in_billing"] == selected_match]

# Layer 1
st.markdown("## Layer 1 — Overall Exposure")
c1, c2, c3, c4, c5, c6 = st.columns(6)

c1.metric("Claims Sold", f"{len(filtered):,}")
c2.metric("Sold Value", fmt(filtered["claim_net"].sum()))
c3.metric("Paid (Billing)", fmt(filtered["paid_truth"].sum()))
c4.metric("Rejected / TakeBack", fmt(filtered["rejected_truth"].sum()))
c5.metric("Pending / Balance", fmt(filtered["pending_truth"].sum()))
c6.metric("Funds Received*", fmt(filtered["alloc_received"].sum(skipna=True)))

c7, c8, c9, c10 = st.columns(4)
c7.metric("Economic Cost*", fmt(filtered["economic_cost"].sum(skipna=True)))
c8.metric("Net Cash Position*", fmt(filtered["net_cash_position"].sum(skipna=True)))
c9.metric("Matched in Billing", f"{(filtered['matched_in_billing'] == 'Matched').sum():,}")
c10.metric("Not Matched", f"{(filtered['matched_in_billing'] == 'Not Matched').sum():,}")

st.caption("*Funds Received / Economic Cost / Net Cash Position depend on the RPA input table in the sidebar.")

# Layer 2
st.markdown("## Layer 2 — RPA Wise")
rpa_view = (
    filtered.groupby("deal_reference", dropna=False, as_index=False)
    .agg(
        deal_date=("deal_date", "min"),
        claims=("claim_id", "size"),
        sold_value=("claim_net", "sum"),
        funds_received=("alloc_received", "sum"),
        paid_billing=("paid_truth", "sum"),
        rejected_takeback=("rejected_truth", "sum"),
        pending_balance=("pending_truth", "sum"),
        economic_cost=("economic_cost", "sum"),
        net_cash_position=("net_cash_position", "sum"),
    )
    .sort_values(["deal_date", "deal_reference"], ascending=[False, True])
)
st.dataframe(rpa_view, use_container_width=True, height=300)

# Layer 3
st.markdown("## Layer 3 — Claim Wise")
claim_cols = [
    "claim_id", "deal_reference", "deal_date", "payer", "insurance", "visit_no", "visit_date",
    "claim_net", "alloc_received", "paid_truth", "rejected_truth", "pending_truth",
    "current_status_truth", "matched_in_billing", "activity_rows", "economic_cost", "net_cash_position"
]
claim_view = filtered[claim_cols].copy()
st.dataframe(claim_view, use_container_width=True, height=420)

# Drill-down
st.markdown("## Drill-down — Billing Detail")
selected_claim = st.selectbox("Select Claim ID", [""] + claim_view["claim_id"].astype(str).tolist())
if selected_claim and not detail_std.empty:
    drill = detail_std[detail_std["claim_id"].astype(str) == selected_claim].copy()
    if drill.empty:
        st.warning("No detail rows found for this claim.")
    else:
        st.dataframe(drill, use_container_width=True, height=350)
else:
    st.caption("Upload Billing Detail file and select a claim to see activity-level breakdown.")

# Downloads
st.markdown("## Download")
download_master = master.copy()
download_rpa = rpa_view.copy()
download_claims = claim_view.copy()

excel_bytes = to_excel_bytes(
    {
        "Master_Merged": download_master,
        "RPA_Summary": download_rpa,
        "Claim_View": download_claims,
        "Klaim_Standardized": klaim_std,
        "Billing_Summary_Standardized": summary_std,
        "Billing_Detail_Standardized": detail_std if not detail_std.empty else pd.DataFrame(),
    }
)
st.download_button(
    "Download Full Klaim Tracker Excel",
    data=excel_bytes,
    file_name="klaim_tracker_output.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
)

st.markdown("## Notes")
st.write(
    """
- Billing Summary is used as the source of truth for Paid / TakeBack / Balance.
- Billing Detail is used only for drill-down, not for top totals.
- Klaim file is used for sold claims and RPA mapping.
- If you enter RPA total value, sale price, fees, and funds received in the sidebar, the app allocates received amount and fees claim-wise.
"""
)
