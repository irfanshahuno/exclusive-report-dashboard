#!/usr/bin/env python3

import sys, os, hashlib, argparse
from datetime import datetime
import pandas as pd
from openpyxl import load_workbook
from openpyxl.styles import PatternFill, Font, Alignment

# =========================================
# Toggle: write the raw "Exclusive_Report" sheet?
# =========================================
WRITE_EXCLUSIVE_SHEET = False  # <-- leave False to skip that sheet

# -------------------- helpers --------------------
def sha1_short(path: str) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()[:12]

def parse_args():
    p = argparse.ArgumentParser(
        description="Build Exclusive_Report_with_Aging from an input .xlsx"
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

# -------------------- ETL parts --------------------
def load_data(input_file: str) -> pd.DataFrame:
    df = pd.read_excel(input_file, engine="openpyxl")
    df.columns = df.columns.str.strip()
    return df

def ensure_numeric(df: pd.DataFrame) -> pd.DataFrame:
    num_cols = [
        "ActivityIns",
        "actRemitInsShare", "actResub1RemitInsShare",
        "actResub2RemitInsShare", "actResub3RemitInsShare",
        "TKBKAmountAct",
    ]
    for c in num_cols:
        if c not in df.columns:
            df[c] = 0
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
    return df


def clean_status(df: pd.DataFrame) -> pd.DataFrame:
    """
    Clean and forward-fill Status so each activity row inherits its claim-block status.
    """
    if "Status" not in df.columns:
        df["Status"] = ""
    df["Status"] = df["Status"].replace(r"^\s*$", pd.NA, regex=True)
    df["Status"] = df["Status"].ffill().fillna("")
    df["Status"] = df["Status"].astype(str).str.strip()
    return df

def status_startswith(series: pd.Series, prefix: str) -> pd.Series:
    s = series.fillna("").astype(str).str.strip()
    return s.str.startswith(prefix, na=False)

def status_contains_submitted_resub(series: pd.Series) -> pd.Series:
    s = series.fillna("").astype(str).str.strip()
    return s.str.contains(r"^Submitted\(Resub-\s*\d+\)", regex=True, na=False)

def build_rcm_summary(df: pd.DataFrame) -> pd.DataFrame:
    required_num_cols = [
        "ActivityIns",
        "Paid",
        "actRemitInsShare",
        "actResub1RemitInsShare",
        "actResub2RemitInsShare",
        "actResub3RemitInsShare",
        "TKBKAmountAct",
        "Balance",
        "Rejection",
        "Accepted",
    ]
    for c in required_num_cols:
        if c not in df.columns:
            df[c] = 0
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)

    if "Insurance" not in df.columns:
        df["Insurance"] = "Not Available"
    if "UniqueID" not in df.columns:
        # fallback so script still runs, but user-confirmed source is UniqueID
        df["UniqueID"] = range(1, len(df) + 1)
    if "Status" not in df.columns:
        df["Status"] = ""

    grouped = df.groupby("Insurance", dropna=False)

    claim_count = grouped["UniqueID"].nunique()
    claimed_amount = grouped["ActivityIns"].sum()
    remitted_amt = grouped["Paid"].sum()
    initial_pay = grouped["actRemitInsShare"].sum()
    resb1_pay = grouped["actResub1RemitInsShare"].sum()
    resb2_pay = grouped["actResub2RemitInsShare"].sum()
    resb3_pay = grouped["actResub3RemitInsShare"].sum()
    total_pay = initial_pay + resb1_pay + resb2_pay + resb3_pay + grouped["TKBKAmountAct"].sum()

    st = df["Status"].fillna("").astype(str).str.strip()

    sub_nt_rmtd = (
        df.loc[status_startswith(st, "Submitted") & ~status_contains_submitted_resub(st)]
          .groupby("Insurance", dropna=False)["Balance"].sum()
    )
    pending_resub = (
        df.loc[status_startswith(st, "Not Submitted")]
          .groupby("Insurance", dropna=False)["Balance"].sum()
    )
    rsub_nt_rmtd = (
        df.loc[status_contains_submitted_resub(st)]
          .groupby("Insurance", dropna=False)["Balance"].sum()
    )
    rejection_accepted = (
        df.loc[status_startswith(st, "Rejection Accepted")]
          .groupby("Insurance", dropna=False)["ActivityIns"].sum()
    )
    final_rejn = grouped["Rejection"].sum()

    summary = pd.DataFrame({
        "Insurance Name": claim_count.index,
        "Claim count": claim_count.values,
        "Claimed Amount": claimed_amount.reindex(claim_count.index, fill_value=0).values,
        "Remited Amt": remitted_amt.reindex(claim_count.index, fill_value=0).values,
        "Initial pay": initial_pay.reindex(claim_count.index, fill_value=0).values,
        "Resb1 pay": resb1_pay.reindex(claim_count.index, fill_value=0).values,
        "Resb2 pay": resb2_pay.reindex(claim_count.index, fill_value=0).values,
        "Resb3 pay": resb3_pay.reindex(claim_count.index, fill_value=0).values,
        "Total pay": total_pay.reindex(claim_count.index, fill_value=0).values,
        "Sub Nt Rmtd (outstanding amount)": sub_nt_rmtd.reindex(claim_count.index, fill_value=0).values,
        "Pending for Resubmission": pending_resub.reindex(claim_count.index, fill_value=0).values,
        "Rsub Nt Rmtd (outstanding amount)": rsub_nt_rmtd.reindex(claim_count.index, fill_value=0).values,
        "Rejection Accepted": rejection_accepted.reindex(claim_count.index, fill_value=0).values,
        "Final Rejn": final_rejn.reindex(claim_count.index, fill_value=0).values,
    })
    summary["Rej. %"] = (summary["Final Rejn"] / summary["Claimed Amount"].replace(0, pd.NA)).fillna(0)
    summary = summary.sort_values("Insurance Name", na_position="last").reset_index(drop=True)

    total_row = {"Insurance Name": "Grand Total"}
    for col in summary.columns[1:]:
        if col == "Rej. %":
            claimed_total = pd.to_numeric(summary["Claimed Amount"], errors="coerce").sum()
            final_total = pd.to_numeric(summary["Final Rejn"], errors="coerce").sum()
            total_row[col] = (final_total / claimed_total) if claimed_total else 0
        else:
            total_row[col] = pd.to_numeric(summary[col], errors="coerce").sum()

    summary = pd.concat([summary, pd.DataFrame([total_row])], ignore_index=True)
    return summary

def compute_measures(df: pd.DataFrame) -> pd.DataFrame:
    df["Paid"] = df[
        ["actRemitInsShare", "actResub1RemitInsShare",
         "actResub2RemitInsShare", "actResub3RemitInsShare",
         "TKBKAmountAct"]
    ].sum(axis=1)

    df["Rejection"], df["Accepted"], df["Balance"] = 0.0, 0.0, 0.0

    if "ActivityStatus" in df.columns and "DenialCode" in df.columns:
        lower_status = df["ActivityStatus"].astype(str).str.lower()
        mask_paid = df["Paid"] > 0
        mask_reject = (df["Paid"] == 0) & (lower_status == "rejected") & (df["DenialCode"].notna())
        mask_balance = (df["Paid"] == 0) & ~mask_reject

        df.loc[mask_paid, "Accepted"] = df["ActivityIns"] - df["Paid"]
        df.loc[mask_reject, "Rejection"] = df["ActivityIns"]
        df.loc[mask_balance, "Balance"] = df["ActivityIns"]

    return df

def add_aging(df: pd.DataFrame) -> pd.DataFrame:
    from datetime import datetime as dt
    date_candidates = [c for c in ["SubmissionDate", "ClaimDate", "VisitDate"] if c in df.columns]
    if date_candidates:
        for c in date_candidates:
            df[c] = pd.to_datetime(df[c], errors="coerce", dayfirst=True)
        df["RefDate"] = df[date_candidates].bfill(axis=1).iloc[:, 0]
    else:
        df["RefDate"] = pd.NaT

    today = pd.Timestamp(dt.today().date())
    df["DaysDiff"] = (today - df["RefDate"]).dt.days

    bins = [-1, 30, 45, 60, 90, float("inf")]
    labels = ["0–30 Days", "31–45 Days", "46–60 Days", "61–90 Days", ">90 Days"]
    df["AgingBucket"] = pd.cut(df["DaysDiff"], bins=bins, labels=labels)
    return df

def ensure_insurance_column(df: pd.DataFrame) -> pd.DataFrame:
    insurance_col = next((c for c in ["Insurance", "PayerName", "Insurer", "Plan"] if c in df.columns), "Insurance")
    if insurance_col not in df.columns:
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

def build_insurance_totals(df: pd.DataFrame) -> pd.DataFrame:
    insurance_totals = (
        df.groupby("Insurance", dropna=False)[["ActivityIns", "Paid", "Rejection", "Accepted", "Balance"]]
          .sum()
          .reset_index()
    )
    insurance_totals = insurance_totals.rename(columns={"ActivityIns": "Net Amount", "Rejection": "Rejected"})
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

def build_monthly_insurance_detail(df: pd.DataFrame) -> pd.DataFrame:
    """For each month, insurance-wise breakdown: Net Amount, Paid, Balance, Rejected, Accepted."""
    date_col = next(
        (c for c in ["VisitDate", "SubmissionDate", "ClaimDate"] if c in df.columns), None
    )
    if date_col is None:
        return pd.DataFrame()

    df = df.copy()
    df[date_col] = pd.to_datetime(df[date_col], errors="coerce", dayfirst=True)
    df = df.dropna(subset=[date_col])
    df["_Month"] = df[date_col].dt.to_period("M").dt.strftime("%B %Y")

    result = (
        df.groupby(["_Month", "Insurance"], observed=True)[
            ["ActivityIns", "Paid", "Rejection", "Accepted", "Balance"]
        ]
        .sum()
        .reset_index()
    )
    result = result.rename(columns={
        "_Month": "Month",
        "ActivityIns": "Net Amount",
        "Rejection": "Rejected",
    })
    result = result[["Month", "Insurance", "Net Amount", "Paid", "Balance", "Rejected", "Accepted"]]
    return result


def build_monthly_totals(df: pd.DataFrame) -> pd.DataFrame:
    """Same structure as Insurance_Totals but grouped by VisitDate month."""
    # Find date column
    date_col = next(
        (c for c in ["VisitDate", "SubmissionDate", "ClaimDate"] if c in df.columns), None
    )
    if date_col is None:
        return pd.DataFrame()

    df = df.copy()
    df[date_col] = pd.to_datetime(df[date_col], errors="coerce", dayfirst=True)
    df = df.dropna(subset=[date_col])
    df["_Month"] = df[date_col].dt.to_period("M")

    monthly = (
        df.groupby("_Month", observed=True)[["ActivityIns", "Paid", "Rejection", "Accepted", "Balance"]]
        .sum()
        .reset_index()
    )
    monthly["_Month"] = monthly["_Month"].dt.strftime("%B %Y")
    monthly = monthly.rename(columns={
        "_Month": "Month",
        "ActivityIns": "Net Amount",
        "Rejection": "Rejected",
    })
    monthly = monthly[["Month", "Net Amount", "Paid", "Balance", "Rejected", "Accepted"]]

    total_row = {
        "Month":      "Grand Total",
        "Net Amount": monthly["Net Amount"].sum(),
        "Paid":       monthly["Paid"].sum(),
        "Balance":    monthly["Balance"].sum(),
        "Rejected":   monthly["Rejected"].sum(),
        "Accepted":   monthly["Accepted"].sum(),
    }
    monthly = pd.concat([monthly, pd.DataFrame([total_row])], ignore_index=True)
    return monthly


# -------------------- styling --------------------
HEADER_FILL = PatternFill(start_color="BDD7EE", end_color="BDD7EE", fill_type="solid")
TOTAL_FILL  = PatternFill(start_color="FCE4D6", end_color="FCE4D6", fill_type="solid")

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
        if ws.title == "RCM_Summary":
            header_map = {ws.cell(row=1, column=c).value: c for c in range(1, ws.max_column + 1)}
            pct_col = header_map.get("Rej. %")
            if pct_col:
                for r in range(2, ws.max_row + 1):
                    ws.cell(row=r, column=pct_col).number_format = "0.00%"
        if ws.title == "Balance_Aging_Summary":
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

        if ws.title in ("RCM_Summary", "Insurance_Totals", "Monthly_Totals"):
            for r in range(2, ws.max_row + 1):
                if ws.cell(row=r, column=1).value == "Grand Total":
                    for c in range(1, ws.max_column + 1):
                        cell = ws.cell(row=r, column=c)
                        cell.fill = TOTAL_FILL
                        cell.font = Font(bold=True)
    wb.save(output_file)

# -------------------- main --------------------
def main():
    args = parse_args()
    input_file = os.path.abspath(args.input_xlsx)
    out_file   = os.path.abspath(args.out_xlsx)

    print(f"📂 Using input : {input_file}")
    print(f"📄 Output file : {out_file}")
    print(f"🔑 Input SHA1  : {sha1_short(input_file)}")

    df = load_data(input_file)
    df = ensure_numeric(df)
    df = clean_status(df)
    df = compute_measures(df)
    df = add_aging(df)
    df = ensure_insurance_column(df)

    balance_df = df.loc[df["Balance"] > 0].copy()
    pivot_summary = build_balance_aging_summary(balance_df)
    insurance_totals = build_insurance_totals(df)
    rcm_summary = build_rcm_summary(df)
    monthly_totals = build_monthly_totals(df)
    monthly_insurance_detail = build_monthly_insurance_detail(df)

    # Write sheets (skip "Exclusive_Report" if disabled)
    with pd.ExcelWriter(out_file, engine="openpyxl") as writer:
        if WRITE_EXCLUSIVE_SHEET:
            df.to_excel(writer, sheet_name="Exclusive_Report", index=False)
        rcm_summary.to_excel(writer, sheet_name="RCM_Summary", index=False)
        insurance_totals.to_excel(writer, sheet_name="Insurance_Totals", index=False)
        if not monthly_totals.empty:
            monthly_totals.to_excel(writer, sheet_name="Monthly_Totals", index=False)
        if not monthly_insurance_detail.empty:
            monthly_insurance_detail.to_excel(writer, sheet_name="Monthly_Insurance_Detail", index=False)
        pivot_summary.to_excel(writer, sheet_name="Balance_Aging_Summary", index=False)
        balance_df.to_excel(writer, sheet_name="Balance_Aging_Detail", index=False)

        meta = pd.DataFrame([{
            "InputFile": os.path.basename(input_file),
            "InputSHA1": sha1_short(input_file),
            "GeneratedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "Exclusive_Report_Written": WRITE_EXCLUSIVE_SHEET,
        }])
        meta.to_excel(writer, sheet_name="Meta", index=False)

    apply_styling(out_file)
    print("✅ Done.")

if __name__ == "__main__":
    main()

