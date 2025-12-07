# exclusive_dashboard.py
import sys
import subprocess
from pathlib import Path
import pandas as pd
import streamlit as st

# ========================= Page setup =========================
st.set_page_config(page_title="Exclusive Report with Aging — Dashboard", layout="wide")
BASE = Path(__file__).parent

DATA_DIR = BASE / "data"
for p in ["easyhealth", "excellent", "excellent_pharmacy"]:
    (DATA_DIR / p).mkdir(parents=True, exist_ok=True)

# ========================= Generators =========================
GEN_MEDICAL = BASE / "exclusive_report_with_aging_final.py"

def resolve_pharmacy_generator() -> Path | None:
    candidates = [
        "pharmacy_exclusive_report_with_aging.py",
        "pharmacy_exclusive_report_with_Aging.py",
        "pharmacy_exclusive_report_with_aging_final.py",
    ]
    for name in candidates:
        p = BASE / name
        if p.exists():
            return p
    return None

GEN_PHARM = resolve_pharmacy_generator()

# ========================= Centers config =====================
CENTERS = {
    "easyhealth": {
        "name": "Easy Health Medical Clinic (MF8031)",
        "folder": DATA_DIR / "easyhealth",
        "src_name": "source.xlsx",
        "out_name": "report.xlsx",
        "generator": GEN_MEDICAL,
    },
    "excellent": {
        "name": "Excellent Medical Center (MF4777)",
        "folder": DATA_DIR / "excellent",
        "src_name": "source.xlsx",
        "out_name": "report.xlsx",
        "generator": GEN_MEDICAL,
    },
    "excellent_pharmacy": {
        "name": "Excellent Pharmacy (PF code)",
        "folder": DATA_DIR / "excellent_pharmacy",
        "src_name": "source.xlsx",
        "out_name": "report.xlsx",
        "generator": GEN_PHARM,
    },
}

# ========================= Helpers =========================
def mtime_token(p: Path) -> float:
    try:
        return p.stat().st_mtime
    except FileNotFoundError:
        return 0.0

def _run(cmd, cwd: Path):
    res = subprocess.run(cmd, capture_output=True, text=True, cwd=str(cwd))
    if res.returncode != 0:
        raise RuntimeError(
            "Command failed:\n" + " ".join(cmd)
            + "\n\nSTDOUT:\n" + (res.stdout or "(empty)")
            + "\n\nSTDERR:\n" + (res.stderr or "(empty)")
        )
    return res

def rebuild_report(generator: Path, src_path: Path, out_path: Path, workdir: Path) -> str:
    """
    Run the generator INSIDE the center folder so scripts that glob('*.xlsx') pick the right file.
    Try:
      1) script --out <out> <src>
      2) script <src> --out <out>
      3) script     (no args; for scripts that just read from CWD and write default name)
    Then, if the script writes a default file name, move/rename it to out_path.
    """
    py = sys.executable
    workdir.mkdir(parents=True, exist_ok=True)

    attempts = [
        [py, str(generator), "--out", str(out_path.name), str(src_path.name)],
        [py, str(generator), str(src_path.name), "--out", str(out_path.name)],
        [py, str(generator)],
    ]
    last_err = None
    for cmd in attempts:
        try:
            res = _run(cmd, cwd=workdir)
            # if desired output doesn't exist, try to detect a common default name
            if not out_path.exists():
                # Look for any freshly created xlsx in the workdir and prefer our known ones
                candidates = [
                    workdir / "report.xlsx",
                    workdir / "Pharmacy_Exclusive_Report_with_Aging.xlsx",
                    workdir / "Exclusive_Report_with_Aging.xlsx",
                ]
                for c in candidates:
                    if c.exists():
                        c.replace(out_path)
                        break
            return res.stdout or "OK"
        except Exception as e:
            last_err = e
    # if all failed, raise last error
    raise last_err or RuntimeError("Unknown generator failure.")

def _pick_sheet(sheet_names, wants):
    lower = [s.lower() for s in sheet_names]
    for i, s in enumerate(lower):
        if all(w in s for w in wants):
            return sheet_names[i]
    for i, s in enumerate(lower):
        if any(w in s for w in wants):
            return sheet_names[i]
    return None

def find_detail_sheet_name(names: list[str]) -> str | None:
    for s in names:
        ls = s.lower()
        if "balance" in ls and "aging" in ls and "detail" in ls:
            return s
    for s in names:
        if "detail" in s.lower():
            return s
    if len(names) >= 3:
        return names[2]
    return None

def autodetect_sheets(xls: pd.ExcelFile):
    names = xls.sheet_names
    totals  = _pick_sheet(names, ["total"]) or _pick_sheet(names, ["insurance"])
    summary = _pick_sheet(names, ["aging", "summary"]) or _pick_sheet(names, ["summary"])
    detail  = find_detail_sheet_name(names)
    if totals is None and names: totals = names[0]
    if summary is None and len(names) > 1: summary = names[1]
    if detail is None and len(names) > 2: detail = names[2] if len(names) > 2 else names[-1]
    return names, totals, summary, detail

def trim_empty_rows(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    df2 = df.dropna(how="all")
    if df2.empty:
        return df2
    blank_rows = df2.fillna("").astype(str).apply(lambda row: "".join(row).strip() == "", axis=1)
    return df2.loc[~blank_rows]

def full_height(df, row_px: int = 45, header_px: int = 70, padding_px: int = 150) -> int:
    n = 0 if df is None else len(df)
    return header_px + (n * row_px) + padding_px

def style_grid(df: pd.DataFrame):
    if not isinstance(df, pd.DataFrame) or df.shape[1] == 0:
        return df if not isinstance(df, pd.DataFrame) else df.style
    df = df.copy()
    df.index = range(1, len(df) + 1)
    first_col = df.columns[0]
    num_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    fmt_map = {c: "{:,.2f}".format for c in num_cols}
    border = "#CBD5E1"; header_bg = "#2196F3"; header_font = "#FFFFFF"
    styler = (
        df.style
        .set_table_styles([
            {"selector": "table", "props": [("border-collapse", "collapse"), ("width", "100%")]},
            {"selector": "th.col_heading","props": [("border", f"1px solid {border}"),
                                                    ("background-color", header_bg),
                                                    ("font-weight", "700"),
                                                    ("color", header_font)]},
            {"selector": "th.row_heading","props": [("border", f"1px solid {border}"),
                                                    ("background-color", "#FFFFFF"),
                                                    ("color", "#000000"),
                                                    ("font-weight", "500")]},
            {"selector": "td","props": [("border", f"1px solid {border}")]}
        ])
        .set_properties(subset=[first_col], **{"font-weight": "600"})
        .format(fmt_map)
    )
    try:
        mask_gt = df[first_col].astype(str).str.contains("grand total", case=False, na=False)
        if mask_gt.any():
            def hi(row):
                return (["font-weight:700; color:black; background-color:#FFF7E0"] * len(row)
                        if mask_gt.iloc[row.name - 1] else [""] * len(row))
            styler = styler.apply(hi, axis=1)
    except Exception:
        pass
    return styler

# ========================= Caches =========================
@st.cache_data(show_spinner=True)
def load_core(path: str, _token: float):
    xls = pd.ExcelFile(path)
    names, s_tot, s_sum, s_det = autodetect_sheets(xls)
    totals  = xls.parse(s_tot)
    summary = xls.parse(s_sum)
    return names, totals, summary, s_tot, s_sum, s_det

@st.cache_data(show_spinner=True)
def load_detail(path: str, sheet_name: str, _token: float):
    xls = pd.ExcelFile(path)
    return xls.parse(sheet_name)

# ========================= State =========================
if "is_admin" not in st.session_state:
    st.session_state.is_admin = False
if "center_key" not in st.session_state:
    st.session_state.center_key = None
if "detail_shown" not in st.session_state:
    st.session_state.detail_shown = {}
if "last_center_key" not in st.session_state:
    st.session_state.last_center_key = None

# ========================= Header & mode =========================
left, right = st.columns([5, 1])
with left:
    st.title("📊 Exclusive Report with Aging — Dashboard")
with right:
    st.session_state.is_admin = st.toggle("Admin mode", value=st.session_state.is_admin)

mode_label = "admin" if st.session_state.is_admin else "view"
st.caption(f"Mode: **{mode_label}** · Center: **{st.session_state.center_key or 'none'}**")

if st.session_state.center_key != st.session_state.last_center_key:
    load_core.clear(); load_detail.clear()
    st.session_state.detail_shown[st.session_state.center_key] = False
    st.session_state.last_center_key = st.session_state.center_key

# ========================= Center selection =========================
ck = st.session_state.center_key
if ck not in CENTERS:
    st.subheader("Choose a center")
    c1, c2, c3 = st.columns(3)
    if c1.button(CENTERS["easyhealth"]["name"], use_container_width=True):
        st.session_state.center_key = "easyhealth"; st.rerun()
    if c2.button(CENTERS["excellent"]["name"], use_container_width=True):
        st.session_state.center_key = "excellent"; st.rerun()
    if c3.button(CENTERS["excellent_pharmacy"]["name"], use_container_width=True):
        st.session_state.center_key = "excellent_pharmacy"; st.rerun()
    st.stop()

cfg = CENTERS[ck]
folder = cfg["folder"]
src_path = folder / cfg["src_name"]
out_path = folder / cfg["out_name"]
generator = cfg["generator"]

if st.button("◀ Choose another center"):
    st.session_state.center_key = None
    st.rerun()

if st.session_state.is_admin:
    st.success("You are in **ADMIN** mode — upload/rebuild is enabled.")
st.caption(f"Center: **{cfg['name']}**  ·  Input: {src_path.name}  ·  Report: {out_path.name}")

# ========================= Admin actions =========================
if st.session_state.is_admin:
    with st.expander("⬆️ Upload/replace source Excel", expanded=False):
        up = st.file_uploader("Upload .xlsx", type=["xlsx"], key=f"upload_{ck}")
        if up:
            folder.mkdir(parents=True, exist_ok=True)
            src_path.write_bytes(up.read())
            st.success(f"Saved to {src_path}")

    colA, colB, colC = st.columns(3)
    if colA.button("↻ Rebuild report", use_container_width=True):
        try:
            if generator is None:
                raise RuntimeError("Pharmacy generator not found. Allowed names:\n"
                                   " - pharmacy_exclusive_report_with_aging.py\n"
                                   " - pharmacy_exclusive_report_with_Aging.py\n"
                                   " - pharmacy_exclusive_report_with_aging_final.py")
            msg = rebuild_report(generator, src_path, out_path, folder)
            st.success("Report rebuilt successfully.")
            if msg.strip(): st.code(msg, language="bash")
            load_core.clear(); load_detail.clear()
            st.session_state.detail_shown[ck] = False
        except Exception as e:
            st.error(str(e))
    if colB.button("🗂 Show file locations", use_container_width=True):
        st.info(f"Source: {src_path}\nReport: {out_path}\nScript: {generator or '(NOT FOUND)'}")
    if colC.button("🗑 Reset (delete) this center's report", use_container_width=True):
        try:
            if out_path.exists(): out_path.unlink()
            st.success("Report deleted.")
            load_core.clear(); load_detail.clear()
            st.session_state.detail_shown[ck] = False
        except Exception as e:
            st.error(str(e))

# ========================= Render =========================
token = mtime_token(out_path)
if token == 0.0:
    msg = "Report not found for this center."
    if st.session_state.is_admin: msg += " (Upload source and click Rebuild.)"
    st.warning(msg)
    st.stop()

try:
    names, totals, summary, s_tot, s_sum, s_det = load_core(str(out_path), token)

    st.caption(f"Diagnostics → Generator: **{generator or 'NOT FOUND'}** · "
               f"Report: **{out_path.name}** · Sheets: **{', '.join(names)}**")

    ins_col_candidates = ["Insurance", "Insurance/Plan", "Plan", "Payer", "PayerName"]
    ins_col = next((c for c in ins_col_candidates if c in totals.columns), None)

    def add_grand_total_if_missing(df: pd.DataFrame) -> pd.DataFrame:
        if df.empty or ins_col is None:
            return df
        if df[ins_col].astype(str).str.contains("grand total", case=False, na=False).any():
            return df
        num_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
        sums = {c: float(df[c].sum()) for c in num_cols}
        gt = {col: "" for col in df.columns}
        gt.update(sums)
        gt[ins_col] = "Grand Total"
        return pd.concat([df, pd.DataFrame([gt], columns=df.columns)], ignore_index=True)

    totals = add_grand_total_if_missing(totals)

    def kpi_vals(totals_df: pd.DataFrame):
        row = None
        if ins_col and totals_df[ins_col].astype(str).str.contains("grand total", case=False, na=False).any():
            row = totals_df.loc[totals_df[ins_col].astype(str).str.contains("grand total", case=False, na=False)].iloc[-1]
        if row is not None:
            def g(c):
                try: return float(row.get(c, 0))
                except: return 0.0
            net = g("NetAmount") or g("Net Amount")
            return net, g("Paid"), g("Balance"), g("Rejected"), g("Accepted")
        def s(c): return float(totals_df[c].sum()) if c in totals_df.columns else 0.0
        net_col = "NetAmount" if "NetAmount" in totals_df.columns else ("Net Amount" if "Net Amount" in totals_df.columns else None)
        net = totals_df[net_col].sum() if net_col else 0.0
        return float(net), s("Paid"), s("Balance"), s("Rejected"), s("Accepted")

    k_net, k_paid, k_bal, k_rej, k_acc = kpi_vals(totals)
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Net Amount", f"{k_net:,.2f}")
    c2.metric("Paid", f"{k_paid:,.2f}")
    c3.metric("Balance", f"{k_bal:,.2f}")
    c4.metric("Rejected", f"{k_rej:,.2f}")
    c5.metric("Accepted", f"{k_acc:,.2f}")

    tabs = st.tabs([f"{s_tot or 'Insurance_Totals'}",
                    f"{s_sum or 'Balance_Aging_Summary'}",
                    f"{s_det or 'Balance_Aging_Detail'}"])

    with tabs[0]:
        df1 = trim_empty_rows(totals)
        st.dataframe(style_grid(df1), use_container_width=True, height=full_height(df1))

    with tabs[1]:
        df2 = trim_empty_rows(summary)
        st.dataframe(style_grid(df2), use_container_width=True, height=full_height(df2))

    with tabs[2]:
        if not s_det:
            st.info("No Balance_Aging_Detail sheet detected in this report.")
        else:
            shown = st.session_state.detail_shown.get(ck, False)
            if not shown:
                if st.button("📂 Load Balance_Aging_Detail (no styling)", key=f"load_detail_{ck}", use_container_width=True):
                    st.session_state.detail_shown[ck] = True
                    st.rerun()
                st.caption(f"(Sheet: {s_det})")
            else:
                df3 = load_detail(str(out_path), s_det, token)
                st.dataframe(df3, use_container_width=True, height=full_height(df3))

except Exception as e:
    try:
        names = pd.ExcelFile(str(out_path)).sheet_names
    except Exception:
        names = []
    st.error(f"{e}\n\nAvailable sheets: {', '.join(names) if names else '(none)'}")

