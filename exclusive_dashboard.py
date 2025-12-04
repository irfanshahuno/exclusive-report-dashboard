import streamlit as st
import pandas as pd
from pathlib import Path

st.set_page_config(page_title="Exclusive Report Dashboard", layout="wide")
st.title("📊 Exclusive Report Dashboard")

# === File names in your repo ===
DATA_XLSX = Path("Check3.xlsx")                     # <-- your actual file in the repo
DATA_PARQ = Path("Check3.parquet")                  # created on first run for speed
DATA_CSV  = Path("Check3.csv")                      # optional fallback if you upload CSV

# === Helpers ===
def parquet_available() -> bool:
    try:
        import pyarrow  # noqa: F401
        return True
    except Exception:
        return False

@st.cache_data(ttl=24*3600)
def load_data():
    # 1) Prefer Parquet if present (fast + small)
    if DATA_PARQ.exists() and parquet_available():
        return pd.read_parquet(DATA_PARQ)

    # 2) CSV fallback (if you upload a CSV for big files)
    if DATA_CSV.exists():
        return pd.read_csv(DATA_CSV)

    # 3) Last resort: read Excel (first run), then save Parquet for next runs
    if not DATA_XLSX.exists():
        raise FileNotFoundError(
            f"Data file not found. Expected one of: {DATA_PARQ.name} / {DATA_CSV.name} / {DATA_XLSX.name}"
        )

    # Read only needed columns to reduce memory (adjust to your columns)
    df = pd.read_excel(DATA_XLSX, engine="openpyxl")
    # Example trim: uncomment if you want to cut RAM
    # needed = ["ClaimID","Insurance","Plan","NetAmount","Paid","Status","DOS"]
    # df = df[needed]

    # Save Parquet for speed next time (if pyarrow is available)
    if parquet_available():
        df.to_parquet(DATA_PARQ, index=False)

    return df

# === Load with friendly errors ===
try:
    df = load_data()
    st.success(f"Loaded {len(df):,} rows")
except FileNotFoundError as e:
    st.error(str(e))
    st.stop()
except Exception as e:
    st.error(f"Failed to load data: {e}")
    st.stop()

# === Simple UI so the app definitely renders ===
st.dataframe(df.head(100), use_container_width=True)
st.write("Columns:", list(df.columns))

