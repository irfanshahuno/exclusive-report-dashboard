import io
import re

import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st


st.set_page_config(page_title="RCM Management Dashboard", page_icon="📊", layout="wide")


def clean_name(name):
    return re.sub(r"\s+", "", str(name).replace("\xa0", " "))


def as_number(series):
    return pd.to_numeric(series, errors="coerce").fillna(0.0)


def status_key(value):
    return re.sub(r"\s+", "", str(value or "")).lower()


def col(df, name):
    """Return a numeric column; missing columns safely become zero."""
    return as_number(df[name]) if name in df.columns else pd.Series(0.0, index=df.index)


def prepare_claims(uploaded_file):
    raw = pd.read_excel(uploaded_file, dtype=object)
    raw.columns = [clean_name(x) for x in raw.columns]
    raw = raw.dropna(how="all").copy()

    # ActivityIns is the user's defined Net Amount.
    raw["Net Amount"] = col(raw, "ActivityIns")

    # Paid is all remittance amounts plus the initial take-back amount.
    # Resubmission approved amounts are moved to their own columns so no amount is double counted.
    resub_paid_columns = [
        "actResub1RemitInsShare", "actResub2RemitInsShare",
        "actResub3RemitInsShare", "actResub4RemitInsShare",
    ]
    for source in resub_paid_columns:
        if source not in raw.columns:
            raw[source] = 0.0
        else:
            raw[source] = col(raw, source)

    raw["General Paid"] = col(raw, "actRemitInsShare") + col(raw, "TKBKAmountAct")
    raw["Resub1 Approved"] = 0.0
    raw["Resub2 Approved"] = 0.0
    raw["Resub3 Approved"] = 0.0
    raw["Resub4 Approved"] = 0.0

    key = raw.get("Status", pd.Series("", index=raw.index)).map(status_key)
    for number in range(1, 5):
        approved = key.eq(f"approved(resub-{number})")
        source = f"actResub{number}RemitInsShare"
        destination = f"Resub{number} Approved"
        raw.loc[approved, destination] = raw.loc[approved, source]
        # The amount is now kept in the dedicated approved column only.
        raw.loc[approved, source] = 0.0

    raw["General Paid"] += sum(col(raw, x) for x in resub_paid_columns)
    raw["Paid"] = raw["General Paid"] + sum(col(raw, f"Resub{n} Approved") for n in range(1, 5))
    raw["Under Process"] = (raw["Net Amount"] - raw["Paid"]).abs()

    raw["Rejection"] = 0.0
    raw["Resub1 Rejection"] = 0.0
    raw["Resub2 Rejection"] = 0.0
    raw["Resub3 Rejection"] = 0.0
    raw["Accepted"] = 0.0
    raw["Resub1 Accepted"] = 0.0
    raw["Resub2 Accepted"] = 0.0

    # Initial rejection requires a rejection status AND a recorded DenialCode.
    initial_denial = raw.get("DenialCode", pd.Series("", index=raw.index)).fillna("").astype(str).str.strip().ne("")
    initial_rejected = key.eq("rejected") & initial_denial
    raw.loc[initial_rejected, "Rejection"] = raw.loc[initial_rejected, "Under Process"]
    raw.loc[initial_rejected, "Under Process"] = 0.0

    for number in range(1, 4):
        mask = key.eq(f"rejected(resub-{number})")
        destination = f"Resub{number} Rejection"
        raw.loc[mask, destination] = raw.loc[mask, "Under Process"]
        raw.loc[mask, "Under Process"] = 0.0

    accepted_rules = {
        "rejectionaccepted": "Accepted",
        "rejectionaccepted(resub-1)": "Resub1 Accepted",
        "rejectionaccepted(resub-2)": "Resub2 Accepted",
    }
    for rule, destination in accepted_rules.items():
        mask = key.eq(rule)
        raw.loc[mask, destination] = raw.loc[mask, "Under Process"]
        raw.loc[mask, "Under Process"] = 0.0

    # Dates are supplied as Excel text in this export; convert for reporting and aging.
    for date_col in ["VisitDate", "SubDate", "RemitDate"]:
        if date_col in raw.columns:
            raw[date_col] = pd.to_datetime(raw[date_col], dayfirst=True, errors="coerce")

    raw["Total Rejection"] = raw[["Rejection", "Resub1 Rejection", "Resub2 Rejection", "Resub3 Rejection"]].sum(axis=1)
    raw["Total Accepted"] = raw[["Accepted", "Resub1 Accepted", "Resub2 Accepted"]].sum(axis=1)
    raw["Reconciliation Difference"] = raw["Net Amount"] - (
        raw["Paid"] + raw["Under Process"] + raw["Total Rejection"] + raw["Total Accepted"]
    )
    return raw


def money(value):
    return f"AED {value:,.2f}"


st.markdown("""
<style>
    .block-container {padding-top: 1.6rem; padding-bottom: 2rem;}
    [data-testid="stMetric"] {background:#ffffff;border:1px solid #e7eaf0;border-radius:12px;padding:12px;}
    h1 {color:#17365d;}
</style>
""", unsafe_allow_html=True)
st.title("RCM Management Dashboard")
st.caption("Activity-level claims analysis • Net Amount = ActivityIns")

uploaded = st.file_uploader("Upload claims Excel file", type=["xlsx"])
if not uploaded:
    st.info("Upload the claims export to generate the dashboard.")
    st.stop()

try:
    df = prepare_claims(uploaded)
except Exception as exc:
    st.error(f"Could not read the Excel file: {exc}")
    st.stop()

with st.sidebar:
    st.header("Filters")
    if "Insurance" in df.columns:
        insurers = st.multiselect("Insurance", sorted(df["Insurance"].dropna().astype(str).unique()))
        if insurers:
            df = df[df["Insurance"].astype(str).isin(insurers)]
    if "DocName" in df.columns:
        doctors = st.multiselect("Doctor", sorted(df["DocName"].dropna().astype(str).unique()))
        if doctors:
            df = df[df["DocName"].astype(str).isin(doctors)]

net = df["Net Amount"].sum()
paid = df["Paid"].sum()
balance = df["Under Process"].sum()
rejection = df["Total Rejection"].sum()
accepted = df["Total Accepted"].sum()

m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("Net Amount", money(net))
m2.metric("Paid", money(paid))
m3.metric("Under Process", money(balance))
m4.metric("Rejection", money(rejection))
m5.metric("Accepted", money(accepted))

check = net - (paid + balance + rejection + accepted)
if abs(check) > 0.01:
    st.warning(f"Reconciliation difference: {money(check)}. Review rows where the amount exceeds paid/rejection/accepted status allocation.")
else:
    st.success("Reconciliation check passed: Net Amount = Paid + Under Process + Rejection + Accepted.")

tab1, tab2, tab3, tab4 = st.tabs(["Management Summary", "Rejections", "Doctor & Service", "Detailed Data"])
with tab1:
    by_insurance = df.groupby("Insurance", dropna=False)[["Net Amount", "Paid", "Under Process", "Total Rejection", "Total Accepted"]].sum().reset_index()
    by_insurance = by_insurance.sort_values("Net Amount", ascending=False)
    left, right = st.columns(2)
    with left:
        st.subheader("Insurance Summary")
        st.dataframe(by_insurance, use_container_width=True, hide_index=True, column_config={x: st.column_config.NumberColumn(format="AED %.2f") for x in by_insurance.columns[1:]})
    with right:
        chart_data = pd.DataFrame({"Category":["Paid", "Under Process", "Rejection", "Accepted"], "Amount":[paid, balance, rejection, accepted]})
        st.plotly_chart(px.pie(chart_data, names="Category", values="Amount", hole=.55, color_discrete_sequence=px.colors.sequential.Blues_r), use_container_width=True)

with tab2:
    denial_cols = [x for x in ["DenialCode", "DenialCode1", "DenialCode2", "DenialCode3", "FinalDenialCode"] if x in df.columns]
    denial_rows = []
    for code_col in denial_cols:
        tmp = df[df[code_col].fillna("").astype(str).str.strip().ne("")].copy()
        tmp["Denial Code"] = tmp[code_col].astype(str).str.strip()
        tmp["Rejected Amount"] = tmp["Total Rejection"]
        denial_rows.append(tmp[["Denial Code", "Rejected Amount"]])
    if denial_rows:
        denial = pd.concat(denial_rows).groupby("Denial Code", as_index=False).agg("sum").sort_values("Rejected Amount", ascending=False)
        st.subheader("Highest Rejection Codes")
        st.dataframe(denial, use_container_width=True, hide_index=True, column_config={"Rejected Amount":st.column_config.NumberColumn(format="AED %.2f")})
        st.plotly_chart(px.bar(denial.head(15), x="Rejected Amount", y="Denial Code", orientation="h", text_auto=".2s", color="Rejected Amount", color_continuous_scale="Reds"), use_container_width=True)
    else:
        st.info("No denial codes found.")

with tab3:
    doctor_service = df.groupby(["DocName", "Code", "Description", "Insurance"], dropna=False).agg(
        Activities=("ActID", "nunique"), Net_Amount=("Net Amount", "sum"), Paid=("Paid", "sum"), Rejection=("Total Rejection", "sum")
    ).reset_index().sort_values("Net_Amount", ascending=False)
    doctor_service["Doctor Net %"] = doctor_service["Net_Amount"] / net if net else 0
    st.subheader("Doctor / Service / Insurance Analysis")
    st.dataframe(doctor_service, use_container_width=True, hide_index=True, column_config={"Doctor Net %":st.column_config.NumberColumn(format="%.1f%%")})

with tab4:
    important = [x for x in ["VisitNo", "ActID", "VisitDate", "DocName", "Insurance", "Code", "Description", "Status", "Net Amount", "Paid", "Under Process", "Rejection", "Resub1 Rejection", "Resub2 Rejection", "Resub3 Rejection", "Accepted", "Resub1 Accepted", "Resub2 Accepted", "Resub1 Approved", "Resub2 Approved", "Resub3 Approved", "FinalDenialCode"] if x in df.columns]
    st.dataframe(df[important], use_container_width=True, hide_index=True)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Processed_Data", index=False)
        by_insurance.to_excel(writer, sheet_name="Insurance_Summary", index=False)
        if denial_rows:
            denial.to_excel(writer, sheet_name="Denial_Code_Summary", index=False)
        doctor_service.to_excel(writer, sheet_name="Doctor_Service", index=False)
    st.download_button("Download processed Excel report", output.getvalue(), "RCM_Management_Report.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
