#!/usr/bin/env python3
import argparse
import glob
from pathlib import Path
from datetime import datetime

import pandas as pd
from openpyxl import load_workbook
from openpyxl.styles import PatternFill, Font, Alignment

# ===================== CLI =====================
parser = argparse.ArgumentParser(description="Build Exclusive Report (XLSB input only)")
parser.add_argument("input", nargs="?", help="Path to .xlsb file. If omitted, will search current folder.")
parser.add_argument("--out", required=False, default="Exclusive_Report_with_Aging.xlsx",
                    help="Output .xlsx path (default: ./Exclusive_Report_with_Aging.xlsx)")
args = parser.parse_args()

# ===================== Resolve input (.xlsb only) =====================
if args.input:
    in_path = Path(args.input).expanduser().resolve()
    if not in_path.exists():
        raise FileNotFoundError(f"❌ Input file not found: {in_path}")
    if in_path.suffix.lower() != ".xlsb":
        raise ValueError(f"❌ Input must be .xlsb, got: {in_path.suffix}")
else:
    # fallback: search current dir for any .xlsb except ones containing "Rejection_Report"
    matches = [Path(p) for p in glob.glob("*.xlsb") if "Rejection_Report" not in p]
    if not matches:
        raise FileNotFoundError("❌ No XLSB file found in this folder.")
    in_path = matches[0]

print(f"📂 Using input file: {in_path}")

# ===================== Resolve output =====================
out_path = Path(args.out).expanduser().resolve()
out_path.parent.mkdir(parents=True, exist_ok=True)

# ===================== Load Data (.xlsb) =====================
df = pd.read_excel(in_path, engine="pyxlsb")
df.columns = df.columns.str.strip()

# ===================== Convert numeric columns =====================
num_cols = [
    "ActivityIns","actRemitInsShare","actResub1RemitInsShare",
    "actResub2RemitInsShare","actResub3RemitInsShare","TKBKAmountAct"
]
for c in num_cols:
    if c not in df.columns:
        df[c] = 0
    df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)

# ===================== Compute Paid & Derived =====================
df["Paid"] = df[
    ["actRemitInsShare","actResub1RemitInsShare",
     "actResub2RemitInsShare","actResub3RemitInsShare","TKBKAmountAct"]
].sum(axis=1)

df["Rejection"], df["Accepted"], df["Balance"] = 0.0, 0.0, 0.0

if "ActivityStatus" in df.columns and "DenialCode" in df.columns:
    lower_status = df["ActivityStatus"].astype(str).str.lower()
    mask_paid = df["Paid"] > 0
    mask_reject = (df["Paid"] == 0) & (lower_status == "rejected") & (df["DenialCode"].notna())
    mask_balance = (df["Paid"] == 0) & ~mask_reject

    df.loc[mask_paid, "Accepted"]   = df["ActivityIns"] - df["Paid"]
    df.loc[mask_reject, "Rejection"] = df["ActivityIns"]
    df.loc[mask_balance, "Balance"]  = df["ActivityIns"]

# ===================== Aging Calculation =====================
date_cols = [c for c in ["SubmissionDate", "ClaimDate", "VisitDate"] if c in df.columns]
if date_cols:
    for col in date_cols:
        df[col] = pd.to_datetime(df[col], errors="coerce", dayfirst=True)
    # first non-null among the date columns
    df["RefDate"] = df[date_cols].bfill(axis=1).iloc[:, 0]
else:
    df["RefDate"] = pd.NaT

today = pd.Timestamp(datetime.today().date())
df["DaysDiff"] = (today - df["RefDate"]).dt.days

bins = [-1, 30, 45, 60, 90, float("inf")]
labels = ["0–30 Days","31–45 Days","46–60 Days","61–90 Days",">90 Days"]
df["AgingBucket"] = pd.cut(df["DaysDiff"], bins=bins, labels=labels)

# ===================== Balance subset =====================
balance_df = df.loc[df["Balance"] > 0].copy()

# ===================== Insurance column =====================
insurance_col = next((c for c in ["Insurance","PayerName","Insurer","Plan"] if c in df.columns), "Insurance")
if insurance_col not in balance_df.columns:
    balance_df[insurance_col] = "Not Available"

# ===================== Pivot (Summary) =====================
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

# ===================== Write Excel (.xlsx) =====================
with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
    df.to_excel(writer, sheet_name="Exclusive_Report", index=False)
    pivot_summary.to_excel(writer, sheet_name="Balance_Aging_Summary", index=False)
    balance_df.to_excel(writer, sheet_name="Balance_Aging_Detail", index=False)

# ===================== Style Headers & Totals =====================
wb = load_workbook(out_path)

for ws in wb.worksheets:
    header_fill = PatternFill(start_color="BDD7EE", end_color="BDD7EE", fill_type="solid")  # blue
    total_fill = PatternFill(start_color="FCE4D6", end_color="FCE4D6", fill_type="solid")  # light orange

    # headers
    for c in range(1, ws.max_column + 1):
        cell = ws.cell(row=1, column=c)
        cell.fill = header_fill
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal="center", vertical="center")

    # highlight totals in summary
    if ws.title == "Balance_Aging_Summary":
        # Grand Total row
        for r in range(2, ws.max_row + 1):
            if ws.cell(row=r, column=1).value == "Grand Total":
                for c in range(1, ws.max_column + 1):
                    cell = ws.cell(row=r, column=c)
                    cell.fill = total_fill
                    cell.font = Font(bold=True)
        # Grand Total column (last col)
        last_col = ws.max_column
        for r in range(1, ws.max_row + 1):
            cell = ws.cell(row=r, column=last_col)
            cell.fill = total_fill
            cell.font = Font(bold=True)

print("💾 Saving file, please wait...")
wb.save(out_path)
print("✅ File saved successfully!")
print(f"📁 Created: {out_path}")

