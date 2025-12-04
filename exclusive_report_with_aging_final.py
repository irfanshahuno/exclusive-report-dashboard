#!/usr/bin/env python3
# exclusive_report_with_aging_final.py

import sys
import os
import hashlib
from datetime import datetime

import pandas as pd
from openpyxl import load_workbook
from openpyxl.styles import PatternFill, Font, Alignment


# ===============================
# Strict input handling
# ===============================
def pick_input_file() -> str:
    """
    Require the path to be passed explicitly:
        python exclusive_report_with_aging_final.py <path_to_xlsx>
    """
    if len(sys.argv) <= 1:
        raise ValueError(
            "❌ Please run:\n  python exclusive_report_with_aging_final.py <path_to_xlsx>\n"
            "Tip: your Streamlit app should pass the *saved upload path* here."
        )

    path = sys.argv[1]
    if not os.path.exists(path):
        raise FileNotFoundError(f"❌ File not found: {path}")
    if not path.lower().endswith(".xlsx"):
        raise ValueError("❌ Please provide an .xlsx file.")
    return path


def sha1_short(path: str) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()[:12]


# ===============================
# Load and normalize
# ===============================
def load_data(input_file: str) -> pd.DataFrame:
    # If your file has multiple sheets or a specific header row, set here:
    # df = pd.read_excel(input_file, sheet_name=0, header=0, engine="openpyxl")
    df = pd.read_excel(input_file, engine="openpyxl")
    df.columns = df.columns.str.strip()
    return df


def ensure_numeric(df: pd.DataFrame) -> pd.DataFrame:
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


# ===============================
# Metrics
# ===============================
def compute_measures(df: pd.DataFrame) -> pd.DataFrame:
    df["Paid"] = df[
        ["actRemitInsShare", "actResub1RemitInsShare",
         "actResub2RemitInsShare", "actResub3RemitInsShare",
         "TKBKAmountAct"]
    ].sum(axis=1)

    df["Rejection"], df["Accepted"], df["Balance"] = 0.0, 0.0, 0.0

    if "ActivityStatus" in df.columns and "DenialCode" in df.columns:
        lower_status = df["ActivityStatus"].astype(str).str.lower()
        mask_paid = df["Paid"] > 0
        mask_reject = (df["Paid"] == 0) & (lower_status == "rejected") & (df["DenialCode"].notna())
        mask_balance = (df["Paid"] == 0) & ~mask_reject

        df.loc[mask_paid, "Accepted"] = df["ActivityIns"] - df["Paid"]
        df.loc[mask_reject, "Rejection"] = df["ActivityIns"]
        df.loc[mask_balance, "Balance"] = df["ActivityIns"]

    return df


def add_aging(df: pd.DataFrame) -> pd.DataFrame:
    date_candidates = [c for c in ["SubmissionDate", "ClaimDate", "VisitDate"] if c in df.columns]
    if date_candidates:
        for c in date_candidates:
            df[c] = pd.to_datetime(df[c], errors="coerce", dayfirst=True)
        # first non-null among candidates
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


# ===============================
# Build outputs
# ===============================
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
    ).reindex(columns=labels)

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
    insurance_totals = insurance_totals.rename(columns={
        "ActivityIns": "Net Amount",
        "Rejection": "Rejected",
    })
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


# ===============================
# Write & style workbook
# ===============================
def style_headers(ws):
    header_fill = PatternFill(start_color="BDD7EE", end_color="BDD7EE", fill_type="solid")
    for c in range(1, ws.max_column + 1):
        cell = ws.cell(row=1, column=c)
        cell.fill = header_fill
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal="center", vertical="center")


def apply_styling(output_file: str):
    wb = load_workbook(output_file)
    total_fill = PatternFill(start_color="FCE4D6", end_color="FCE4D6", fill_type="solid")

    for ws in wb.worksheets:
        style_headers(ws)

        if ws.title == "Balance_Aging_Summary":
            # shade "Grand Total" row
            for r in range(2, ws.max_row + 1):
                if ws.cell(row=r, column=1).value == "Grand Total":
                    for c in range(1, ws.max_column + 1):
                        cell = ws.cell(row=r, column=c)
                        cell.fill = total_fill
                        cell.font = Font(bold=True)
            # shade last column (Grand Total)
            last_col = ws.max_column
            for r in range(1, ws.max_row + 1):
                cell = ws.cell(row=r, column=last_col)
                cell.fill = total_fill
                cell.font = Font(bold=True)

        if ws.title == "Insurance_Totals":
            for r in range(2, ws.max_row + 1):
                if ws.cell(row=r, column=1).value == "Grand Total":
                    for c in range(1, ws.max_column + 1):
                        cell = ws.cell(row=r, column=c)
                        cell.fill = total_fill
                        cell.font = Font(bold=True)

    print("💾 Saving file, please wait...")
    wb.save(output_file)
    print("✅ File saved successfully!")
    print(f"📁 Created: {output_file}")


# ===============================
# Main
# ===============================
def main():
    input_file = pick_input_file()
    print(f"📂 Using input file: {input_file}")
    print(f"🔑 SHA1: {sha1_short(input_file)}")

    df = load_data(input_file)
    df = ensure_numeric(df)
    df = compute_measures(df)
    df = add_aging(df)
    df = ensure_insurance_column(df)

    balance_df = df.loc[df["Balance"] > 0].copy()

    pivot_summary = build_balance_aging_summary(balance_df)
    insurance_totals = build_insurance_totals(df)

    output_file = "Exclusive_Report_with_Aging.xlsx"
    with pd.ExcelWriter(output_file, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Exclusive_Report", index=False)                  # 1
        insurance_totals.to_excel(writer, sheet_name="Insurance_Totals", index=False)   # 2
        pivot_summary.to_excel(writer, sheet_name="Balance_Aging_Summary", index=False)  # 3
        balance_df.to_excel(writer, sheet_name="Balance_Aging_Detail", index=False)     # 4

    apply_styling(output_file)


if __name__ == "__main__":
    main()
