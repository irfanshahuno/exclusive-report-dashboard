import io
import hashlib
from datetime import datetime

import pandas as pd
import streamlit as st
from openpyxl import load_workbook
from openpyxl.styles import PatternFill, Font, Alignment

# -------------------- helpers --------------------
def sha1_short(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()[:12]

# -------------------- ETL --------------------
def load_data(file_bytes: bytes) -> pd.DataFrame:
    df = pd.read_excel(io.BytesIO(file_bytes), engine="openpyxl")
    df.columns = df.columns.str.strip()
    return df

def ensure_numeric(df):
    num_cols = [
        "ActivityIns",
        "actRemitInsShare", "actResub1RemitInsShare",
        "actResub2RemitInsShare", "actResub3RemitInsShare",
        "TKBKAmountAct",
    ]
    for c in num_cols:
        if c not in df.columns:
            df[c] = 0
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
    return df

def compute_measures(df):
    df["Paid"] = df[[
        "actRemitInsShare", "actResub1RemitInsShare",
        "actResub2RemitInsShare", "actResub3RemitInsShare",
        "TKBKAmountAct"
    ]].sum(axis=1)

    df["Rejection"], df["Accepted"], df["Balance"] = 0.0, 0.0, 0.0

    if "ActivityStatus" in df.columns and "DenialCode" in df.columns:
        lower_status = df["ActivityStatus"].astype(str).str.lower()
        mask_paid    = df["Paid"] > 0
        mask_reject  = (df["Paid"] == 0) & (lower_status == "rejected") & (df["DenialCode"].notna())
        mask_balance = (df["Paid"] == 0) & ~mask_reject

        df.loc[mask_paid,    "Accepted"]  = df["ActivityIns"] - df["Paid"]
        df.loc[mask_reject,  "Rejection"] = df["ActivityIns"]
        df.loc[mask_balance, "Balance"]   = df["ActivityIns"]

    return df

def add_aging(df):
    date_candidates = [c for c in ["SubmissionDate", "ClaimDate", "VisitDate"] if c in df.columns]
    if date_candidates:
        for c in date_candidates:
            df[c] = pd.to_datetime(df[c], errors="coerce", dayfirst=True)
        df["RefDate"] = df[date_candidates].bfill(axis=1).iloc[:, 0]
    else:
        df["RefDate"] = pd.NaT

    today = pd.Timestamp(datetime.today().date())
    df["DaysDiff"] = (today - df["RefDate"]).dt.days

    bins   = [-1, 30, 45, 60, 90, float("inf")]
    labels = ["0–30 Days", "31–45 Days", "46–60 Days", "61–90 Days", ">90 Days"]
    df["AgingBucket"] = pd.cut(df["DaysDiff"], bins=bins, labels=labels)
    return df

def ensure_insurance_column(df):
    insurance_col = next(
        (c for c in ["Insurance", "PayerName", "Insurer", "Plan"] if c in df.columns),
        "Insurance"
    )
    if insurance_col not in df.columns:
        df["Insurance"] = "Not Available"
    elif insurance_col != "Insurance":
        df["Insurance"] = df[insurance_col]
    return df

# -------------------- builders --------------------
def build_balance_aging_summary(balance_df):
    labels = ["0–30 Days", "31–45 Days", "46–60 Days", "61–90 Days", ">90 Days"]
    pivot = pd.pivot_table(
        balance_df, index="Insurance", columns="AgingBucket",
        values="Balance", aggfunc="sum", fill_value=0, observed=False,
    ).reindex(columns=labels)
    pivot["Grand Total"] = pivot.sum(axis=1)
    pivot.loc["Grand Total"] = pivot.sum(axis=0)
    pivot.reset_index(inplace=True)
    return pivot

def build_insurance_totals(df):
    t = (
        df.groupby("Insurance", dropna=False)[["ActivityIns","Paid","Rejection","Accepted","Balance"]]
          .sum().reset_index()
    )
    t = t.rename(columns={"ActivityIns": "Net Amount", "Rejection": "Rejected"})
    t = t[["Insurance","Net Amount","Paid","Balance","Rejected","Accepted"]]
    total = {
        "Insurance": "Grand Total",
        "Net Amount": t["Net Amount"].sum(),
        "Paid": t["Paid"].sum(),
        "Balance": t["Balance"].sum(),
        "Rejected": t["Rejected"].sum(),
        "Accepted": t["Accepted"].sum(),
    }
    return pd.concat([t, pd.DataFrame([total])], ignore_index=True)

def build_monthly_totals(df):
    date_col = next((c for c in ["VisitDate","SubmissionDate","ClaimDate"] if c in df.columns), None)
    if date_col is None:
        return pd.DataFrame()
    df = df.copy()
    df[date_col] = pd.to_datetime(df[date_col], errors="coerce", dayfirst=True)
    df = df.dropna(subset=[date_col])
    df["_Month"] = df[date_col].dt.to_period("M")
    m = (
        df.groupby("_Month", observed=True)[["ActivityIns","Paid","Rejection","Accepted","Balance"]]
          .sum().reset_index()
    )
    m["_Month"] = m["_Month"].dt.strftime("%B %Y")
    m = m.rename(columns={"_Month":"Month","ActivityIns":"Net Amount","Rejection":"Rejected"})
    m = m[["Month","Net Amount","Paid","Balance","Rejected","Accepted"]]
    total = {
        "Month": "Grand Total",
        "Net Amount": m["Net Amount"].sum(),
        "Paid": m["Paid"].sum(),
        "Balance": m["Balance"].sum(),
        "Rejected": m["Rejected"].sum(),
        "Accepted": m["Accepted"].sum(),
    }
    return pd.concat([m, pd.DataFrame([total])], ignore_index=True)

def build_monthly_insurance_detail(df):
    date_col = next((c for c in ["VisitDate","SubmissionDate","ClaimDate"] if c in df.columns), None)
    if date_col is None:
        return pd.DataFrame()
    df = df.copy()
    df[date_col] = pd.to_datetime(df[date_col], errors="coerce", dayfirst=True)
    df = df.dropna(subset=[date_col])
    df["_Month"] = df[date_col].dt.to_period("M").dt.strftime("%B %Y")
    r = (
        df.groupby(["_Month","Insurance"], observed=True)[["ActivityIns","Paid","Rejection","Accepted","Balance"]]
          .sum().reset_index()
    )
    r = r.rename(columns={"_Month":"Month","ActivityIns":"Net Amount","Rejection":"Rejected"})
    return r[["Month","Insurance","Net Amount","Paid","Balance","Rejected","Accepted"]]

# -------------------- styling --------------------
HEADER_FILL = PatternFill(start_color="BDD7EE", end_color="BDD7EE", fill_type="solid")
TOTAL_FILL  = PatternFill(start_color="FCE4D6", end_color="FCE4D6", fill_type="solid")

def style_headers(ws):
    for c in range(1, ws.max_column + 1):
        cell = ws.cell(row=1, column=c)
        cell.fill = HEADER_FILL
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal="center", vertical="center")

def apply_styling(wb):
    for ws in wb.worksheets:
        style_headers(ws)
        if ws.title == "Balance_Aging_Summary":
            for r in range(2, ws.max_row + 1):
                if ws.cell(row=r, column=1).value == "Grand Total":
                    for c in range(1, ws.max_column + 1):
                        cell = ws.cell(row=r, column=c)
                        cell.fill = TOTAL_FILL
                        cell.font = Font(bold=True)
            last_col = ws.max_column
            for r in range(1, ws.max_row + 1):
                cell = ws.cell(row=r, column=last_col)
                cell.fill = TOTAL_FILL
                cell.font = Font(bold=True)
        if ws.title in ("Insurance_Totals", "Monthly_Totals"):
            for r in range(2, ws.max_row + 1):
                if ws.cell(row=r, column=1).value == "Grand Total":
                    for c in range(1, ws.max_column + 1):
                        cell = ws.cell(row=r, column=c)
                        cell.fill = TOTAL_FILL
                        cell.font = Font(bold=True)
    return wb

# -------------------- generate report in memory --------------------
def generate_report(file_bytes: bytes, filename: str) -> bytes:
    df = load_data(file_bytes)
    df = ensure_numeric(df)
    df = compute_measures(df)
    df = add_aging(df)
    df = ensure_insurance_column(df)

    balance_df              = df.loc[df["Balance"] > 0].copy()
    pivot_summary           = build_balance_aging_summary(balance_df)
    insurance_totals        = build_insurance_totals(df)
    monthly_totals          = build_monthly_totals(df)
    monthly_insurance_detail = build_monthly_insurance_detail(df)

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        # Sheet 1
        insurance_totals.to_excel(writer, sheet_name="Insurance_Totals", index=False)
        # Sheet 2
        if not monthly_totals.empty:
            monthly_totals.to_excel(writer, sheet_name="Monthly_Totals", index=False)
        else:
            pd.DataFrame([{"Note": "No date column found"}]).to_excel(writer, sheet_name="Monthly_Totals", index=False)
        # Sheet 3
        if not monthly_insurance_detail.empty:
            monthly_insurance_detail.to_excel(writer, sheet_name="Monthly_Insurance_Detail", index=False)
        else:
            pd.DataFrame([{"Note": "No date column found"}]).to_excel(writer, sheet_name="Monthly_Insurance_Detail", index=False)
        # Sheet 4
        pivot_summary.to_excel(writer, sheet_name="Balance_Aging_Summary", index=False)
        # Sheet 5
        balance_df.to_excel(writer, sheet_name="Balance_Aging_Detail", index=False)
        # Sheet 6 - always write raw data (reset categoricals first)
        df_export = df.copy()
        for col in df_export.select_dtypes(["category"]).columns:
            df_export[col] = df_export[col].astype(str)
        df_export.to_excel(writer, sheet_name="Exclusive_Report", index=False)
        # Sheet 7
        meta = pd.DataFrame([{
            "InputFile":   filename,
            "InputSHA1":   sha1_short(file_bytes),
            "GeneratedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }])
        meta.to_excel(writer, sheet_name="Meta", index=False)

    # Apply styling
    output.seek(0)
    wb = load_workbook(output)
    wb = apply_styling(wb)
    styled = io.BytesIO()
    wb.save(styled)
    styled.seek(0)
    return styled.read()

# -------------------- Streamlit UI --------------------
st.set_page_config(page_title="Exclusive Report Generator", page_icon="📊", layout="centered")

st.title("📊 Exclusive Report Generator")
st.markdown("Upload your billing Excel file and download the full report.")

uploaded_file = st.file_uploader("Upload Excel file (.xlsx)", type=["xlsx"])

if uploaded_file:
    st.success(f"✅ File uploaded: **{uploaded_file.name}**")

    if st.button("Generate Report", type="primary"):
        with st.spinner("Processing..."):
            try:
                file_bytes = uploaded_file.read()
                result_bytes = generate_report(file_bytes, uploaded_file.name)

                out_name = uploaded_file.name.replace(".xlsx", "_report.xlsx")
                st.download_button(
                    label="⬇️ Download Report",
                    data=result_bytes,
                    file_name=out_name,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
                st.success("Report ready! Click the button above to download.")
            except Exception as e:
                st.error(f"❌ Error: {e}")
