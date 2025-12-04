import streamlit as st, pandas as pd
from pathlib import Path

DATA_XLSX = Path("Exclusive_Report_with_Aging.xlsx")
DATA_PARQ = Path("Exclusive_Report_with_Aging.parquet")
DATA_CSV  = Path("Exclusive_Report_with_Aging.csv")  # optional fallback

@st.cache_data(ttl=24*3600)
def smart_load():
    if DATA_PARQ.exists():
        return pd.read_parquet(DATA_PARQ)

    if DATA_CSV.exists():
        return pd.read_csv(DATA_CSV)  # or aggregate_from_csv(DATA_CSV) for big files

    # last resort: Excel → Parquet (first run only)
    df = pd.read_excel(DATA_XLSX, engine="openpyxl",
                       # usecols=["ClaimID","Insurance","Plan","NetAmount","Paid","Status","DOS"]
                       )
    df.to_parquet(DATA_PARQ, index=False)
    return df

df = smart_load()
