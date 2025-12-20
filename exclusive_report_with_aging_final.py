#!/usr/bin/env python3

import os, hashlib, argparse
from datetime import datetime
import pandas as pd
from openpyxl import load_workbook
from openpyxl.styles import PatternFill, Font, Alignment

# =========================================
# Toggle: write the raw "Exclusive_Report" sheet?
# =========================================
WRITE_EXCLUSIVE_SHEET = False  # <-- leave False to skip that sheet

# =========================================
# SOLD TO KLAIM insurers (keyword match)
# =========================================
SOLD_TO_KLAIM_KEYS = {"DAMAN", "FMC", "NEXTCARE", "SUKOON", "ALMADALLAH"}

# -------------------- helpers --------------------
def sha1_short(path: str) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()[:12]

def parse_args():
    p = argparse.ArgumentParser(description="Build Exclusive_Report_with_Aging from an input .xlsx")
    p.add_argument("input_xlsx", help="Path to source Excel (.xlsx)")
    p.add_argument("--out", dest="out_xlsx", required=True, help="Path to write the output workbook (.xlsx)")
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

def ensure_insgroup_column(df: pd.DataFrame) -> pd.DataFrame:
    cand = next((c for c in ["InsGroup", "Item Group", "ItemGroup", "ServiceGroup", "Item_Group"] if c in df.columns), None)
    if cand:
        df["InsGroup"] = df[cand]
    else:
        df["InsGroup"] = "-"
    df["InsGroup"] = df["InsGroup"].fillna("-").astype(str).str.strip()
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

def build_balance_aging_insgroup(balance_df: pd.DataFrame) -> pd.DataFrame:
    labels = ["0–30 Days", "31–45 Days", "46–60 Days", "61–90 Days", ">90 Days"]
    pivot_ig = pd.pivot_table(
        balance_df,
        index=["Insurance", "InsGroup"],
        columns="AgingBucket",
        values="Balance",
        aggfunc="sum",
        fill_value=0,
        observed=False,
    ).reindex(columns=labels)
    pivot_ig["Grand Total"] = pivot_ig.sum(axis=1)
    return pivot_ig.reset_index()

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
    return pd.concat([insurance_totals, pd.DataFrame([total_row])], ignore_index=True)

# =========================================
# NEW: Build Pending Detail sheet (ALL columns)
# - Determine PendingStage from Status:
#   Not Submitted / Submitted => Initial pending
#   Not Submitted(Resub- 1)/Submitted(Resub- 1) => Resub1 pending
#   Not Submitted(Resub- 2)/Submitted(Resub- 2) => Resub2 pending
#   Not Submitted(Resub- 3)/Submitted(Resub- 3) => Resub3 pending
# - Sold to Klaim: if Insurance contains DAMAN/FMC/NEXTCARE/SUKOON/ALMADALLAH
# - At the end: SoldNote column (blank or "Sold to Klaim (InsuranceName)")
# =========================================
def build_balance_pending_detail(balance_df: pd.DataFrame) -> pd.DataFrame:
    out = balance_df.copy()

    # Status may not exist in some files
    if "Status" not in out.columns:
        out["Status"] = ""

    status = out["Status"].fillna("").astype(str).str.strip()
    s = status.str.lower()

    is_submitted_like = s.str.contains("submitted", na=False)  # catches "Submitted" and "Not Submitted"
    has_r1 = s.str.contains("resub- 1", na=False) | s.str.contains("resub-1", na=False) | s.str.contains("resub 1", na=False)
    has_r2 = s.str.contains("resub- 2", na=False) | s.str.contains("resub-2", na=False) | s.str.contains("resub 2", na=False)
    has_r3 = s.str.contains("resub- 3", na=False) | s.str.contains("resub-3", na=False) | s.str.contains("resub 3", na=False)

    out["PendingStage"] = "Unknown / Other"
    out.loc[is_submitted_like & ~has_r1 & ~has_r2 & ~has_r3, "PendingStage"] = "Initial Submission Pending"
    out.loc[is_submitted_like & has_r1, "PendingStage"] = "Resubmission 1 Pending"
    out.loc[is_submitted_like & has_r2, "PendingStage"] = "Resubmission 2 Pending"
    out.loc[is_submitted_like & has_r3, "PendingStage"] = "Resubmission 3 Pending"

    # Sold-to-Klaim based on Insurance name
    ins = out.get("Insurance", pd.Series(["Not Available"] * len(out), index=out.index))
    ins_str = ins.fillna("").astype(str).str.strip()
    ins_upper = ins_str.str.upper()

    sold_mask = pd.Series(False, index=out.index)
    for k in SOLD_TO_KLAIM_KEYS:
        sold_mask = sold_mask | ins_upper.str.contains(k.upper(), na=False)

    out["SoldToKlaim"] = sold_mask.map(lambda v: "YES" if v else "NO")

    # IMPORTANT: user wants note "at the end"
    out["SoldNote"] = ""
    out.loc[sold_mask, "SoldNote"] = "Sold to Klaim (" + ins_str.loc[sold_mask] + ")"

    # Put the new columns at the very end (exactly as requested)
    new_cols = ["PendingStage", "SoldToKlaim", "SoldNote"]
    base_cols = [c for c in out.columns if c not in new_cols]
    out = out[base_cols + new_cols]

    return out

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

        if ws.title == "Balance_Aging_Summary":
            # highlight grand total row + last column
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

        if ws.title == "Insurance_Totals":
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
    df = compute_measures(df)
    df = add_aging(df)
    df = ensure_insurance_column(df)
    df = ensure_insgroup_column(df)

    balance_df = df.loc[df["Balance"] > 0].copy()

    pivot_summary = build_balance_aging_summary(balance_df)
    pivot_insgroup = build_balance_aging_insgroup(balance_df)
    insurance_totals = build_insurance_totals(df)

    # NEW: pending detail full columns + sold note at end
    pending_detail_df = build_balance_pending_detail(balance_df)

    with pd.ExcelWriter(out_file, engine="openpyxl") as writer:
        if WRITE_EXCLUSIVE_SHEET:
            df.to_excel(writer, sheet_name="Exclusive_Report", index=False)

        insurance_totals.to_excel(writer, sheet_name="Insurance_Totals", index=False)
        pivot_summary.to_excel(writer, sheet_name="Balance_Aging_Summary", index=False)
        pivot_insgroup.to_excel(writer, sheet_name="Balance_Aging_InsGroup", index=False)
        balance_df.to_excel(writer, sheet_name="Balance_Aging_Detail", index=False)

        # NEW SHEET
        pending_detail_df.to_excel(writer, sheet_name="Balance_Pending_Detail", index=False)

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

