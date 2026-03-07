#!/usr/bin/env python3

import os, hashlib, argparse
from datetime import datetime
import pandas as pd
from openpyxl import load_workbook
from openpyxl.styles import PatternFill, Font, Alignment

# =========================================
# Toggle: write the raw "Exclusive_Report" sheet?
# =========================================
WRITE_EXCLUSIVE_SHEET = False

# -------------------- Status → Bucket & Date mapping --------------------
#
# BALANCE statuses → use matching date column for aging
BALANCE_STATUS_DATE_MAP = {
    "not submitted":        "SubDate",
    "submitted":            "SubDate",
    "submitted(resub-1)":   "Resub1Date",
    "submitted(resub-2)":   "Resub2Date",
    "submitted(resub-3)":   "Resub3Date",
    "submitted(resub-4)":   "Resub4Date",
    "approved(resub-1)":    "Resub1Date",
    "approved(resub-2)":    "Resub2Date",
    "approved(resub-3)":    "Resub3Date",
    "approved(resub-4)":    "Resub4Date",
}

# PAID statuses (remit sum is used as Paid value)
PAID_STATUSES = {
    "approved",
}

# REJECTED: status contains "Rejected" but NOT "Rejection Accepted"
# ACCEPTED: status contains "Rejection Accepted"
# Everything else not in any of the above → unclassified (should not happen)

# -------------------- helpers --------------------
def sha1_short(path: str) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()[:12]

def normalize_status(s: str) -> str:
    """Lowercase, strip, normalize 'Resub- 1' → 'Resub-1'."""
    s = str(s).strip().lower()
    import re
    s = re.sub(r"resub-\s+", "resub-", s)
    return s

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
    os.makedirs(os.path.dirname(os.path.abspath(args.out_xlsx)) or ".", exist_ok=True)
    return args

# -------------------- ETL --------------------
def load_data(input_file: str) -> pd.DataFrame:
    df = pd.read_excel(input_file, engine="openpyxl")
    df.columns = df.columns.str.strip()
    return df

def ensure_numeric(df: pd.DataFrame) -> pd.DataFrame:
    num_cols = [
        "SubInsShare",
        "RemitInsShare", "Resub1RemitInsShare", "Resub2RemitInsShare",
        "Resub3RemitInsShare", "Resub4RemitInsShare",
        "TakeBack",
    ]
    for c in num_cols:
        if c not in df.columns:
            df[c] = 0
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
    return df

def compute_measures(df: pd.DataFrame) -> pd.DataFrame:
    # ── Net Amount ──────────────────────────────────────────────────────
    df["Net Amount"] = df["SubInsShare"]

    # ── Remit sum (actual cash received) ────────────────────────────────
    remit_cols = [
        "RemitInsShare", "Resub1RemitInsShare", "Resub2RemitInsShare",
        "Resub3RemitInsShare", "Resub4RemitInsShare", "TakeBack",
    ]
    df["_RemitSum"] = df[remit_cols].sum(axis=1)

    # ── Classify each row into exactly ONE bucket ────────────────────────
    df["Paid"]      = 0.0
    df["Balance"]   = 0.0
    df["Rejected"]  = 0.0
    df["Accepted"]  = 0.0

    if "Status" not in df.columns:
        # fallback: everything is balance
        df["Balance"] = df["Net Amount"]
        return df

    raw_status  = df["Status"].astype(str).str.strip()
    norm_status = raw_status.apply(normalize_status)

    # 1. ACCEPTED — "Rejection Accepted" (check before Rejected)
    mask_accepted = raw_status.str.contains("Rejection Accepted", case=False, na=False)

    # 2. REJECTED — "Rejected" but not "Rejection Accepted"
    mask_rejected = (
        raw_status.str.contains("Rejected", case=False, na=False) &
        ~mask_accepted
    )

    # 3. BALANCE — statuses in BALANCE_STATUS_DATE_MAP
    mask_balance = norm_status.isin(BALANCE_STATUS_DATE_MAP.keys())

    # 4. PAID — statuses in PAID_STATUSES
    mask_paid = norm_status.isin(PAID_STATUSES)

    # Assign Net Amount to each bucket
    df.loc[mask_accepted, "Accepted"] = df.loc[mask_accepted, "Net Amount"]
    df.loc[mask_rejected, "Rejected"] = df.loc[mask_rejected, "Net Amount"]
    df.loc[mask_balance,  "Balance"]  = df.loc[mask_balance,  "Net Amount"]
    df.loc[mask_paid,     "Paid"]     = df.loc[mask_paid,     "_RemitSum"]

    return df

def parse_date_columns(df: pd.DataFrame) -> pd.DataFrame:
    date_cols = ["SubDate", "Resub1Date", "Resub2Date", "Resub3Date", "Resub4Date"]
    for c in date_cols:
        if c in df.columns:
            df[c] = pd.to_datetime(df[c], errors="coerce", dayfirst=True)
        else:
            df[c] = pd.NaT
    return df

def add_aging(df: pd.DataFrame) -> pd.DataFrame:
    """Pick aging date per row based on status → BALANCE_STATUS_DATE_MAP."""
    today = pd.Timestamp(datetime.today().date())

    def pick_date(row):
        key = normalize_status(row.get("Status", ""))
        date_col = BALANCE_STATUS_DATE_MAP.get(key)
        if date_col and pd.notna(row.get(date_col)):
            return row[date_col]
        return pd.NaT

    df["RefDate"]  = df.apply(pick_date, axis=1)
    df["DaysDiff"] = (today - df["RefDate"]).dt.days

    bins   = [-1, 30, 45, 60, 90, float("inf")]
    labels = ["0–30 Days", "31–45 Days", "46–60 Days", "61–90 Days", ">90 Days"]
    df["AgingBucket"] = pd.cut(df["DaysDiff"], bins=bins, labels=labels)
    return df

def get_balance_df(df: pd.DataFrame) -> pd.DataFrame:
    """Only balance-bucket rows with Balance > 0."""
    norm_status = df["Status"].astype(str).str.strip().apply(normalize_status)
    mask = norm_status.isin(BALANCE_STATUS_DATE_MAP.keys()) & (df["Balance"] > 0)
    return df.loc[mask].copy()

# -------------------- summary builders --------------------
def build_insurance_totals(df: pd.DataFrame) -> pd.DataFrame:
    grp = (
        df.groupby("Insurance", dropna=False)[
            ["Net Amount", "Paid", "Balance", "Rejected", "Accepted"]
        ]
        .sum()
        .reset_index()
    )
    grp = grp[["Insurance", "Net Amount", "Paid", "Balance", "Rejected", "Accepted"]]
    total_row = {
        "Insurance":  "Grand Total",
        "Net Amount": grp["Net Amount"].sum(),
        "Paid":       grp["Paid"].sum(),
        "Balance":    grp["Balance"].sum(),
        "Rejected":   grp["Rejected"].sum(),
        "Accepted":   grp["Accepted"].sum(),
    }
    return pd.concat([grp, pd.DataFrame([total_row])], ignore_index=True)

def build_monthly_totals(df: pd.DataFrame) -> pd.DataFrame:
    if "SubDate" not in df.columns:
        return pd.DataFrame()
    tmp = df.copy()
    tmp["SubDate"] = pd.to_datetime(tmp["SubDate"], errors="coerce", dayfirst=True)
    tmp = tmp.dropna(subset=["SubDate"])
    tmp["_Month"] = tmp["SubDate"].dt.to_period("M")

    monthly = (
        tmp.groupby("_Month", observed=True)[
            ["Net Amount", "Paid", "Balance", "Rejected", "Accepted"]
        ]
        .sum()
        .reset_index()
    )
    monthly["_Month"] = monthly["_Month"].dt.strftime("%B %Y")
    monthly = monthly.rename(columns={"_Month": "Month"})
    monthly = monthly[["Month", "Net Amount", "Paid", "Balance", "Rejected", "Accepted"]]

    total_row = {
        "Month":      "Grand Total",
        "Net Amount": monthly["Net Amount"].sum(),
        "Paid":       monthly["Paid"].sum(),
        "Balance":    monthly["Balance"].sum(),
        "Rejected":   monthly["Rejected"].sum(),
        "Accepted":   monthly["Accepted"].sum(),
    }
    return pd.concat([monthly, pd.DataFrame([total_row])], ignore_index=True)

def build_monthly_insurance_detail(df: pd.DataFrame) -> pd.DataFrame:
    if "SubDate" not in df.columns:
        return pd.DataFrame()
    tmp = df.copy()
    tmp["SubDate"] = pd.to_datetime(tmp["SubDate"], errors="coerce", dayfirst=True)
    tmp = tmp.dropna(subset=["SubDate"])
    tmp["_Month"] = tmp["SubDate"].dt.to_period("M").dt.strftime("%B %Y")

    result = (
        tmp.groupby(["_Month", "Insurance"], observed=True)[
            ["Net Amount", "Paid", "Balance", "Rejected", "Accepted"]
        ]
        .sum()
        .reset_index()
    )
    result = result.rename(columns={"_Month": "Month"})
    return result[["Month", "Insurance", "Net Amount", "Paid", "Balance", "Rejected", "Accepted"]]

def build_balance_aging_summary(balance_df: pd.DataFrame) -> pd.DataFrame:
    labels = ["0–30 Days", "31–45 Days", "46–60 Days", "61–90 Days", ">90 Days"]
    pivot = pd.pivot_table(
        balance_df,
        index="Insurance",
        columns="AgingBucket",
        values="Balance",
        aggfunc="sum",
        fill_value=0,
        observed=False,
    ).reindex(columns=labels, fill_value=0)
    pivot["Grand Total"] = pivot.sum(axis=1)
    pivot.loc["Grand Total"] = pivot.sum(axis=0)
    pivot.reset_index(inplace=True)
    return pivot

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
        if ws.title in ("Insurance_Totals", "Monthly_Totals", "Balance_Aging_Summary"):
            for r in range(2, ws.max_row + 1):
                if ws.cell(row=r, column=1).value == "Grand Total":
                    for c in range(1, ws.max_column + 1):
                        cell = ws.cell(row=r, column=c)
                        cell.fill = TOTAL_FILL
                        cell.font = Font(bold=True)
        if ws.title == "Balance_Aging_Summary":
            last_col = ws.max_column
            for r in range(1, ws.max_row + 1):
                cell = ws.cell(row=r, column=last_col)
                cell.fill = TOTAL_FILL
                cell.font = Font(bold=True)
    wb.save(output_file)

# -------------------- main --------------------
def main():
    args       = parse_args()
    input_file = os.path.abspath(args.input_xlsx)
    out_file   = os.path.abspath(args.out_xlsx)

    print(f"📂 Using input : {input_file}")
    print(f"📄 Output file : {out_file}")
    print(f"🔑 Input SHA1  : {sha1_short(input_file)}")

    df = load_data(input_file)
    df = ensure_numeric(df)
    df = compute_measures(df)
    df = parse_date_columns(df)
    df = add_aging(df)

    if "Insurance" not in df.columns:
        df["Insurance"] = "Not Available"

    balance_df               = get_balance_df(df)
    insurance_totals         = build_insurance_totals(df)
    monthly_totals           = build_monthly_totals(df)
    monthly_insurance_detail = build_monthly_insurance_detail(df)
    pivot_summary            = build_balance_aging_summary(balance_df)

    # ── Validation check ────────────────────────────────────────────────
    total_net      = df["Net Amount"].sum()
    total_buckets  = df[["Paid","Balance","Rejected","Accepted"]].sum().sum()
    diff           = abs(total_net - total_buckets)
    print(f"✅ Net Amount   : {total_net:,.2f}")
    print(f"✅ P+B+R+A sum  : {total_buckets:,.2f}")
    print(f"{'✅' if diff < 0.01 else '⚠️'} Difference    : {diff:,.2f}")

    with pd.ExcelWriter(out_file, engine="openpyxl") as writer:
        if WRITE_EXCLUSIVE_SHEET:
            df.to_excel(writer, sheet_name="Exclusive_Report", index=False)
        insurance_totals.to_excel(writer, sheet_name="Insurance_Totals", index=False)
        if not monthly_totals.empty:
            monthly_totals.to_excel(writer, sheet_name="Monthly_Totals", index=False)
        if not monthly_insurance_detail.empty:
            monthly_insurance_detail.to_excel(
                writer, sheet_name="Monthly_Insurance_Detail", index=False
            )
        pivot_summary.to_excel(writer, sheet_name="Balance_Aging_Summary", index=False)
        balance_df.to_excel(writer, sheet_name="Balance_Aging_Detail", index=False)

        meta = pd.DataFrame([{
            "InputFile":                os.path.basename(input_file),
            "InputSHA1":                sha1_short(input_file),
            "GeneratedAt":              datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "Exclusive_Report_Written": WRITE_EXCLUSIVE_SHEET,
        }])
        meta.to_excel(writer, sheet_name="Meta", index=False)

    apply_styling(out_file)
    print("✅ Done.")

if __name__ == "__main__":
    main()
