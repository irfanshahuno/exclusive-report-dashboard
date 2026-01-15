# ====================== ROUTE: Rejection page (lazy-load) ======================
if st.query_params.get("view") == "rejection":
    from rejection_view import render_rejection_page

    ck = st.session_state.get("center_key")
    yy = st.session_state.get("year")

    if ck not in CENTERS or yy is None:
        st.warning("Please select center and year first.")
        st.stop()

    cfg_r = CENTERS[ck]
    folder_r = cfg_r["folder_root"] / str(yy)
    folder_r.mkdir(parents=True, exist_ok=True)
    src_r = resolve_source_path(folder_r, preferred=cfg_r["src_name"])

    # Back button: remove view param only
    if st.button("⬅ Back to Dashboard", use_container_width=False, key="back_from_rej"):
        try:
            if "view" in st.query_params:
                del st.query_params["view"]
        except Exception:
            pass
        st.rerun()

    render_rejection_page(
        center_key=ck,
        center_name=cfg_r["name"],
        year=yy,
        src_path=str(src_r),
    )
    st.stop()
# ==============================================================================

