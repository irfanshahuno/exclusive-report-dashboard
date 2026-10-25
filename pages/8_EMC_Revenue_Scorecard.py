"""EMC Revenue Scorecard - Streamlit page.

Page of the exclusive-report-dashboard app (emc_logic.py sits in the repo root).
Upload the raw HIS ProcedureDetails report; it is corrected, scored ball by ball and can be emailed to management.
"""
import html as _h
import os
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

for _p in (Path(__file__).resolve().parent, Path(__file__).resolve().parents[1]):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
import emc_logic as L  # noqa: E402

st.set_page_config(page_title="EMC Revenue Scorecard", page_icon="🏏", layout="wide")

# ---------------------------------------------------------------- style
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Barlow+Semi+Condensed:wght@500;600;700&family=IBM+Plex+Sans:wght@400;500;600&display=swap');
:root{
  --ink:#18211C; --muted:#5D6A62; --line:#E1E6E0; --soft:#F2F5F1; --card:#FFFFFF;
  --pitch:#1E6A49; --pitch-soft:#E3F1E9; --four:#2F5FC9; --dot:#C3CCC5;
  --ok:#1E7A45; --ok-bg:#E2F3E8; --warn:#9A6200; --warn-bg:#FBF0D9; --bad:#B3261E; --bad-bg:#FBE4E1;
}
html, body, [class*="css"], .stMarkdown, .stText, p, li, label, input, button, textarea {font-family:'IBM Plex Sans', system-ui, sans-serif;}
.block-container{padding-top:1.6rem; max-width:1280px;}
h1,h2,h3{font-family:'Barlow Semi Condensed', 'Arial Narrow', sans-serif !important; letter-spacing:.01em;}

/* hero */
.hero{background:linear-gradient(135deg,#123F2C 0%,#1E6A49 70%,#2A7F59 100%); color:#fff; border-radius:16px;
      padding:26px 30px; display:flex; justify-content:space-between; align-items:flex-end; flex-wrap:wrap; gap:16px; margin-bottom:18px;}
.hero h1{color:#fff !important; font-size:38px; margin:0; line-height:1.05; padding:0;}
.hero p{color:#CFE6D9; margin:6px 0 0; font-size:14px;}
.hero .chips{display:flex; gap:8px; flex-wrap:wrap;}
.chip{background:rgba(255,255,255,.14); border:1px solid rgba(255,255,255,.22); color:#fff; padding:5px 12px;
      border-radius:999px; font-size:12.5px; font-weight:500; white-space:nowrap;}

/* KPI tiles */
.kpis{display:grid; grid-template-columns:repeat(auto-fit,minmax(210px,1fr)); gap:14px; margin:6px 0 18px;}
.kpi{background:var(--card); border:1px solid var(--line); border-radius:14px; padding:16px 18px;}
.kpi .lbl{font-size:11px; text-transform:uppercase; letter-spacing:.09em; color:var(--muted); font-weight:600;}
.kpi .val{font-family:'Barlow Semi Condensed',sans-serif; font-size:36px; font-weight:700; color:var(--ink); line-height:1.1; margin-top:4px;}
.kpi .val small{font-size:17px; color:var(--muted); font-weight:500;}
.kpi .sub{font-size:12.5px; color:var(--muted); margin-top:2px;}
.bar{height:6px; background:var(--soft); border-radius:4px; margin-top:10px; overflow:hidden;}
.bar i{display:block; height:100%; border-radius:4px; background:var(--pitch);}

/* doctor cards */
.docs{display:grid; grid-template-columns:repeat(auto-fill,minmax(360px,1fr)); gap:16px; margin-top:4px;}
.doc{background:var(--card); border:1px solid var(--line); border-radius:16px; padding:18px 20px; box-shadow:0 1px 2px rgba(24,33,28,.04);}
.doc .top{display:flex; justify-content:space-between; align-items:flex-start; gap:10px;}
.doc .name{font-family:'Barlow Semi Condensed',sans-serif; font-size:21px; font-weight:700; color:var(--ink); line-height:1.15;}
.doc .role{font-size:12px; color:var(--muted);}
.pill{display:inline-block; font-size:11px; font-weight:700; letter-spacing:.07em; padding:4px 10px; border-radius:999px; white-space:nowrap;}
.p-ON{background:var(--ok-bg); color:var(--ok);} .p-WATCH{background:var(--warn-bg); color:var(--warn);} .p-CHECK{background:var(--bad-bg); color:var(--bad);}
.score{display:flex; align-items:baseline; gap:8px; margin:12px 0 2px;}
.score .runs{font-family:'Barlow Semi Condensed',sans-serif; font-size:40px; font-weight:700; color:var(--ink); line-height:1;}
.score .of{font-size:13px; color:var(--muted);}
.stats{display:grid; grid-template-columns:repeat(5,1fr); gap:6px; margin:14px 0 10px;}
.stat{background:var(--soft); border-radius:10px; padding:8px 6px; text-align:center;}
.stat b{display:block; font-family:'Barlow Semi Condensed',sans-serif; font-size:21px; color:var(--ink); line-height:1.1;}
.stat span{font-size:10.5px; color:var(--muted); text-transform:uppercase; letter-spacing:.06em;}
.stat.f b{color:var(--four);} .stat.s b{color:var(--pitch);}
.strip{display:flex; flex-wrap:wrap; gap:3px; margin-top:6px;}
.ball{width:15px; height:15px; border-radius:50%; font:700 8.5px/15px 'IBM Plex Sans',sans-serif; text-align:center; color:#fff; box-sizing:border-box;}
.b0{border:1.5px solid var(--dot);} .b4{background:var(--four);} .b6{background:var(--pitch);}
.need{font-size:12.5px; color:var(--muted); margin-top:10px;}
.need b{color:var(--ink);}
.made{font-size:12.5px; color:var(--muted); margin-top:10px; line-height:1.6;}
.made b{color:var(--ink); font-weight:600;}
.ball{cursor:default;}
.tag4{color:var(--four); font-weight:700;} .tag6{color:var(--pitch); font-weight:700;}
.sl{display:grid; gap:8px; padding:4px 0 6px;}
.sr{display:grid; grid-template-columns:34px 150px 1fr 70px; gap:14px; align-items:center; background:var(--card);
    border:1px solid var(--line); border-radius:12px; padding:10px 14px;}
.bb{width:30px; height:30px; border-radius:50%; color:#fff; font:700 14px/30px 'Barlow Semi Condensed',sans-serif; text-align:center;}
.bb.b4{background:var(--four);} .bb.b6{background:var(--pitch);}
.sr-id b{display:block; font-size:13.5px; color:var(--ink); font-variant-numeric:tabular-nums;}
.sr-id span{font-size:12px; color:var(--muted);}
.sr-items{display:flex; flex-wrap:wrap; gap:6px;}
.chip-i{font-size:12.5px; padding:4px 10px; border-radius:999px; font-weight:500; white-space:nowrap;}
.chip-i em{font-style:normal; font-weight:700; margin-left:4px; opacity:.85;}
.chip-i.lab{background:#E8EEFB; color:#2546A0;} .chip-i.proc{background:var(--pitch-soft); color:#17553A;}
.sr-runs{text-align:right; font-family:'Barlow Semi Condensed',sans-serif; font-size:20px; font-weight:700; color:var(--ink); line-height:1;}
.sr-runs span{display:block; font-family:'IBM Plex Sans',sans-serif; font-size:10.5px; font-weight:500; color:var(--muted); text-transform:uppercase; letter-spacing:.06em;}
.tbl td.nm,.tbl th.nm{text-align:left; color:var(--muted); font-size:12.5px; white-space:normal; min-width:180px;}
.tbl.ins td.nm{color:#33413A;}

/* tables */
.tbl{width:100%; border-collapse:separate; border-spacing:0; background:var(--card); border:1px solid var(--line); border-radius:12px; overflow:hidden; font-size:13.5px; margin-bottom:18px;}
.tbl th{background:var(--soft); color:var(--muted); font-size:11px; text-transform:uppercase; letter-spacing:.07em; font-weight:600; padding:9px 12px; text-align:right; border-bottom:1px solid var(--line);}
.tbl td{padding:9px 12px; text-align:right; border-bottom:1px solid var(--line); color:var(--ink); font-variant-numeric:tabular-nums;}
.tbl th:first-child,.tbl td:first-child{text-align:left;}
.tbl tr:last-child td{border-bottom:0;}
.tbl tr.tot td{font-weight:600; background:var(--soft);}
.tbl .c4{color:var(--four); font-weight:600;} .tbl .c6{color:var(--pitch); font-weight:600;}
.sec{font-family:'Barlow Semi Condensed',sans-serif; font-size:19px; font-weight:700; color:var(--ink); margin:14px 0 8px;}
.legend{display:flex; gap:16px; flex-wrap:wrap; font-size:12.5px; color:var(--muted); align-items:center; margin:2px 0 12px;}
.legend span{display:inline-flex; gap:6px; align-items:center;}
.note{font-size:12.5px; color:var(--muted);}
.empty{background:var(--card); border:1.5px dashed var(--line); border-radius:16px; padding:34px; text-align:center; color:var(--muted);}
.empty b{display:block; font-family:'Barlow Semi Condensed',sans-serif; font-size:22px; color:var(--ink); margin-bottom:6px;}
div[data-testid="stTabs"] button p{font-weight:600;}
</style>
""", unsafe_allow_html=True)

E = _h.escape


def fmt(n):
    return f"{n:,.0f}"


def table(df, cols, money=(), four="4s", six="6s", total_key=None):
    th = "".join(f"<th>{E(c)}</th>" for c in cols)
    body = ""
    for _, r in df.iterrows():
        tot = total_key is not None and str(r[cols[0]]) == total_key
        tds = ""
        for c in cols:
            v = r[c]
            if v is None or (isinstance(v, float) and pd.isna(v)):
                v = "–"
            elif c in money:
                v = fmt(v)
            cls = ' class="c4"' if c == four else ' class="c6"' if c == six else ""
            tds += f"<td{cls}>{E(str(v))}</td>"
        body += f'<tr{" class=tot" if tot else ""}>{tds}</tr>'
    return f'<table class="tbl"><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table>'


# ---------------------------------------------------------------- header + controls
up_col, chk_col = st.columns([3, 2], vertical_alignment="bottom")
with up_col:
    up = st.file_uploader("HIS ProcedureDetails report", type=["xlsx", "xls"],
                          help="Coded or not coded. The file is corrected automatically.")
with chk_col:
    if hasattr(st, "segmented_control"):
        check = st.segmented_control("Check", list(L.PACE), default="Closing") or "Closing"
    else:
        check = st.radio("Check", list(L.PACE), index=3, horizontal=True)

lines = None
if up:
    try:
        lines = L.read_report(up.getvalue(), up.name)
    except Exception as e:  # noqa: BLE001
        st.error(f'Could not read "{up.name}". {e}')

if lines is None:
    st.markdown("""
    <div class="hero"><div><h1>EMC Revenue Scorecard</h1>
    <p>Every patient is a ball. Dot = consultation only · 4 = one lab or procedure · 6 = two or more.</p></div>
    <div class="chips"><span class="chip">Daman level 3</span><span class="chip">Others level 2</span><span class="chip">Insurance money after copay</span></div></div>
    <div class="empty"><b>Upload today's ProcedureDetails report</b>
    Export it from Cortex, drop it above and pick the check time. The scorecard, insurance view, labs and procedures and the email are built from it.</div>
    """, unsafe_allow_html=True)
    st.stop()

visits, logdf, dates = L.correct(lines)
ddf, idf, itdf, strips = L.summarize(visits, L.PACE[check])
meta = f"Date {', '.join(dates)} · {len(visits)} patients · file {up.name}"
clinic = ddf[ddf["Doctor"] == "Clinic"].iloc[0]
docs = ddf[ddf["Doctor"] != "Clinic"]
doc_visits = {}
for _v in visits:
    doc_visits.setdefault(_v["doctor"], []).append(_v)


def items_text(v):
    return " + ".join(f'{L.item_name(c["code"], c["name"])} ({round(c["ins"], 2):g})' for c in v["items"])


def money(x):
    x = round(float(x), 2)
    return f"{x:,.0f}" if x == int(x) else f"{x:,.2f}".rstrip("0").rstrip(".")


def chips(v):
    out = []
    for c in v["items"]:
        kind = "lab" if c["type"] in ("LAB", "RADIOLOGY") else "proc"
        out.append(f'<span class="chip-i {kind}">{E(L.item_name(c["code"], c["name"]))} <em>{money(c["ins"])}</em></span>')
    return "".join(out)


def agg_names(vs):
    cnt = {}
    for v in vs:
        for c in v["items"]:
            key = (L.item_name(c["code"], c["name"]), round(c["ins"], 2))
            cnt[key] = cnt.get(key, 0) + 1
    return ", ".join(f"{n} ({money(pr)})" + (f" ×{k}" if k > 1 else "")
                     for (n, pr), k in sorted(cnt.items(), key=lambda x: (-x[1], x[0][0])))


def top_items(vs, n=6):
    cnt, amt = {}, {}
    for v in vs:
        for c in v["items"]:
            nm = L.item_name(c["code"], c["name"])
            cnt[nm] = cnt.get(nm, 0) + 1
            amt[nm] = amt.get(nm, 0) + c["ins"]
    return [(f"{nm} ({money(amt[nm] / k)})", k) for nm, k in sorted(cnt.items(), key=lambda x: -x[1])[:n]]

st.markdown(f"""
<div class="hero"><div><h1>EMC Revenue Scorecard</h1>
<p>{E(', '.join(dates))} &nbsp;·&nbsp; {len(visits)} patients &nbsp;·&nbsp; {len(docs)} doctors &nbsp;·&nbsp; {E(check)} check</p></div>
<div class="chips"><span class="chip">{len(logdf)} corrections applied</span><span class="chip">{E(up.name)}</span></div></div>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------- KPIs
runs_ratio = clinic["Runs"] / max(clinic["Runs needed"], 1)
score_ratio = clinic["Scoring"] / max(clinic["Scoring needed"], 1)
st.markdown(f"""
<div class="kpis">
 <div class="kpi"><div class="lbl">Clinic runs</div><div class="val">{fmt(clinic["Runs"])} <small>/ {fmt(clinic["Runs needed"])}</small></div>
  <div class="sub">{runs_ratio:.0%} of the {E(check)} pace</div><div class="bar"><i style="width:{min(runs_ratio,1)*100:.0f}%"></i></div></div>
 <div class="kpi"><div class="lbl">Scoring balls</div><div class="val">{int(clinic["Scoring"])} <small>/ {int(clinic["Scoring needed"])}</small></div>
  <div class="sub">{int(clinic["4s"])} fours · {int(clinic["6s"])} sixes</div><div class="bar"><i style="width:{min(score_ratio,1)*100:.0f}%;background:#2F5FC9"></i></div></div>
 <div class="kpi"><div class="lbl">Balls faced</div><div class="val">{int(clinic["Balls"])}</div>
  <div class="sub">{int(clinic["Dots"])} dots · {clinic["Dots"] / max(clinic["Balls"],1):.0%} consultation only</div></div>
 <div class="kpi"><div class="lbl">Runs per ball</div><div class="val">{clinic["Runs"] / max(clinic["Balls"],1):,.0f} <small>AED</small></div>
  <div class="sub">Insurance money per patient</div></div>
</div>
""", unsafe_allow_html=True)

tab1, tab2, tab3, tab4, tab5 = st.tabs(["Scorecard", "By insurance", "Labs and procedures", "Corrections", "Email"])

# ---------------------------------------------------------------- scorecard
with tab1:
    st.markdown("""<div class="legend"><span><i class="ball b0"></i>Dot · consultation only</span>
    <span><i class="ball b4">4</i>One lab or procedure</span><span><i class="ball b6">6</i>Two or more</span></div>""",
                unsafe_allow_html=True)
    cards = ""
    for _, d in docs.sort_values("% of day", ascending=False).iterrows():
        key = str(d["Doctor"]).replace(" (FM)", "")
        vs = doc_visits.get(key, [])
        strip = "".join(
            f'<i class="ball b{v["ball"]}" title="{E(v["insurance"])} · EMR {E(v.get("emr") or v["inv"])} · '
            f'{E(items_text(v) or "consultation only")} · {fmt(v["runs"])} AED">{v["ball"] if v["ball"] else ""}</i>'
            for v in vs)
        tops = top_items(vs)
        made = " · ".join(f"<b>{E(n)}</b> ×{k}" for n, k in tops) if tops else "No labs or procedures yet"
        st_cls = str(d["Status"]).split()[0]
        need = int(d["Scoring still needed"]) if d["Scoring still needed"] not in ("", None) else 0
        ratio = d["Runs"] / max(d["Runs needed"], 1)
        need_txt = (f"Needs <b>{need} more scoring balls</b> by {E(check)}" if need
                    else f"Scoring on pace for {E(check)}")
        cards += f"""
        <div class="doc">
          <div class="top"><div><div class="name">{E(key)}</div>
            <div class="role">{"Family Medicine" if "(FM)" in str(d["Doctor"]) else "General Practice"} · target {fmt(d["Runs target (day)"])} a day</div></div>
            <span class="pill p-{st_cls}">{E(str(d["Status"]))}</span></div>
          <div class="score"><span class="runs">{fmt(d["Runs"])}</span><span class="of">runs of {fmt(d["Runs needed"])} needed · {d["% of day"]}% of day</span></div>
          <div class="bar"><i style="width:{min(ratio,1)*100:.0f}%"></i></div>
          <div class="stats">
            <div class="stat"><b>{d["Balls"]}</b><span>Balls</span></div>
            <div class="stat"><b>{d["Dots"]}</b><span>Dots</span></div>
            <div class="stat f"><b>{d["4s"]}</b><span>4s</span></div>
            <div class="stat s"><b>{d["6s"]}</b><span>6s</span></div>
            <div class="stat"><b>{d["Scoring"]}</b><span>Scoring</span></div>
          </div>
          <div class="strip">{strip}</div>
          <div class="made">{made}</div>
          <div class="need">{need_txt} · {fmt(d["Runs"] / max(d["Balls"],1))} AED per ball</div>
        </div>"""
    st.markdown(f'<div class="docs">{cards}</div>', unsafe_allow_html=True)
    st.markdown('<div class="note" style="margin-top:8px">Hover a ball to see the insurance, EMR number, items and runs.</div>',
                unsafe_allow_html=True)

    st.markdown('<div class="sec">What made the 4s and 6s</div>', unsafe_allow_html=True)
    for key in sorted(doc_visits):
        scored = [v for v in doc_visits[key] if v["ball"]]
        if not scored:
            continue
        n4 = sum(1 for v in scored if v["ball"] == 4)
        n6 = len(scored) - n4
        with st.expander(f"{key}  ·  {n4} fours · {n6} sixes"):
            rows = ""
            for v in sorted(scored, key=lambda x: (-x["ball"], -x["runs"])):
                rows += (f'<div class="sr"><span class="bb b{v["ball"]}">{v["ball"]}</span>'
                         f'<div class="sr-id"><b>EMR {E(v.get("emr") or "–")}</b><span>{E(v["insurance"])}</span></div>'
                         f'<div class="sr-items">{chips(v)}</div>'
                         f'<div class="sr-runs">{fmt(v["runs"])}<span>runs</span></div></div>')
            st.markdown(f'<div class="sl">{rows}</div>', unsafe_allow_html=True)

    st.markdown('<div class="sec">Summary</div>', unsafe_allow_html=True)
    st.markdown(table(ddf, ["Doctor", "Balls", "Dots", "4s", "6s", "Scoring", "Scoring needed", "Runs", "Runs needed",
                            "% of day", "Status"], money=("Runs", "Runs needed"), total_key="Clinic"),
                unsafe_allow_html=True)
    st.markdown('<div class="note">Runs = insurance money after copay on corrected prices; cash visits at other-insurer prices. '
                f'Daily target: GP 34 balls, 22 scoring, {fmt(L.TARGETS["gp"]["runs"])} runs · Family Medicine 30 balls, '
                f'{fmt(L.TARGETS["fm"]["runs"])} runs.</div>', unsafe_allow_html=True)

# ---------------------------------------------------------------- by insurance
with tab2:
    for doc in sorted(doc_visits):
        vs = doc_visits[doc]
        by = {}
        for v in vs:
            by.setdefault(v["insurance"], []).append(v)
        rows = ""
        for ins, ivs in sorted(by.items(), key=lambda x: -len(x[1])):
            f4 = [v for v in ivs if v["ball"] == 4]
            f6 = [v for v in ivs if v["ball"] == 6]
            runs = sum(v["runs"] for v in ivs)
            rows += (f'<tr><td>{E(ins)}</td><td>{len(ivs)}</td><td>{sum(1 for v in ivs if v["ball"] == 0)}</td>'
                     f'<td class="c4">{len(f4)}</td><td class="nm">{E(agg_names(f4)) or "–"}</td>'
                     f'<td class="c6">{len(f6)}</td><td class="nm">{E(agg_names(f6)) or "–"}</td>'
                     f'<td>{fmt(runs)}</td><td>{fmt(runs / len(ivs))}</td></tr>')
        f4 = [v for v in vs if v["ball"] == 4]
        f6 = [v for v in vs if v["ball"] == 6]
        runs = sum(v["runs"] for v in vs)
        rows += (f'<tr class="tot"><td>Total</td><td>{len(vs)}</td><td>{sum(1 for v in vs if v["ball"] == 0)}</td>'
                 f'<td class="c4">{len(f4)}</td><td class="nm"></td><td class="c6">{len(f6)}</td><td class="nm"></td>'
                 f'<td>{fmt(runs)}</td><td>{fmt(runs / max(len(vs), 1))}</td></tr>')
        st.markdown(f'<div class="sec">{E(doc)}</div>', unsafe_allow_html=True)
        st.markdown('<table class="tbl ins"><thead><tr><th>Insurance</th><th>Balls</th><th>Dots</th>'
                    '<th>4s</th><th class="nm">What the 4s were</th><th>6s</th><th class="nm">What the 6s were</th>'
                    f'<th>Runs</th><th>Runs per ball</th></tr></thead><tbody>{rows}</tbody></table>',
                    unsafe_allow_html=True)

# ---------------------------------------------------------------- labs and procedures
with tab3:
    st.markdown('<div class="note">Blood collection (36415) is part of the lab and is not counted as a ball.</div>',
                unsafe_allow_html=True)
    if len(itdf):
        for doc, g in itdf.groupby("Doctor", sort=True):
            st.markdown(f'<div class="sec">{E(doc)}</div>', unsafe_allow_html=True)
            st.markdown(table(g, ["Item", "Type", "Code", "Count", "Runs"], money=("Runs",), four="", six=""),
                        unsafe_allow_html=True)
    else:
        st.markdown('<div class="empty"><b>No labs or procedures</b>Every patient in this report had a consultation only.</div>',
                    unsafe_allow_html=True)

# ---------------------------------------------------------------- corrections
with tab4:
    st.markdown('<div class="note">Daman level 3 (99213 = 95, 99203 = 142) · other insurers level 2 (99212 = 56, 99202 = 98) · '
                'one consultation line per visit · Daman labs at 0 from the Daman list (20% copay) · non-Daman labs at 0 at the deck price · '
                'medicine at the claim price · free follow-ups as billed · cash at other-insurer prices.</div>', unsafe_allow_html=True)
    if len(logdf):
        summary = logdf["Correction"].value_counts().rename_axis("Correction").reset_index(name="Lines")
        st.markdown(table(summary, ["Correction", "Lines"], four="", six=""), unsafe_allow_html=True)
        st.dataframe(logdf.astype(str), hide_index=True, width="stretch")
    else:
        st.success("Nothing to correct in this report.")

xlsx = L.to_excel(ddf, idf, itdf, logdf, meta)
fname = f"EMC_Scorecard_{dates[0] if dates else ''}_{check.replace(' ', '')}.xlsx"

# ---------------------------------------------------------------- email
with tab5:
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
    c1, c2 = st.columns(2)
    to = c1.text_input("Send to (comma separated)", value=_secret("EMAIL_TO"))
    cc = c2.text_input("CC (comma separated)", value=_secret("EMAIL_CC"))
    subject = st.text_input("Subject", value=f"EMC Revenue Scorecard - {', '.join(dates)} - {check} check")
    html = L.email_html(ddf, idf, itdf, logdf, meta, check)
    with st.expander("Preview email"):
        st.html(html)
    b1, b2 = st.columns([1, 3])
    b2.download_button("Download Excel", xlsx, file_name=fname,
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    if not smtp:
        st.warning("Email is not set up yet. Add SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS and EMAIL_TO in the app's Settings → Secrets.")
    elif b1.button("Send to management", type="primary"):
        recipients = [x.strip() for x in to.split(",") if x.strip()]
        if not recipients:
            st.error("Add at least one email address.")
        else:
            try:
                L.send_email(smtp, recipients, subject, html, xlsx, fname,
                             [x.strip() for x in cc.split(",") if x.strip()])
                st.success(f"Sent to {', '.join(recipients)}.")
            except Exception as e:  # noqa: BLE001
                st.error(f"Email not sent: {e}")

st.download_button("Download Excel", xlsx, file_name=fname, key="dl_bottom",
                   mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
