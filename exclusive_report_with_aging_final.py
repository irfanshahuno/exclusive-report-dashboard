#!/usr/bin/env python3

import sys, os, hashlib, argparse
from datetime import datetime
import pandas as pd
from openpyxl import load_workbook
from openpyxl.styles import PatternFill, Font, Alignment, Border, Side
from openpyxl.utils import get_column_letter

WRITE_EXCLUSIVE_SHEET = False

# -------------------- helpers --------------------
def sha1_short(path):
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
    os.makedirs(os.path.dirname(os.path.abspath(args.out_xlsx)) or ".", exist_ok=True)
    return args

# -------------------- ETL --------------------
def load_data(input_file):
    df = pd.read_excel(input_file, engine="openpyxl")
    df.columns = df.columns.str.strip()
    return df

def ensure_numeric(df):
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

def ffill_status(df):
    """Forward-fill the Status column: blank/NaN rows inherit the last non-empty status above."""
    if "Status" not in df.columns:
        df["Status"] = ""
    df["Status"] = (
        df["Status"]
        .astype(str)
        .str.strip()
        .replace({"": pd.NA, "nan": pd.NA, "None": pd.NA})
    )
    df["Status"] = df["Status"].ffill().fillna("")
    return df


def compute_measures(df):
    # ── Step 1: ffill Status FIRST so all bucketing is correct ──────────────
    df = ffill_status(df)

    # ── Step 2: remittance columns ───────────────────────────────────────────
    df["InitialPay"] = df["actRemitInsShare"]
    df["Resub1Pay"]  = df["actResub1RemitInsShare"]
    df["Resub2Pay"]  = df["actResub2RemitInsShare"]
    df["Resub3Pay"]  = df["actResub3RemitInsShare"]

    df["RemittedAmt"] = df[["actRemitInsShare", "actResub1RemitInsShare",
                              "actResub2RemitInsShare", "actResub3RemitInsShare",
                              "TKBKAmountAct"]].sum(axis=1)

    df["TotalPay"] = df[["actRemitInsShare", "actResub1RemitInsShare",
                           "actResub2RemitInsShare", "actResub3RemitInsShare",
                           "TKBKAmountAct"]].sum(axis=1)

    df["Paid"] = df["RemittedAmt"]

    # ── Step 3: Status-based buckets (on ffilled Status) ────────────────────
    st = df["Status"].astype(str).str.strip()

    # Sub Nt Rmtd  → Status == "Submitted" (exact, case-insensitive)
    mask_submitted   = st.str.lower() == "submitted"

    # Rsub Nt Rmtd → Status is "Submitted(Resub- N)" — submitted resubmissions only
    mask_resub       = st.str.lower().str.contains(r"submitted\(resub-\s*\d", na=False)

    # Rejection Accepted → Status starts with "Rejection Accepted"
    mask_rej_acc     = st.str.lower().str.startswith("rejection accepted")

    # Pending for Resubmission → Status starts with "Not Submitted" (covers Not Submitted, Not Submitted(Resub- 1/2/3) etc)
    mask_pending     = st.str.lower().str.startswith("not submitted")

    df["SubNtRmtd"]   = df["ActivityIns"].where(mask_submitted, 0.0)
    df["RsubNtRmtd"]  = df["ActivityIns"].where(mask_resub,     0.0)
    df["Accepted"]    = df["ActivityIns"].where(mask_rej_acc,   0.0)
    df["PendingResub"]= df["ActivityIns"].where(mask_pending,   0.0)

    # ── Step 4: Final Rejection & Balance (existing logic) ───────────────────
    df["Rejection"] = 0.0
    df["Balance"]   = 0.0

    if "ActivityStatus" in df.columns and "DenialCode" in df.columns:
        lower_as   = df["ActivityStatus"].astype(str).str.lower()
        mask_paid    = df["Paid"] > 0
        mask_reject  = (df["Paid"] == 0) & (lower_as == "rejected") & df["DenialCode"].notna()
        mask_balance = (df["Paid"] == 0) & ~mask_reject

        df.loc[mask_reject,  "Rejection"] = df["ActivityIns"]
        df.loc[mask_balance, "Balance"]   = df["ActivityIns"]

    return df

def add_aging(df):
    date_candidates = [c for c in ["SubmissionDate", "ClaimDate", "VisitDate"] if c in df.columns]
    if date_candidates:
        for c in date_candidates:
            df[c] = pd.to_datetime(df[c], errors="coerce", dayfirst=True)
        df["RefDate"] = df[date_candidates].bfill(axis=1).iloc[:, 0]
    else:
        df["RefDate"] = pd.NaT

    today = pd.Timestamp(datetime.today().date())
    df["DaysDiff"] = (today - df["RefDate"]).dt.days
    bins   = [-1, 30, 45, 60, 90, float("inf")]
    labels = ["0–30 Days", "31–45 Days", "46–60 Days", "61–90 Days", ">90 Days"]
    df["AgingBucket"] = pd.cut(df["DaysDiff"], bins=bins, labels=labels)
    return df

def ensure_insurance_column(df):
    insurance_col = next((c for c in ["Insurance", "PayerName", "Insurer", "Plan"] if c in df.columns), None)
    if insurance_col is None:
        df["Insurance"] = "Not Available"
    elif insurance_col != "Insurance":
        df["Insurance"] = df[insurance_col]
    return df

# -------------------- Summary builders --------------------

def build_rcm_summary(df, date_label=""):
    """
    Management-facing RCM Summary sheet with columns:
    Insurance Name | Claim count | Claimed Amount | Remitted Amt |
    Initial pay | Resb1 pay | Resb2 pay | Resb3 pay | Total pay |
    Sub Nt Rmtd | Pending for Resubmission | Rsub Nt Rmtd |
    Rejection Accepted | Final Rejn | Rej. %
    """
    grp = df.groupby("Insurance", dropna=False)

    # Claim count = distinct UniqueIDs per insurance (remove duplicates)
    uid_col = next((c for c in ["UniqueID", "ClaimID", "ActivityID"] if c in df.columns), None)
    if uid_col:
        claim_counts = df.groupby("Insurance", dropna=False)[uid_col].nunique()
    else:
        claim_counts = grp["ActivityIns"].count()

    summary = pd.DataFrame({
        "Insurance Name":                        claim_counts.index,
        "Claim count":                           claim_counts.astype(int).values,
        "Claimed Amount":                        grp["ActivityIns"].sum().values,
        "Remitted Amt":                          grp["RemittedAmt"].sum().values,
        "Initial pay":                           grp["InitialPay"].sum().values,
        "Resb1 pay":                             grp["Resub1Pay"].sum().values,
        "Resb2 pay":                             grp["Resub2Pay"].sum().values,
        "Resb3 pay":                             grp["Resub3Pay"].sum().values,
        "Total pay":                             grp["TotalPay"].sum().values,
        "Sub Nt Rmtd\n(outstanding amount)":    grp["SubNtRmtd"].sum().values,
        "Pending for\nResubmission":            grp["PendingResub"].sum().values,
        "Rsub Nt Rmtd\n(outstanding amount)":   grp["RsubNtRmtd"].sum().values,
        "Rejection Accepted":                    grp["Accepted"].sum().values,
        "Final Rejn":                            grp["Rejection"].sum().values,
    })

    # Sort A→Z by insurance name
    summary = summary.sort_values("Insurance Name").reset_index(drop=True)

    # Rej. % = Final Rejn / Claimed Amount * 100
    summary["Rej. %"] = summary.apply(
        lambda r: (r["Final Rejn"] / r["Claimed Amount"] * 100) if r["Claimed Amount"] != 0 else 0,
        axis=1
    )

    # Grand Total row
    total = {
        "Insurance Name": "Grand Total",
        "Claim count": int(summary["Claim count"].sum()),
        "Claimed Amount": summary["Claimed Amount"].sum(),
        "Remitted Amt": summary["Remitted Amt"].sum(),
        "Initial pay": summary["Initial pay"].sum(),
        "Resb1 pay": summary["Resb1 pay"].sum(),
        "Resb2 pay": summary["Resb2 pay"].sum(),
        "Resb3 pay": summary["Resb3 pay"].sum(),
        "Total pay": summary["Total pay"].sum(),
        "Sub Nt Rmtd\n(outstanding amount)": summary["Sub Nt Rmtd\n(outstanding amount)"].sum(),
        "Pending for\nResubmission": summary["Pending for\nResubmission"].sum(),
        "Rsub Nt Rmtd\n(outstanding amount)": summary["Rsub Nt Rmtd\n(outstanding amount)"].sum(),
        "Rejection Accepted": summary["Rejection Accepted"].sum(),
        "Final Rejn": summary["Final Rejn"].sum(),
        "Rej. %": 0.0,
    }
    tot_claimed = total["Claimed Amount"]
    if tot_claimed:
        total["Rej. %"] = total["Final Rejn"] / tot_claimed * 100

    summary = pd.concat([summary, pd.DataFrame([total])], ignore_index=True)
    return summary, date_label

def build_balance_aging_summary(balance_df):
    labels = ["0–30 Days", "31–45 Days", "46–60 Days", "61–90 Days", ">90 Days"]
    pivot = pd.pivot_table(
        balance_df, index="Insurance", columns="AgingBucket",
        values="Balance", aggfunc="sum", fill_value=0, observed=False,
    ).reindex(columns=labels)
    pivot["Grand Total"] = pivot.sum(axis=1)
    pivot.loc["Grand Total"] = pivot.sum(axis=0)
    pivot.reset_index(inplace=True)
    return pivot

def build_insurance_totals(df):
    agg_cols = ["ActivityIns", "Paid", "Rejection", "Accepted", "Balance",
                "InitialPay", "Resub1Pay", "Resub2Pay", "Resub3Pay",
                "TotalPay", "RemittedAmt", "SubNtRmtd", "PendingResub", "RsubNtRmtd"]
    agg_cols = [c for c in agg_cols if c in df.columns]
    t = (
        df.groupby("Insurance", dropna=False)[agg_cols]
          .sum().reset_index()
          .rename(columns={
              "ActivityIns":  "Net Amount",
              "Rejection":    "Rejected",
              "InitialPay":   "Initial pay",
              "Resub1Pay":    "Resb1 pay",
              "Resub2Pay":    "Resb2 pay",
              "Resub3Pay":    "Resb3 pay",
              "TotalPay":     "Total pay",
              "RemittedAmt":  "Remitted Amt",
              "SubNtRmtd":    "Sub Nt Rmtd",
              "PendingResub": "Pending for Resubmission",
              "RsubNtRmtd":   "Rsub Nt Rmtd",
          })
    )
    uid_col2 = next((c for c in ["UniqueID", "ClaimID", "ActivityID"] if c in df.columns), None)
    if uid_col2:
        counts = df.groupby("Insurance", dropna=False)[uid_col2].nunique().reset_index()
    else:
        counts = df.groupby("Insurance", dropna=False)["ActivityIns"].count().reset_index()
    counts.columns = ["Insurance", "Claim count"]
    t = t.merge(counts, on="Insurance", how="left")
    ordered = ["Insurance", "Claim count", "Net Amount", "Remitted Amt",
               "Initial pay", "Resb1 pay", "Resb2 pay", "Resb3 pay", "Total pay",
               "Sub Nt Rmtd", "Pending for Resubmission", "Rsub Nt Rmtd",
               "Paid", "Balance", "Rejected", "Accepted"]
    t = t[[c for c in ordered if c in t.columns]]
    total = {c: t[c].sum() for c in t.columns if c != "Insurance"}
    total["Insurance"] = "Grand Total"
    return pd.concat([t, pd.DataFrame([total])], ignore_index=True)

def build_monthly_totals(df):
    date_col = next((c for c in ["VisitDate", "SubmissionDate", "ClaimDate"] if c in df.columns), None)
    if date_col is None:
        return pd.DataFrame()
    df = df.copy()
    df[date_col] = pd.to_datetime(df[date_col], errors="coerce", dayfirst=True)
    df = df.dropna(subset=[date_col])
    df["_Month"] = df[date_col].dt.to_period("M")
    m = (
        df.groupby("_Month", observed=True)[["ActivityIns", "Paid", "Rejection", "Accepted", "Balance"]]
          .sum().reset_index()
    )
    m["_Month"] = m["_Month"].dt.strftime("%B %Y")
    m = m.rename(columns={"_Month": "Month", "ActivityIns": "Net Amount", "Rejection": "Rejected"})
    m = m[["Month", "Net Amount", "Paid", "Balance", "Rejected", "Accepted"]]
    total = {c: m[c].sum() for c in m.columns if c != "Month"}
    total["Month"] = "Grand Total"
    return pd.concat([m, pd.DataFrame([total])], ignore_index=True)

def build_monthly_insurance_detail(df):
    date_col = next((c for c in ["VisitDate", "SubmissionDate", "ClaimDate"] if c in df.columns), None)
    if date_col is None:
        return pd.DataFrame()
    df = df.copy()
    df[date_col] = pd.to_datetime(df[date_col], errors="coerce", dayfirst=True)
    df = df.dropna(subset=[date_col])
    df["_Month"] = df[date_col].dt.to_period("M").dt.strftime("%B %Y")
    r = (
        df.groupby(["_Month", "Insurance"], observed=True)[
            ["ActivityIns", "Paid", "Rejection", "Accepted", "Balance"]
        ].sum().reset_index()
         .rename(columns={"_Month": "Month", "ActivityIns": "Net Amount", "Rejection": "Rejected"})
    )
    return r[["Month", "Insurance", "Net Amount", "Paid", "Balance", "Rejected", "Accepted"]]

# -------------------- Styling --------------------
HEADER_FILL   = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")   # dark blue
SUBHDR_FILL   = PatternFill(start_color="2E75B6", end_color="2E75B6", fill_type="solid")   # medium blue
GREEN_FILL    = PatternFill(start_color="375623", end_color="375623", fill_type="solid")   # dark green for pay cols
TOTAL_FILL    = PatternFill(start_color="FCE4D6", end_color="FCE4D6", fill_type="solid")
ALT_FILL      = PatternFill(start_color="EBF3FB", end_color="EBF3FB", fill_type="solid")
OLD_HEADER    = PatternFill(start_color="BDD7EE", end_color="BDD7EE", fill_type="solid")

WHITE_BOLD    = Font(bold=True, color="FFFFFF", name="Arial", size=9)
BLACK_BOLD    = Font(bold=True, name="Arial", size=9)
NORMAL_FONT   = Font(name="Arial", size=9)
RED_FONT      = Font(name="Arial", size=9, color="C00000")

CENTER        = Alignment(horizontal="center", vertical="center", wrap_text=True)
LEFT          = Alignment(horizontal="left",   vertical="center", wrap_text=True)

thin = Side(style="thin", color="BFBFBF")
THIN_BORDER = Border(left=thin, right=thin, top=thin, bottom=thin)

NUM_FMT  = '#,##0.00'
INT_FMT  = '#,##0'
PCT_FMT  = '0.00"%"'


def style_rcm_summary(ws, title_label):
    """Apply full styling to the RCM_Summary sheet."""
    # ---- Title row (row 1) ----
    title_text = f"EMC - RCM SUMMARY{(' - ' + title_label) if title_label else ''}"
    ws.insert_rows(1)
    ws.insert_rows(1)
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=15)
    title_cell = ws.cell(row=1, column=1, value=title_text)
    title_cell.font = Font(bold=True, name="Arial", size=14, color="FFFFFF")
    title_cell.fill = HEADER_FILL
    title_cell.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 30

    # ---- Column header row (now row 3 after insert) ----
    header_row = 3
    # Mark "pay" columns (cols 5-9, E-I = Initial pay through Total pay) with green
    pay_cols = {5, 6, 7, 8, 9}
    for col in range(1, 16):
        cell = ws.cell(row=header_row, column=col)
        cell.font   = WHITE_BOLD
        cell.fill   = GREEN_FILL if col in pay_cols else SUBHDR_FILL
        cell.alignment = CENTER
        cell.border = THIN_BORDER
    ws.row_dimensions[header_row].height = 42

    # ---- Blank separator row 2 ----
    ws.row_dimensions[2].height = 4
    for col in range(1, 16):
        ws.cell(row=2, column=col).fill = HEADER_FILL

    # ---- Data rows ----
    max_row = ws.max_row
    for row in range(header_row + 1, max_row + 1):
        ins_val = ws.cell(row=row, column=1).value
        is_total = str(ins_val) == "Grand Total"
        for col in range(1, 16):
            cell = ws.cell(row=row, column=col)
            cell.border = THIN_BORDER
            if is_total:
                cell.fill = TOTAL_FILL
                cell.font = BLACK_BOLD
                cell.alignment = CENTER if col > 1 else LEFT
            else:
                # Alternating rows
                cell.fill = ALT_FILL if row % 2 == 0 else PatternFill(fill_type=None)
                cell.font = NORMAL_FONT
                cell.alignment = CENTER if col > 1 else LEFT

            # Number formats
            if col == 1:
                cell.alignment = LEFT
            elif col == 2:   # Claim count
                cell.number_format = INT_FMT
            elif col == 15:  # Rej. %
                cell.number_format = '0.00'
                try:
                    _pct = float(cell.value or 0)
                except (ValueError, TypeError):
                    _pct = 0.0
                if not is_total and _pct > 5:
                    cell.font = RED_FONT
            else:
                cell.number_format = NUM_FMT

    # ---- Column widths ----
    col_widths = [38, 10, 14, 13, 11, 10, 10, 10, 11, 14, 14, 14, 14, 12, 8]
    for i, w in enumerate(col_widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w

    ws.freeze_panes = "B4"


def style_headers_generic(ws):
    for c in range(1, ws.max_column + 1):
        cell = ws.cell(row=1, column=c)
        cell.fill = OLD_HEADER
        cell.font = Font(bold=True, name="Arial", size=9)
        cell.alignment = CENTER


def apply_styling(output_file):
    wb = load_workbook(output_file)

    for ws in wb.worksheets:
        if ws.title == "RCM_Summary":
            style_rcm_summary(ws, "")
            continue

        style_headers_generic(ws)

        if ws.title == "Balance_Aging_Summary":
            for r in range(2, ws.max_row + 1):
                if ws.cell(row=r, column=1).value == "Grand Total":
                    for c in range(1, ws.max_column + 1):
                        cell = ws.cell(row=r, column=c)
                        cell.fill = TOTAL_FILL
                        cell.font = Font(bold=True, name="Arial", size=9)
            last_col = ws.max_column
            for r in range(1, ws.max_row + 1):
                ws.cell(row=r, column=last_col).fill = TOTAL_FILL
                ws.cell(row=r, column=last_col).font = Font(bold=True, name="Arial", size=9)

        if ws.title in ("Insurance_Totals", "Monthly_Totals"):
            for r in range(2, ws.max_row + 1):
                if ws.cell(row=r, column=1).value == "Grand Total":
                    for c in range(1, ws.max_column + 1):
                        cell = ws.cell(row=r, column=c)
                        cell.fill = TOTAL_FILL
                        cell.font = Font(bold=True, name="Arial", size=9)

    wb.save(output_file)


# -------------------- main --------------------
def main():
    args = parse_args()
    input_file = os.path.abspath(args.input_xlsx)
    out_file   = os.path.abspath(args.out_xlsx)

    print(f"📂 Input : {input_file}")
    print(f"📄 Output: {out_file}")
    print(f"🔑 SHA1  : {sha1_short(input_file)}")

    df = load_data(input_file)
    df = ensure_numeric(df)
    df = compute_measures(df)
    df = add_aging(df)
    df = ensure_insurance_column(df)

    rcm_summary, date_label = build_rcm_summary(df)
    balance_df              = df.loc[df["Balance"] > 0].copy()
    pivot_summary           = build_balance_aging_summary(balance_df)
    insurance_totals        = build_insurance_totals(df)
    monthly_totals          = build_monthly_totals(df)
    monthly_insurance_detail = build_monthly_insurance_detail(df)

    with pd.ExcelWriter(out_file, engine="openpyxl") as writer:
        # RCM_Summary — write manually so Total pay uses Excel formula
        rcm_summary.to_excel(writer, sheet_name="RCM_Summary", index=False)
        # Patch Total pay (col I = col 9, 1-based) with SUM formula
        # After styling, rows shift by 2 (title + blank), but here we write BEFORE styling
        # so data row 1 = Excel row 2 (header is row 1)
        ws_rcm = writer.sheets["RCM_Summary"]
        n_data = len(rcm_summary)  # includes Grand Total row
        for r in range(2, n_data + 2):  # row 2 .. last data row
            # Col 9 = I = Total pay = SUM(E:H) = InitialPay+Resb1+Resb2+Resb3+TKBK
            ws_rcm.cell(row=r, column=9).value = f"=SUM(E{r}:H{r})"
            # Col 15 = O = Rej. % = Final Rejn / Claimed Amount * 100
            ws_rcm.cell(row=r, column=15).value = f"=IFERROR(N{r}/C{r}*100,0)"
            # Claim count: force integer
            cc = ws_rcm.cell(row=r, column=2).value
            if cc is not None:
                try:
                    ws_rcm.cell(row=r, column=2).value = int(float(cc))
                except Exception:
                    pass
        if WRITE_EXCLUSIVE_SHEET:
            df.to_excel(writer, sheet_name="Exclusive_Report", index=False)
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
        }])
        meta.to_excel(writer, sheet_name="Meta", index=False)

    apply_styling(out_file)
    print("✅ Done.")


if __name__ == "__main__":
    main()
