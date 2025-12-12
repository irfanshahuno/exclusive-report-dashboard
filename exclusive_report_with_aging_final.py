#!/usr/bin/env python3
import argparse
import glob
from pathlib import Path
from datetime import datetime
import pandas as pd
import numpy as np
from openpyxl import load_workbook
from openpyxl.styles import PatternFill, Font, Alignment

REQUIRED_COLS = [
    "ActivityIns","actRemitInsShare","actResub1RemitInsShare",
    "actResub2RemitInsShare","actResub3RemitInsShare","TKBKAmountAct",
    "ActivityStatus","DenialCode",
    "SubmissionDate","ClaimDate","VisitDate",
    "Insurance","PayerName","Insurer","Plan"
]

def choose_input(path_arg: str | None) -> Path:
    if path_arg:
        p = Path(path_arg).expanduser().resolve()
        if not p.exists():
            raise FileNotFoundError(f"❌ Input not found: {p}")
        if p.suffix.lower() not in (".xlsb", ".xlsx"):
            raise ValueError(f"❌ Input must be .xlsb or .xlsx, got: {p.suffix}")
        return p
    # search current folder: prefer .xlsb, else .xlsx
    xlsb = [Path(x) for x in glob.glob("*.xlsb") if "Rejection_Report" not in x]
    xlsx = [Path(x) for x in glob.glob("*.xlsx") if "Rejection_Report" not in x]
    if xlsb:
        return xlsb[0].resolve()
    if xlsx:
        return xlsx[0].resolve()
    raise FileNotFoundError("❌ No XLSB/XLSX file found in this folder.")

def read_excel_any(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".xlsb":
        df = pd.read_excel(path, engine="pyxlsb")
    elif suffix == ".xlsx":
        df = pd.read_excel(path, engine="openpyxl")
    else:
        raise ValueError(f"❌ Unsupported extension: {suffix}")
    df.columns = df.columns.str.strip()
    return df

def downcast_numeric(df: pd.DataFrame) -> pd.DataFrame:
    for col in df.select_dtypes(include=["int64","int32","int16","int8"]).columns:
        df[col] = pd.to_numeric(df[col], downcast="integer")
    for col in df.select_dtypes(include=["float64","float32"]).columns:
        df[col] = pd.to_numeric(df[col], downcast="float")
    return df

def first_present_column(df, candidates):
    for c in candidates:
        if c in df.columns:
            return c
    return None

def main():
    parser = argparse.ArgumentParser(description="Exclusive Report (robust; .xlsb/.xlsx input)")
    parser.add_argument("input", nargs="?", help="Path to .xlsb or .xlsx file")
    parser.add_argument("--out", default="Exclusive_Report_with_Aging.xlsx", help="Output .xlsx path")
    args = parser.parse_args()

    in_path = choose_input(args.input)
    out_path = Path(args.out).expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"📂 Using input file: {in_path}")
    df = read_excel_any(in_path)

    # --- Ensure numeric columns exist & are numeric ---
    num_cols = [
        "ActivityIns","actRemitInsShare","actResub1RemitInsShare",
        "actResub2RemitInsShare","actResub3RemitInsShare","TKBKAmountAct"
    ]
    for c in num_cols:
        if c not in df.columns:
            df[c] = 0
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)

    # --- Compute Paid / Accepted / Rejection / Balance ---
    df["Paid"] = (
        df.get("actRemitInsShare", 0)
        + df.get("actResub1RemitInsShare", 0)
        + df.get("actResub2RemitInsShare", 0)
        + df.get("actResub3RemitInsShare", 0)
        + df.get("TKBKAmountAct", 0)
    )
    df["Rejection"] = 0.0
    df["Accepted"]  = 0.0
    df["Balance"]   = 0.0

    if "ActivityStatus" in df.columns and "DenialCode" in df.columns:
        lower_status = df["ActivityStatus"].astype(str).str.lower()
        mask_paid    = df["Paid"].values > 0
        mask_reject  = (~mask_paid) & (lower_status.values == "rejected") & (df["DenialCode"].notna().values)
        mask_balance = (~mask_paid) & (~mask_reject)

        df.loc[mask_paid, "Accepted"]   = df.loc[mask_paid, "ActivityIns"] - df.loc[mask_paid, "Paid"]
        df.loc[mask_reject, "Rejection"] = df.loc[mask_reject, "ActivityIns"]
        df.loc[mask_balance, "Balance"]  = df.loc[mask_balance, "ActivityIns"]

    # --- Aging calculation ---
    for col in ("SubmissionDate","ClaimDate","VisitDate"):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce", dayfirst=True)

    ref = None
    for col in ("SubmissionDate","ClaimDate","VisitDate"):
        if col in df.columns:
            ref = df[col] if ref is None else ref.fillna(df[col])
    df["RefDate"] = ref if ref is not None else pd.NaT

    today = pd.Timestamp(datetime.today().date())
    df["DaysDiff"] = (today - df["RefDate"]).dt.days

    bins   = np.array([-1, 30, 45, 60, 90, np.inf])
    labels = ["0–30 Days","31–45 Days","46–60 Days","61–90 Days",">90 Days"]
    df["AgingBucket"] = pd.cut(df["DaysDiff"], bins=bins, labels=labels)

    # --- Detail (balance only) ---
    insurance_col = first_present_column(df, ["Insurance","PayerName","Insurer","Plan"]) or "Insurance"
    if insurance_col not in df.columns:
        df[insurance_col] = "Not Available"

    keep_cols = list(dict.fromkeys(
        [insurance_col, "ActivityIns","Paid","Rejection","Accepted","Balance",
         "SubmissionDate","ClaimDate","VisitDate","RefDate","DaysDiff","AgingBucket"]
    ))
    keep_cols = [c for c in keep_cols if c in df.columns]
    balance_df = df.loc[df["Balance"] > 0, keep_cols]

    df = downcast_numeric(df)
    balance_df = downcast_numeric(balance_df)

    # --- Summary pivot ---
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
    pivot_summary = pivot_summary.reset_index()

    # --- Write Excel ---
    print("📝 Writing Excel…")
    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Exclusive_Report", index=False)
        pivot_summary.to_excel(writer, sheet_name="Balance_Aging_Summary", index=False)
        balance_df.to_excel(writer, sheet_name="Balance_Aging_Detail", index=False)

    # --- Style headers & totals ---
    wb = load_workbook(out_path)
    header_fill = PatternFill(start_color="BDD7EE", end_color="BDD7EE", fill_type="solid")
    total_fill  = PatternFill(start_color="FCE4D6", end_color="FCE4D6", fill_type="solid")

    for ws in wb.worksheets:
        for c in range(1, ws.max_column + 1):
            cell = ws.cell(row=1, column=c)
            cell.fill = header_fill
            cell.font = Font(bold=True)
            cell.alignment = Alignment(horizontal="center", vertical="center")

        if ws.title == "Balance_Aging_Summary":
            # Grand Total row
            for r in range(2, ws.max_row + 1):
                if ws.cell(row=r, column=1).value == "Grand Total":
                    for c in range(1, ws.max_column + 1):
                        cell = ws.cell(row=r, column=c)
                        cell.fill = total_fill
                        cell.font = Font(bold=True)
            # Grand Total column (last)
            last_col = ws.max_column
            for r in range(1, ws.max_row + 1):
                cell = ws.cell(row=r, column=last_col)
                cell.fill = total_fill
                cell.font = Font(bold=True)

    print("💾 Saving file…")
    wb.save(out_path)
    print(f"✅ Done: {out_path}")

if __name__ == "__main__":
    main()

