#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Exclusive Report with Aging — robust generator
- Inputs: .xlsb / .xlsx / .xlsm
- Outputs: Exclusive_Report, Insurance_Totals, Balance_Aging_Summary, Balance_Aging_Detail
"""

import argparse
import sys
import os
import glob
from pathlib import Path
from datetime import datetime
import pandas as pd

# ------------------------------ Config ------------------------------
INS_TOT_SHEET = "Insurance_Totals"
SUMMARY_SHEET = "Balance_Aging_Summary"
DETAIL_SHEET = "Balance_Aging_Detail"
RAW_SHEET = "Exclusive_Report"

NUM_COL_CANDIDATES = [
    "ActivityIns",
    "actRemitInsShare", "actResub1RemitInsShare",
    "actResub2RemitInsShare", "actResub3RemitInsShare",
    "TKBKAmountAct",
]

INSURANCE_COL_CANDIDATES = ["Insurance", "PayerName", "Insurer", "Plan"]

DATE_COL_CANDIDATES = ["SubmissionDate", "ClaimDate", "VisitDate"]

AGING_BINS = [-1, 30, 45, 60, 90, float("inf")]
AGING_LABELS = ["0–30 Days", "31–45 Days", "46–60 Days", "61–90 Days", ">90 Days"]

OUTPUT_DEFAULT = "Exclusive_Report_with_Aging.xlsx"

# ------------------------------ Helpers ------------------------------
def _pick_first_existing(cols, candidates):
    for c in candidates:
        if c in cols:
            return c
    return candidates[0]  # return first as default name if none exist

def _read_excel_any(path: Path) -> pd.DataFrame:
    """Read .xlsb / .xlsx / .xlsm; choose engine automatically."""
    ext = path.suffix.lower()
    if ext == ".xlsb":
        try:
            return pd.read_excel(path, engine="pyxlsb")
        except Exception as e:
            raise RuntimeError(
                "Failed to read .xlsb — install pyxlsb or check the file.\n" + str(e)
            )
    # .xlsx/.xlsm
    return pd.read_excel(path, engine="openpyxl")

def _discover_input_file(cwd: Path) -> Path | None:
    files = [f for f in cwd.iterdir() if f.suffix.lower() in {".xlsb", ".xlsx", ".xlsm"}]
    files = [f for f in files if "Rejection_Report" not in f.name]
    return files[0] if files else None

def _coerce_numeric(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    for c in cols:
        if c not in df.columns:
            df[c] = 0
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
    return df

def _ensure_basic_columns(df: pd.DataFrame) -> pd.DataFrame:
    # If absolutely no numeric columns from our set exist, create them
    for c in NUM_COL_CANDIDATES:
        if c not in df.columns:
            df[c] = 0
    # ActivityStatus/DenialCode convenience presence
    if "ActivityStatus" not in df.columns:
        df["ActivityStatus"] = ""
    if "DenialCode" not in df.columns:
        df["DenialCode"] = pd.NA
    return df

def _compute_financials(df: pd.DataFrame) -> pd.DataFrame:
    # Paid
    paid_cols = ["actRemitInsShare","actResub1RemitInsShare","actResub2RemitInsShare","actResub3RemitInsShare","TKBKAmountAct"]
    df["Paid"] = df[paid_cols].sum(axis=1)

    # Initialize
    df["Rejection"] = 0.0
    df["Accepted"] = 0.0
    df["Balance"] = 0.0

    # Logic
    lower_status = df["ActivityStatus"].astype(str).str.lower()
    mask_paid = df["Paid"] > 0
    mask_reject = (df["Paid"] == 0) & (lower_status == "rejected") & (df["DenialCode"].notna())
    mask_balance = (df["Paid"] == 0) & ~mask_reject

    df.loc[mask_paid, "Accepted"] = df["ActivityIns"] - df["Paid"]
    df.loc[mask_reject, "Rejection"] = df["ActivityIns"]
    df.loc[mask_balance,"Balance"] = df["ActivityIns"]
    return df

def _compute_aging(df: pd.DataFrame) -> pd.DataFrame:
    # Parse dates if present
    present_date_cols = [c for c in DATE_COL_CANDIDATES if c in df.columns]
    if present_date_cols:
        for col in present_date_cols:
            df[col] = pd.to_datetime(df[col], errors="coerce", dayfirst=True)
        # backfill across date columns, pick first real date
        df["RefDate"] = df[present_date_cols].bfill(axis=1).iloc[:, 0]
    else:
        df["RefDate"] = pd.NaT

    today = pd.Timestamp(datetime.today().date())
    df["DaysDiff"] = (today - df["RefDate"]).dt.days

    # If date missing, we can treat them as oldest bucket to be safe for collections
    # (prevents NaN buckets collapsing the pivot)
    with pd.option_context("future.no_silent_downcasting", True):
        df.loc[df["DaysDiff"].isna(), "DaysDiff"] = 9999

    df["AgingBucket"] = pd.cut(df["DaysDiff"], bins=AGING_BINS, labels=AGING_LABELS)
    return df

def _make_insurance_totals(df: pd.DataFrame, insurance_col: str) -> pd.DataFrame:
    # Build totals by Insurance
    numerics = ["ActivityIns", "Paid", "Balance", "Rejection", "Accepted"]
    pivot = (
        df.groupby(insurance_col, dropna=False)[numerics]
            .sum(numeric_only=True)
            .reset_index()
    )
    # Clean empty/None insurance names
    pivot[insurance_col] = pivot[insurance_col].astype(str).str.strip().replace(
        {"": "Not Available", "nan": "Not Available", "None": "Not Available"}
    )
    # Append Grand Total row
    gt = {col: pivot[col].sum() if col in numerics else "Grand Total" for col in [insurance_col] + numerics}
    pivot = pd.concat([pivot, pd.DataFrame([gt])], ignore_index=True)
    # Keep a nice order
    cols = [insurance_col] + numerics
    pivot = pivot[cols]
    return pivot

def _make_aging_summary(balance_df: pd.DataFrame, insurance_col: str) -> pd.DataFrame:
    # Pivot with all columns in order
    pivot_summary = pd.pivot_table(
        balance_df,
        index=insurance_col,
        columns="AgingBucket",
        values="Balance",
        aggfunc="sum",
        fill_value=0,
        observed=False,  # quiet future warning noise
    )

    # Ensure all labels are present in correct order
    pivot_summary = pivot_summary.reindex(columns=AGING_LABELS, fill_value=0)
    pivot_summary["Grand Total"] = pivot_summary.sum(axis=1)
    # Bottom grand total
    total_row = pivot_summary.sum(axis=0)
    total_row.name = "Grand Total"
    pivot_summary = pd.concat([pivot_summary, total_row.to_frame().T])

    pivot_summary = pivot_summary.reset_index()
    return pivot_summary

# ------------------------------ Main ------------------------------
def main():
    parser = argparse.ArgumentParser(description="Build Exclusive Report with Aging")
    parser.add_argument("input", nargs="?", help="Path to input Excel (.xlsb/.xlsx/.xlsm). If omitted, auto-detects in current folder.")
    parser.add_argument("--out", dest="out", default=OUTPUT_DEFAULT, help=f"Output Excel filename (default: {OUTPUT_DEFAULT})")
    args, unknown = parser.parse_known_args()

    # Handle dashboard's alternate ordering: if args.input is None but an unknown looks like a file, use it
    if args.input is None:
        file_like = [u for u in unknown if str(u).lower().endswith((".xlsb", ".xlsx", ".xlsm"))]
        if file_like:
            args.input = file_like[-1]  # last one is safest

    # Auto-discover input if still missing
    if not args.input:
        discovered = _discover_input_file(Path.cwd())
        if not discovered:
            print("❌ No Excel file found in this folder (.xlsb/.xlsx/.xlsm).", file=sys.stderr)
            sys.exit(1)
        args.input = str(discovered)

    in_path = Path(args.input)
    out_path = Path(args.out)

    print(f"📂 Using input file: {in_path}")
    print("🧠 Reading Excel (auto engine)…")

    try:
        df = _read_excel_any(in_path)
    except Exception as e:
        print(f"❌ Failed to read input: {e}", file=sys.stderr)
        sys.exit(2)

    # Normalize columns
    df.columns = df.columns.astype(str).str.strip()

    # Ensure numeric columns and presence
    df = _ensure_basic_columns(df)
    df = _coerce_numeric(df, NUM_COL_CANDIDATES)

    # Compute financial columns
    df = _compute_financials(df)

    # Compute aging
    df = _compute_aging(df)

    # Determine Insurance column
    insurance_col = _pick_first_existing(df.columns, INSURANCE_COL_CANDIDATES)
    if insurance_col not in df.columns:
        df[insurance_col] = "Not Available"

    # Make balance-only detail for summary
    balance_df = df.loc[df["Balance"] > 0].copy()

    # Build Insurance Totals
    ins_totals = _make_insurance_totals(df, insurance_col)

    # Build Aging Summary
    aging_summary = _make_aging_summary(balance_df, insurance_col)

    # Write output
    print("📝 Writing Excel…")
    from openpyxl import load_workbook
    from openpyxl.styles import PatternFill, Font, Alignment

    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        # Raw
        df.to_excel(writer, sheet_name=RAW_SHEET, index=False)
        # Insurance Totals for dashboard
        ins_totals.to_excel(writer, sheet_name=INS_TOT_SHEET, index=False)
        # Summary + Detail
        aging_summary.to_excel(writer, sheet_name=SUMMARY_SHEET, index=False)
        balance_df.to_excel(writer, sheet_name=DETAIL_SHEET, index=False)

    # Styling (headers + Grand Totals highlight in summary/ins_totals)
    wb = load_workbook(out_path)

    header_fill = PatternFill(start_color="2196F3", end_color="2196F3", fill_type="solid")    # blue
    total_fill = PatternFill(start_color="FFF7E0", end_color="FFF7E0", fill_type="solid")    # light yellow

    def style_headers(ws):
        for c in range(1, ws.max_column + 1):
            cell = ws.cell(row=1, column=c)
            cell.fill = header_fill
            cell.font = Font(bold=True, color="FFFFFF")
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    def highlight_grand_total_ws(ws, label_col_idx=1, label_text="Grand Total"):
        # Highlight the entire "Grand Total" row
        for r in range(2, ws.max_row + 1):
            if str(ws.cell(row=r, column=label_col_idx).value).strip() == label_text:
                for c in range(1, ws.max_column + 1):
                    tcell = ws.cell(row=r, column=c)
                    tcell.fill = total_fill
                    tcell.font = Font(bold=True)
        # Highlight the last column if it's named "Grand Total"
        # (Only for summary sheet, where last column is Grand Total)
        header_last = str(ws.cell(row=1, column=ws.max_column).value or "").strip().lower()
        if "grand total" in header_last:
            for r in range(1, ws.max_row + 1):
                tcell = ws.cell(row=r, column=ws.max_column)
                tcell.fill = total_fill
                tcell.font = Font(bold=True)

    for ws in wb.worksheets:
        style_headers(ws)
        if ws.title in (SUMMARY_SHEET, INS_TOT_SHEET):
            highlight_grand_total_ws(ws, label_col_idx=1, label_text="Grand Total")

    print("💾 Saving file…")
    wb.save(out_path)
    print(f"✅ Done: {out_path}")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"❌ Unexpected error: {e}", file=sys.stderr)
        sys.exit(99)

