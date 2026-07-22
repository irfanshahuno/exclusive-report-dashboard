import io
from datetime import datetime as dt

import pandas as pd
import streamlit as st
from openpyxl import load_workbook
from openpyxl.styles import PatternFill, Font, Alignment
from openpyxl.utils import get_column_letter

st.set_page_config(page_title='Professional Rejection Analysis', layout='wide', page_icon='📊')

COL_STATUS = 'Status'
COL_AMOUNT = 'ActivityIns'
COL_DENIAL = 'DenialCode'
COL_INSURANCE = 'Insurance'

PAID_COLS = [
    'actRemitInsShare',
    'actResub1RemitInsShare',
    'actResub2RemitInsShare',
    'actResub3RemitInsShare',
    'TKBKAmountAct',
]

DETAIL_COLS = [
    'UniqueID', 'ClaimID', 'ActID', 'PatientID', 'PatientName',
    'VisitDate', 'SubDate', 'Insurance', 'DenialCode', 'Status',
    'ActivityIns', 'Paid', 'Balance'
]


def fmt_aed(value):
    try:
        return f'AED {float(value):,.2f}'
    except Exception:
        return f'AED {value}'


def clean_text(series):
    return series.fillna('').astype(str).str.strip()


def normalize_status(series):
    return clean_text(series).str.replace(r'\s+', ' ', regex=True)


def is_rejection_status(series):
    return normalize_status(series).str.lower().str.startswith('rejected')


def is_resubmission_status(series):
    return normalize_status(series).str.lower().str.contains('resub', na=False)


def load_and_prepare(file_bytes):
    df = pd.read_excel(io.BytesIO(file_bytes), engine='openpyxl')
    df.columns = df.columns.astype(str).str.strip()
    df = df.dropna(how='all').copy()

    missing = [c for c in [COL_STATUS, COL_AMOUNT] if c not in df.columns]
    if missing:
        raise ValueError('Missing required columns: ' + ', '.join(missing))

    if COL_DENIAL not in df.columns:
        df[COL_DENIAL] = 'Not Available'
    if COL_INSURANCE not in df.columns:
        df[COL_INSURANCE] = 'Not Available'

    for c in PAID_COLS:
        if c not in df.columns:
            df[c] = 0

    for c in [COL_AMOUNT] + PAID_COLS:
        df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)

    df['Paid'] = df[PAID_COLS].sum(axis=1)
    df['Balance'] = df[COL_AMOUNT] - df['Paid']

    df[COL_STATUS] = normalize_status(df[COL_STATUS])
    df[COL_DENIAL] = clean_text(df[COL_DENIAL])
    df[COL_INSURANCE] = clean_text(df[COL_INSURANCE])

    df.loc[df[COL_STATUS].eq(''), COL_STATUS] = 'Not Available'
    df.loc[df[COL_DENIAL].eq(''), COL_DENIAL] = 'Not Available'
    df.loc[df[COL_INSURANCE].eq(''), COL_INSURANCE] = 'Not Available'

    df['_is_rejected'] = is_rejection_status(df[COL_STATUS])
    df['_is_resub_status'] = is_resubmission_status(df[COL_STATUS])
    df['_is_rejected_unpaid'] = df['_is_rejected'] & df['Paid'].eq(0)
    return df


def summarize_by(df, group_col):
    if df.empty:
        return pd.DataFrame(columns=[group_col, 'Count', 'Amount', 'Paid', 'Balance'])

    out = (
        df.groupby(group_col, dropna=False)
        .agg(
            Count=(group_col, 'size'),
            Amount=(COL_AMOUNT, 'sum'),
            Paid=('Paid', 'sum'),
            Balance=('Balance', 'sum'),
        )
        .reset_index()
    )

    for c in ['Amount', 'Paid', 'Balance']:
        out[c] = out[c].round(2)
    return out.sort_values(['Amount', 'Count'], ascending=[False, False])


def rejection_summary(df):
    rejected = df[df['_is_rejected']]
    rows = [
        ['Total Activities', len(df), df[COL_AMOUNT].sum(), df['Paid'].sum(), df['Balance'].sum()],
        ['Total Rejected', len(rejected), rejected[COL_AMOUNT].sum(), rejected['Paid'].sum(), rejected['Balance'].sum()],
        ['Rejected & Unpaid', int(df['_is_rejected_unpaid'].sum()), df.loc[df['_is_rejected_unpaid'], COL_AMOUNT].sum(), 0, df.loc[df['_is_rejected_unpaid'], 'Balance'].sum()],
        ['Rejected with Payment', int((df['_is_rejected'] & df['Paid'].gt(0)).sum()), df.loc[df['_is_rejected'] & df['Paid'].gt(0), COL_AMOUNT].sum(), df.loc[df['_is_rejected'] & df['Paid'].gt(0), 'Paid'].sum(), df.loc[df['_is_rejected'] & df['Paid'].gt(0), 'Balance'].sum()],
        ['Resubmission Status Rows', int(df['_is_resub_status'].sum()), df.loc[df['_is_resub_status'], COL_AMOUNT].sum(), df.loc[df['_is_resub_status'], 'Paid'].sum(), df.loc[df['_is_resub_status'], 'Balance'].sum()],
    ]
    out = pd.DataFrame(rows, columns=['Metric', 'Count', 'Amount', 'Paid', 'Balance'])
    for c in ['Amount', 'Paid', 'Balance']:
        out[c] = out[c].round(2)
    return out


def top_denials(df, top_n=10):
    rejected = df[df['_is_rejected']]
    out = summarize_by(rejected, COL_DENIAL)
    out = out[out[COL_DENIAL].ne('Not Available')].head(top_n).copy()
    out.insert(0, 'Rank', range(1, len(out) + 1))
    return out


HEADER_FILL = PatternFill('solid', fgColor='1F4E78')
HEADER_FONT = Font(color='FFFFFF', bold=True)
WARNING_FILL = PatternFill('solid', fgColor='FCE4D6')


def style_excel(xlsx_bytes):
    wb = load_workbook(io.BytesIO(xlsx_bytes))
    for ws in wb.worksheets:
        ws.freeze_panes = 'A2'
        ws.auto_filter.ref = ws.dimensions

        for cell in ws[1]:
            cell.fill = HEADER_FILL
            cell.font = HEADER_FONT
            cell.alignment = Alignment(horizontal='center', vertical='center')

        for col_idx, cells in enumerate(ws.columns, start=1):
            max_len = 0
            for cell in list(cells)[:300]:
                value = '' if cell.value is None else str(cell.value)
                max_len = max(max_len, len(value))
            ws.column_dimensions[get_column_letter(col_idx)].width = min(max(max_len + 2, 12), 35)

        headers = {cell.value: cell.column for cell in ws[1]}
        for header in ['Amount', 'Paid', 'Balance', 'ActivityIns']:
            if header in headers:
                col_idx = headers[header]
                for row in range(2, ws.max_row + 1):
                    ws.cell(row=row, column=col_idx).number_format = '#,##0.00'

        if 'Balance' in headers:
            col_idx = headers['Balance']
            for row in range(2, ws.max_row + 1):
                val = ws.cell(row=row, column=col_idx).value
                if isinstance(val, (int, float)) and val < 0:
                    ws.cell(row=row, column=col_idx).fill = WARNING_FILL

    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def build_report(df):
    rejected = df[df['_is_rejected']].copy()
    detail_cols = [c for c in DETAIL_COLS if c in rejected.columns]

    meta = pd.DataFrame([{
        'GeneratedAt': dt.now().strftime('%Y-%m-%d %H:%M:%S'),
        'TotalActivities': len(df),
        'TotalRejected': int(df['_is_rejected'].sum()),
        'RejectedUnpaid': int(df['_is_rejected_unpaid'].sum()),
        'PaidFormula': 'actRemitInsShare + actResub1RemitInsShare + actResub2RemitInsShare + actResub3RemitInsShare + TKBKAmountAct',
        'BalanceFormula': 'ActivityIns - Paid',
        'RejectionRule': "Status starts with 'Rejected'",
    }])

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine='openpyxl') as writer:
        rejection_summary(df).to_excel(writer, sheet_name='Rejection_Summary', index=False)
        top_denials(df, 10).to_excel(writer, sheet_name='Top_Denials', index=False)
        summarize_by(df, COL_STATUS).to_excel(writer, sheet_name='Status_Summary', index=False)
        summarize_by(rejected, COL_DENIAL).to_excel(writer, sheet_name='By_DenialCode', index=False)
        summarize_by(rejected, COL_INSURANCE).to_excel(writer, sheet_name='By_Insurance', index=False)
        rejected[detail_cols].to_excel(writer, sheet_name='Rejected_Detail', index=False)
        meta.to_excel(writer, sheet_name='Meta', index=False)
    return style_excel(buf.getvalue())


for key, default in {
    'processed_data': None,
    'processed_filename': None,
    'processed_time': None,
    'report_bytes': None,
}.items():
    if key not in st.session_state:
        st.session_state[key] = default

st.markdown('## Professional Rejection Analysis')
st.caption('Paid = actRemitInsShare + actResub1RemitInsShare + actResub2RemitInsShare + actResub3RemitInsShare + TKBKAmountAct')
st.caption("Balance = ActivityIns - Paid | Rejection = Status starts with 'Rejected'")

uploaded = st.file_uploader('Upload ClaimComparison Excel', type=['xlsx'])

c1, c2 = st.columns(2)
with c1:
    process_clicked = st.button('Process File', type='primary', use_container_width=True, disabled=uploaded is None)
with c2:
    clear_clicked = st.button('Clear Previous Results', use_container_width=True)

if clear_clicked:
    for key in ['processed_data', 'processed_filename', 'processed_time', 'report_bytes']:
        st.session_state[key] = None
    st.rerun()

if process_clicked and uploaded is not None:
    try:
        with st.spinner('Reading and analyzing rejection data...'):
            df = load_and_prepare(uploaded.getvalue())
            st.session_state.processed_data = df
            st.session_state.processed_filename = uploaded.name
            st.session_state.processed_time = dt.now()
            st.session_state.report_bytes = build_report(df)
        st.success('File processed successfully.')
    except Exception as exc:
        st.error(f'Could not process the file: {exc}')

if st.session_state.processed_data is None:
    st.info('Upload a file and click Process File. Previous results remain visible until another file is processed or cleared.')
    st.stop()

df = st.session_state.processed_data
rejected = df[df['_is_rejected']].copy()

st.markdown(f"**Processed file:** {st.session_state.processed_filename}  \n**Processed at:** {st.session_state.processed_time:%d-%b-%Y %I:%M %p}")

st.markdown('### Executive Rejection Summary')
k1, k2, k3, k4, k5 = st.columns(5)
k1.metric('Total Activities', f'{len(df):,}', fmt_aed(df[COL_AMOUNT].sum()))
k2.metric('Rejected Activities', f'{len(rejected):,}', fmt_aed(rejected[COL_AMOUNT].sum()))
k3.metric('Rejected & Unpaid', f"{int(df['_is_rejected_unpaid'].sum()):,}", fmt_aed(df.loc[df['_is_rejected_unpaid'], 'Balance'].sum()))
k4.metric('Paid on Rejections', fmt_aed(rejected['Paid'].sum()))
k5.metric('Rejected Balance', fmt_aed(rejected['Balance'].sum()))

st.markdown('### Most Common Denial Codes')
top_n = st.slider('Number of denial codes to show', 5, 20, 10)
top_df = top_denials(df, top_n)
if top_df.empty:
    st.warning('No denial codes were found for rejected activities.')
else:
    st.dataframe(top_df, use_container_width=True, hide_index=True)
    st.bar_chart(top_df.set_index(COL_DENIAL)[['Count']])

st.download_button(
    'Download Professional Rejection Report',
    data=st.session_state.report_bytes,
    file_name=f'Professional_Rejection_Report_{dt.now():%Y%m%d_%H%M}.xlsx',
    mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    use_container_width=True,
)

st.divider()

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    'Rejection Summary', 'Status Summary', 'Denial Analysis', 'Insurance Analysis', 'Rejected Detail'
])

with tab1:
    st.dataframe(rejection_summary(df), use_container_width=True, hide_index=True)

with tab2:
    status_summary = summarize_by(df, COL_STATUS)
    status_summary['_priority'] = status_summary[COL_STATUS].str.lower().apply(
        lambda x: 0 if x.startswith('rejected') else 1 if 'resub' in x else 2
    )
    status_summary = status_summary.sort_values(['_priority', 'Amount'], ascending=[True, False]).drop(columns='_priority')
    st.dataframe(status_summary, use_container_width=True, hide_index=True)

with tab3:
    ins_filter = st.selectbox('Filter by insurance', ['All'] + sorted(rejected[COL_INSURANCE].unique().tolist()))
    temp = rejected if ins_filter == 'All' else rejected[rejected[COL_INSURANCE] == ins_filter]
    st.dataframe(summarize_by(temp, COL_DENIAL), use_container_width=True, hide_index=True)

with tab4:
    st.dataframe(summarize_by(rejected, COL_INSURANCE), use_container_width=True, hide_index=True)

with tab5:
    s1, s2, s3 = st.columns(3)
    status_filter = s1.selectbox('Status', ['All'] + sorted(rejected[COL_STATUS].unique().tolist()))
    insurance_filter = s2.selectbox('Insurance', ['All'] + sorted(rejected[COL_INSURANCE].unique().tolist()))
    denial_filter = s3.selectbox('Denial Code', ['All'] + sorted(rejected[COL_DENIAL].unique().tolist()))

    detail = rejected.copy()
    if status_filter != 'All':
        detail = detail[detail[COL_STATUS] == status_filter]
    if insurance_filter != 'All':
        detail = detail[detail[COL_INSURANCE] == insurance_filter]
    if denial_filter != 'All':
        detail = detail[detail[COL_DENIAL] == denial_filter]

    c1, c2 = st.columns(2)
    unpaid_only = c1.checkbox('Show unpaid only')
    positive_balance_only = c2.checkbox('Show positive balance only')
    if unpaid_only:
        detail = detail[detail['Paid'].eq(0)]
    if positive_balance_only:
        detail = detail[detail['Balance'].gt(0)]

    cols = [c for c in DETAIL_COLS if c in detail.columns]
    st.caption(
        f"{len(detail):,} activities | Amount: {fmt_aed(detail[COL_AMOUNT].sum())} | "
        f"Paid: {fmt_aed(detail['Paid'].sum())} | Balance: {fmt_aed(detail['Balance'].sum())}"
    )
    st.dataframe(detail[cols], use_container_width=True, hide_index=True)
