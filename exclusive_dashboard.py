    with t3:
        st.caption("Loads only when you click, to keep things fast.")
        if st.button("Load Balance_Aging_Detail (paged, memory-safe)"):
            try:
                detail_sheet2 = s_det or SHEET_DETAIL
                if not detail_sheet2 or detail_sheet2 not in available:
                    raise RuntimeError(f"Detail sheet not found. Available: {', '.join(available)}")

                # Read just header to get total rows & columns
                head = pd.read_excel(str(out_path), sheet_name=detail_sheet2, engine="openpyxl", nrows=0)
                all_cols = list(head.columns.astype(str))

                # How many rows are there? (cheap: read only the first column to count)
                first_col = all_cols[0]
                col_only = pd.read_excel(
                    str(out_path), sheet_name=detail_sheet2, engine="openpyxl",
                    usecols=[first_col], dtype=str
                )
                total_rows = len(col_only)
                st.info(f"Rows in sheet: {total_rows:,}")

                # Controls
                page_size = st.number_input("Rows per page", min_value=100, max_value=20000, step=1000, value=5000)
                max_page = max(1, (total_rows + page_size - 1) // page_size)
                page = st.number_input("Page", min_value=1, max_value=max_page, step=1, value=1)

                start = (page - 1) * page_size          # 0-based data row index
                # skiprows: 0 is header, data starts at 1
                skip = list(range(1, 1 + start))        # skip rows before our page
                nrows = min(page_size, total_rows - start)

                # Optional: narrow to display columns if you like (kept full here)
                df_page = pd.read_excel(
                    str(out_path), sheet_name=detail_sheet2, engine="openpyxl",
                    skiprows=skip, nrows=nrows
                )

                # Apply active date filter (on the page only) if present
                if st.session_state.date_filter_active and date_col and date_col in df_page.columns:
                    s_dates3 = pd.to_datetime(df_page[date_col], errors="coerce")
                    mask3 = (s_dates3.dt.date >= (st.session_state.date_filter_start or date.min)) & \
                            (s_dates3.dt.date <= (st.session_state.date_filter_end or date.max))
                    df_page = df_page.loc[mask3].copy()

                df_page = trim_empty_rows(df_page)
                df_page.index = range(start + 1, start + 1 + len(df_page))
                st.dataframe(df_page, use_container_width=True, height=full_height(df_page))

                # Downloads
                dl1, dl2 = st.columns(2)
                with dl1:
                    st.download_button(
                        "⬇️ Download full report (.xlsx)",
                        out_path.read_bytes(),
                        file_name=out_path.name,
                        use_container_width=True,
                        key=f"dl_xlsx_detail_{ck}_{st.session_state.year}"
                    )
                with dl2:
                    st.download_button(
                        "⬇️ Export this page (CSV)",
                        df_page.to_csv(index=False).encode("utf-8"),
                        file_name=f"{cfg['key']}_{st.session_state.year}_detail_p{page}.csv",
                        use_container_width=True,
                        key=f"dl_csv_detail_{ck}_{st.session_state.year}_p{page}"
                    )
            except Exception as e:
                st.error(str(e))


