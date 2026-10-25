"""EMC Revenue Scorecard - Streamlit app.

Page of the exclusive-report-dashboard app (emc_logic.py sits in the repo root).
Upload the raw HIS ProcedureDetails report; it is corrected, scored and can be emailed to management.
"""
import sys
from pathlib import Path

import streamlit as st

for _p in (Path(__file__).resolve().parent, Path(__file__).resolve().parents[1]):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
import emc_logic as L  # noqa: E402

st.set_page_config(page_title="EMC Revenue Scorecard", page_icon="🏏", layout="wide")
st.markdown("""<style>
.ball{display:inline-block;width:15px;height:15px;border-radius:50%;margin:1px;font:700 9px/15px sans-serif;text-align:center;color:#fff;vertical-align:middle;box-sizing:border-box}
.b0{border:1.5px solid #B9C3BC}.b4{background:#2F5FC9}.b6{background:#1E6A49}
</style>""", unsafe_allow_html=True)

st.title("EMC Revenue Scorecard")
st.caption("Upload the HIS ProcedureDetails report (coded or not coded). It is corrected automatically and scored ball by ball.")

c1, c2 = st.columns([3, 2])
up = c1.file_uploader("ProcedureDetails file", type=["xlsx", "xls"])
check = c2.radio("Check", list(L.PACE), index=3, horizontal=True)

if not up:
    st.info("Upload a ProcedureDetails report to see the scorecard.")
    st.stop()

try:
    lines = L.read_report(up.getvalue(), up.name)
except Exception as e:  # noqa: BLE001
    st.error(f'Could not read "{up.name}". {e}')
    st.stop()

visits, logdf, dates = L.correct(lines)
ddf, idf, itdf, strips = L.summarize(visits, L.PACE[check])
meta = f"Date {', '.join(dates)} · {len(visits)} patients · file {up.name}"
st.caption(meta)

clinic = ddf[ddf["Doctor"] == "Clinic"].iloc[0]
k1, k2, k3, k4 = st.columns(4)
k1.metric("Clinic runs", f'{clinic["Runs"]:,.0f}', f'{clinic["Runs"] - clinic["Runs needed"]:+,.0f} vs {check} pace')
k2.metric("Scoring balls", int(clinic["Scoring"]), f'{int(clinic["Scoring"] - clinic["Scoring needed"]):+d} vs {check} pace')
k3.metric("Balls faced", int(clinic["Balls"]))
k3.caption(f"{int(clinic['Dots'])} dots")
k4.metric("Runs per ball", f'{clinic["Runs"] / max(clinic["Balls"], 1):,.0f}')

tab1, tab2, tab3, tab4, tab5 = st.tabs(["Scorecard", "By insurance", "Labs and procedures", "Corrections", "Email"])


def color_status(v):
    c = L.STATUS_COLORS.get(v)
    return f"background-color:{c[0]};color:{c[1]};font-weight:bold" if c else ""


with tab1:
    show = ddf[["Doctor", "Balls", "Dots", "4s", "6s", "Scoring", "Scoring needed", "Runs", "Runs needed", "% of day", "Status", "Scoring still needed"]]
    st.dataframe(show.style.map(color_status, subset=["Status"]).format({"Runs": "{:,.0f}", "Runs needed": "{:,.0f}"}),
                 hide_index=True, width="stretch")
    st.caption("Dot = consultation only · 4 = one lab or procedure · 6 = two or more. Runs = insurance money after copay; cash at other-insurer prices. "
               "Target per GP: 34 balls, 22 scoring balls, 3,388 runs; Family Medicine 30 balls, 3,592 runs.")
    st.subheader("Ball by ball")
    for doc, balls in strips.items():
        dots = "".join(f'<span class="ball b{b}">{b if b else ""}</span>' for b in balls)
        st.markdown(f"**{doc}**<br>{dots}", unsafe_allow_html=True)

with tab2:
    for doc, g in idf.groupby("Doctor", sort=True):
        st.markdown(f"**{doc}**")
        st.dataframe(g.drop(columns="Doctor"), hide_index=True, width="stretch")

with tab3:
    st.caption("Blood collection (36415) is part of the lab and not counted as a ball.")
    for doc, g in itdf.groupby("Doctor", sort=True) if len(itdf) else []:
        st.markdown(f"**{doc}**")
        st.dataframe(g.drop(columns="Doctor"), hide_index=True, width="stretch")

with tab4:
    st.caption("Daman level 3 (99213 = 95, 99203 = 142); other insurers level 2 (99212 = 56, 99202 = 98); one consultation "
               "line per visit; labs at 0 priced from the Daman list; medicine max 3 AED; free follow-ups as billed; cash priced as other insurers (level 2, same lab and procedure prices).")
    if len(logdf):
        st.dataframe(logdf, hide_index=True, width="stretch")
    else:
        st.write("Nothing to correct in this report.")

xlsx = L.to_excel(ddf, idf, itdf, logdf, meta)
st.download_button("Download Excel", xlsx, file_name=f"EMC_Scorecard_{dates[0] if dates else ''}_{check.replace(' ', '')}.xlsx",
                   mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

with tab5:
    import os

    def _secret(name, default=""):
        try:
            if name in st.secrets:
                return str(st.secrets[name])
        except Exception:  # no secrets file
            pass
        return os.environ.get(name, default)

    smtp = {"host": _secret("SMTP_HOST"), "port": _secret("SMTP_PORT", "465"),
            "user": _secret("SMTP_USER"), "password": _secret("SMTP_PASS")}
    if not (smtp["host"] and smtp["user"] and smtp["password"]):
        smtp = {}
    default_to = _secret("EMAIL_TO")
    to = st.text_input("Send to (comma separated)", value=default_to)
    cc = st.text_input("CC (comma separated)", value=_secret("EMAIL_CC"))
    subject = st.text_input("Subject", value=f"EMC Revenue Scorecard - {', '.join(dates)} - {check} check")
    html = L.email_html(ddf, idf, itdf, logdf, meta, check)
    with st.expander("Preview email"):
        st.html(html)
    if not smtp:
        st.warning("Email is not set up yet. Add SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS and EMAIL_TO in the app\'s Settings → Secrets.")
    elif st.button("Send to management", type="primary"):
        recipients = [x.strip() for x in to.split(",") if x.strip()]
        if not recipients:
            st.error("Add at least one email address.")
        else:
            try:
                L.send_email(smtp, recipients, subject, html, xlsx,
                             f"EMC_Scorecard_{dates[0] if dates else ''}_{check.replace(' ', '')}.xlsx",
                             [x.strip() for x in cc.split(",") if x.strip()])
                st.success(f"Sent to {', '.join(recipients)}.")
            except Exception as e:  # noqa: BLE001
                st.error(f"Email not sent: {e}")
