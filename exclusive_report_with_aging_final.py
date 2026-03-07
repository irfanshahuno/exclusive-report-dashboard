#!/usr/bin/env python3

import os, hashlib, argparse, re
from datetime import datetime
import pandas as pd
from openpyxl import load_workbook
from openpyxl.styles import PatternFill, Font, Alignment

WRITE_EXCLUSIVE_SHEET = False

HEADER_FILL = PatternFill(start_color="BDD7EE", end_color="BDD7EE", fill_type="solid")
TOTAL_FILL  = PatternFill(start_color="FCE4D6", end_color="FCE4D6", fill_type="solid")


def sha1_short(path: str) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()[:12]


def parse_args():
    p = argparse.ArgumentParser(
        description="Build Exclusive report with status-based logic and submission-stage balance tracking from an input .xlsx"
    )
    p.add_argument("input_xlsx", help="Path to source Excel (.xlsx)")
    p.add_argument("--out", dest="out_xlsx", required=True,
                   help="Path to write the output workbook (.xlsx)")
    args = p.parse_args()

    if not os.path.exists(args.input_xlsx):
        raise FileNotFoundError(f"❌ File not found: {args.input_xlsx}")
    if not args.input_xlsx.lower().endswith(".xlsx"):
        raise ValueError("❌ Input must be .xlsx")
    out_dir = os.path.dirname(os.path.abspath(args.out_xlsx)) or "."
    os.makedirs(out_dir, exist_ok=True)
    return args


def load_data(input_file: str) -> pd.DataFrame:
    df = pd.read_excel(input_file, engine="openpyxl")
    df.columns = df.columns.astype(str).str.strip()
    return df


def ensure_numeric(df: pd.DataFrame) -> pd.DataFrame:
    numeric_defaults = [
        "SubInsShare",
        "RemitInsShare",
        "Resub1RemitInsShare",
        "Resub2RemitInsShare",
        "Resub3RemitInsShare",
        "Resub4RemitInsShare",
        "TakeBack",
    ]
    for col in numeric_defaults:
        if col not in df.columns:
            df[col] = 0
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    return df


def normalize_status_series(s: pd.Series) -> pd.Series:
    return (
        s.astype(str)
         .str.strip()
         .str.lower()
         .str.replace(r"\s+", " ", regex=True)
    )


def is_rejected_status(status: pd.Series) -> pd.Series:
    return status.str.match(r"^rejected\s*(\(\s*resub\s*-\s*\d+\s*\))?$", na=False)


def is_accepted_status(status: pd.Series) -> pd.Series:
    return status.str.match(r"^rejection accepted\s*(\(\s*resub\s*-\s*\d+\s*\))?$", na=False)


def extract_stage_info(status_value: str):
    s = str(status_value or "").strip()
    s_norm = re.sub(r"\s+", " ", s.lower())

    # Submitted / Not Submitted / Approved with optional resub stage
    # Examples:
    # Submitted
    # Submitted(Resub- 1)
    # Not Submitted(Resub- 2)
    # Approved(Resub- 1)
    m = re.match(r"^(submitted|not submitted|approved)\s*(?:\(\s*resub\s*-\s*(\d+)\s*\))?$", s_norm)
    if not m:
        return "Other", "Other", None

    base = m.group(1)
    n = m.group(2)
    stage_num = int(n) if n is not None else 0
    stage_label = "Initial Submission" if stage_num == 0 else f"Resub-{stage_num}"

    base_map = {
        "submitted": "Submitted",
        "not submitted": "Not Submitted",
        "approved": "Approved",
    }
    return base_map[base], stage_label, stage_num


def compute_measures(df: pd.DataFrame) -> pd.DataFrame:
    df["Net Amount"] = df["SubInsShare"]
    df["Paid"] = df[[
        "RemitInsShare",
        "Resub1RemitInsShare",
        "Resub2RemitInsShare",
        "Resub3RemitInsShare",
        "Resub4RemitInsShare",
        "TakeBack",
    ]].sum(axis=1)

    df["Balance"] = (df["Net Amount"] - df["Paid"]).clip(lower=0)

    df["Rejected"] = 0.0
    df["Accepted"] = 0.0

    if "Status" not in df.columns:
        df["Status"] = ""

    status_norm = normalize_status_series(df["Status"])
    mask_rejected = is_rejected_status(status_norm)
    mask_accepted = is_accepted_status(status_norm)

    df.loc[mask_rejected, "Rejected"] = df.loc[mask_rejected, "Net Amount"]
    df.loc[mask_accepted, "Accepted"] = df.loc[mask_accepted, "Net Amount"]

    stage_info = df["Status"].apply(extract_stage_info)
    df["Balance Status Group"] = stage_info.apply(lambda x: x[0])
    df["Balance Submission Stage"] = stage_info.apply(lambda x: x[1])
    df["Balance Submission No"] = stage_info.apply(lambda x: x[2])

    # Split balance into stage-wise columns so you can see initial / resub1 / resub2 balance separately
    df["Initial Submission Balance"] = 0.0
    for n in range(1, 11):
        df[f"Resub-{n} Balance"] = 0.0

    mask_balance = df["Balance"] > 0
    df.loc[mask_balance & (df["Balance Submission No"] == 0), "Initial Submission Balance"] = df.loc[
        mask_balance & (df["Balance Submission No"] == 0), "Balance"
    ]
    for n in range(1, 11):
        col = f"Resub-{n} Balance"
        df.loc[mask_balance & (df["Balance Submission No"] == n), col] = df.loc[
            mask_balance & (df["Balance Submission No"] == n), "Balance"
        ]

    return df


def add_aging(df: pd.DataFrame) -> pd.DataFrame:
    # For balance tracking, user asked to take SubDate first.
    date_candidates = [c for c in ["SubDate", "SubmissionDate", "ClaimDate", "VisitDate"] if c in df.columns]
    if date_candidates:
        for c in date_candidates:
            df[c] = pd.to_datetime(df[c], errors="coerce", dayfirst=True)
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
    insurance_col = next((c for c in ["Insurance", "PayerName", "Insurer", "Plan"] if c in df.columns), None)
    if insurance_col is None:
        df["Insurance"] = "Not Available"
    elif insurance_col != "Insurance":
        df["Insurance"] = df[insurance_col]
    return df


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


def build_balance_stage_summary(balance_df: pd.DataFrame) -> pd.DataFrame:
    stage_order = ["Initial Submission"] + [f"Resub-{n}" for n in range(1, 11)] + ["Other"]
    summary = pd.pivot_table(
        balance_df,
        index="Insurance",
        columns="Balance Submission Stage",
        values="Balance",
        aggfunc="sum",
        fill_value=0,
        observed=False,
    )
    existing_cols = [c for c in stage_order if c in summary.columns]
    summary = summary.reindex(columns=existing_cols)
    summary["Grand Total"] = summary.sum(axis=1)
    summary.loc["Grand Total"] = summary.sum(axis=0)
    summary.reset_index(inplace=True)
    return summary


def build_balance_status_stage_summary(balance_df: pd.DataFrame) -> pd.DataFrame:
    result = (
        balance_df.groupby(["Balance Status Group", "Balance Submission Stage"], dropna=False)["Balance"]
        .sum()
        .reset_index()
        .sort_values(["Balance Status Group", "Balance Submission Stage"])
    )
    total_row = pd.DataFrame([{
        "Balance Status Group": "Grand Total",
        "Balance Submission Stage": "",
        "Balance": result["Balance"].sum() if not result.empty else 0,
    }])
    return pd.concat([result, total_row], ignore_index=True)


def build_insurance_totals(df: pd.DataFrame) -> pd.DataFrame:
    insurance_totals = (
        df.groupby("Insurance", dropna=False)[["Net Amount", "Paid", "Balance", "Rejected", "Accepted"]]
          .sum()
          .reset_index()
    )
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


def build_monthly_totals(df: pd.DataFrame) -> pd.DataFrame:
    date_col = next((c for c in ["VisitDate", "SubDate", "SubmissionDate", "ClaimDate"] if c in df.columns), None)
    if date_col is None:
        return pd.DataFrame()

    tmp = df.copy()
    tmp[date_col] = pd.to_datetime(tmp[date_col], errors="coerce", dayfirst=True)
    tmp = tmp.dropna(subset=[date_col])
    tmp["Month"] = tmp[date_col].dt.to_period("M").dt.strftime("%B %Y")

    monthly = (
        tmp.groupby("Month", observed=True)[["Net Amount", "Paid", "Balance", "Rejected", "Accepted"]]
           .sum()
           .reset_index()
    )

    total_row = {
        "Month": "Grand Total",
        "Net Amount": monthly["Net Amount"].sum(),
        "Paid": monthly["Paid"].sum(),
        "Balance": monthly["Balance"].sum(),
        "Rejected": monthly["Rejected"].sum(),
        "Accepted": monthly["Accepted"].sum(),
    }
    monthly = pd.concat([monthly, pd.DataFrame([total_row])], ignore_index=True)
    return monthly


def build_monthly_insurance_detail(df: pd.DataFrame) -> pd.DataFrame:
    date_col = next((c for c in ["VisitDate", "SubDate", "SubmissionDate", "ClaimDate"] if c in df.columns), None)
    if date_col is None:
        return pd.DataFrame()

    tmp = df.copy()
    tmp[date_col] = pd.to_datetime(tmp[date_col], errors="coerce", dayfirst=True)
    tmp = tmp.dropna(subset=[date_col])
    tmp["Month"] = tmp[date_col].dt.to_period("M").dt.strftime("%B %Y")

    result = (
        tmp.groupby(["Month", "Insurance"], observed=True)[["Net Amount", "Paid", "Balance", "Rejected", "Accepted"]]
           .sum()
           .reset_index()
    )
    return result[["Month", "Insurance", "Net Amount", "Paid", "Balance", "Rejected", "Accepted"]]


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
        if ws.title in ("Balance_Aging_Summary", "Balance_By_Submission_Stage"):
            for r in range(2, ws.max_row + 1):
                if ws.cell(row=r, column=1).value == "Grand Total":
                    for c in range(1, ws.max_column + 1):
                        cell = ws.cell(row=r, column=c)
                        cell.fill = TOTAL_FILL
                        cell.font = Font(bold=True)
            last_col = ws.max_column
            for r in range(1, ws.max_row + 1):
                cell = ws.cell(row=r, column=last_col)
                cell.fill = TOTAL_FILL
                cell.font = Font(bold=True)

        if ws.title in ("Insurance_Totals", "Monthly_Totals", "Balance_Status_Stage_Summary"):
            for r in range(2, ws.max_row + 1):
                if ws.cell(row=r, column=1).value == "Grand Total":
                    for c in range(1, ws.max_column + 1):
                        cell = ws.cell(row=r, column=c)
                        cell.fill = TOTAL_FILL
                        cell.font = Font(bold=True)
    wb.save(output_file)


def main():
    args = parse_args()
    input_file = os.path.abspath(args.input_xlsx)
    out_file = os.path.abspath(args.out_xlsx)

    print(f"📂 Using input : {input_file}")
    print(f"📄 Output file : {out_file}")
    print(f"🔑 Input SHA1  : {sha1_short(input_file)}")

    df = load_data(input_file)
    df = ensure_numeric(df)
    df = compute_measures(df)
    df = add_aging(df)
    df = ensure_insurance_column(df)

    balance_df = df.loc[df["Balance"] > 0].copy()
    insurance_totals = build_insurance_totals(df)
    monthly_totals = build_monthly_totals(df)
    monthly_insurance_detail = build_monthly_insurance_detail(df)
    balance_aging_summary = build_balance_aging_summary(balance_df)
    balance_stage_summary = build_balance_stage_summary(balance_df)
    balance_status_stage_summary = build_balance_status_stage_summary(balance_df)

    with pd.ExcelWriter(out_file, engine="openpyxl") as writer:
        if WRITE_EXCLUSIVE_SHEET:
            df.to_excel(writer, sheet_name="Exclusive_Report", index=False)
        insurance_totals.to_excel(writer, sheet_name="Insurance_Totals", index=False)
        if not monthly_totals.empty:
            monthly_totals.to_excel(writer, sheet_name="Monthly_Totals", index=False)
        if not monthly_insurance_detail.empty:
            monthly_insurance_detail.to_excel(writer, sheet_name="Monthly_Insurance_Detail", index=False)
        balance_aging_summary.to_excel(writer, sheet_name="Balance_Aging_Summary", index=False)
        balance_stage_summary.to_excel(writer, sheet_name="Balance_By_Submission_Stage", index=False)
        balance_status_stage_summary.to_excel(writer, sheet_name="Balance_Status_Stage_Summary", index=False)
        balance_df.to_excel(writer, sheet_name="Balance_Aging_Detail", index=False)

        meta = pd.DataFrame([{
            "InputFile": os.path.basename(input_file),
            "InputSHA1": sha1_short(input_file),
            "GeneratedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "Exclusive_Report_Written": WRITE_EXCLUSIVE_SHEET,
            "Logic": (
                "Net Amount=SubInsShare; Paid=Remit+Resub1+Resub2+Resub3+Resub4+TakeBack; "
                "Accepted=Net Amount only for Rejection Accepted statuses; Rejected=Net Amount for Rejected statuses; "
                "Balance stage derived from Status using Submitted/Not Submitted/Approved with optional Resub-N; "
                "Aging RefDate prefers SubDate"
            ),
        }])
        meta.to_excel(writer, sheet_name="Meta", index=False)

    apply_styling(out_file)
    print("✅ Done.")


if __name__ == "__main__":
    main()
