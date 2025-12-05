# ---------- Admin tools ----------
if mode == "admin" and admin_ok:
    with st.expander("⬆️ Upload/replace source Excel", expanded=False):
        up = st.file_uploader("Upload .xlsx", type=["xlsx"])
        if up:
            cfg["source"].write_bytes(up.read())
            st.success(f"Saved to {cfg['source'].name}")

    col1, col2 = st.columns(2)
    if col1.button("↻ Rebuild report", use_container_width=True):
        try:
            out = rebuild(cfg)
            st.success("Report rebuilt successfully.")
            if out.strip():
                st.code(out, language="bash")
            load_report.clear()
        except Exception as e:
            st.error(str(e))
    if col2.button("🗂 Show file locations", use_container_width=True):
        st.info(f"Source: {cfg['source']}\nReport: {cfg['report']}\nScript: {GENERATOR}")

