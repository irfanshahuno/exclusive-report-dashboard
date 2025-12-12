import pandas as pd
import glob, os
from datetime import datetime
from openpyxl import load_workbook
from openpyxl.styles import PatternFill, Font, Alignment

# ==== STEP 1: Locate Excel file ====
files = glob.glob("*.xlsx")
if not files:
    raise FileNotFoundError("❌ No Excel file found in this folder.")
input_file = [f for f in files if "Rejection_Report" not in f][0]
print(f"📂 Using input file: {input_file}")

# ==== STEP 2: Load Data ====
df = pd.read_excel(input_file, engine="openpyxl")
df.columns = df.columns.str.strip()

# ==== STEP 3: Convert numeric columns ====
num_cols = [
    "ActivityIns","actRemitInsShare","actResub1RemitInsShare",
    "actResub2RemitInsShare","actResub3RemitInsShare","TKBKAmountAct"
]
for c in num_cols:
    if c not in df.columns:
        df[c] = 0
    df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)

# ==== STEP 4: Compute Paid & Derived Columns ====
df["Paid"] = df[
    ["actRemitInsShare","actResub1RemitInsShare",
     "actResub2RemitInsShare","actResub3RemitInsShare",
     "TKBKAmountAct"]
].sum(axis=1)

df["Rejection"], df["Accepted"], df["Balance"] = 0.0, 0.0, 0.0

if "ActivityStatus" in df.columns and "DenialCode" in df.columns:
    lower_status = df["ActivityStatus"].astype(str).str.lower()
    mask_paid = df["Paid"] > 0
    mask_reject = (df["Paid"] == 0) & (lower_status == "rejected") & (df["DenialCode"].notna())
    mask_balance = (df["Paid"] == 0) & ~mask_reject

    df.loc[mask_paid, "Accepted"]  = df["ActivityIns"] - df["Paid"]
    df.loc[mask_reject, "Rejection"] = df["ActivityIns"]
    df.loc[mask_balance, "Balance"]  = df["ActivityIns"]

# ==== STEP 5: Efficient Aging Calculation ====
date_cols = [c for c in ["SubmissionDate", "ClaimDate", "VisitDate"] if c in df.columns]
if date_cols:
    for col in date_cols:
        df[col] = pd.to_datetime(df[col], errors="coerce", dayfirst=True)
    df["RefDate"] = df[date_cols].bfill(axis=1).iloc[:, 0]
else:
    df["RefDate"] = pd.NaT

today = pd.Timestamp(datetime.today().date())
df["DaysDiff"] = (today - df["RefDate"]).dt.days

bins = [-1, 30, 45, 60, 90, float("inf")]
labels = ["0–30 Days","31–45 Days","46–60 Days","61–90 Days",">90 Days"]
df["AgingBucket"] = pd.cut(df["DaysDiff"], bins=bins, labels=labels)

# ==== STEP 6: Filter balance data ====
balance_df = df.loc[df["Balance"] > 0].copy()

# ==== STEP 7: Determine insurance column ====
insurance_col = next((c for c in ["Insurance","PayerName","Insurer","Plan"] if c in df.columns), "Insurance")
if insurance_col not in df.columns:
    balance_df[insurance_col] = "Not Available"

# ==== STEP 8: Pivot Summary (no warning) ====
pivot_summary = pd.pivot_table(
    balance_df,
    index=insurance_col,
    columns="AgingBucket",
    values="Balance",
    aggfunc="sum",
    fill_value=0,
    observed=False  # suppresses future warning
)

pivot_summary = pivot_summary.reindex(columns=labels)
pivot_summary["Grand Total"] = pivot_summary.sum(axis=1)
pivot_summary.loc["Grand Total"] = pivot_summary.sum(axis=0)
pivot_summary.reset_index(inplace=True)

# ==== STEP 9: Write to Excel ====
output_file = "Exclusive_Report_with_Aging.xlsx"
with pd.ExcelWriter(output_file, engine="openpyxl") as writer:
    df.to_excel(writer, sheet_name="Exclusive_Report", index=False)
    pivot_summary.to_excel(writer, sheet_name="Balance_Aging_Summary", index=False)
    balance_df.to_excel(writer, sheet_name="Balance_Aging_Detail", index=False)

# ==== STEP 10: Styling Headers + Grand Total ====
wb = load_workbook(output_file)

for ws in wb.worksheets:
    header_fill = PatternFill(start_color="BDD7EE", end_color="BDD7EE", fill_type="solid")  # blue
    total_fill = PatternFill(start_color="FCE4D6", end_color="FCE4D6", fill_type="solid")  # light orange

    # --- Style headers ---
    for c in range(1, ws.max_column + 1):
        cell = ws.cell(row=1, column=c)
        cell.fill = header_fill
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal="center", vertical="center")

    # --- Highlight Grand Total row/column (only in summary sheet) ---
    if ws.title == "Balance_Aging_Summary":
        for r in range(2, ws.max_row + 1):
            val = ws.cell(row=r, column=1).value
            if val == "Grand Total":
                for c in range(1, ws.max_column + 1):
                    cell = ws.cell(row=r, column=c)
                    cell.fill = total_fill
                    cell.font = Font(bold=True)
        # Grand Total column (last)
        col = ws.max_column
        for r in range(1, ws.max_row + 1):
            cell = ws.cell(row=r, column=col)
            cell.fill = total_fill
            cell.font = Font(bold=True)

# ==== STEP 11: Save with progress message ====
print("💾 Saving file, please wait... (this may take up to a minute for large files)")
wb.save(output_file)
print("✅ File saved successfully!")
print(f"📁 Created: {output_file}")

