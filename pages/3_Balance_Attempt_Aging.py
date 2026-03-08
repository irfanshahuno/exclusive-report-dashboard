#!/usr/bin/env python3
import io
import re
from pathlib import Path
from datetime import datetime as dt

import pandas as pd
import streamlit as st

# ✅ NEEDFUL (S3 fallback)
import boto3
from botocore.exceptions import ClientError

# =========================================================
# ✅ NEEDFUL: View password gate that respects main dashboard session
# =========================================================
VIEW_PASSWORD = st.secrets.get("VIEW_PASSWORD", "Emc@2026")


def require_view_access_balance():
    if st.session_state.get("is_view_auth", False):
        return

    st.set_page_config(page_title="Balance — Access", layout="wide")
    st.set_option("client.showErrorDetails", False)

    st.title("🔒 Dashboard Access")
    st.info("Enter the view password to open the balance page.")

    pwd = st.text_input("View Password", type="password", key="balance_view_pwd")
    if st.button("Enter", use_container_width=True, key="balance_view_btn"):
        if pwd == VIEW_PASSWORD:
            st.session_state.is_view_auth = True
            st.rerun()
        else:
            st.error("Incorrect password.")

    st.stop()


require_view_access_balance()

# =========================================================
# Settings
# =========================================================
st.set_page_config(page_title="Balance — Initial / Resub with Aging", layout="wide")
st.title("Balance — Initial / Resub with Aging (Summary)")

THIS_FILE = Path(__file__).resolve()
BASE = THIS_FILE.parents[1] if THIS_FILE.parent.name == "pages" else THIS_FILE.parent

DATA_DIR = BASE / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

YEARS = [2024, 2025, 2026]

CENTERS = {
    "easyhealth": "Easy Health Medical Clinic (MF8031)",
    "excellent": "Excellent Medical Center (MF4777)",
    "pharmacy": "Excellent Pharmacy (PF3205)",
}

AGING_ORDER = ["0–30 Days", "31–45 Days", "46–60 Days", "61–90 Days", "91–120 Days", ">120 Days"]
SOLD_TO_KLAIM_KEYWORDS_DEFAULT = ["NextCare", "Sukoon", "Almadallah", "Daman", "FMC"]
SOLD_TO_KLAIM_KEYWORDS_PHARMACY = ["ALMADALLAH-AD", "Daman"]
GT_PAT = re.compile(r"^\s*(grand\s*total|total)\s*$", re.I)

# =========================================================
# UI
# =========================================================
st.markdown(
    """
<style>
.stApp{ background: linear-gradient(180deg, #F7FAFF 0%, #FFFFFF 45%) !important; }
hr{ border: none !important; height:1px !important; background:#E6EEF8 !important; }

div.stButton > button{
  width: 100% !important;
  min-height: 52px !important;
  padding: 12px 18px !important;
  font-size: 16px !important;
  font-weight: 800 !important;
  background: #EEF6FF !important;
  color: #0B2D5C !important;
  border: 1.8px solid #B6D4FF !important;
  border-radius: 14px !important;
  box-shadow: 0 3px 10px rgba(11, 45, 92, 0.10) !important;
}
div.stButton > button:hover{
  background: #DCEBFF !important;
  border-color: #6FA4FF !important;
}

.center-title{ color:#0B2D5C !important; font-weight: 900 !important; margin-bottom: 0.15rem !important; }
.kpi-grid{ display:grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 14px; margin-top: 10px; margin-bottom: 10px; }
.kpi-card{
  background: rgba(255,255,255,0.96);
  border: 1.4px solid #E3ECFA;
  border-radius: 16px;
  padding: 14px 16px;
  box-shadow: 0 8px 18px rgba(11,45,92,0.06);
  min-width: 0;
}
.kpi-label{ font-size: 13px; color: #64748B; font-weight: 750; margin-bottom: 6px; }
.kpi-value{
  font-size: clamp(16px, 2.0vw, 28px);
  font-weight: 900;
  color: #111827;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.kpi-card.current{ background: linear-gradient(180deg, #F1F7FF 0%, #FFFFFF 100%); border-color: #CFE3FF; }
.kpi-card.current .kpi-value{ color:#0B2D5C; }

.sub-section-title{
  font-size: 13px; font-weight: 800; color: #64748B; letter-spacing: 0.6px;
  text-transform: uppercase; margin: 18px 0 8px 2px;
}
.sub-grid{ display: grid; grid-template-columns: repeat(auto-fill, minmax(170px, 1fr)); gap: 10px; margin-bottom: 10px; }
.sub-card{
  background: #FAFCFF; border: 1.3px solid #E3ECFA; border-radius: 13px; padding: 11px 14px;
  box-shadow: 0 4px 12px rgba(11,45,92,0.05); min-width: 0;
}
.sub-card.initial{ border-left: 4px solid #3B82F6; }
.sub-card.resub{ border-left: 4px solid #8B5CF6; }
.sub-card.approved{ border-left: 4px solid #10B981; }
.sub-card.rejected{ border-left: 4px solid #EF4444; }
.sub-card.other{ border-left: 4px solid #F59E0B; }
.sub-card.total{ border-left: 4px solid #0B2D5C; background: linear-gradient(135deg, #EEF6FF 0%, #F8FBFF 100%); border: 1.5px solid #CFE3FF; }
.sub-card.total .sub-label{ color: #0B2D5C; font-weight: 800; }
.sub-card.total .sub-value{ color: #0B2D5C; }
.sub-label{ font-size: 11.5px; color: #64748B; font-weight: 700; margin-bottom: 5px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.sub-value{ font-size: clamp(14px, 1.6vw, 22px); font-weight: 900; color: #111827; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

.meta-chip-wrap{ display:flex; flex-wrap:wrap; gap:8px; margin: 6px 0 14px 0; }
.meta-chip{ background:#F5F9FF; border:1px solid #D8E7FF; border-radius:999px; padding:6px 10px; font-size:12px; color:#49627D; font-weight:700; }
.split-stat{ background:#fff; border:1px solid #E5EDF8; border-radius:12px; padding:10px 12px; }
.split-title{ font-size:12px; color:#64748B; font-weight:800; text-transform:uppercase; letter-spacing:0.4px; }
.split-val{ font-size:24px; color:#0B2D5C; font-weight:900; margin-top:4px; }

@media (max-width: 1100px){
  .kpi-grid{ grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .sub-grid{ grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
</style>
""",
    unsafe_allow_html=True,
)


def fmt2(x):
    try:
        return f"{float(x):,.2f}"
    except Exception:
        return "—"


def render_balance_kpi_cards(total_balance, sold_to_klaim_balance, current_balance, sold_over60, current_over60):
    html = f"""
    <div class="kpi-grid">
      <div class="kpi-card"><div class="kpi-label">Total Balance</div><div class="kpi-value">{fmt2(total_balance)}</div></div>
      <div class="kpi-card"><div class="kpi-label">Insurance Balance Sold to Klaim</div><div class="kpi-value">{fmt2(sold_to_klaim_balance)}</div></div>
      <div class="kpi-card current"><div class="kpi-label">Current Balance (Total - Sold)</div><div class="kpi-value">{fmt2(current_balance)}</div></div>
      <div class="kpi-card"><div class="kpi-label">Sold to Klaim &gt;60 Days</div><div class="kpi-value">{fmt2(sold_over60)}</div></div>
      <div class="kpi-card"><div class="kpi-label">Current &gt;60 Days</div><div class="kpi-value">{fmt2(current_over60)}</div></div>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)


def render_meta_chips(center_key: str, year: int, built: str, keywords_used: list[str]):
    chips = [
        f'<span class="meta-chip">Center: {CENTERS.get(center_key, center_key)}</span>',
        f'<span class="meta-chip">Year: {year}</span>',
        f'<span class="meta-chip">Built: {built}</span>',
        f'<span class="meta-chip">Klaim Sold Keywords: {", ".join(keywords_used)}</span>',
    ]
    st.markdown(f'<div class="meta-chip-wrap">{"".join(chips)}</div>', unsafe_allow_html=True)


# =========================================================
# Breakdown helpers
# =========================================================
def _classify_status(raw: str) -> tuple[str, str]:
    s = str(raw).strip()
    sl = s.lower()
    m = re.search(r"resub[-\s]*(\d+)", sl)
    if m:
        n = int(m.group(1))
        suffix = {1: "1st", 2: "2nd", 3: "3rd"}.get(n, f"{n}th")
        return (f"{suffix} Resubmission", "resub")
    if "approved" in sl:
        return ("Approved", "approved")
    if any(x in sl for x in ["reject", "denial", "denied"]):
        return ("Rejected / Denied", "rejected")
    if "submit" in sl:
        return ("Initial Submission", "initial")
    label = s if s not in ("", "nan", "None") else "Unknown"
    return (label, "other")


def compute_submission_breakdown(df: pd.DataFrame) -> list[dict]:
    if "Status" not in df.columns:
        return []
    dfc = df.copy()
    dfc["Status"] = dfc["Status"].replace("", pd.NA).ffill()
    dfc = dfc[dfc["Balance"] > 0].copy()
    if dfc.empty:
        return []
    dfc[["_label", "_class"]] = pd.DataFrame(dfc["Status"].apply(_classify_status).tolist(), index=dfc.index)
    grouped = (
        dfc.groupby(["_label", "_class"], sort=False)["Balance"]
        .sum()
        .reset_index()
        .rename(columns={"Balance": "total"})
    )
    order = ["Initial Submission", "1st Resubmission", "2nd Resubmission", "3rd Resubmission", "Approved", "Rejected / Denied"]
    grouped["_order"] = grouped["_label"].apply(lambda x: order.index(x) if x in order else 99)
    grouped = grouped.sort_values("_order")
    return [{"label": r["_label"], "css_class": r["_class"], "balance": float(r["total"])} for _, r in grouped.iterrows()]


def render_submission_breakdown(breakdown: list[dict], total_balance: float = 0.0):
    if not breakdown:
        return
    grand_total = total_balance if total_balance > 0 else sum(b["balance"] for b in breakdown)
    cards_html = "".join(
        f'''<div class="sub-card {b["css_class"]}"><div class="sub-label">{b["label"]}</div><div class="sub-value">{fmt2(b["balance"])}<\/div><\/div>'''
        for b in breakdown
    )
    total_card = f'''<div class="sub-card total"><div class="sub-label">Total Balance</div><div class="sub-value">{fmt2(grand_total)}<\/div><\/div>'''
    st.markdown(f'<div class="sub-section-title">Balance by Submission Attempt</div><div class="sub-grid">{cards_html}{total_card}</div>', unsafe_allow_html=True)


# =========================================================
# Stage section
# =========================================================
STAGE_DEFINITIONS = [
    {"label": "Initial Submission",  "css": "initial"},
    {"label": "1st Resubmission",    "css": "resub1"},
    {"label": "2nd Resubmission",    "css": "resub2"},
    {"label": "3rd Resubmission",    "css": "resub3"},
    {"label": "Approved",            "css": "approved"},
    {"label": "Rejected / Denied",   "css": "rejected"},
]

STAGE_COLORS = {
    "initial":  "#3B82F6",
    "resub1":   "#8B5CF6",
    "resub2":   "#7C3AED",
    "resub3":   "#6D28D9",
    "approved": "#10B981",
    "rejected": "#EF4444",
}


def _stage_key(status: str) -> str:
    s = str(status).lower().strip()
    m = re.search(r"resub[-\s]*(\d+)", s)
    if m:
        n = int(m.group(1))
        return {1: "resub1", 2: "resub2", 3: "resub3"}.get(n, f"resub{n}")
    if "approved" in s:
        return "approved"
    if any(x in s for x in ["reject", "denial", "denied"]):
        return "rejected"
    if "submit" in s:
        return "initial"
    return "initial"


def _make_pivot(dfc: pd.DataFrame):
    if dfc.empty:
        return None
    pivot = dfc.pivot_table(index="Insurance", columns="AgingBucket", values="Balance", aggfunc="sum", fill_value=0)
    ordered_cols = [c for c in AGING_ORDER if c in pivot.columns]
    if "Unknown" in pivot.columns:
        pivot = pivot.rename(columns={"Unknown": "No Date"})
        ordered_cols = ordered_cols + ["No Date"]
    pivot = pivot[[c for c in ordered_cols if c in pivot.columns]]
    pivot["Total"] = pivot.sum(axis=1)
    pivot = pivot.sort_values("Total", ascending=False)
    grand = pivot.sum(numeric_only=True).rename("Grand Total")
    pivot = pd.concat([pivot, grand.to_frame().T])
    return pivot


def _make_aging_summary(dfc: pd.DataFrame):
    if dfc.empty:
        return None
    existing_known = [c for c in AGING_ORDER if c in dfc["AgingBucket"].unique()]
    has_unknown = "Unknown" in dfc["AgingBucket"].unique()
    all_buckets = existing_known + (["Unknown"] if has_unknown else [])
    summary = (
        dfc.groupby("AgingBucket")["Balance"]
        .sum()
        .reindex(all_buckets)
        .fillna(0)
        .reset_index()
    )
    summary["AgingBucket"] = summary["AgingBucket"].replace("Unknown", "No Date")
    total = summary["Balance"].sum()
    summary["% of Total"] = (summary["Balance"] / total * 100).round(1) if total > 0 else 0.0
    summary["Balance"] = summary["Balance"].round(2)
    grand = pd.DataFrame([{"AgingBucket": "Grand Total", "Balance": round(total, 2), "% of Total": 100.0 if total > 0 else 0.0}])
    return pd.concat([summary, grand], ignore_index=True)


def _df_to_csv_bytes(df: pd.DataFrame) -> bytes:
    out = io.StringIO()
    df.to_csv(out, index=False)
    return out.getvalue().encode("utf-8-sig")


def _df_to_excel_bytes(dfs: dict[str, pd.DataFrame]) -> bytes:
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        for sheet, df in dfs.items():
            df.to_excel(writer, index=False, sheet_name=sheet[:31])
    buffer.seek(0)
    return buffer.getvalue()


def compute_stages(df: pd.DataFrame, sold_keywords: list[str]) -> list[dict]:
    if "Insurance" not in df.columns or "AgingBucket" not in df.columns:
        return []
    status_filled = df["Status"].replace("", pd.NA).ffill() if "Status" in df.columns else pd.Series("initial", index=df.index)
    df = df.copy()
    df["_stage_key"] = status_filled.apply(_stage_key)
    df["_is_sold"] = sold_to_klaim_mask(df["Insurance"], sold_keywords)
    base = df[df["Balance"] > 0][["Insurance", "AgingBucket", "Balance", "_stage_key", "_is_sold"]].copy()
    base["Balance"] = pd.to_numeric(base["Balance"], errors="coerce").fillna(0)

    stages_out = []
    for stage_def in STAGE_DEFINITIONS:
        css = stage_def["css"]
        subset = base[base["_stage_key"] == css].copy()
        if subset.empty:
            continue

        current_subset = subset[~subset["_is_sold"]][["Insurance", "AgingBucket", "Balance"]].copy()
        sold_subset = subset[subset["_is_sold"]][["Insurance", "AgingBucket", "Balance"]].copy()
        all_subset = subset[["Insurance", "AgingBucket", "Balance"]].copy()

        stage_total = float(all_subset["Balance"].sum())
        current_total = float(current_subset["Balance"].sum())
        sold_total = float(sold_subset["Balance"].sum())

        stages_out.append({
            "label": stage_def["label"],
            "css": css,
            "total": stage_total,
            "current_total": current_total,
            "sold_total": sold_total,
            "all_pivot": _make_pivot(all_subset),
            "all_summary": _make_aging_summary(all_subset),
            "current_pivot": _make_pivot(current_subset),
            "current_summary": _make_aging_summary(current_subset),
            "sold_pivot": _make_pivot(sold_subset),
            "sold_summary": _make_aging_summary(sold_subset),
        })
    return stages_out


def _blue_cell(val: float, max_val: float) -> str:
    if max_val <= 0 or val <= 0:
        return ""
    intensity = min(val / max_val, 1.0)
    r = int(238 - intensity * (238 - 59))
    g = int(246 - intensity * (246 - 130))
    b = int(255 - intensity * (255 - 246))
    text = "#0B2D5C" if intensity > 0.55 else "#1e3a5f"
    return f"background-color: rgb({r},{g},{b}); color: {text};"


def _style_insurance_aging(pivot: pd.DataFrame):
    fmt_dict = {c: "{:,.2f}" for c in pivot.columns}
    data_cols = [c for c in pivot.columns if c != "Total"]
    data_rows = [r for r in pivot.index if r != "Grand Total"]
    max_val = float(pivot.loc[data_rows, data_cols].max().max()) if data_rows and data_cols else 1.0

    def style_cells(df):
        styles = pd.DataFrame("", index=df.index, columns=df.columns)
        for row in df.index:
            for col in df.columns:
                if row == "Grand Total":
                    styles.loc[row, col] = "background-color: #EEF6FF; font-weight: 900; color: #0B2D5C;"
                elif col == "Total":
                    styles.loc[row, col] = "font-weight: 800; color: #0B2D5C;"
                elif col in data_cols:
                    try:
                        styles.loc[row, col] = _blue_cell(float(df.loc[row, col]), max_val)
                    except Exception:
                        pass
        return styles

    return (
        pivot.style
        .format(fmt_dict)
        .apply(style_cells, axis=None)
        .set_properties(**{"font-size": "13px", "text-align": "right", "padding": "6px 12px"})
        .set_table_styles([
            {"selector": "th", "props": [("background-color", "#F1F7FF"), ("color", "#0B2D5C"), ("font-weight", "800"), ("font-size", "12px"), ("text-align", "center"), ("padding", "8px 12px"), ("border-bottom", "2px solid #CFE3FF")]},
            {"selector": "th.row_heading", "props": [("text-align", "left"), ("min-width", "160px"), ("font-weight", "700")]},
            {"selector": "td", "props": [("border-bottom", "1px solid #F0F4FA")]},
            {"selector": "table", "props": [("border-collapse", "collapse"), ("width", "100%")]},
        ])
    )


def _style_aging_summary(df: pd.DataFrame, accent_color: str):
    max_bal = float(df.loc[df["AgingBucket"] != "Grand Total", "Balance"].max()) if not df.empty else 1.0
    hex_col = accent_color.lstrip("#")
    r0, g0, b0 = tuple(int(hex_col[i:i+2], 16) for i in (0, 2, 4))

    def tint(intensity):
        ri = int((1 - intensity * 0.65) * 255)
        gi = int((1 - intensity * 0.65) * 255)
        bi = int((1 - intensity * 0.65) * 255)
        ri = int(ri + intensity * 0.65 * r0)
        gi = int(gi + intensity * 0.65 * g0)
        bi = int(bi + intensity * 0.65 * b0)
        text = "#0B2D5C" if intensity > 0.55 else "#1e3a5f"
        return f"background-color: rgb({ri},{gi},{bi}); color: {text};"

    def cell_style(df2):
        styles = pd.DataFrame("", index=df2.index, columns=df2.columns)
        for i in df2.index:
            if df2.loc[i, "AgingBucket"] == "Grand Total":
                styles.loc[i, :] = "background-color: #EEF6FF; font-weight: 900; color: #0B2D5C;"
            else:
                try:
                    bal = float(df2.loc[i, "Balance"])
                    intensity = min(bal / max_bal, 1.0) if max_bal > 0 else 0
                    styles.loc[i, "Balance"] = tint(intensity)
                except Exception:
                    pass
        return styles

    return (
        df.style
        .format({"Balance": "{:,.2f}", "% of Total": "{:.1f}%"})
        .apply(cell_style, axis=None)
        .set_properties(**{"font-size": "13px", "padding": "6px 10px"})
        .set_table_styles([
            {"selector": "th", "props": [("background-color", "#F1F7FF"), ("color", "#0B2D5C"), ("font-weight", "800"), ("font-size", "12px"), ("padding", "8px 10px"), ("border-bottom", "2px solid #CFE3FF")]},
            {"selector": "td", "props": [("border-bottom", "1px solid #F0F4FA")]},
        ])
        .hide(axis="index")
    )


def _pivot_to_download_df(pivot: pd.DataFrame | None) -> pd.DataFrame:
    if pivot is None:
        return pd.DataFrame()
    out = pivot.reset_index().rename(columns={"index": "Insurance"})
    return out


def render_stage_downloads(stage: dict, stage_slug: str):
    all_pivot_df = _pivot_to_download_df(stage["all_pivot"])
    current_pivot_df = _pivot_to_download_df(stage["current_pivot"])
    sold_pivot_df = _pivot_to_download_df(stage["sold_pivot"])
    all_summary_df = stage["all_summary"] if stage["all_summary"] is not None else pd.DataFrame()
    current_summary_df = stage["current_summary"] if stage["current_summary"] is not None else pd.DataFrame()
    sold_summary_df = stage["sold_summary"] if stage["sold_summary"] is not None else pd.DataFrame()

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.download_button(
            "CSV — All",
            data=_df_to_csv_bytes(all_pivot_df),
            file_name=f"{stage_slug}_all_insurance_aging.csv",
            mime="text/csv",
            use_container_width=True,
            key=f"csv_all_{stage_slug}",
        )
    with c2:
        st.download_button(
            "CSV — Current",
            data=_df_to_csv_bytes(current_pivot_df),
            file_name=f"{stage_slug}_current_insurance_aging.csv",
            mime="text/csv",
            use_container_width=True,
            key=f"csv_current_{stage_slug}",
        )
    with c3:
        st.download_button(
            "CSV — Klaim Sold",
            data=_df_to_csv_bytes(sold_pivot_df),
            file_name=f"{stage_slug}_klaim_sold_insurance_aging.csv",
            mime="text/csv",
            use_container_width=True,
            key=f"csv_sold_{stage_slug}",
        )
    with c4:
        st.download_button(
            "Excel — Full Stage",
            data=_df_to_excel_bytes({
                "All Insurance Aging": all_pivot_df,
                "All Aging Summary": all_summary_df,
                "Current Insurance Aging": current_pivot_df,
                "Current Aging Summary": current_summary_df,
                "Klaim Sold Insurance Aging": sold_pivot_df,
                "Klaim Sold Aging Summary": sold_summary_df,
            }),
            file_name=f"{stage_slug}_full_stage_breakdown.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
            key=f"xlsx_stage_{stage_slug}",
        )


def render_pivot_and_summary(title_prefix: str, pivot, summary, color: str):
    st.markdown(f"**{title_prefix} — Insurance × Aging Bucket**")
    if pivot is None:
        st.info("No data.")
        return
    col1, col2 = st.columns([3, 1], gap="large")
    with col1:
        st.dataframe(_style_insurance_aging(pivot), use_container_width=True, height=min(40 + 38 * len(pivot), 520))
    with col2:
        st.markdown("**Aging Summary**")
        if summary is not None:
            st.dataframe(_style_aging_summary(summary, color), use_container_width=True, height=min(60 + 38 * len(summary), 400))
        else:
            st.info("No data.")


def render_stages_section(stages: list[dict], canonical_total: float = 0.0):
    if not stages:
        return

    st.markdown('<div class="sub-section-title">Aging Breakdown by Submission Stage</div>', unsafe_allow_html=True)
    grand_total = canonical_total if canonical_total > 0 else sum(s["total"] for s in stages)

    for stage in stages:
        label = stage["label"]
        css = stage["css"]
        total = stage["total"]
        color = STAGE_COLORS.get(css, "#3B82F6")
        pct = (total / grand_total * 100) if grand_total > 0 else 0
        stage_slug = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")

        with st.expander(f"{label} — {fmt2(total)}", expanded=(css == "initial")):
            st.markdown(
                f'<span style="border-left:4px solid {color}; padding-left:10px; font-weight:800; color:#0B2D5C;">{label}</span> '
                f'<span style="color:#64748B; font-size:13px; margin-left:10px;">Total: <strong style="color:{color};">{fmt2(total)}</strong>'
                f'<span style="margin-left:8px; color:#94A3B8;">({pct:.1f}% of all)</span></span>',
                unsafe_allow_html=True,
            )
            st.markdown("")

            c1, c2, c3 = st.columns(3)
            c1.markdown(f'<div class="split-stat"><div class="split-title">Total</div><div class="split-val">{fmt2(stage["total"])}<\/div><\/div>', unsafe_allow_html=True)
            c2.markdown(f'<div class="split-stat"><div class="split-title">Current</div><div class="split-val">{fmt2(stage["current_total"])}<\/div><\/div>', unsafe_allow_html=True)
            c3.markdown(f'<div class="split-stat"><div class="split-title">Klaim Sold</div><div class="split-val">{fmt2(stage["sold_total"])}<\/div><\/div>', unsafe_allow_html=True)
            st.markdown("")

            tabs = st.tabs(["All", "Current Only", "Klaim Sold Only"])
            with tabs[0]:
                render_pivot_and_summary("All", stage["all_pivot"], stage["all_summary"], color)
            with tabs[1]:
                render_pivot_and_summary("Current", stage["current_pivot"], stage["current_summary"], color)
            with tabs[2]:
                render_pivot_and_summary("Klaim Sold", stage["sold_pivot"], stage["sold_summary"], color)

            st.markdown("")
            render_stage_downloads(stage, stage_slug)


# =========================================================
# Helpers (generic medical-center logic)
# =========================================================
INSURANCE_COLS = ["Insurance", "PayerName", "Insurer", "Plan"]
NET_COLS = ["ActivityIns", "Net Amount", "NetAmount"]
PAID_COLS = ["actRemitInsShare", "actResub1RemitInsShare", "actResub2RemitInsShare", "actResub3RemitInsShare", "TKBKAmountAct"]
ACTIVITY_STATUS_COLS = ["ActivityStatus"]
DENIAL_COLS = ["DenialCode", "Denial Code"]
DATE_COLS = ["SubmissionDate", "ClaimDate", "VisitDate", "ServiceDate", "InvoiceDate", "EncounterDate"]
RESUB_DATE_COLS = {0: "SubDate", 1: "Resub1Date", 2: "Resub2Date", 3: "Resub3Date"}
SUBDATE_COL = "SubDate"


def pick(df, candidates):
    for c in candidates:
        if c in df.columns:
            return c
    return None


def ensure_insurance(df):
    c = pick(df, INSURANCE_COLS)
    if c is None:
        df["Insurance"] = "Not Available"
    elif c != "Insurance":
        df["Insurance"] = df[c]
    df["Insurance"] = df["Insurance"].fillna("Not Available").astype(str)
    return df


def ensure_numeric(df):
    net = pick(df, NET_COLS) or "ActivityIns"
    if net not in df.columns:
        df[net] = 0
    df[net] = pd.to_numeric(df[net], errors="coerce").fillna(0)
    present_paid = [c for c in PAID_COLS if c in df.columns]
    for c in present_paid:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
    return df, net, present_paid


def compute_measures(df, net_col, paid_cols):
    df["Paid"] = df[paid_cols].sum(axis=1) if paid_cols else 0.0
    df["Rejected"] = 0.0
    df["Balance"] = 0.0
    df["Accepted"] = 0.0

    act_status = pick(df, ACTIVITY_STATUS_COLS)
    denial = pick(df, DENIAL_COLS)

    if act_status and denial:
        s = df[act_status].astype(str).str.lower().str.strip()
        denial_ok = df[denial].notna() & (df[denial].astype(str).str.strip() != "")
        paid_mask = df["Paid"] > 0
        reject_mask = (df["Paid"] == 0) & (s == "rejected") & denial_ok
        balance_mask = (df["Paid"] == 0) & (~reject_mask)
        df.loc[paid_mask, "Accepted"] = (df.loc[paid_mask, net_col] - df.loc[paid_mask, "Paid"]).clip(lower=0)
        df.loc[reject_mask, "Rejected"] = df.loc[reject_mask, net_col]
        df.loc[balance_mask, "Balance"] = df.loc[balance_mask, net_col]
    else:
        paid_mask = df["Paid"] > 0
        df.loc[paid_mask, "Accepted"] = (df.loc[paid_mask, net_col] - df.loc[paid_mask, "Paid"]).clip(lower=0)
        df.loc[df["Paid"] == 0, "Balance"] = df.loc[df["Paid"] == 0, net_col]
    return df


def _resub_number_from_status(status: str):
    m = re.search(r"resub[-\s]*(\d+)", str(status).lower())
    return int(m.group(1)) if m else None


def add_aging(df: pd.DataFrame) -> pd.DataFrame:
    today = pd.Timestamp(dt.today().date())
    bins = [-1, 30, 45, 60, 90, 120, float("inf")]
    labels = ["0–30 Days", "31–45 Days", "46–60 Days", "61–90 Days", "91–120 Days", ">120 Days"]
    has_smart = any(c in df.columns for c in RESUB_DATE_COLS.values())

    if not has_smart:
        existing = [c for c in DATE_COLS if c in df.columns]
        for c in existing:
            df[c] = pd.to_datetime(df[c], errors="coerce", dayfirst=True)
        df["RefDate"] = df[existing].bfill(axis=1).iloc[:, 0] if existing else pd.NaT
        df["DaysDiff"] = (today - df["RefDate"]).dt.days
        df["AgingBucket"] = pd.cut(df["DaysDiff"], bins=bins, labels=labels)
        df["AgingBucket"] = df["AgingBucket"].astype(str).replace("nan", "Unknown")
        return df

    for _, col in RESUB_DATE_COLS.items():
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce", dayfirst=True)

    status_filled = df["Status"].replace("", pd.NA).ffill() if "Status" in df.columns else pd.Series("", index=df.index)

    def _pick_date(idx):
        s = str(status_filled.iloc[idx])
        resub_n = _resub_number_from_status(s)
        col = RESUB_DATE_COLS.get(resub_n, SUBDATE_COL) if resub_n is not None else SUBDATE_COL
        if col in df.columns:
            return df[col].iloc[idx]
        for fallback_col in RESUB_DATE_COLS.values():
            if fallback_col in df.columns:
                v = df[fallback_col].iloc[idx]
                if pd.notna(v):
                    return v
        return pd.NaT

    df["RefDate"] = pd.to_datetime([_pick_date(i) for i in range(len(df))], errors="coerce")
    df["DaysDiff"] = (today - df["RefDate"]).dt.days
    df["AgingBucket"] = pd.cut(df["DaysDiff"], bins=bins, labels=labels)
    df["AgingBucket"] = df["AgingBucket"].astype(str).replace("nan", "Unknown")
    return df


def sold_to_klaim_mask(series: pd.Series, keywords) -> pd.Series:
    s = series.fillna("").astype(str).str.lower()
    kws = [k.lower() for k in keywords if str(k).strip()]
    if not kws:
        return pd.Series([False] * len(series), index=series.index)
    pat = "|".join(re.escape(k) for k in kws)
    return s.str.contains(pat, regex=True)


def is_over_60_bucket(bucket_series: pd.Series) -> pd.Series:
    b = bucket_series.fillna("").astype(str)
    return b.isin(["61–90 Days", "91–120 Days", ">120 Days"])


# =========================================================
# Pharmacy logic
# =========================================================
def ci_get(df, names):
    lower_map = {str(c).strip().lower(): c for c in df.columns}
    for n in names:
        k = str(n).strip().lower()
        if k in lower_map:
            return lower_map[k]
    return None


def compute_pharmacy_balance(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    col_net = ci_get(df, ["Claim Amount", "Claim Amount (Net)", "NetAmount", "Net Amount", "TotalAmount", "Total Amount", "Net"])
    col_paid = ci_get(df, ["Remitted Amount", "Remitted Amount (Paid)", "Paid", "Remit Amount", "RemitAmount"])
    col_stat = ci_get(df, ["ClaimStatus", "Status", "ResponseType"])
    col_payer = ci_get(df, ["Insurance", "PayerName", "Insurer", "Plan", "InsurancePlan"])
    col_date = ci_get(df, ["ClaimDate", "RxDate", "DispenseDate", "SubmissionDate", "VisitDate", "DOS", "DateOfService"])

    if not col_net or not col_paid or not col_stat:
        df = ensure_insurance(df)
        df, net_col, paid_cols = ensure_numeric(df)
        df = compute_measures(df, net_col, paid_cols)
        return df

    if not col_payer:
        col_payer = "Insurance"
        df[col_payer] = "Not Available"
    if not col_date:
        col_date = "ClaimDate"
        df[col_date] = pd.NaT

    df[col_net] = pd.to_numeric(df[col_net], errors="coerce").fillna(0.0).clip(lower=0)
    df[col_paid] = pd.to_numeric(df[col_paid], errors="coerce").fillna(0.0).clip(lower=0)
    df[col_date] = pd.to_datetime(df[col_date], errors="coerce", dayfirst=True)

    lower_status = df[col_stat].astype(str).str.lower().str.strip()
    net = df[col_net]
    paid = df[col_paid]
    diff = (net - paid).clip(lower=0)

    df["Insurance"] = df[col_payer].fillna("Not Available").astype(str)
    df["Rejected"] = 0.0
    df["Accepted"] = 0.0
    df["Balance"] = 0.0
    df["Paid"] = paid

    mask_denied = lower_status.isin(["denied", "rejected"])
    df.loc[mask_denied, "Rejected"] = net
    df.loc[mask_denied, ["Accepted", "Balance"]] = 0.0
    tiny_threshold = 4.0
    mask_paid = paid > 0
    mask_tiny = diff <= tiny_threshold
    mask_acc = (~mask_denied) & mask_paid & mask_tiny
    df.loc[mask_acc, "Accepted"] = diff
    df.loc[mask_acc, "Balance"] = 0.0
    mask_bal = (~mask_denied) & (diff > tiny_threshold)
    df.loc[mask_bal, "Balance"] = diff
    df["RefDate"] = df[col_date]
    return df


# =========================================================
# Admin mode
# =========================================================
def is_admin_mode() -> bool:
    secret_pwd = st.secrets.get("ADMIN_PASSWORD", "")
    if secret_pwd:
        if st.session_state.get("is_admin", False):
            return True
        with st.popover("🔒 Admin login"):
            pwd = st.text_input("Password", type="password", key="admin_pwd")
            if st.button("Login", key="admin_login_btn"):
                if pwd == secret_pwd:
                    st.session_state.is_admin = True
                    st.rerun()
                else:
                    st.error("Wrong password")
        return False
    return st.toggle("Admin mode", value=st.session_state.get("is_admin", False))


st.session_state.is_admin = is_admin_mode()


# =========================================================
# S3 helpers
# =========================================================
def _get_s3_cfg():
    access_key = st.secrets.get("AWS_ACCESS_KEY_ID", "")
    secret_key = st.secrets.get("AWS_SECRET_ACCESS_KEY", "")
    region = st.secrets.get("AWS_REGION") or st.secrets.get("AWS_DEFAULT_REGION") or "eu-north-1"
    bucket = st.secrets.get("S3_BUCKET_NAME") or st.secrets.get("S3_BUCKET") or ""
    prefix = st.secrets.get("S3_PREFIX", "").strip().strip("/")
    if not (access_key and secret_key and bucket):
        return None
    return {"access_key": access_key, "secret_key": secret_key, "region": region, "bucket": bucket, "prefix": prefix}


def _s3_client(cfg):
    return boto3.client("s3", aws_access_key_id=cfg["access_key"], aws_secret_access_key=cfg["secret_key"], region_name=cfg["region"])


def s3_key_for(center_key: str, year: int, filename: str) -> str:
    cfg = _get_s3_cfg()
    pre = (cfg["prefix"] + "/") if (cfg and cfg.get("prefix")) else ""
    return f"{pre}{center_key}/{year}/{filename}"


def ensure_local_from_s3(local_path: Path, center_key: str, year: int) -> bool:
    if local_path.exists():
        return True
    cfg = _get_s3_cfg()
    if cfg is None:
        return False
    key = s3_key_for(center_key, year, local_path.name)
    client = _s3_client(cfg)
    try:
        local_path.parent.mkdir(parents=True, exist_ok=True)
        client.download_file(cfg["bucket"], key, str(local_path))
        return local_path.exists()
    except ClientError:
        return False


# =========================================================
# Paths
# =========================================================
def report_path(center_key: str, year: int) -> Path:
    if center_key == "pharmacy":
        return DATA_DIR / "excellent_pharmacy" / str(year) / "Pharmacy_Exclusive_Report_with_Aging.xlsx"
    if center_key == "excellent":
        return DATA_DIR / "excellent" / str(year) / "report.xlsx"
    if center_key == "easyhealth":
        return DATA_DIR / "easyhealth" / str(year) / "report.xlsx"
    return DATA_DIR / center_key / str(year) / "report.xlsx"


def save_uploaded_report(center_key: str, year: int, upload) -> Path:
    rp = report_path(center_key, year)
    rp.parent.mkdir(parents=True, exist_ok=True)
    rp.write_bytes(upload.read())
    return rp


# =========================================================
# Query params
# =========================================================
def _qs_first(key: str):
    v = st.query_params.get(key)
    if isinstance(v, (list, tuple)):
        return v[0] if v else None
    return v


qs_year = _qs_first("year")
qs_center = _qs_first("center")

if qs_year:
    try:
        st.session_state.year = int(qs_year)
    except Exception:
        pass
elif st.session_state.get("year") is None:
    if st.session_state.get("rcm_year") in YEARS:
        st.session_state.year = int(st.session_state.get("rcm_year"))

if qs_center:
    qs_center = str(qs_center).strip().lower()
    if qs_center in CENTERS:
        st.session_state.center_key = qs_center

st.caption(
    f"Mode: **{'admin' if st.session_state.get('is_admin') else 'view'}** · "
    f"Year: **{st.session_state.get('year') or 'none'}** · "
    f"Center: **{st.session_state.get('center_key') or 'all'}**"
)

if st.session_state.get("year") is None:
    st.subheader("Select Year")
    cols = st.columns(3)
    for i, y in enumerate(YEARS):
        with cols[i]:
            if st.button(f"Pending Balance {y}", use_container_width=True, key=f"pb_{y}"):
                st.session_state.year = y
                st.query_params["year"] = str(y)
                st.rerun()
    st.stop()

year = int(st.session_state.year)
if st.query_params.get("year") != str(year):
    st.query_params["year"] = str(year)

centers_to_show = ["excellent", "pharmacy"] if year == 2024 else ["excellent", "pharmacy", "easyhealth"]
forced_center = st.session_state.get("center_key")
if forced_center in centers_to_show:
    centers_to_show = [forced_center]


# =========================================================
# Load
# =========================================================
@st.cache_data(show_spinner=True)
def load_kpis_only(path_str: str, token: float, center_key: str):
    xls = pd.ExcelFile(path_str, engine="openpyxl")
    preferred = ["Balance_Aging_Detail", "Balance_Aging_Summary", "Insurance_Totals"]
    base_sheet = next((s for s in preferred if s in xls.sheet_names), xls.sheet_names[0])
    df = pd.read_excel(xls, sheet_name=base_sheet)
    df.columns = [str(c).strip() for c in df.columns]

    if center_key == "pharmacy":
        df = compute_pharmacy_balance(df)
        df = add_aging(df) if "AgingBucket" not in df.columns else df
        keywords = SOLD_TO_KLAIM_KEYWORDS_PHARMACY
    else:
        df = ensure_insurance(df)
        df, net_col, paid_cols = ensure_numeric(df)
        df = compute_measures(df, net_col, paid_cols)
        df = add_aging(df)
        keywords = SOLD_TO_KLAIM_KEYWORDS_DEFAULT

    balance_df = df[df["Balance"] > 0].copy()
    total_balance = float(pd.to_numeric(balance_df["Balance"], errors="coerce").fillna(0).sum())
    sold_mask = sold_to_klaim_mask(balance_df["Insurance"], keywords)
    sold_to_klaim_balance = float(pd.to_numeric(balance_df.loc[sold_mask, "Balance"], errors="coerce").fillna(0).sum())
    current_balance = total_balance - sold_to_klaim_balance
    over60_mask = is_over_60_bucket(balance_df["AgingBucket"])
    sold_over60 = float(pd.to_numeric(balance_df.loc[sold_mask & over60_mask, "Balance"], errors="coerce").fillna(0).sum())
    current_over60 = float(pd.to_numeric(balance_df.loc[(~sold_mask) & over60_mask, "Balance"], errors="coerce").fillna(0).sum())

    submission_breakdown = compute_submission_breakdown(df)
    stages = compute_stages(df, keywords)

    return total_balance, sold_to_klaim_balance, current_balance, sold_over60, current_over60, keywords, submission_breakdown, stages


# =========================================================
# Render
# =========================================================
def render_center_kpis_only(center_key: str, year: int):
    st.markdown(f"<h2 class='center-title'>{CENTERS[center_key]}</h2>", unsafe_allow_html=True)
    rp = report_path(center_key, year)
    ensure_local_from_s3(rp, center_key, year)
    token = rp.stat().st_mtime if rp.exists() else 0.0
    built = "—" if not token else dt.fromtimestamp(token).strftime("%Y-%m-%d %H:%M")

    if st.session_state.get("is_admin"):
        with st.expander("⬆️ Admin: Upload/replace report for this center & year", expanded=False):
            up = st.file_uploader("Upload report (.xlsx)", type=["xlsx"], key=f"u_{center_key}_{year}")
            if up:
                dst = save_uploaded_report(center_key, year, up)
                st.success(f"Saved ✅ {dst}")
                load_kpis_only.clear()
                st.rerun()

    if not rp.exists():
        st.warning("No saved report found for this center/year. Admin must upload/rebuild once (or ensure report exists in S3), then management can view anytime.")
        st.markdown("---")
        return

    total_balance, sold_to_klaim_balance, current_balance, sold_over60, current_over60, keywords_used, submission_breakdown, stages = load_kpis_only(str(rp), token, center_key)

    render_meta_chips(center_key, year, built, keywords_used)
    render_balance_kpi_cards(total_balance, sold_to_klaim_balance, current_balance, sold_over60, current_over60)
    render_submission_breakdown(submission_breakdown, total_balance=total_balance)
    render_stages_section(stages, canonical_total=total_balance)
    st.markdown("---")


# =========================================================
# Page output
# =========================================================
st.markdown(f"## Pending Balance — {year}")
for ckey in centers_to_show:
    render_center_kpis_only(ckey, year)
