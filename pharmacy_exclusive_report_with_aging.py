#!/usr/bin/env python3
import time
import pandas as pd
import glob
from datetime import datetime
from openpyxl import load_workbook
from openpyxl.styles import PatternFill, Font, Alignment

# =================== CONFIG ===================
OUTPUT_XLSX     = "Pharmacy_Exclusive_Report_with_Aging.xlsx"
TINY_THRESHOLD  = 4        # ≤ 4 goes to Accepted (not Balance)
DECIMALS        = 2
BINS            = [-1, 30, 45, 60, 90, float("inf")]
LABELS          = ["0–30 Days", "31–45 Days", "46–60 Days", "61–90 Days", ">90 Days"]

# =================== HELPERS ===================
def find_input_file():
    files = [f for f in glob.glob("*.xlsx") if "Rejection_Report" not in f]
    if not files:
        raise FileNotFoundError("❌ No Excel file (.xlsx) found in this folder.")
    return files[0]

def ci_get(df, names):
    lower_map = {c.lower(): c for c in df.columns}
    for n in names:
        if n.lower() in lower_map:
            return lower_map[n.lower()]
    return None

def style_headers(wb):
    header_fill = PatternFill(start_color="BDD7EE", end_color="BDD7EE", fill_type="solid")  # blue
    total_fill  = PatternFill(start_color="FCE4D6", end_color="FCE4D6", fill_type="solid")  # light orange
    for ws in wb.worksheets:
        for c in range(1, ws.max_column + 1):
            cell = ws.cell(row=1, column=c)
            cell.fill = header_fill
            cell.font = Font(bold=True)
            cell.alignment = Alignment(horizontal="center", vertical="center")
        if ws.title == "Balance_Aging_Summary":
            for r in range(2, ws.max_row + 1):
                if ws.cell(row=r, column=1).value == "Grand Total":
                    for c in range(1, ws.max_column + 1):
                        gt = ws.cell(row=r, column=c)
                        gt.fill = total_fill
                        gt.font = Font(bold=True)
            last_col = ws.max_column
            for r in range(1, ws.max_row + 1):
                gt = ws.cell(row=r, column=last_col)
                gt.fill = total_fill
                gt.font = Font(bold=True)

# =================== TIMER START ===================
t0 = time.time()
print("▶️ Starting Pharmacy report…")

# =================== LOAD ===================
print("📂 Locating & loading Excel…")
input_file = find_input_file()
print(f"   Using: {input_file}")
df = pd.read_excel(input_file, engine="openpyxl")
df.columns = df.columns.str.strip()
t1 = time.time()
print(f"⏳ Load time: {t1 - t0:.2f}s")

# ===== Detect columns (prefer your pharmacy names) =====
col_net   = ci_get(df, ["Claim Amount","NetAmount","Net Amount","TotalAmount","Total Amount","Net"])
col_paid  = ci_get(df, ["Remitted Amount","Paid","Remit Amount","RemitAmount"])
col_stat  = ci_get(df, ["ClaimStatus","Status","ResponseType"])
col_payer = ci_get(df, ["Insurance","PayerName","Insurer","Plan","InsurancePlan"])
col_date  = ci_get(df, ["ClaimDate","RxDate","DispenseDate","SubmissionDate","VisitDate","DOS","DateOfService"])

missing = []
if not col_net:  missing.append("Claim Amount (net)")
if not col_paid: missing.append("Remitted Amount (paid)")
if not col_stat: missing.append("ClaimStatus")
if missing:
    raise ValueError("❌ Required columns missing: " + ", ".join(missing))
if not col_payer:
    col_payer = "Insurance"; df[col_payer] = "Not Available"
if not col_date:
    col_date = "ClaimDate"; df[col_date] = pd.NaT

# =================== PROCESS ===================
print("⚙️ Processing metrics…")
# Numerics & date
for c in [col_net, col_paid]:
    df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
df[col_date] = pd.to_datetime(df[col_date], errors="coerce", dayfirst=True)

lower_status = df[col_stat].astype(str).str.lower()
net  = df[col_net].clip(lower=0)
paid = df[col_paid].clip(lower=0)
diff = (net - paid).clip(lower=0)

df["Rejected"] = 0.0
df["Accepted"] = 0.0
df["Balance"]  = 0.0

# Rejected = full net when denied
mask_denied = (lower_status == "denied")
df.loc[mask_denied, "Rejected"] = net

# Accepted = tiny leftover (≤4) only when paid > 0 and not denied
mask_paid  = paid > 0
mask_tiny  = diff <= TINY_THRESHOLD
mask_acc   = (~mask_denied) & mask_paid & mask_tiny
df.loc[mask_acc, "Accepted"] = diff
df.loc[mask_acc, "Balance"]  = 0.0

# Balance = residual > 4 for non-denied
mask_bal = (~mask_denied) & (diff > TINY_THRESHOLD)
df.loc[mask_bal, "Balance"] = diff

# Force zero for denied
df.loc[mask_denied, ["Accepted","Balance"]] = 0.0

# Standardized names
df.rename(columns={
    col_net: "NetAmount",
    col_paid: "Paid",
    col_payer: "Insurance",
    col_date: "RefDate"
}, inplace=True)

# Round money cols
money_cols = ["NetAmount","Paid","Balance","Rejected","Accepted"]
for c in money_cols:
    df[c] = df[c].round(DECIMALS)

# Strong “total row” remover (no-text + equals a grand sum or empty date)
grand = df[money_cols].sum().round(DECIMALS)
text_like = [c for c in ["RxId","Bill No","ClaimXmlId","ClaimStatus","Insurance","Plan","PayerName","Insurer"] if c in df.columns]
empty_text_mask = pd.Series(True, index=df.index)
if text_like:
    empty_text_mask = df[text_like].apply(lambda s: s.astype(str).str.strip().replace({"nan":"","None":""}), axis=0).eq("").all(axis=1)

eq_grand_mask = False
for c in money_cols:
    eq_grand_mask = eq_grand_mask | (df[c].round(DECIMALS) == grand[c])
date_empty = df["RefDate"].isna()
totals_like = (empty_text_mask & (eq_grand_mask | date_empty))
removed_rows = int(totals_like.sum())
df = df.loc[~totals_like].copy()

# Enforce identity (Net = Paid+Balance+Rejected+Accepted)
sum_cols = (df["Paid"] + df["Balance"] + df["Rejected"] + df["Accepted"]).round(DECIMALS)
drift = (df["NetAmount"].round(DECIMALS) - sum_cols).round(DECIMALS)
df["Accepted"] = (df["Accepted"] + drift).round(DECIMALS)

# Aging buckets
today = pd.Timestamp(datetime.today().date())
df["DaysDiff"] = (today - df["RefDate"]).dt.days
df["AgingBucket"] = pd.cut(df["DaysDiff"], bins=BINS, labels=LABELS)

# Balance-only views
balance_df = df.loc[df["Balance"] > 0].copy()
pivot_summary = pd.pivot_table(
    balance_df,
    index="Insurance",
    columns="AgingBucket",
    values="Balance",
    aggfunc="sum",
    fill_value=0,
    observed=False
)
pivot_summary = pivot_summary.reindex(columns=LABELS)
pivot_summary["Grand Total"] = pivot_summary.sum(axis=1)
pivot_summary.loc["Grand Total"] = pivot_summary.sum(axis=0)
pivot_summary.reset_index(inplace=True)
for col in pivot_summary.columns:
    if col != "Insurance":
        pivot_summary[col] = pd.to_numeric(pivot_summary[col], errors="coerce").round(DECIMALS)

# Insurance totals
insurance_totals = (
    df.groupby("Insurance", dropna=False)[["NetAmount","Paid","Balance","Rejected","Accepted"]]
      .sum().reset_index()
)
for c in ["NetAmount","Paid","Balance","Rejected","Accepted"]:
    insurance_totals[c] = insurance_totals[c].round(DECIMALS)

t2 = time.time()
print(f"⚙️ Processing time: {t2 - t1:.2f}s")

# =================== VALIDATION ===================
print("🧪 Running self-checks…")
checks = {}

# A) Row identity exactness
row_sum = (df["Paid"] + df["Balance"] + df["Rejected"] + df["Accepted"]).round(DECIMALS)
row_diff = (df["NetAmount"].round(DECIMALS) - row_sum).round(DECIMALS)
checks["A_rows_balanced"] = bool((row_diff == 0).all())
checks["A_rows_unbalanced_count"] = int((row_diff != 0).sum())
checks["A_max_abs_row_drift"] = float(row_diff.abs().max()) if len(row_diff) else 0.0

# B) Grand totals consistency
tot_left  = df["NetAmount"].sum().round(DECIMALS)
tot_right = (df["Paid"] + df["Balance"] + df["Rejected"] + df["Accepted"]).sum().round(DECIMALS)
checks["B_totals_match"] = bool(tot_left == tot_right)
checks["B_totals_left_net"] = float(tot_left)
checks["B_totals_right_sum"] = float(tot_right)

# C) No totals rows left
checks["C_removed_totals_rows"] = removed_rows

# D) Aging consistency (detail vs summary)
balance_total_detail = float(balance_df["Balance"].sum().round(DECIMALS))
# Sum all numeric columns except Insurance and the bottom Grand Total row
summary_no_gt = pivot_summary[pivot_summary["Insurance"] != "Grand Total"]
balance_total_summary = float(summary_no_gt.drop(columns=["Insurance"]).sum(axis=1).sum().round(DECIMALS))
checks["D_aging_detail_equals_summary"] = bool(abs(balance_total_detail - balance_total_summary) < 0.01)
checks["D_balance_detail_sum"] = balance_total_detail
checks["D_balance_summary_sum"] = balance_total_summary

# =================== SAVE ===================
print("💾 Saving Excel…")
with pd.ExcelWriter(OUTPUT_XLSX, engine="openpyxl") as writer:
    df.to_excel(writer, sheet_name="Exclusive_Report", index=False)
    insurance_totals.to_excel(writer, sheet_name="Insurance_Totals", index=False)
    pivot_summary.to_excel(writer, sheet_name="Balance_Aging_Summary", index=False)
    balance_df.to_excel(writer, sheet_name="Balance_Aging_Detail", index=False)
    # Validation sheet
    pd.DataFrame([checks]).to_excel(writer, sheet_name="Validation", index=False)

wb = load_workbook(OUTPUT_XLSX)
style_headers(wb)
wb.save(OUTPUT_XLSX)
t3 = time.time()
print(f"💾 Save time: {t3 - t2:.2f}s")

# =================== SUMMARY ===================
print(f"✅ Total time: {t3 - t0:.2f}s")
print("✅ Self-checks summary:")
for k, v in checks.items():
    print(f"   - {k}: {v}")


