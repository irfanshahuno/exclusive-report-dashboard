import streamlit as st

st.set_page_config(page_title="Exclusive Report Dashboard", layout="wide")

# ---- Password Gate (only once per session) ----
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.title("Login")
    pwd = st.text_input("Enter password", type="password")
    if pwd == "Emc@2026":
        st.session_state.authenticated = True
        st.rerun()
    st.stop()

# ---- Main Tabs ----
tab1, tab2 = st.tabs(["Dashboard", "Rejections"])

with tab1:
    # This will run your existing dashboard file
    import exclusive_dashboard  # keep your current dashboard code there

with tab2:
    from rejection_streamlit import run_rejection_app
    run_rejection_app()
