#!/usr/bin/env python3
import sys, re
from pathlib import Path
from datetime import datetime
import pandas as pd
from openpyxl import load_workbook
from openpyxl.styles import PatternFill, Font, Alignment

def norm(s: str) -> str:
    return re.sub(r"\s+", " ", str(s).strip().lower())

ALIASES = {
    "net": [
        "claim amount (net)", "claim amount", "net amount", "netamount",
        "claim amt", "amount", "net", "claimamount", "claim_amnt"
    ],
    "paid": [
        "remitted amount (paid)", "remitted amount", "paid amount", "paid",
        "remittedamount", "remitted amt", "remitted", "ins share", "ins_share"
    ],
    "status": ["claim status", "status", "payment status", "activitystatus"],
    "denial": ["denial code", "denialcode", "denial", "rejection code", "reason code"],
    "insurance": ["insurance", "insurance name", "payer", "payer name", "insurer", "plan"],
    "date": ["claim date", "submission date", "dispense date", "invoice date", "visit date", "service date"],
}

def find_col(df: pd.DataFrame, keys: list[str]) -> str | None:
    cols = {norm(c): c for c in df.columns}
    for k in keys:
        nk = norm(k)
        if nk in cols: return cols[nk]
    for nk, raw in cols.items():
        for k in keys:
            if norm(k) in nk:
                return raw
    return None

def require(df: pd.DataFrame, want: list[str], label: str) -> str:
    col = find_col(df, want)
    if not col:
        raise ValueError(f"❌ Required columns missing: {', '.join(want)} (for {label})")
    return col

def coerce_num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce").fillna(0.0)

def main():
    if len(sys.argv) < 2:
        print("Usage: pharmacy_exclusive_report_with_aging.py <source.xlsx>")
        sys.exit(2)

    src_path = Path(sys.argv[1]).resolve()
    out_path = src_path.parent / "Pharmacy_Exclusive_Report_with_Aging.xlsx"

    print("▶️  Starting Pharmacy report…")
    print(f"🧾 Using source: {src_path.name}")

    df = pd.read_excel(src_path, engine="openpyxl")
    df.columns = [c.strip() for c in df.columns]

    net_col    = require(df, ALIASES["net"],   "Net Amount")
    paid_col   = require(df, ALIASES["paid"],  "Paid Amount")
    status_col = find_col(df, ALIASES["status"])
    denial_col = find_col(df, ALIASES["denial"])
    ins_col    = find_col(df, ALIASES["insurance"]) or "Insurance"
    date_col   = find_col(df, ALIASES["date"])  # optional

    if ins_col not in df.columns:
        df[ins_col] = "Not Available"

    df["_Net"]  = coerce_num(df[net_col])
    df["_Paid"] = coerce_num(df[paid_col])

    df["Balance"]  = df["_Net"] - df["_Paid"]
    df["Rejected"] = 0.0
    df["Accepted"] = 0.0

    if status_col:
        st_lower = df[status_col].astype(str).str.lower()
        is_denied = st_lower.str.contains(r"\b(denied|reject|rejected|declined)\b", regex=True, na=False)
    else:
        is_denied = pd.Series(False, index=df.index)
        if denial_col:
            is_denied = df[denial_col].astype(str).str.len().fillna(0) > 0

    mask_reject = (df["_Paid"] <= 0.000001) & is_denied
    df.loc[mask_reject, "Rejected"] = df["_Net"]
    df.loc[mask_reject, "Balance"] = 0.0

    mask_paid = df["_Paid"] > 0
    mask_small_residual = (df["Balance"].abs() <= 4)
    mask_accept = mask_paid & mask_small_residual
    df.loc[mask_accept, "Accepted"] = df["_Net"] - df["_Paid"]
    df.loc[mask_accept, "Balance"] = 0.0

    df_out = df.copy()
    df_out.rename(columns={
        net_col: "NetAmount",
        paid_col: "Paid",
        ins_col: "Insurance",
    }, inplace=True)
    if status_col and status_col != "ClaimStatus":
        df_out.rename(columns={status_col: "ClaimStatus"}, inplace=True)
    if denial_col and denial_col != "DenialCode":
        df_out.rename(columns={denial_col: "DenialCode"}, inplace=True)

    # ---------- FIXED AGING (always use a Series) ----------
    if date_col:
        dt_series = pd.to_datetime(df[date_col], errors="coerce", dayfirst=True)
    else:
        dt_series = pd.Series(pd.NaT, index=df.index)  # <-- key fix: Series of NaT

    today = pd.Timestamp(datetime.today().date())
    days = (today - dt_series).dt.days  # safe even when all NaT -> NaN
    df_out["AgingDays"] = days

    bins = [-1, 30, 45, 60, 90, float("inf")]
    labels = ["0–30 Days", "31–45 Days", "46–60 Days", "61–90 Days", ">90 Days"]
    df_out["AgingBucket"] = pd.cut(days, bins=bins, labels=labels)

    keep_cols = ["Insurance", "NetAmount", "Paid", "Balance", "Rejected", "Accepted", "AgingBucket"]
    extra_cols = [c for c in ["ClaimStatus", "DenialCode"] if c in df_out.columns]
    excl = df_out[[c for c in keep_cols + extra_cols if c in df_out.columns]].copy()

    totals = (excl.groupby("Insurance", dropna=False)[["NetAmount","Paid","Balance","Rejected","Accepted"]]
                .sum(numeric_only=True).reset_index())

    detail = excl.loc[excl["Balance"] > 0].copy()
    summary = (detail.pivot_table(index="Insurance", columns="AgingBucket",
                                  values="Balance", aggfunc="sum", fill_value=0)
                      .reindex(columns=labels, fill_value=0))
    summary["Grand Total"] = summary.sum(axis=1)
    summary = summary.reset_index()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        excl.to_excel(writer, sheet_name="Exclusive_Report", index=False)
        totals.to_excel(writer, sheet_name="Insurance_Totals", index=False)
        summary.to_excel(writer, sheet_name="Balance_Aging_Summary", index=False)
        detail.to_excel(writer, sheet_name="Balance_Aging_Detail", index=False)

    wb = load_workbook(out_path)
    header_fill = PatternFill(start_color="BDD7EE", end_color="BDD7EE", fill_type="solid")
    for ws in wb.worksheets:
        for c in range(1, ws.max_column + 1):
            cell = ws.cell(row=1, column=c)
            cell.fill = header_fill
            cell.font = Font(bold=True)
            cell.alignment = Alignment(horizontal="center", vertical="center")
    wb.save(out_path)

    print(f"✅ Saved: {out_path.name}")

if __name__ == "__main__":
    main()

