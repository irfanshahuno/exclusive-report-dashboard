import streamlit as st
import pandas as pd
from pathlib import Path

st.set_page_config(page_title="Exclusive Report Dashboard", layout="wide")
st.title("📊 Exclusive Report Dashboard")

DATA_XLSX = Path("Check3.xlsx")
DATA_PARQ = Path("Check3.parquet")
DATA_CSV  = Path("Check3.csv")

def parquet_available():
    try:
        import pyarrow  # noqa
        return True
    except Exception:
        return False

@st.cache_data(ttl=24*3600)
def load_data():
    if DATA_PARQ.exists() and parquet_available():
        return pd.read_parquet(DATA_PARQ)
    if DATA_CSV.exists():
        return pd.read_csv(DATA_CSV)
    df = pd.read_excel(DATA_XLSX, engine="openpyxl")
    if parquet_available():
        df.to_parquet(DATA_PARQ, index=False)
    return df

try:
    df = load_data()
except Exception as e:
    st.error(f"Failed to load data: {e}")
    st.stop()

st.success(f"Loaded {len(df):,} rows")

# ---------- derive standard columns (rename if present) ----------
# Try to map common column names:
rename_map = {
    "InsPlan": "Plan",
    "InsuranceName": "Insurance",
    "Net Amount": "NetAmount",
    "Paid Amount": "Paid",
    "VisitDate": "DOS",            # treat VisitDate as DOS if DOS missing
    "ActivityStart": "DOS",        # else use ActivityStart
}
for k, v in rename_map.items():
    if k in df.columns and v not in df.columns:
        df = df.rename(columns={k: v})

# Numeric safety
for num in ["NetAmount", "Paid"]:
    if num in df.columns:
        df[num] = pd.to_numeric(df[num], errors="coerce")

if "Paid" in df.columns and "NetAmount" in df.columns:
    df["Balance"] = (df["NetAmount"] - df["Paid"]).fillna(0)

# Date safety
if "DOS" in df.columns:
    df["DOS"] = pd.to_datetime(df["DOS"], errors="coerce")

# ---------- Sidebar filters ----------
with st.sidebar:
    st.header("Filters")
    ins = st.multiselect("Insurance", sorted(df["Insurance"].dropna().unique()) if "Insurance" in df else [])
    plan = st.multiselect("Plan", sorted(df["Plan"].dropna().unique()) if "Plan" in df else [])
    if "DOS" in df.columns:
        min_d, max_d = pd.to_datetime(df["DOS"].min()), pd.to_datetime(df["DOS"].max())
        date_range = st.date_input("Date range", (min_d.date(), max_d.date()))
    else:
        date_range = None
    search = st.text_input("Search (MemberID / Claim / Patient)", "")

# apply filters
filtered = df.copy()

if ins and "Insurance" in filtered:
    filtered = filtered[filtered["Insurance"].isin(ins)]
if plan and "Plan" in filtered:
    filtered = filtered[filtered["Plan"].isin(plan)]
if date_range and "DOS" in filtered:
    start, end = pd.to_datetime(date_range[0]), pd.to_datetime(date_range[1])
    filtered = filtered[(filtered["DOS"] >= start) & (filtered["DOS"] <= end)]
if search:
    s = search.lower()
    cols = [c for c in ["MemberID","UniqueID","EncPatID","PatName","ClaimID"] if c in filtered]
    if cols:
        filtered = filtered[filtered[cols].astype(str).apply(lambda r: r.str.lower().str.contains(s)).any(axis=1)]

st.caption(f"Showing {len(filtered):,} rows after filters")

# ---------- KPI cards ----------
def safe_sum(col):
    return float(filtered[col].sum()) if col in filtered else 0.0

c1, c2, c3 = st.columns(3)
c1.metric("Net Amount", f"AED {safe_sum('NetAmount'):,.2f}")
c2.metric("Paid", f"AED {safe_sum('Paid'):,.2f}")
c3.metric("Balance", f"AED {safe_sum('Balance'):,.2f}")

# ---------- Grouped summary (Insurance → Plan) ----------
group_cols = [c for c in ["Insurance","Plan"] if c in filtered]
value_cols = [c for c in ["NetAmount","Paid","Balance"] if c in filtered]
if group_cols and value_cols:
    summary = (filtered
               .groupby(group_cols, dropna=False)[value_cols]
               .sum()
               .reset_index()
               .sort_values(value_cols[-1], ascending=False))
    st.subheader("Summary by Insurance / Plan")
    st.dataframe(summary, use_container_width=True)

# ---------- Detail table ----------
st.subheader("Detail")
st.dataframe(filtered.head(1000), use_container_width=True)

# ---------- Downloads ----------
@st.cache_data
def to_csv(df_): return df_.to_csv(index=False).encode("utf-8")
st.download_button("Download filtered CSV", to_csv(filtered), file_name="exclusive_filtered.csv")

if parquet_available():
    @st.cache_data
    def to_parquet_bytes(df_): return df_.to_parquet(index=False)
    st.download_button("Download filtered Parquet", to_parquet_bytes(filtered), file_name="exclusive_filtered.parquet")



