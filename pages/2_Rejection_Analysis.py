def render_main_kpis(stats, df_by_ins: pd.DataFrame, df_full_detail: pd.DataFrame):

    st.markdown("""
    <style>
    .kpi-box {
        background: white;
        border: 1px solid #e6ebf2;
        border-radius: 16px;
        padding: 18px 20px;
        box-shadow: 0 4px 14px rgba(15,23,42,0.06);
    }
    .kpi-title {
        font-size: 13px;
        color: #64748b;
        margin-bottom: 6px;
        font-weight: 600;
    }
    .kpi-value {
        font-size: 30px;
        font-weight: 900;
        color: #0f172a;
        line-height: 1.1;
    }
    .kpi-sub {
        font-size: 12px;
        color: #94a3b8;
        margin-top: 6px;
    }
    .kpi-chip {
        display: inline-block;
        margin-top: 10px;
        padding: 6px 14px;
        border-radius: 999px;
        background: #f1f5f9;
        color: #334155;
        font-size: 12px;
        font-weight: 800;
    }
    </style>
    """, unsafe_allow_html=True)

    # ---------- calculations ----------
    tmp = df_by_ins.copy()
    tmp = tmp[tmp["Insurance"].astype(str).str.lower() != "grand total"]

    tmp["RejectedAmount"] = pd.to_numeric(tmp["RejectedAmount"], errors="coerce").fillna(0)
    tmp["RejectedCount"] = pd.to_numeric(tmp["RejectedCount"], errors="coerce").fillna(0)

    total_amt = float(tmp["RejectedAmount"].sum())
    total_cnt = int(tmp["RejectedCount"].sum())

    top3 = tmp.sort_values("RejectedAmount", ascending=False).head(3)

    def get_top(i):
        if len(top3) > i:
            return top3.iloc[i]["Insurance"], float(top3.iloc[i]["RejectedAmount"])
        return "-", 0

    ins1, amt1 = get_top(0)
    ins2, amt2 = get_top(1)
    ins3, amt3 = get_top(2)

    # =============================
    # ROW 1 — CORE KPIs
    # =============================
    c1, c2, c3 = st.columns(3)

    with c1:
        st.markdown(f"""
        <div class="kpi-box">
            <div class="kpi-title">Rejected Rows</div>
            <div class="kpi-value">{stats['rejected_rows']:,}</div>
            <div class="kpi-sub">Paid = 0 • Status = Rejected • DenialCode not empty</div>
        </div>
        """, unsafe_allow_html=True)

    with c2:
        st.markdown(f"""
        <div class="kpi-box">
            <div class="kpi-title">Total Rejected Amount</div>
            <div class="kpi-value">AED {total_amt:,.2f}</div>
            <div class="kpi-sub">All insurers (excluding Grand Total)</div>
        </div>
        """, unsafe_allow_html=True)

    with c3:
        st.markdown(f"""
        <div class="kpi-box">
            <div class="kpi-title">Total Rejected Claims</div>
            <div class="kpi-value">{total_cnt:,}</div>
            <div class="kpi-sub">Total rejected activities</div>
        </div>
        """, unsafe_allow_html=True)

    # =============================
    # ROW 2 — TOP INSURERS
    # =============================
    st.markdown("### 🔝 Top Insurances by Rejected Amount")

    t1, t2, t3 = st.columns(3)

    with t1:
        st.markdown(f"""
        <div class="kpi-box">
            <div class="kpi-title">Top Insurance #1</div>
            <div class="kpi-value">{ins1}</div>
            <div class="kpi-chip">AED {amt1:,.2f}</div>
        </div>
        """, unsafe_allow_html=True)

    with t2:
        st.markdown(f"""
        <div class="kpi-box">
            <div class="kpi-title">Top Insurance #2</div>
            <div class="kpi-value">{ins2}</div>
            <div class="kpi-chip">AED {amt2:,.2f}</div>
        </div>
        """, unsafe_allow_html=True)

    with t3:
        st.markdown(f"""
        <div class="kpi-box">
            <div class="kpi-title">Top Insurance #3</div>
            <div class="kpi-value">{ins3}</div>
            <div class="kpi-chip">AED {amt3:,.2f}</div>
        </div>
        """, unsafe_allow_html=True)
