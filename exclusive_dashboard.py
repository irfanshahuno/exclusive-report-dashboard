import pandas as pd
import streamlit as st
from openpyxl import load_workbook
from openpyxl.styles import PatternFill, Font, Alignment
from datetime import datetime
import io

st.set_page_config(page_title="Exclusive Rejection Report", page_icon="📊", layout="wide")
st.title("📊 Exclusive Rejection Report Generator")

st.markdown("""
Upload your Excel file below.  
The app will automatically calculate **Paid, Rejection, Accepted, Balance, Check, CheckDiff**,  
add totals, and let you **download the final styled report**.
""")

uploaded_file = st.file_uploader("📂 Upload your Excel file", type=["xlsx"])

if uploaded_file:
    # --- Load Data ---
    df = pd.read_excel(uploaded_file, engine="openpyxl")
    df.columns = df.columns.str.strip()

    # --- Convert numeric columns ---
    num_cols = ["ActivityIns", "actRemitInsShare", "actResub1RemitInsShare",
                "actResub2RemitInsShare", "actResub3RemitInsShare", "TKBKAmountAct"]
    for col in num_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
        else:
            df[col] = 0.0

    # --- Paid ---
    df["Paid"] = df[["actRemitInsShare", "actResub1RemitInsShare",
                     "actResub2RemitInsShare", "actResub3RemitInsShare",
                     "TKBKAmountAct"]].sum(axis=1)

    # --- Initialize buckets ---
    df["Rejection"] = 0.0
    df["Accepted"] = 0.0
    df["Balance"] = 0.0

    # --- Exclusive Logic ---
    if "ActivityStatus" in df.columns and "DenialCode" in df.columns:
        mask_paid = df["Paid"] > 0
        df.loc[mask_paid, "Accepted"] = df["ActivityIns"] - df["Paid"]
        df.loc[mask_paid, ["Balance", "Rejection"]] = 0

        mask_reject = (df["Paid"] == 0) & \
                      (df["ActivityStatus"].astype(str).str.lower() == "rejected") & \
                      (df["DenialCode"].notna())
        df.loc[mask_reject, "Rejection"] = df["ActivityIns"]
        df.loc[mask_reject, ["Balance", "Accepted"]] = 0

        mask_balance = (df["Paid"] == 0) & ~mask_reject
        df.loc[mask_balance, "Balance"] = df["ActivityIns"]
        df.loc[mask_balance, ["Rejection", "Accepted"]] = 0

    # --- Check Columns ---
    df["Check"] = df["Paid"] + df["Accepted"] + df["Rejection"] + df["Balance"]
    df["CheckDiff"] = df["ActivityIns"] - df["Check"]

    # --- Totals ---
    totals = df[num_cols + ["Paid", "Rejection", "Accepted", "Balance", "Check", "CheckDiff"]].sum(numeric_only=True)
    totals["RowType"] = "Total"
    df["RowType"] = "Detail"
    final_report = pd.concat([df, pd.DataFrame([totals])], ignore_index=True)

    # --- Style and Save to BytesIO ---
    temp_output = io.BytesIO()
    final_report.to_excel(temp_output, index=False, engine="openpyxl")
    temp_output.seek(0)

    wb = load_workbook(temp_output)
    ws = wb.active

    header_fill = PatternFill(start_color="BDD7EE", end_color="BDD7EE", fill_type="solid")  # blue header
    highlight_fill = PatternFill(start_color="FFD966", end_color="FFD966", fill_type="solid")  # orange/yellow

    for col in range(1, ws.max_column + 1):
        cell = ws.cell(row=1, column=col)
        if cell.value in ["Paid", "Balance", "Rejection", "Accepted", "Check", "CheckDiff"]:
            cell.fill = highlight_fill
        else:
            cell.fill = header_fill
        cell.font = Font(bold=True, color="000000")
        cell.alignment = Alignment(horizontal="center", vertical="center")

    # Re-save styled workbook into memory
    styled_output = io.BytesIO()
    wb.save(styled_output)
    styled_output.seek(0)

    st.subheader("📊 Processed Report Preview")
    st.dataframe(final_report.head())

    # --- Download Button ---
    today = datetime.now().strftime("%Y-%m-%d")
    file_name = f"Rejection_Report_{today}.xlsx"

    st.download_button(
        label="⬇️ Download Final Styled Report",
        data=styled_output,
        file_name=file_name,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

    st.success("✅ Report generated and styled successfully!")


