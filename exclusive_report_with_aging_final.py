#!/usr/bin/env python3

import os
import hashlib
import argparse
from datetime import datetime
import pandas as pd
from openpyxl import load_workbook
from openpyxl.styles import PatternFill, Font, Alignment

WRITE_EXCLUSIVE_SHEET = False


def sha1_short(path: str) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()[:12]


def parse_args():
    p = argparse.ArgumentParser(description="Build report from an input .xlsx")
    p.add_argument("input_xlsx", help="Path to source Excel (.xlsx)")
    p.add_argument("--out", dest="out_xlsx", required=True, help="Path to output Excel (.xlsx)")
    args = p.parse_args()

    if not os.path.exists(args.input_xlsx):
        raise FileNotFoundError(f"File not found: {args.input_xlsx}")
    if not args.input_xlsx.lower().endswith(".xlsx"):
        raise ValueError("Input file must be .xlsx")
    if not args.out_xlsx.lower().endswith(".xlsx"):
        raise ValueError("Output file must be .xlsx")

    out_dir = os.path.dirname(os.path.abspath(args.out_xlsx)) or "."
    os.makedirs(out_dir, exist_ok=True)
    return args


def load_data(input_file: str) -> pd.DataFrame:
    df = pd.read_excel(input_file, engine="openpyxl")
    df.columns = df.columns.astype(str).str.strip()
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
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
    return df


def normalize_text(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).str.strip()


def compute_measures(df: pd.DataFrame) -> pd.DataFrame:
    df["Paid"] = df[
        [
            "actRemitInsShare",
            "actResub1RemitInsShare",
            "actResub2RemitInsShare",
            "actResub3RemitInsShare",
            "TKBKAmountAct",
        ]
    ].sum(axis=1)

    df["UnderProcess"] = pd.to_numeric(df["ActivityIns"], errors="coerce").fillna(0.0) - df["Paid"]
    df["Rejection"] = 0.0
    df["Accepted"] = 0.0

    denial = normalize_text(df["DenialCode"]) if "DenialCode" in df.columns else pd.Series("", index=df.index)
    activity_status = normalize_text(df["ActivityStatus"]) if "ActivityStatus" in df.columns else pd.Series("", index=df.index)

    has_denial = denial.ne("") & denial.str.lower().ne("nan")
    move_to_rej = has_denial & (df["UnderProcess"] != 0)
    df.loc[move_to_rej, "Rejection"] = df.loc[move_to_rej, "UnderProcess"]
    df.loc[move_to_rej, "UnderProcess"] = 0.0

    accepted_codes = {"COPY-001", "PRCE-001"}
    move_to_acc = denial.str.upper().isin(accepted_codes) & (df["Rejection"] != 0)
    df.loc[move_to_acc, "Accepted"] = df.loc[move_to_acc, "Rejection"]
    df.loc[move_to_acc, "Rejection"] = 0.0

    move_back_submitted = (
        activity_status.str.lower().eq("submitted")
        & (df["Rejection"] != 0)
        & (df["UnderProcess"] == 0)
    )
    df.loc[move_back_submitted, "UnderProcess"] = df.loc[move_back_submitted, "Rejection"]
    df.loc[move_back_submitted, "Rejection"] = 0.0

    duplicate_mask = (
        (df["UnderProcess"].round(2) != 0)
        & (df["Rejection"].round(2) != 0)
        & (df["UnderProcess"].round(2) == df["Rejection"].round(2))
    )
    df.loc[duplicate_mask, "Rejection"] = 0.0

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
    labels = ["0-30 Days", "31-45 Days", "46-60 Days", "61-90 Days", ">90 Days"]
    df["AgingBucket"] = pd.cut(df["DaysDiff"], bins=bins, labels=labels)
    return df


def ensure_insurance_column(df: pd.DataFrame) -> pd.DataFrame:
    insurance_col = next((c for c in ["Insurance", "PayerName", "Insurer", "Plan"] if c in df.columns), None)
    if insurance_col is None:
        df["Insurance"] = "Not Available"
    elif insurance_col != "Insurance":
        df["Insurance"] = normalize_text(df[insurance_col]).replace("", "Not Available")
    else:
        df["Insurance"] = normalize_text(df["Insurance"]).replace("", "Not Available")
    return df


def build_balance_aging_summary(underprocess_df: pd.DataFrame) -> pd.DataFrame:
    labels = ["0-30 Days", "31-45 Days", "46-60 Days", "61-90 Days", ">90 Days"]

    if underprocess_df.empty:
        return pd.DataFrame(columns=["Insurance"] + labels + ["Grand Total"])

    pivot_summary = pd.pivot_table(
        underprocess_df,
        index="Insurance",
        columns="AgingBucket",
        values="UnderProcess",
        aggfunc="sum",
        fill_value=0,
        observed=False,
    )

    pivot_summary = pivot_summary.reindex(columns=labels, fill_value=0)
    pivot_summary["Grand Total"] = pivot_summary.sum(axis=1)
    pivot_summary.loc["Grand Total"] = pivot_summary.sum(axis=0)
    pivot_summary.reset_index(inplace=True)
    return pivot_summary


def build_insurance_totals(df: pd.DataFrame) -> pd.DataFrame:
    insurance_totals = (
        df.groupby("Insurance", dropna=False)[["ActivityIns", "Paid", "UnderProcess", "Rejection", "Accepted"]]
        .sum()
        .reset_index()
    )

    insurance_totals = insurance_totals.rename(
        columns={
            "ActivityIns": "Net Amount",
            "Rejection": "Rejected",
            "UnderProcess": "UnderProcess",
        }
    )

    insurance_totals = insurance_totals[["Insurance", "Net Amount", "Paid", "UnderProcess", "Rejected", "Accepted"]]

    total_row = {
        "Insurance": "Grand Total",
        "Net Amount": insurance_totals["Net Amount"].sum(),
        "Paid": insurance_totals["Paid"].sum(),
        "UnderProcess": insurance_totals["UnderProcess"].sum(),
        "Rejected": insurance_totals["Rejected"].sum(),
        "Accepted": insurance_totals["Accepted"].sum(),
    }
    insurance_totals = pd.concat([insurance_totals, pd.DataFrame([total_row])], ignore_index=True)
    return insurance_totals


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

        if ws.title in ("Balance_Aging_Summary", "Insurance_Totals"):
            for r in range(2, ws.max_row + 1):
                if ws.cell(row=r, column=1).value == "Grand Total":
                    for c in range(1, ws.max_column + 1):
                        cell = ws.cell(row=r, column=c)
                        cell.fill = TOTAL_FILL
                        cell.font = Font(bold=True)

        if ws.title == "Balance_Aging_Summary" and ws.max_column >= 1:
            last_col = ws.max_column
            for r in range(1, ws.max_row + 1):
                cell = ws.cell(row=r, column=last_col)
                cell.fill = TOTAL_FILL
                cell.font = Font(bold=True)

    wb.save(output_file)


def main():
    args = parse_args()
    input_file = os.path.abspath(args.input_xlsx)
    out_file = os.path.abspath(args.out_xlsx)

    print(f"Using input: {input_file}")
    print(f"Output file: {out_file}")
    print(f"Input SHA1: {sha1_short(input_file)}")

    df = load_data(input_file)
    df = ensure_numeric(df)
    df = compute_measures(df)
    df = add_aging(df)
    df = ensure_insurance_column(df)

    underprocess_df = df.loc[df["UnderProcess"] > 0].copy()
    pivot_summary = build_balance_aging_summary(underprocess_df)
    insurance_totals = build_insurance_totals(df)

    with pd.ExcelWriter(out_file, engine="openpyxl") as writer:
        if WRITE_EXCLUSIVE_SHEET:
            df.to_excel(writer, sheet_name="Exclusive_Report", index=False)

        insurance_totals.to_excel(writer, sheet_name="Insurance_Totals", index=False)
        # Keep old sheet names so existing app keeps working
        pivot_summary.to_excel(writer, sheet_name="Balance_Aging_Summary", index=False)
        underprocess_df.to_excel(writer, sheet_name="Balance_Aging_Detail", index=False)

        meta = pd.DataFrame([{
            "InputFile": os.path.basename(input_file),
            "InputSHA1": sha1_short(input_file),
            "GeneratedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "Exclusive_Report_Written": WRITE_EXCLUSIVE_SHEET,
        }])
        meta.to_excel(writer, sheet_name="Meta", index=False)

    apply_styling(out_file)
    print("Done.")


if __name__ == "__main__":
    main()
