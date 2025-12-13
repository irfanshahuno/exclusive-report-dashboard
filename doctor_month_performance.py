# doctor_month_performance.py
import argparse
from pathlib import Path
import pandas as pd
import re
import calendar

REQUIRED = ["VisitNo", "VisitDate", "DocName", "Item Group", "ActivityIns"]

def normalize_docname(s):
    if pd.isna(s): return ""
    s = str(s).strip()
    s = re.sub(r"\s+", " ", s)
    return s if s.isupper() else s.title()

def to_month_num(x):
    if pd.isna(x): return 0
    try:
        n = int(str(x).strip())
        return n if 1 <= n <= 12 else 0
    except:
        name = str(x).strip()
        cap = name.capitalize()
        if cap in list(calendar.month_name):
            idx = list(calendar.month_name).index(cap)
            return idx if 1 <= idx <= 12 else 0
        if cap in list(calendar.month_abbr):
            idx = list(calendar.month_abbr).index(cap)
            return idx if 1 <= idx <= 12 else 0
        return 0

def month_abbr_from_num(n: int) -> str:
    return calendar.month_abbr[n] if 1 <= n <= 12 else ""

def load_minimal(src) -> pd.DataFrame:
    # src can be file path OR file-like (UploadedFile/BytesIO)
    xls = pd.ExcelFile(src)
    sheet = "Claim List" if "Claim List" in xls.sheet_names else xls.sheet_names[0]
    try:
        df = pd.read_excel(
            src, sheet_name=sheet,
            usecols=lambda c: str(c).strip() in (REQUIRED + ["Month", "Year"])
        )
    except Exception:
        df = pd.read_excel(src, sheet_name=sheet)
    df.columns = [c.strip() for c in df.columns]
    return df

def ensure_year_month(df: pd.DataFrame) -> pd.DataFrame:
    has_year = "Year" in df.columns
    has_month = "Month" in df.columns
    if has_year:
        df["Year"] = pd.to_numeric(df["Year"], errors="coerce").fillna(0).astype(int)
    if has_month:
        df["MonthNum"] = df["Month"].apply(to_month_num).astype(int)
    if not has_year or not has_month or (df["MonthNum"].eq(0).any()):
        vd = pd.to_datetime(df["VisitDate"], errors="coerce")
        if not has_year:
            df["Year"] = vd.dt.year.fillna(0).astype(int)
        if not has_month:
            df["MonthNum"] = vd.dt.month.fillna(0).astype(int)
        else:
            df.loc[df["MonthNum"].eq(0), "MonthNum"] = vd.dt.month.fillna(0).astype(int)
    df["Month"] = df["MonthNum"].map(month_abbr_from_num)
    return df

def build_report(df: pd.DataFrame) -> pd.DataFrame:
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(f"Missing columns in source: {missing}")
    df["DocName"] = df["DocName"].apply(normalize_docname)
    df["Item Group"] = (
        df["Item Group"].astype(str).str.strip()
        .replace({"nan": "", "NaN": "", "None": ""})
        .where(lambda s: s.ne(""), "Other")
    )
    df["ActivityIns"] = pd.to_numeric(df["ActivityIns"], errors="coerce").fillna(0)
    df = ensure_year_month(df)
    dedup = df.drop_duplicates(
        subset=["VisitNo", "DocName", "Item Group", "Year", "MonthNum", "ActivityIns"]
    )
    visits = (
        dedup.groupby(["DocName", "Year", "MonthNum"])["VisitNo"]
        .nunique().rename("Visits")
    )
    amount = dedup.pivot_table(
        index=["DocName", "Year", "MonthNum"],
        columns="Item Group",
        values="ActivityIns",
        aggfunc="sum",
        fill_value=0.0,
    )
    expected = ["Consultation", "Medicines", "Procedure"]
    for g in expected:
        if g not in amount.columns:
            amount[g] = 0.0
    extras = [c for c in amount.columns if c not in expected]
    if extras:
        amount["Other"] = amount[extras].sum(axis=1)
        amount = amount.drop(columns=[c for c in extras if c != "Other"])
    ordered_vals = ["Consultation", "Medicines", "Procedure"] + (["Other"] if "Other" in amount.columns else [])
    amount = amount.reindex(columns=ordered_vals)
    table = amount.merge(visits, left_index=True, right_index=True, how="left").reset_index()
    table["Month"] = table["MonthNum"].map(month_abbr_from_num)
    table["Row_Total"] = table[ordered_vals].sum(axis=1)
    table["Avg_per_Visit"] = (table["Row_Total"] / table["Visits"]).where(table["Visits"] > 0, 0).round(0).astype(int)
    table = table.sort_values(["DocName", "Year", "MonthNum"]).reset_index(drop=True)
    blocks = []
    for doc, block in table.groupby("DocName", sort=False):
        total = {
            "DocName": doc, "Year": 0, "MonthNum": 0, "Month": "TOTAL",
            "Visits": block["Visits"].sum(), "Row_Total": block["Row_Total"].sum()
        }
        for c in ordered_vals: total[c] = block[c].sum()
        total["Avg_per_Visit"] = int(round(total["Row_Total"] / total["Visits"])) if total["Visits"] > 0 else 0
        block = block[["DocName","Year","MonthNum","Month","Visits"] + ordered_vals + ["Row_Total","Avg_per_Visit"]]
        blocks.append(pd.concat([block, pd.DataFrame([total])[block.columns]], ignore_index=True))
    final = pd.concat(blocks, ignore_index=True).rename(columns={"DocName": "Doctor"})
    return final[["Doctor","Year","MonthNum","Month","Visits"] + ordered_vals + ["Row_Total","Avg_per_Visit"]]
