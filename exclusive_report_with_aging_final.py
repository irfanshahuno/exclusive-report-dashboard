#!/usr/bin/env python3
import sys, os, glob
from datetime import datetime
import pandas as pd
from openpyxl import load_workbook
from openpyxl.styles import PatternFill, Font, Alignment

# ============================================================
# Optional CLI:
#   python exclusive_report_with_aging_final.py input.xlsx --out output.xlsx
# If no args are provided, it auto-picks the first .xlsx (excluding Rejection_Report)
# and writes Exclusive_Report_with_Aging.xlsx (your original behavior).
# ============================================================

def parse_cli() -> tuple[str, str]:
    files = glob.glob("*.xlsx")
    files = [f for f in files if "Rejection_Report" not in f]

    input_file = None
    out_file = "Exclusive_Report_with_Aging.xlsx"

    # simple argv parser
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--out":
            if i + 1 >= len(args):
                raise SystemExit("error: --out requires a filename")
            out_file = args[i + 1]
            i += 2
        elif a.startswith("-"):
            raise SystemExit(f"unknown argument: {a}")
        else:
            # positional = input file
            input_file = a
            i += 1

    if input_file is None:
        if not files:
            raise FileNotFoundError("❌ No Excel file found in this folder.")
        input_file = files[0]

    return input_file, out_file


def main():
    # ---- STEP 1: Locate Excel file ----
    input_file, output_file = parse_cli()
    print(f"📂 Using input file: {input_file}")
    print(f"📝 Output will be: {output_file}")

    # ---- STEP 2: Load Data ----
    df = pd.read_excel(input_file, engine="openpyxl")
    df.columns = df.columns.str.strip()

    # ---- STEP 3: Convert numeric columns ----
    num_cols = [
        "ActivityIns", "actRemitInsShare", "actResub1RemitInsShare",
        "actResub2RemitInsShare", "actResub3RemitInsShare", "TKBKAmountAct"
    ]
    for c in num_cols:
        if c not in df.columns:
            df[c] = 0
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)

    # ---- STEP 4: Compute Paid & Derived Columns (UNCHANGED LOGIC) ----
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

    # ---- STEP 5: Efficient Aging Calculation ----
    date_cols = [c for c in ["SubmissionDate", "ClaimDate", "VisitDate"] if c in df.columns]
    if date_cols:
        for col in date_cols:
            df[col] = pd.to_datetime(df[col], errors="coerce", dayfirst=True)
        df["RefDate"] = df[date_cols].bfill(axis=1).iloc[:, 0]
    else:
        df["RefDate"] = pd.NaT

    today = pd.Timestamp(datetime.today().date())
    df["DaysDiff"] = (today - df["RefDate"]).dt.days

    bins   = [-1, 30, 45, 60, 90, float("inf")]
    labels = ["0–30 Days", "31–45 Days", "46–60 Days", "61–90 Days", ">90 Days"]
    df["AgingBucket"] = pd.cut(df["DaysDiff"], bins=bins, labels=labels)

    # ---- STEP 6: Balance-only data (for Aging tabs) ----
    balance_df = df.loc[df["Balance"] > 0].copy()

    # ---- STEP 7: Determine insurance column ----
    insurance_col = next((c for c in ["Insurance", "PayerName", "Insurer", "Plan"] if c in df.columns), "Insurance")
    if insurance_col not in df.columns:
        df[insurance_col] = "Not Available"
        balance_df[insurance_col] = "Not Available"

    # ---- STEP 8: Balance_Aging_Summary (UNCHANGED) ----
    pivot_summary = pd.pivot_table(
        balance_df,
        index=insurance_col,
        columns="AgingBucket",
        values="Balance",
        aggfunc="sum",
        fill_value=0,
        observed=False
    )
    pivot_summary = pivot_summary.reindex(columns=labels)
    pivot_summary["Grand Total"] = pivot_summary.sum(axis=1)
    pivot_summary.loc["Grand Total"] = pivot_summary.sum(axis=0)
    pivot_summary.reset_index(inplace=True)

    # ---- NEW STEP 8B: Insurance_Totals (Amounts per insurance) ----
    # Net Amount, Paid, Balance, Rejection, Accepted with Grand Total row
    totals = df.groupby(insurance_col, dropna=False).agg({
        "ActivityIns": "sum",
        "Paid": "sum",
        "Balance": "sum",
        "Rejection": "sum",
        "Accepted": "sum"
    }).reset_index()

    # Rename to display names expected by dashboard
    totals = totals.rename(columns={
        insurance_col: "Insurance",
        "ActivityIns": "Net Amount",
        "Paid": "Paid",
        "Balance": "Balance",
        "Rejection": "Rejected",
        "Accepted": "Accepted"
    })

    # Append Grand Total row
    gt_row = {
        "Insurance": "Grand Total",
        "Net Amount": totals["Net Amount"].sum(),
        "Paid": totals["Paid"].sum(),
        "Balance": totals["Balance"].sum(),
        "Rejected": totals["Rejected"].sum(),
        "Accepted": totals["Accepted"].sum(),
    }
    totals = pd.concat([totals, pd.DataFrame([gt_row])], ignore_index=True)

    # ---- STEP 9: Write to Excel ----
    with pd.ExcelWriter(output_file, engine="openpyxl") as writer:
        df.to_excel(writer,                  sheet_name="Exclusive_Report",        index=False)
        totals.to_excel(writer,              sheet_name="Insurance_Totals",        index=False)  # NEW
        pivot_summary.to_excel(writer,       sheet_name="Balance_Aging_Summary",   index=False)
        balance_df.to_excel(writer,          sheet_name="Balance_Aging_Detail",    index=False)

    # ---- STEP 10: Styling Headers + Grand Total ----
    wb = load_workbook(output_file)
    header_fill = PatternFill(start_color="BDD7EE", end_color="BDD7EE", fill_type="solid")  # blue
    total_fill  = PatternFill(start_color="FCE4D6", end_color="FCE4D6", fill_type="solid")  # light orange

    for ws in wb.worksheets:
        # --- Style headers ---
        for c in range(1, ws.max_column + 1):
            cell = ws.cell(row=1, column=c)
            cell.fill = header_fill
            cell.font = Font(bold=True)
            cell.alignment = Alignment(horizontal="center", vertical="center")

        # --- Highlight 'Grand Total' row/column where applicable ---
        if ws.title in ("Balance_Aging_Summary", "Insurance_Totals"):
            # highlight the "Grand Total" row (first column must contain label)
            for r in range(2, ws.max_row + 1):
                val = ws.cell(row=r, column=1).value
                if str(val).strip().lower() in ("grand total", "grand_total", "totals", "total"):
                    for c in range(1, ws.max_column + 1):
                        cell = ws.cell(row=r, column=c)
                        cell.fill = total_fill
                        cell.font = Font(bold=True)
            # For Balance_Aging_Summary, also highlight the last column (Grand Total)
            if ws.title == "Balance_Aging_Summary":
                col = ws.max_column
                for r in range(1, ws.max_row + 1):
                    cell = ws.cell(row=r, column=col)
                    cell.fill = total_fill
                    cell.font = Font(bold=True)

    # ---- STEP 11: Save with progress message ----
    print("💾 Saving file, please wait... (this may take up to a minute for large files)")
    wb.save(output_file)
    print("✅ File saved successfully!")
    print(f"📁 Created: {output_file}")


if __name__ == "__main__":
    main()


