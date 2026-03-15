#!/usr/bin/env python3

import os
import hashlib
import argparse
from datetime import datetime
import pandas as pd
from openpyxl import load_workbook
from openpyxl.styles import PatternFill, Font, Alignment

WRITE_EXCLUSIVE_SHEET = True

def sha1_short(path: str) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()[:12]

def parse_args():
    p = argparse.ArgumentParser(description="Build Exclusive_Report_with_Aging from an input .xlsx")
    p.add_argument("input_xlsx", help="Path to source Excel (.xlsx)")
    p.add_argument("--out", dest="out_xlsx", required=True, help="Path to write the output workbook (.xlsx)")
    args = p.parse_args()

    if not os.path.exists(args.input_xlsx):
        raise FileNotFoundError(f"File not found: {args.input_xlsx}")
    if not args.input_xlsx.lower().endswith(".xlsx"):
        raise ValueError("Input must be .xlsx")

    out_dir = os.path.dirname(os.path.abspath(args.out_xlsx)) or "."
    os.makedirs(out_dir, exist_ok=True)
    return args

def load_data(input_file: str) -> pd.DataFrame:
    df = pd.read_excel(input_file, engine="openpyxl")
    df.columns = df.columns.str.strip()
    return df

def ensure_numeric(df: pd.DataFrame) -> pd.DataFrame:
    num_cols = [
        "ActivityIns",
        "actRemitInsShare",
        "actResub1RemitInsShare",
        "actResub2RemitInsShare",
        "actResub3RemitInsShare",
        "TKBKAmountAct",
    ]
    for c in num_cols:
        if c not in df.columns:
            df[c] = 0
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
    return df

def compute_measures(df: pd.DataFrame) -> pd.DataFrame:
    remit_cols = [
        "actRemitInsShare",
        "actResub1RemitInsShare",
        "actResub2RemitInsShare",
        "actResub3RemitInsShare",
        "TKBKAmountAct",
    ]

    df["Paid"] = df[remit_cols].sum(axis=1)

    df["Rejection"] = 0.0
    df["Accepted"] = 0.0
    df["Balance"] = 0.0

    lower_status = df["ActivityStatus"].astype(str).str.strip().str.lower() if "ActivityStatus" in df.columns else ""

    denial_present = df["DenialCode"].notna() if "DenialCode" in df.columns else False

    mask_paid = df["Paid"] > 0
    mask_reject = (df["Paid"] == 0) & (lower_status == "rejected") & denial_present
    mask_balance = (df["Paid"] == 0) & ~mask_reject

    df.loc[mask_paid, "Accepted"] = (df.loc[mask_paid, "ActivityIns"] - df.loc[mask_paid, "Paid"]).clip(lower=0)
    df.loc[mask_reject, "Rejection"] = df.loc[mask_reject, "ActivityIns"]
    df.loc[mask_balance, "Balance"] = df.loc[mask_balance, "ActivityIns"]

    return df

def add_aging(df: pd.DataFrame) -> pd.DataFrame:
    date_candidates = [c for c in ["SubmissionDate", "ClaimDate", "VisitDate"] if c in df.columns]

    if date_candidates:
        for c in date_candidates:
            df[c] = pd.to_datetime(df[c], errors="coerce", dayfirst=True)
        df["RefDate"] = df[date_candidates].bfill(axis=1).iloc[:, 0]
    else:
        df["RefDate"] = pd.NaT

    today = pd.Timestamp(datetime.today().date())
    df["DaysDiff"] = (today - df["RefDate"]).dt.days

    bins = [-1, 30, 45, 60, 90, float("inf")]
    labels = ["0–30 Days", "31–45 Days", "46–60 Days", "61–90 Days", ">90 Days"]
    df["AgingBucket"] = pd.cut(df["DaysDiff"], bins=bins, labels=labels)
    return df

def ensure_insurance_column(df: pd.DataFrame) -> pd.DataFrame:
    insurance_col = next((c for c in ["Insurance", "PayerName", "Insurer", "Plan"] if c in df.columns), "Insurance")
    if insurance_col not in df.columns:
        df["Insurance"] = "Not Available"
    elif insurance_col != "Insurance":
        df["Insurance"] = df[insurance_col]
    return df

def build_balance_aging_summary(balance_df: pd.DataFrame) -> pd.DataFrame:
    labels = ["0–30 Days", "31–45 Days", "46–60 Days", "61–90 Days", ">90 Days"]

    pivot_summary = pd.pivot_table(
        balance_df,
        index="Insurance",
        columns="AgingBucket",
        values="Balance",
        aggfunc="sum",
        fill_value=0,
        observed=False,
    ).reindex(columns=labels, fill_value=0)

    pivot_summary["Grand Total"] = pivot_summary.sum(axis=1)
    pivot_summary.loc["Grand Total"] = pivot_summary.sum(axis=0)
    pivot_summary.reset_index(inplace=True)
    return pivot_summary

def build_insurance_totals(df: pd.DataFrame) -> pd.DataFrame:
    insurance_totals = (
        df.groupby("Insurance", dropna=False)[["ActivityIns", "Paid", "Rejection", "Accepted", "Balance"]]
        .sum()
        .reset_index()
    )

    insurance_totals = insurance_totals.rename(columns={"ActivityIns": "Net Amount", "Rejection": "Rejected"})

    insurance_totals = insurance_totals[["Insurance", "Net Amount", "Paid", "Balance", "Rejected", "Accepted"]]

    total_row = {
        "Insurance": "Grand Total",
        "Net Amount": insurance_totals["Net Amount"].sum(),
        "Paid": insurance_totals["Paid"].sum(),
        "Balance": insurance_totals["Balance"].sum(),
        "Rejected": insurance_totals["Rejected"].sum(),
        "Accepted": insurance_totals["Accepted"].sum(),
    }

    insurance_totals = pd.concat([insurance_totals, pd.DataFrame([total_row])], ignore_index=True)
    return insurance_totals

def build_monthly_totals(df: pd.DataFrame) -> pd.DataFrame:
    date_col = next((c for c in ["VisitDate", "SubmissionDate", "ClaimDate"] if c in df.columns), None)
    if date_col is None:
        return pd.DataFrame()

    temp = df.copy()
    temp[date_col] = pd.to_datetime(temp[date_col], errors="coerce", dayfirst=True)
    temp = temp.dropna(subset=[date_col])

    temp["_Month"] = temp[date_col].dt.to_period("M")

    monthly = (
        temp.groupby("_Month", observed=True)[["ActivityIns", "Paid", "Rejection", "Accepted", "Balance"]]
        .sum()
        .reset_index()
        .sort_values("_Month")
    )

    monthly["Month"] = monthly["_Month"].dt.strftime("%B %Y")

    monthly = monthly.rename(columns={"ActivityIns": "Net Amount", "Rejection": "Rejected"})

    monthly = monthly[["Month", "Net Amount", "Paid", "Balance", "Rejected", "Accepted"]]

    total_row = {
        "Month": "Grand Total",
        "Net Amount": monthly["Net Amount"].sum(),
        "Paid": monthly["Paid"].sum(),
        "Balance": monthly["Balance"].sum(),
        "Rejected": monthly["Rejected"].sum(),
        "Accepted": monthly["Accepted"].sum(),
    }

    monthly = pd.concat([monthly, pd.DataFrame([total_row])], ignore_index=True)
    return monthly

HEADER_FILL = PatternFill(start_color="BDD7EE", end_color="BDD7EE", fill_type="solid")
TOTAL_FILL = PatternFill(start_color="FCE4D6", end_color="FCE4D6", fill_type="solid")

def style_headers(ws):
    for c in range(1, ws.max_column + 1):
        cell = ws.cell(row=1, column=c)
        cell.fill = HEADER_FILL
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal="center", vertical="center")

def apply_styling(output_file: str):
    wb = load_workbook(output_file)

    for ws in wb.worksheets:
        style_headers(ws)

        if ws.title in ("Insurance_Totals", "Monthly_Totals"):
            for r in range(2, ws.max_row + 1):
                if ws.cell(row=r, column=1).value == "Grand Total":
                    for c in range(1, ws.max_column + 1):
                        cell = ws.cell(row=r, column=c)
                        cell.fill = TOTAL_FILL
                        cell.font = Font(bold=True)

    wb.save(output_file)

def main():
    args = parse_args()
    input_file = os.path.abspath(args.input_xlsx)
    out_file = os.path.abspath(args.out_xlsx)

    df = load_data(input_file)
    df = ensure_numeric(df)
    df = compute_measures(df)
    df = add_aging(df)
    df = ensure_insurance_column(df)

    balance_df = df.loc[df["Balance"] > 0].copy()

    pivot_summary = build_balance_aging_summary(balance_df)
    insurance_totals = build_insurance_totals(df)
    monthly_totals = build_monthly_totals(df)

    with pd.ExcelWriter(out_file, engine="openpyxl") as writer:

        insurance_totals.to_excel(writer, sheet_name="Insurance_Totals", index=False)

        if not monthly_totals.empty:
            monthly_totals.to_excel(writer, sheet_name="Monthly_Totals", index=False)

        pivot_summary.to_excel(writer, sheet_name="Balance_Aging_Summary", index=False)
        balance_df.to_excel(writer, sheet_name="Balance_Aging_Detail", index=False)

        if WRITE_EXCLUSIVE_SHEET:
            df.to_excel(writer, sheet_name="Exclusive_Report", index=False)

    apply_styling(out_file)

if __name__ == "__main__":
    main()
