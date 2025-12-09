#!/usr/bin/env python3
import sys, os, glob
from datetime import datetime
import pandas as pd
from openpyxl import load_workbook
from openpyxl.styles import PatternFill, Font, Alignment

# ============================================================
# Optional CLI:
#   python exclusive_report_with_aging_final.py input.xlsx --out output.xlsx
#   (Also supports .xlsb; engine chosen automatically by file extension)
# If no args are provided, it auto-picks the first .xlsx/.xlsb (excluding Rejection_Report)
# and writes Exclusive_Report_with_Aging.xlsx by default.
# ============================================================

# ---- Tuning knobs ----
TINY_THRESHOLD = 4          # <=4 goes to Accepted (not Balance)
DECIMALS = 2
BINS   = [-1, 30, 45, 60, 90, float("inf")]
LABELS = ["0–30 Days", "31–45 Days", "46–60 Days", "61–90 Days", ">90 Days"]

def _choose_engine(input_file: str) -> str | None:
    f = input_file.lower()
    if f.endswith(".xlsb"):
        return "pyxlsb"
    if f.endswith(".xlsx") or f.endswith(".xlsm"):
        return "openpyxl"
    # let pandas guess for others
    return None

def parse_cli() -> tuple[str, str]:
    files = [f for f in (glob.glob("*.xlsx") + glob.glob("*.xlsb")) if "Rejection_Report" not in f]
    input_file = None
    out_file = "Exclusive_Report_with_Aging.xlsx"

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--out":
            if i + 1 >= len(args):
                raise SystemExit("error: --out requires a filename")
            out_file = args[i + 1]; i += 2
        elif a.startswith("-"):
            raise SystemExit(f"unknown argument: {a}")
        else:
            input_file = a; i += 1

    if input_file is None:
        if not files:
            raise FileNotFoundError("❌ No Excel file found in this folder.")
        input_file = files[0]

    # normalize output extension
    if not out_file.lower().endswith(".xlsx"):
        out_file = os.path.splitext(out_file)[0] + ".xlsx"

    return input_file, out_file

def main():
    # ---- STEP 1: Locate Excel file ----
    input_file, output_file = parse_cli()
    print(f"📂 Using input file: {input_file}")
    print(f"📝 Output will be: {output_file}")

    engine = _choose_engine(input_file)
    if engine:
        print(f"🔧 Using read engine: {engine}")
    else:
        print("🔧 Using pandas default read engine")

    # ---- STEP 2: Load Data ----
    df = pd.read_excel(input_file, engine=engine)
    df.columns = df.columns.str.strip()

    # ---- STEP 3: Convert numeric columns ----
    num_cols = [
        "ActivityIns", "actRemitInsShare", "actResub1RemitInsShare",
        "actResub2RemitInsShare", "actResub3RemitInsShare", "TKBKAmountAct"
    ]
    for c in num_cols:
        if c not in df.columns:
            df[c] = 0
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)

    # ---- STEP 4: Compute Paid & Classification (unified with pharmacy logic) ----
    df["Paid"] = df[[
        "actRemitInsShare", "actResub1RemitInsShare",
        "actResub2RemitInsShare", "actResub3RemitInsShare",
        "TKBKAmountAct"
    ]].sum(axis=1)

    # Base columns
    df["Rejected"], df["Accepted"], df["Balance"] = 0.0, 0.0, 0.0

    # Normalize status for robust detection
    status_col = "ActivityStatus" if "ActivityStatus" in df.columns else None
    denial_code_col = "DenialCode" if "DenialCode" in df.columns else None  # not strictly needed, but kept

    lower_status = df[status_col].astype(str).str.lower() if status_col else pd.Series("", index=df.index)

    # Consider both 'rejected' and 'denied' as denial states
    mask_denied = lower_status.isin(["rejected", "denied"])
    net = df["ActivityIns"].clip(lower=0.0)
    paid = df["Paid"].clip(lower=0.0)
    diff = (net - paid).clip(lower=0.0)

    # Rejected rows → full net
    df.loc[mask_denied, "Rejected"] = net

    # Accepted tiny leftover (<= TINY_THRESHOLD) when paid>0 & not denied
    mask_paid  = paid > 0
    mask_tiny  = diff <= TINY_THRESHOLD
    mask_acc   = (~mask_denied) & mask_paid & mask_tiny
    df.loc[mask_acc, "Accepted"] = diff
    df.loc[mask_acc, "Balance"]  = 0.0

    # Balance = residual > TINY_THRESHOLD for non-denied
    mask_bal = (~mask_denied) & (diff > TINY_THRESHOLD)
    df.loc[mask_bal, "Balance"] = diff

    # Force zero accepted/balance for denied rows (already set Rejected)
    df.loc[mask_denied, ["Accepted","Balance"]] = 0.0

    # ---- STEP 4B: Per-row identity reconciliation ----
    # Ensure: ActivityIns == Paid + Balance + Rejected + Accepted (rounded)
    right_sum = (df["Paid"] + df["Balance"] + df["Rejected"] + df["Accepted"]).round(DECIMALS)
    drift = (df["ActivityIns"].round(DECIMALS) - right_sum).round(DECIMALS)
    # Push residual drift into Accepted (typical micro-rounding)
    df["Accepted"] = (df["Accepted"] + drift).round(DECIMALS)

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
    df["AgingBucket"] = pd.cut(df["DaysDiff"], bins=BINS, labels=LABELS)

    # ---- STEP 6: Balance-only data (for Aging tabs) ----
    balance_df = df.loc[df["Balance"] > 0].copy()

    # ---- STEP 7: Determine Insurance column ----
    insurance_col = next((c for c in ["Insurance", "PayerName", "Insurer", "Plan"] if c in df.columns), "Insurance")
    if insurance_col not in df.columns:
        df[insurance_col] = "Not Available"
        balance_df[insurance_col] = "Not Available"

    # ---- STEP 8: Balance_Aging_Summary ----
    if balance_df.empty:
        pivot_summary = pd.DataFrame({ "Insurance": [] })
        for lab in LABELS:
            pivot_summary[lab] = []
        pivot_summary["Grand Total"] = []
    else:
        pivot_summary = pd.pivot_table(
            balance_df,
            index=insurance_col,
            columns="AgingBucket",
            values="Balance",
            aggfunc="sum",
            fill_value=0,
            observed=False
        )
        pivot_summary = pivot_summary.reindex(columns=LABELS).fillna(0)
        pivot_summary["Grand Total"] = pivot_summary.sum(axis=1)
        pivot_summary.loc["Grand Total"] = pivot_summary.sum(axis=0)
        pivot_summary.reset_index(inplace=True)
        pivot_summary.rename(columns={insurance_col: "Insurance"}, inplace=True)

    # ---- STEP 8B: Insurance_Totals ----
    totals = df.groupby(insurance_col, dropna=False).agg({
        "ActivityIns": "sum",
        "Paid": "sum",
        "Balance": "sum",
        "Rejected": "sum",
        "Accepted": "sum"
    }).reset_index()

    totals = totals.rename(columns={
        insurance_col: "Insurance",
        "ActivityIns": "Net Amount",
        "Paid": "Paid",
        "Balance": "Balance",
        "Rejected": "Rejected",
        "Accepted": "Accepted"
    })

    # Grand Total row
    gt_row = {
        "Insurance": "Grand Total",
        "Net Amount": totals["Net Amount"].sum(),
        "Paid": totals["Paid"].sum(),
        "Balance": totals["Balance"].sum(),
        "Rejected": totals["Rejected"].sum(),
        "Accepted": totals["Accepted"].sum(),
    }
    totals = pd.concat([totals, pd.DataFrame([gt_row])], ignore_index=True)

    # Round money columns
    for c in ["Net Amount", "Paid", "Balance", "Rejected", "Accepted"]:
        totals[c] = pd.to_numeric(totals[c], errors="coerce").round(DECIMALS)

    # ---- STEP 9: Validation ----
    checks = {}
    # Per-row balance
    row_sum = (df["Paid"] + df["Balance"] + df["Rejected"] + df["Accepted"]).round(DECIMALS)
    row_diff = (df["ActivityIns"].round(DECIMALS) - row_sum).round(DECIMALS)
    checks["A_rows_balanced"] = bool((row_diff == 0).all())
    checks["A_rows_unbalanced_count"] = int((row_diff != 0).sum())
    checks["A_max_abs_row_drift"] = float(row_diff.abs().max()) if len(row_diff) else 0.0
    # Totals match
    tot_left  = float(df["ActivityIns"].sum().round(DECIMALS))
    tot_right = float((df["Paid"] + df["Balance"] + df["Rejected"] + df["Accepted"]).sum().round(DECIMALS))
    checks["B_totals_match"] = bool(tot_left == tot_right)
    checks["B_totals_left_net"] = tot_left
    checks["B_totals_right_sum"] = tot_right
    # Aging detail vs summary (exclude GT row)
    if balance_df.empty:
        checks["C_aging_detail_equals_summary"] = True
        checks["C_balance_detail_sum"] = 0.0
        checks["C_balance_summary_sum"] = 0.0
    else:
        balance_total_detail = float(balance_df["Balance"].sum().round(DECIMALS))
        summary_no_gt = pivot_summary[pivot_summary["Insurance"] != "Grand Total"]
        balance_total_summary = float(summary_no_gt.drop(columns=["Insurance"]).sum(axis=1).sum().round(DECIMALS))
        checks["C_aging_detail_equals_summary"] = bool(abs(balance_total_detail - balance_total_summary) < 0.01)
        checks["C_balance_detail_sum"] = balance_total_detail
        checks["C_balance_summary_sum"] = balance_total_summary

    # ---- STEP 10: Write to Excel ----
    with pd.ExcelWriter(output_file, engine="openpyxl") as writer:
        df.to_excel(writer,                sheet_name="Exclusive_Report",        index=False)
        totals.to_excel(writer,            sheet_name="Insurance_Totals",        index=False)
        pivot_summary.to_excel(writer,     sheet_name="Balance_Aging_Summary",   index=False)
        balance_df.to_excel(writer,        sheet_name="Balance_Aging_Detail",    index=False)
        pd.DataFrame([checks]).to_excel(writer, sheet_name="Validation",         index=False)

    # ---- STEP 11: Styling Headers + Grand Total ----
    wb = load_workbook(output_file)
    header_fill = PatternFill(start_color="BDD7EE", end_color="BDD7EE", fill_type="solid")  # blue
    total_fill  = PatternFill(start_color="FCE4D6", end_color="FCE4D6", fill_type="solid")  # light orange

    for ws in wb.worksheets:
        # Headers
        for c in range(1, ws.max_column + 1):
            cell = ws.cell(row=1, column=c)
            cell.fill = header_fill
            cell.font = Font(bold=True)
            cell.alignment = Alignment(horizontal="center", vertical="center")

        # Highlight 'Grand Total' row (and GT column in aging summary)
        if ws.title in ("Balance_Aging_Summary", "Insurance_Totals"):
            for r in range(2, ws.max_row + 1):
                val = ws.cell(row=r, column=1).value
                if str(val).strip().lower() in ("grand total", "grand_total", "totals", "total"):
                    for c in range(1, ws.max_column + 1):
                        cell = ws.cell(row=r, column=c)
                        cell.fill = total_fill
                        cell.font = Font(bold=True)
            if ws.title == "Balance_Aging_Summary":
                col = ws.max_column
                for r in range(1, ws.max_row + 1):
                    cell = ws.cell(row=r, column=col)
                    cell.fill = total_fill
                    cell.font = Font(bold=True)

    print("💾 Saving file, please wait...")
    wb.save(output_file)
    print("✅ Excel saved:", output_file)

    # ---- STEP 11B: Also save a Parquet copy (size printed) ----
    try:
        parquet_path = output_file.replace(".xlsx", ".parquet")
        # Only the main detail sheet ("Exclusive_Report") is serialized to Parquet;
        # that’s typically the largest table users want to size-check.
        df.to_parquet(parquet_path, engine="fastparquet", compression="zstd")
        size_mb = round(os.path.getsize(parquet_path) / 1_000_000, 2)
        print(f"🪶 Parquet saved: {parquet_path}  ({size_mb} MB)")
    except Exception as e:
        print("⚠️ Could not write Parquet:", e)

    print("📁 Done.")

if __name__ == "__main__":
    main()

