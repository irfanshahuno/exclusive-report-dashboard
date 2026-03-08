#!/usr/bin/env python3
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
# - If user already authenticated in main dashboard (is_view_auth=True), skip.
# - If balance page opened directly, ask password.
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
st.title("Balance — Aging & Submission Overview")

# ✅ NEEDFUL CHANGE ONLY:
# If this file is inside /pages, store data at repo root /data (not /pages/data)
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

# Your required order: start from 0–30
AGING_ORDER = ["0–30 Days", "31–45 Days", "46–60 Days", "61–90 Days", "91–120 Days", ">120 Days"]

# Default sold-to-klaim keywords (for medical centers)
SOLD_TO_KLAIM_KEYWORDS_DEFAULT = ["NextCare", "Sukoon", "Almadallah", "Daman", "FMC"]

# Pharmacy sold insurers
SOLD_TO_KLAIM_KEYWORDS_PHARMACY = ["ALMADALLAH-AD", "Daman"]

GT_PAT = re.compile(r"^\s*(grand\s*total|total)\s*$", re.I)

# =========================================================
# PREMIUM + SOOTHING UI (ONLY STYLES) + KPI AUTO-FIT
# =========================================================
st.markdown(
    """
<style>
:root{
  --bg:#F6F9FE;
  --card:#FFFFFF;
  --text:#0F172A;
  --muted:#64748B;
  --line:#D9E6F7;
  --line-strong:#BFD4F3;
  --brand:#163A70;
  --brand-soft:#EEF5FF;
  --shadow:0 8px 24px rgba(15, 23, 42, 0.06);
}
.block-container{padding-top:1.25rem;padding-bottom:2rem;max-width:1500px;}
.stApp{background: linear-gradient(180deg, #F8FBFF 0%, #FFFFFF 45%) !important;}
h1,h2,h3{ color: var(--brand); }
hr{ border:none !important;height:1px !important;background:#E6EEF8 !important; }
.center-title{color:var(--brand) !important;font-weight:900 !important;margin-bottom:.1rem !important;letter-spacing:.1px;}
.meta-chip-wrap{display:flex;flex-wrap:wrap;gap:10px;margin:8px 0 18px 0;}
.meta-chip{background:#F8FBFF;border:1px solid var(--line);color:var(--muted);border-radius:999px;padding:7px 12px;font-size:12px;font-weight:700;}
.section-title{font-size:13px;font-weight:900;color:var(--muted);letter-spacing:.08em;text-transform:uppercase;margin:22px 0 10px 2px;}
.section-subtitle{font-size:12px;color:#94A3B8;margin:-4px 0 12px 2px;}
.kpi-grid{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:14px;margin-top:8px;margin-bottom:10px;}
.kpi-card{background:linear-gradient(180deg,#FFFFFF 0%,#FBFDFF 100%);border:1.4px solid var(--line);border-radius:18px;padding:16px 18px;box-shadow:var(--shadow);min-width:0;}
.kpi-card.current{background:linear-gradient(180deg,#F4F8FF 0%,#FFFFFF 100%);border-color:var(--line-strong);}
.kpi-label{font-size:12px;line-height:1.35;min-height:34px;color:var(--muted);font-weight:800;margin-bottom:10px;}
.kpi-value{font-size:clamp(18px,1.9vw,30px);font-weight:900;color:var(--text);letter-spacing:.2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.kpi-card.current .kpi-value{color:var(--brand);}
.sub-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin-bottom:10px;}
.sub-card{background:#FFFFFF;border:1.3px solid var(--line);border-radius:16px;padding:14px 16px;box-shadow:0 6px 16px rgba(11,45,92,0.05);min-width:0;}
.sub-card.initial{border-top:4px solid #3B82F6;}
.sub-card.resub{border-top:4px solid #8B5CF6;}
.sub-card.approved{border-top:4px solid #10B981;}
.sub-card.rejected{border-top:4px solid #EF4444;}
.sub-card.total{border-top:4px solid #BFDBFE;background:linear-gradient(180deg,#F7FBFF 0%,#FFFFFF 100%);}
.sub-card.other{border-top:4px solid #F59E0B;}
.sub-label{font-size:11.5px;color:var(--muted);font-weight:800;margin-bottom:8px;line-height:1.35;}
.sub-value{font-size:clamp(16px,1.75vw,24px);font-weight:900;color:var(--text);}
.stage-banner{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:12px 14px;border:1px solid var(--line);border-radius:14px;background:linear-gradient(180deg,#FFFFFF 0%,#FBFDFF 100%);margin:2px 0 12px 0;}
.stage-banner-left{display:flex;align-items:center;gap:12px;}
.stage-dot{width:10px;height:10px;border-radius:999px;flex:0 0 auto;}
.stage-title{font-size:15px;font-weight:900;color:var(--brand);}
.stage-meta{font-size:12px;color:#94A3B8;font-weight:700;}
.stage-total{font-size:22px;font-weight:900;color:var(--brand);white-space:nowrap;}
div.stButton > button{width:100% !important;min-height:48px !important;padding:10px 16px !important;font-size:15px !important;font-weight:800 !important;background:var(--brand-soft) !important;color:var(--brand) !important;border:1.5px solid var(--line-strong) !important;border-radius:14px !important;box-shadow:0 3px 10px rgba(11,45,92,0.08) !important;}
div[data-testid="stExpander"]{border:1px solid var(--line) !important;border-radius:16px !important;background:#FFFFFF !important;box-shadow:0 6px 20px rgba(15,23,42,0.04);margin-bottom:14px;}
div[data-testid="stDataFrame"]{border:1px solid #EAF1FB;border-radius:14px;overflow:hidden;}
@media (max-width:1200px){.kpi-grid{grid-template-columns:repeat(2,minmax(0,1fr));}.sub-grid{grid-template-columns:repeat(2,minmax(0,1fr));}}
@media (max-width:760px){.kpi-grid,.sub-grid{grid-template-columns:1fr;}}
</style>
""",
    unsafe_allow_html=True,
)


def render_section_heading(title: str, subtitle: str | None = None):
    st.markdown(f'<div class="section-title">{title}</div>', unsafe_allow_html=True)
    if subtitle:
        st.markdown(f'<div class="section-subtitle">{subtitle}</div>', unsafe_allow_html=True)


def render_balance_kpi_cards(total_balance, sold_to_klaim_balance, current_balance, sold_over60, current_over60):
    def fmt(x):
        try:
            return f"{float(x):,.2f}"
        except Exception:
            return "—"

    html = f"""
    <div class="kpi-grid">
      <div class="kpi-card" title="{fmt(total_balance)}">
        <div class="kpi-label">Total Balance</div>
        <div class="kpi-value">{fmt(total_balance)}</div>
      </div>

      <div class="kpi-card" title="{fmt(sold_to_klaim_balance)}">
        <div class="kpi-label">Insurance Balance Sold to Klaim</div>
        <div class="kpi-value">{fmt(sold_to_klaim_balance)}</div>
      </div>

      <div class="kpi-card current" title="{fmt(current_balance)}">
        <div class="kpi-label">Current Balance (Total - Sold)</div>
        <div class="kpi-value">{fmt(current_balance)}</div>
      </div>

      <div class="kpi-card" title="{fmt(sold_over60)}">
        <div class="kpi-label">Sold to Klaim &gt;60 Days</div>
        <div class="kpi-value">{fmt(sold_over60)}</div>
      </div>

      <div class="kpi-card" title="{fmt(current_over60)}">
        <div class="kpi-label">Current &gt;60 Days</div>
        <div class="kpi-value">{fmt(current_over60)}</div>
      </div>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)


# =========================================================
# Submission-attempt breakdown renderer
# =========================================================
def _classify_status(raw: str) -> tuple[str, str]:
    """
    Returns (display_label, css_class) for a given raw Status value.
    Examples:
      'Submitted'               → ('Initial Submission', 'initial')
      'Submitted(Resub- 1)'     → ('1st Resubmission', 'resub')
      'Rejection Accepted(Resub- 1)' → ('1st Resubmission', 'resub')
      'Submitted(Resub- 2)'     → ('2nd Resubmission', 'resub')
      'Approved'                → ('Approved', 'approved')
      'Rejected'                → ('Rejected', 'rejected')
    """
    s = str(raw).strip()
    sl = s.lower()

    # ── Resubmission: extract the number ──────────────────
    m = re.search(r"resub[-\s]*(\d+)", sl)
    if m:
        n = int(m.group(1))
        suffix = {1: "1st", 2: "2nd", 3: "3rd"}.get(n, f"{n}th")
        return (f"{suffix} Resubmission", "resub")

    # ── Approved ──────────────────────────────────────────
    if "approved" in sl:
        return ("Approved", "approved")

    # ── Rejected / Denial ────────────────────────────────
    if any(x in sl for x in ["reject", "denial", "denied"]):
        return ("Rejected / Denied", "rejected")

    # ── Initial Submitted ─────────────────────────────────
    if "submit" in sl:
        return ("Initial Submission", "initial")

    # ── Anything else ─────────────────────────────────────
    label = s if s not in ("", "nan", "None") else "Unknown"
    return (label, "other")


def compute_submission_breakdown(df: pd.DataFrame) -> list[dict]:
    """
    Forward-fill the 'Status' column, then sum Balance per classified group.
    Returns list of {label, css_class, balance} sorted by natural order.
    """
    if "Status" not in df.columns:
        return []

    dfc = df.copy()
    # Forward-fill blanks / NaN in Status column
    dfc["Status"] = dfc["Status"].replace("", pd.NA)
    dfc["Status"] = dfc["Status"].ffill()

    # Only rows with a positive balance
    dfc = dfc[dfc["Balance"] > 0].copy()
    if dfc.empty:
        return []

    dfc["_label"], dfc["_class"] = zip(*dfc["Status"].apply(_classify_status))

    grouped = (
        dfc.groupby(["_label", "_class"], sort=False)["Balance"]
        .sum()
        .reset_index()
        .rename(columns={"Balance": "total"})
    )

    # Natural sort order
    order = [
        "Initial Submission",
        "1st Resubmission",
        "2nd Resubmission",
        "3rd Resubmission",
        "Approved",
        "Rejected / Denied",
    ]

    def sort_key(row):
        try:
            return order.index(row["_label"])
        except ValueError:
            return 99

    grouped["_order"] = grouped.apply(sort_key, axis=1)
    grouped = grouped.sort_values("_order")

    return [
        {"label": r["_label"], "css_class": r["_class"], "balance": float(r["total"])}
        for _, r in grouped.iterrows()
    ]


def render_submission_breakdown(breakdown: list[dict]):
    if not breakdown:
        return

    def fmt(x):
        try:
            return f"{float(x):,.2f}"
        except Exception:
            return "—"

    render_section_heading("Balance by Submission Attempt", "Clear stage-wise view of all positive outstanding balances")

    total_all = sum(float(b.get("balance", 0) or 0) for b in breakdown)
    cards = list(breakdown)
    cards.append({"label": "Total (All Stages)", "css_class": "total", "balance": total_all})

    cards_html = "".join(
        f'<div class="sub-card {b["css_class"]}" title="{fmt(b["balance"])}">'
        f'<div class="sub-label">{b["label"]}</div>'
        f'<div class="sub-value">{fmt(b["balance"])}<\/div>'
        f'<\/div>'
        for b in cards
    )

    st.markdown(f'<div class="sub-grid">{cards_html}</div>', unsafe_allow_html=True)


# =========================================================
# Insurance × Aging — per submission stage
# =========================================================

# Defines the display order + labels for each stage
STAGE_DEFINITIONS = [
    {"label": "Initial Submission",  "css": "initial",  "resub_n": None},
    {"label": "1st Resubmission",    "css": "resub1",   "resub_n": 1},
    {"label": "2nd Resubmission",    "css": "resub2",   "resub_n": 2},
    {"label": "3rd Resubmission",    "css": "resub3",   "resub_n": 3},
    {"label": "Approved",            "css": "approved", "resub_n": "approved"},
    {"label": "Rejected / Denied",   "css": "rejected", "resub_n": "rejected"},
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
    """Map a raw (ffilled) Status value to a stage key matching STAGE_DEFINITIONS css."""
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
    return "initial"  # default


def _make_pivot(dfc: pd.DataFrame):
    """Build Insurance × AgingBucket pivot with Grand Total row.
    Unknown aging rows are included in a separate 'No Date' column."""
    if dfc.empty:
        return None
    pivot = dfc.pivot_table(
        index="Insurance", columns="AgingBucket",
        values="Balance", aggfunc="sum", fill_value=0,
    )
    # Known buckets first, then Unknown last as "No Date"
    ordered_cols = [c for c in AGING_ORDER if c in pivot.columns]
    if "Unknown" in pivot.columns:
        ordered_cols = ordered_cols + ["Unknown"]
        pivot = pivot.rename(columns={"Unknown": "No Date"})
        ordered_cols = [c if c != "Unknown" else "No Date" for c in ordered_cols]
    pivot = pivot[ordered_cols]
    pivot["Total"] = pivot.sum(axis=1)
    pivot = pivot.sort_values("Total", ascending=False)
    grand = pivot.sum(numeric_only=True).rename("Grand Total")
    pivot = pd.concat([pivot, grand.to_frame().T])
    return pivot


def _make_aging_summary(dfc: pd.DataFrame):
    """Build AgingBucket → Balance + % summary with Grand Total row.
    Unknown aging rows appear as 'No Date' at the bottom."""
    if dfc.empty:
        return None
    # Known buckets in order, then No Date
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
    grand = pd.DataFrame([{"AgingBucket": "Grand Total",
                           "Balance": round(total, 2), "% of Total": 100.0}])
    return pd.concat([summary, grand], ignore_index=True)


def compute_stages(df: pd.DataFrame) -> list[dict]:
    """
    Returns a list of stage dicts, each containing:
      label, css, total_balance, pivot, aging_summary
    Only stages that have at least one positive-balance row are included.
    """
    if "Insurance" not in df.columns or "AgingBucket" not in df.columns:
        return []

    # Forward-fill Status
    status_filled = (
        df["Status"].replace("", pd.NA).ffill()
        if "Status" in df.columns
        else pd.Series("initial", index=df.index)
    )

    df = df.copy()
    df["_stage_key"] = status_filled.apply(_stage_key)

    base = df[
        df["Balance"] > 0
    ][["Insurance", "AgingBucket", "Balance", "_stage_key"]].copy()
    base["Balance"] = pd.to_numeric(base["Balance"], errors="coerce").fillna(0)

    stages_out = []
    for stage_def in STAGE_DEFINITIONS:
        css = stage_def["css"]
        subset = base[base["_stage_key"] == css][["Insurance", "AgingBucket", "Balance"]].copy()
        if subset.empty:
            continue
        total = float(subset["Balance"].sum())
        stages_out.append({
            "label":        stage_def["label"],
            "css":          css,
            "total":        total,
            "pivot":        _make_pivot(subset),
            "aging_summary": _make_aging_summary(subset),
        })

    return stages_out


# Keep these thin wrappers so load_kpis_only doesn't need restructuring
def compute_insurance_aging_table(df):
    return None   # replaced by compute_stages

def compute_aging_summary(df):
    return None   # replaced by compute_stages


def _blue_cell(val: float, max_val: float) -> str:
    """Return inline CSS background based on value intensity — no matplotlib needed."""
    if max_val <= 0 or val <= 0:
        return ""
    intensity = min(val / max_val, 1.0)
    # Map 0→1 to light blue (#EEF6FF) → medium blue (#3B82F6)
    r = int(238 - intensity * (238 - 59))
    g = int(246 - intensity * (246 - 130))
    b = int(255 - intensity * (255 - 246))
    text = "#0B2D5C" if intensity > 0.55 else "#1e3a5f"
    return f"background-color: rgb({r},{g},{b}); color: {text};"


def _style_insurance_aging(pivot: pd.DataFrame):
    """Apply formatting to the pivot table — no matplotlib dependency."""
    fmt_dict = {c: "{:,.2f}" for c in pivot.columns}

    # Compute max across all data cells (exclude Grand Total row and Total col)
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

    styler = (
        pivot.style
        .format(fmt_dict)
        .apply(style_cells, axis=None)
        .set_properties(**{
            "font-size": "13px",
            "text-align": "right",
            "padding": "6px 12px",
        })
        .set_table_styles([
            {"selector": "th", "props": [
                ("background-color", "#F1F7FF"),
                ("color", "#0B2D5C"),
                ("font-weight", "800"),
                ("font-size", "12px"),
                ("text-align", "center"),
                ("padding", "8px 12px"),
                ("border-bottom", "2px solid #CFE3FF"),
            ]},
            {"selector": "th.row_heading", "props": [
                ("text-align", "left"),
                ("min-width", "160px"),
                ("font-weight", "700"),
            ]},
            {"selector": "td", "props": [("border-bottom", "1px solid #F0F4FA")]},
            {"selector": "table", "props": [("border-collapse", "collapse"), ("width", "100%")]},
        ])
    )
    return styler


def _style_aging_summary(df: pd.DataFrame, accent_color: str):
    """Style the aging summary table with a given accent color — no matplotlib."""
    max_bal = float(df.loc[df["AgingBucket"] != "Grand Total", "Balance"].max()) if not df.empty else 1.0

    # Build a custom single-color gradient using the accent color
    import colorsys
    # Parse hex → HSV so we can vary lightness
    hex_col = accent_color.lstrip("#")
    r0, g0, b0 = tuple(int(hex_col[i:i+2], 16) for i in (0, 2, 4))
    h, s, v = colorsys.rgb_to_hsv(r0/255, g0/255, b0/255)

    def tint(intensity):
        """intensity 0→1: white → accent color"""
        ri = int((1 - intensity * 0.65) * 255)
        gi = int((1 - intensity * 0.65) * 255)
        bi = int((1 - intensity * 0.65) * 255)
        # blend with accent
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
            {"selector": "th", "props": [
                ("background-color", "#F1F7FF"), ("color", "#0B2D5C"),
                ("font-weight", "800"), ("font-size", "12px"),
                ("padding", "8px 10px"), ("border-bottom", "2px solid #CFE3FF"),
            ]},
            {"selector": "td", "props": [("border-bottom", "1px solid #F0F4FA")]},
        ])
        .hide(axis="index")
    )


def render_insurance_aging_tables(pivot, aging_summary):
    """Legacy stub — replaced by render_stages_section below."""
    pass


def render_stages_section(stages: list[dict]):
    """Professional, cleaner stage sections with compact banners and aligned tables."""
    if not stages:
        return

    render_section_heading("Aging Breakdown by Submission Stage", "Each section shows insurance-wise aging and a compact aging summary")

    grand_total = sum(s["total"] for s in stages)

    for idx, stage in enumerate(stages):
        label   = stage["label"]
        css     = stage["css"]
        total   = stage["total"]
        pivot   = stage["pivot"]
        summary = stage["aging_summary"]
        color   = STAGE_COLORS.get(css, "#3B82F6")
        pct     = (total / grand_total * 100) if grand_total > 0 else 0

        with st.expander(f"{label}  ·  {total:,.2f}", expanded=(idx == 0)):
            st.markdown(
                f'''<div class="stage-banner">
                      <div class="stage-banner-left">
                        <span class="stage-dot" style="background:{color};"></span>
                        <div>
                          <div class="stage-title">{label}</div>
                          <div class="stage-meta">Share of overall balance: {pct:.1f}%</div>
                        </div>
                      </div>
                      <div class="stage-total">{total:,.2f}</div>
                    </div>''',
                unsafe_allow_html=True,
            )

            col1, col2 = st.columns([2.25, 1], gap="large")

            with col1:
                st.markdown("**Insurance × Aging Bucket**")
                if pivot is not None:
                    st.dataframe(
                        _style_insurance_aging(pivot),
                        use_container_width=True,
                        height=min(80 + 38 * len(pivot), 520),
                    )
                else:
                    st.info("No data.")

            with col2:
                st.markdown("**Aging Summary**")
                if summary is not None:
                    st.dataframe(
                        _style_aging_summary(summary, color),
                        use_container_width=True,
                        height=min(80 + 38 * len(summary), 380),
                    )
                else:
                    st.info("No data.")

    st.markdown(
        f'''<div class="stage-banner" style="margin-top:18px; background:linear-gradient(180deg,#F7FBFF 0%,#FFFFFF 100%);">
              <div class="stage-banner-left">
                <span class="stage-dot" style="background:#BFDBFE;"></span>
                <div>
                  <div class="stage-title">Grand Total (All Stages)</div>
                  <div class="stage-meta">Combined outstanding balance across all submission stages</div>
                </div>
              </div>
              <div class="stage-total">{grand_total:,.2f}</div>
            </div>''',
        unsafe_allow_html=True,
    )


# =========================================================
# Helpers (generic medical-center logic)
# =========================================================
INSURANCE_COLS = ["Insurance", "PayerName", "Insurer", "Plan"]
NET_COLS = ["ActivityIns", "Net Amount", "NetAmount"]
PAID_COLS = [
    "actRemitInsShare",
    "actResub1RemitInsShare",
    "actResub2RemitInsShare",
    "actResub3RemitInsShare",
    "TKBKAmountAct",
]
ACTIVITY_STATUS_COLS = ["ActivityStatus"]
DENIAL_COLS = ["DenialCode", "Denial Code"]
DATE_COLS = ["SubmissionDate", "ClaimDate", "VisitDate", "ServiceDate", "InvoiceDate", "EncounterDate"]

# Submission-attempt date columns (used in smart aging)
# Maps resub number → date column name.  0 = initial submission.
RESUB_DATE_COLS = {
    0: "SubDate",
    1: "Resub1Date",
    2: "Resub2Date",
    3: "Resub3Date",
}
SUBDATE_COL = "SubDate"   # fallback / approved / rejected


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


def _resub_number_from_status(status: str) -> int | None:
    """Extract resub number from a status string. Returns None if not a resub."""
    m = re.search(r"resub[-\s]*(\d+)", str(status).lower())
    return int(m.group(1)) if m else None


def add_aging(df: pd.DataFrame) -> pd.DataFrame:
    """
    Smart aging: picks the correct date column per row based on the Status column.
      - Initial Submission (no resub tag)  → SubDate
      - Resub 1                            → Resub1Date
      - Resub 2                            → Resub2Date
      - Resub 3                            → Resub3Date
      - Approved / Rejected / anything else → SubDate
    Falls back to generic DATE_COLS if none of the resub columns exist.
    """
    today = pd.Timestamp(dt.today().date())
    bins   = [-1, 30, 45, 60, 90, 120, float("inf")]
    labels = ["0–30 Days", "31–45 Days", "46–60 Days", "61–90 Days", "91–120 Days", ">120 Days"]

    # ── Check whether the smart date columns are present ────────────────
    has_smart = any(c in df.columns for c in RESUB_DATE_COLS.values())

    if not has_smart:
        # ── Fallback: original generic logic ────────────────────────────
        existing = [c for c in DATE_COLS if c in df.columns]
        for c in existing:
            df[c] = pd.to_datetime(df[c], errors="coerce", dayfirst=True)
        df["RefDate"] = df[existing].bfill(axis=1).iloc[:, 0] if existing else pd.NaT
        df["DaysDiff"] = (today - df["RefDate"]).dt.days
        df["AgingBucket"] = pd.cut(df["DaysDiff"], bins=bins, labels=labels)
        df["AgingBucket"] = df["AgingBucket"].astype(str).replace("nan", "Unknown")
        return df

    # ── Parse all resub date columns that exist ──────────────────────────
    for resub_n, col in RESUB_DATE_COLS.items():
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce", dayfirst=True)

    # ── Forward-fill Status so blank rows inherit their parent status ────
    status_filled = (
        df["Status"].replace("", pd.NA).ffill()
        if "Status" in df.columns
        else pd.Series("", index=df.index)
    )

    # ── Assign RefDate per row based on the status ───────────────────────
    def _pick_date(idx):
        s = str(status_filled.iloc[idx])
        resub_n = _resub_number_from_status(s)
        if resub_n is not None:
            col = RESUB_DATE_COLS.get(resub_n, SUBDATE_COL)
        else:
            col = SUBDATE_COL          # initial / approved / rejected → SubDate
        if col in df.columns:
            return df[col].iloc[idx]
        # If that specific date col is missing, cascade down to any available
        for fallback_col in RESUB_DATE_COLS.values():
            if fallback_col in df.columns:
                v = df[fallback_col].iloc[idx]
                if pd.notna(v):
                    return v
        return pd.NaT

    df["RefDate"] = pd.to_datetime(
        [_pick_date(i) for i in range(len(df))], errors="coerce"
    )

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
# Pharmacy logic (NEEDFUL)
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
        # fallback to generic
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
# Admin mode (optional)
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
    else:
        return st.toggle("Admin mode", value=st.session_state.get("is_admin", False))


st.session_state.is_admin = is_admin_mode()

# =========================================================
# ✅ S3 FALLBACK HELPERS (NEEDFUL)
# =========================================================
def _get_s3_cfg():
    access_key = st.secrets.get("AWS_ACCESS_KEY_ID", "")
    secret_key = st.secrets.get("AWS_SECRET_ACCESS_KEY", "")

    region = (
        st.secrets.get("AWS_REGION")
        or st.secrets.get("AWS_DEFAULT_REGION")
        or "eu-north-1"
    )

    bucket = (
        st.secrets.get("S3_BUCKET_NAME")
        or st.secrets.get("S3_BUCKET")
        or ""
    )

    prefix = st.secrets.get("S3_PREFIX", "").strip().strip("/")

    if not (access_key and secret_key and bucket):
        return None

    return {
        "access_key": access_key,
        "secret_key": secret_key,
        "region": region,
        "bucket": bucket,
        "prefix": prefix,
    }


def _s3_client(cfg):
    return boto3.client(
        "s3",
        aws_access_key_id=cfg["access_key"],
        aws_secret_access_key=cfg["secret_key"],
        region_name=cfg["region"],
    )


def s3_key_for(center_key: str, year: int, filename: str) -> str:
    cfg = _get_s3_cfg()
    pre = (cfg["prefix"] + "/") if (cfg and cfg.get("prefix")) else ""
    # IMPORTANT: matches your uploaded structure: streamlit/<center>/<year>/...
    # If you used S3_PREFIX="streamlit", then prefix handles that.
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
# Paths (match main dashboard)
# =========================================================
def report_path(center_key: str, year: int) -> Path:
    if center_key == "pharmacy":
        return DATA_DIR / "excellent_pharmacy" / str(year) / "Pharmacy_Exclusive_Report_with_Aging.xlsx"
    elif center_key == "excellent":
        return DATA_DIR / "excellent" / str(year) / "report.xlsx"
    elif center_key == "easyhealth":
        return DATA_DIR / "easyhealth" / str(year) / "report.xlsx"
    else:
        return DATA_DIR / center_key / str(year) / "report.xlsx"


def save_uploaded_report(center_key: str, year: int, upload) -> Path:
    rp = report_path(center_key, year)
    rp.parent.mkdir(parents=True, exist_ok=True)
    rp.write_bytes(upload.read())
    return rp


# =========================================================
# ✅ NEEDFUL: Read query params from dashboard click
# - If center/year given → do NOT show password again (handled above) and do NOT show year selection.
# - If opened directly (no center/year), show the old year landing.
# =========================================================
def _qs_first(key: str):
    v = st.query_params.get(key)
    if isinstance(v, (list, tuple)):
        return v[0] if v else None
    return v


qs_year = _qs_first("year")
qs_center = _qs_first("center")

# set year from query OR from main dashboard selection
if qs_year:
    try:
        st.session_state.year = int(qs_year)
    except Exception:
        pass
elif st.session_state.get("year") is None:
    # main dashboard uses rcm_year
    if st.session_state.get("rcm_year") in YEARS:
        st.session_state.year = int(st.session_state.get("rcm_year"))

# set center from query params (only when coming from dashboard click)
if qs_center:
    qs_center = str(qs_center).strip().lower()
    if qs_center in CENTERS:
        st.session_state.center_key = qs_center

st.caption(
    f"Mode: **{'admin' if st.session_state.get('is_admin') else 'view'}** · "
    f"Year: **{st.session_state.get('year') or 'none'}** · "
    f"Center: **{st.session_state.get('center_key') or 'all'}**"
)

# =========================================================
# Year landing (ONLY if opened directly, no year provided anywhere)
# =========================================================
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

# Keep query params consistent
if st.query_params.get("year") != str(year):
    st.query_params["year"] = str(year)

# =========================================================
# Centers to show (2024: no easyhealth)
# =========================================================
if year == 2024:
    centers_to_show = ["excellent", "pharmacy"]
else:
    centers_to_show = ["excellent", "pharmacy", "easyhealth"]

forced_center = st.session_state.get("center_key")
if forced_center in centers_to_show:
    centers_to_show = [forced_center]


# =========================================================
# ✅ LOAD KPI (detail sheet first) — FIXED
# =========================================================
@st.cache_data(show_spinner=True)
def load_kpis_only(path_str: str, token: float, center_key: str):
    xls = pd.ExcelFile(path_str, engine="openpyxl")

    # ✅ NEEDFUL: pick correct sheet (detail first)
    preferred = ["Balance_Aging_Detail", "Balance_Aging_Summary", "Insurance_Totals"]
    base_sheet = None
    for s in preferred:
        if s in xls.sheet_names:
            base_sheet = s
            break

    if base_sheet is None:
        base_sheet = xls.sheet_names[0]

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
    balance_df = balance_df[balance_df["AgingBucket"] != "Unknown"].copy()

    total_balance = float(pd.to_numeric(balance_df["Balance"], errors="coerce").fillna(0).sum())

    sold_mask = sold_to_klaim_mask(balance_df["Insurance"], keywords)
    sold_to_klaim_balance = float(pd.to_numeric(balance_df.loc[sold_mask, "Balance"], errors="coerce").fillna(0).sum())
    current_balance = total_balance - sold_to_klaim_balance

    over60_mask = is_over_60_bucket(balance_df["AgingBucket"])
    sold_over60 = float(pd.to_numeric(balance_df.loc[sold_mask & over60_mask, "Balance"], errors="coerce").fillna(0).sum())
    current_over60 = float(pd.to_numeric(balance_df.loc[(~sold_mask) & over60_mask, "Balance"], errors="coerce").fillna(0).sum())

    # ── Submission attempt breakdown ─────────────────────
    # Use full df so Status ffill works on original row order, then filter Balance > 0 inside
    submission_breakdown = compute_submission_breakdown(df)

    # ── Per-stage Insurance × Aging breakdown ────────────
    stages = compute_stages(df)

    return (
        total_balance, sold_to_klaim_balance, current_balance,
        sold_over60, current_over60, keywords,
        submission_breakdown, stages,
    )


# =========================================================
# Render per center
# =========================================================
def render_center_kpis_only(center_key: str, year: int):
    st.markdown(f"<h2 class='center-title'>{CENTERS[center_key]}</h2>", unsafe_allow_html=True)
    st.markdown(
        f'''<div class="meta-chip-wrap">
              <span class="meta-chip">Year: {year}</span>
              <span class="meta-chip">Center Key: {center_key}</span>
            </div>''',
        unsafe_allow_html=True,
    )

    rp = report_path(center_key, year)

    # ✅ NEEDFUL: S3 fallback (download if local missing)
    ensure_local_from_s3(rp, center_key, year)

    token = rp.stat().st_mtime if rp.exists() else 0.0
    built = "—" if not token else dt.fromtimestamp(token).strftime("%Y-%m-%d %H:%M")
    st.caption(f"Saved report: `{rp}` · Built: **{built}**")

    if st.session_state.get("is_admin"):
        with st.expander("⬆️ Admin: Upload/replace report for this center & year", expanded=False):
            up = st.file_uploader("Upload report (.xlsx)", type=["xlsx"], key=f"u_{center_key}_{year}")
            if up:
                dst = save_uploaded_report(center_key, year, up)
                st.success(f"Saved ✅ {dst}")
                load_kpis_only.clear()
                st.rerun()

    if not rp.exists():
        st.warning(
            "No saved report found for this center/year.\n\n"
            "✅ Admin must upload/rebuild once (or ensure report exists in S3), then management can view anytime."
        )
        st.markdown("---")
        return

    (
        total_balance, sold_to_klaim_balance, current_balance,
        sold_over60, current_over60, keywords_used,
        submission_breakdown, stages,
    ) = load_kpis_only(str(rp), token, center_key)

    render_balance_kpi_cards(total_balance, sold_to_klaim_balance, current_balance, sold_over60, current_over60)
    st.markdown(
        f'''<div class="meta-chip-wrap"><span class="meta-chip">Sold-to-Klaim keywords: {', '.join(keywords_used)}</span></div>''',
        unsafe_allow_html=True,
    )

    render_submission_breakdown(submission_breakdown)
    render_stages_section(stages)
    st.markdown("---")


# =========================================================
# Page output
# =========================================================
st.markdown(f"## Pending Balance — {year}")

for ckey in centers_to_show:
    render_center_kpis_only(ckey, year)
