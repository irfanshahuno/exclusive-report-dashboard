#!/usr/bin/env python3

import os, sys, time, subprocess
from pathlib import Path
import pandas as pd
import streamlit as st

# -------------------- Page --------------------
st.set_page_config(page_title="Exclusive Report with Aging — Dashboard", layout="wide")
st.title("📊 Exclusive Report with Aging — Dashboard")

# -------------------- Paths --------------------
BASE_DIR     = Path(__file__).parent.resolve()
SCRIPT_PATH  = (BASE_DIR / "exclusive_report_with_aging_final.py").resolve()
REPORTS_DIR  = (BASE_DIR / "reports").resolve()
REPORTS_DIR.mkdir(parents=True, exist_ok=True)
DEFAULT_REPORT = REPORTS_DIR / "Exclusive_Report_with_Aging.xlsx"

# -------------------- Detect Mode (viewer/admin) --------------------
import urllib.parse

# Safe detection for all Streamlit versions
query_str = st.experimental_get_query_params()  # ✅ this works reliably
mode_value = query_str.get("mode", ["viewer"])[0].strip().lower()
IS_ADMIN = (mode_value == "admin")

# Optional: clean display (hide grey text for boss)
if not IS_ADMIN:
    st.markdown("""
        <style>
        .viewer-note {display:none !important;}
        </style>
    """, unsafe_allow_html=True)

st.caption(f"<span class='viewer-note'>Mode: {'Admin' if IS_ADMIN else 'Viewer'} · Add `?mode=admin` to use the uploader.</span>",
           unsafe_allow_html=True)
