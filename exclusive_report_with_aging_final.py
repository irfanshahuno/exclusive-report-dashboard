#!/usr/bin/env python3
import argparse
import glob
from pathlib import Path
from datetime import datetime
import numpy as np
import pandas as pd
from openpyxl import load_workbook
from openpyxl.styles import PatternFill, Font, Alignment

# ======================= Helpers =======================

def choose_input(path_arg: str | None) -> Path:
    """Choose input file; prefer .xlsb then .xlsx if no arg is given."""
    if path_arg:
        p = Path(path_arg).expanduser().resolve()
        if not p.exists():
            raise FileNotFoundError(f"❌ Input not found: {p}")
        if p.suffix.lower() not in (".xlsb", ".xlsx"):
            raise ValueError(f"❌ Input must be .xlsb or .xlsx, got: {p.suffix}")
        return p
    xlsb = [Path(x) for x in glob.glob("*.xlsb") if "Rejection_Report" not in x]
    xlsx = [Path(x) for x in glob.glob("*.xlsx") if "Rejection_Report" not in x]
    if xlsb:
        return xlsb[0].resolve()
    if xlsx:
        return xlsx[0].resolve()
    raise FileNotFoundError("❌ No XLSB/XLSX file found in this folder.")

def read_excel_any(path: Path) -> pd.DataFrame:
    """Read .xlsb with pyxlsb; .xlsx with openpyxl; trim header whitespace."""
    if path.suffix.lower() == ".xlsb":
        df = pd.read_excel(path, engine="pyxlsb")
    elif path.suffix.lower() == ".xlsx":
        df = pd.read_excel(path, engine="openpyxl")
    else:
        raise ValueError(f"❌ Unsupported extension: {path.suffix}")
    df.columns = df.columns.str.strip()
    return df

def downcast_numeric(df: pd.DataFrame) -> pd.DataFrame:
    """Shrink numeric memory footprint."""
    for col in df.select_dtypes(include=["int64","int32","int16","int8"]).columns:
        df[col] = pd.to_numeric(df[col], downcast="integer")
    for col in df.select_dtypes(include=["float64","float32"]).columns:
        df[col] = pd.to_numeric(df[col], downcast="float")
    return df

def first_present_column(df: pd.DataFrame, candidates):
    for c in candidates:
        if c in df.columns:
            return c
    return None

# ======================= Main =======================

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

    # --- Ensure numeric columns exist & numeric ---
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

    # Shrink memory
    df = downcast_numeric(df)
    balance_df = downcast_numeric(balance_df)

    # --- Summary pivot (Balance Aging Summary) ---
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

    # --- Insurance Totals (ActivityIns / Paid / Rejection / Accepted / Balance) ---
    totals_cols = ["ActivityIns","Paid","Rejection","Accepted","Balance"]
    insurance_totals = (
        df.groupby(insurance_col, dropna=False)[totals_cols]
          .sum(numeric_only=True)
          .reset_index()
    )
    # Add Grand Total row
    gt_vals = insurance_totals[totals_cols].sum(numeric_only=True)
    gt_row = {insurance_col: "Grand Total", **gt_vals.to_dict()}
    insurance_totals = pd.concat([insurance_totals, pd.DataFrame([gt_row])], ignore_index=True)

    # ======================= Write Excel =======================
    print("📝 Writing Excel…")
    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        # Canonical (space) names expected by your dashboard
        df.to_excel(writer, sheet_name="Exclusive Report", index=False)
        insurance_totals.to_excel(writer, sheet_name="Insurance Totals", index=False)
        pivot_summary.to_excel(writer, sheet_name="Balance Aging Summary", index=False)
        balance_df.to_excel(writer, sheet_name="Balance Aging Detail", index=False)

        # Backward-compatible underscore aliases (optional but harmless)
        df.to_excel(writer, sheet_name="Exclusive_Report", index=False)
        pivot_summary.to_excel(writer, sheet_name="Balance_Aging_Summary", index=False)
        balance_df.to_excel(writer, sheet_name="Balance_Aging_Detail", index=False)

    # ======================= Style =======================
    wb = load_workbook(out_path)
    header_fill = PatternFill(start_color="BDD7EE", end_color="BDD7EE", fill_type="solid")
    total_fill  = PatternFill(start_color="FCE4D6", end_color="FCE4D6", fill_type="solid")

    def style_headers(ws):
        for c in range(1, ws.max_column + 1):
            cell = ws.cell(row=1, column=c)
            cell.fill = header_fill
            cell.font = Font(bold=True)
            cell.alignment = Alignment(horizontal="center", vertical="center")

    def style_grand_total_row(ws, key_col=1, label="Grand Total"):
        for r in range(2, ws.max_row + 1):
            if str(ws.cell(row=r, column=key_col).value) == label:
                for c in range(1, ws.max_column + 1):
                    cell = ws.cell(row=r, column=c)
                    cell.fill = total_fill
                    cell.font = Font(bold=True)
                break

    for name in [
        "Exclusive Report","Insurance Totals","Balance Aging Summary","Balance Aging Detail",
        "Exclusive_Report","Balance_Aging_Summary","Balance_Aging_Detail"
    ]:
        ws = wb[name]
        style_headers(ws)
        if name in ("Insurance Totals","Balance Aging Summary"):
            style_grand_total_row(ws, key_col=1, label="Grand Total")
        if name in ("Balance Aging Summary","Balance_Aging_Summary"):
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

