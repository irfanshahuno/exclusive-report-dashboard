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
.block-container{padding-top:3.8rem; max-width:1280px;}
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
.stats{display:grid; grid-template-columns:repeat(6,1fr); gap:6px; margin:14px 0 10px;}
.stat{background:var(--soft); border-radius:10px; padding:8px 6px; text-align:center;}
.stat b{display:block; font-family:'Barlow Semi Condensed',sans-serif; font-size:19px; white-space:nowrap; color:var(--ink); line-height:1.1;}
.stat span{font-size:9.5px; color:var(--muted); text-transform:uppercase; letter-spacing:.06em;}
.stat{position:relative;}
.rsub{position:absolute; top:6px; right:6px; font-style:normal; font-size:10.5px; font-weight:700; color:#fff;
      background:#7D8A83; border-radius:999px; padding:1px 6px;}
.stat.r b{color:#7D8A83;}
.tbl td.cr{color:#7D8A83; font-weight:700;}
.stat .mini{display:block; height:4px; background:#E4E9E6; border-radius:4px; margin:5px 8px 3px; overflow:hidden;}
.stat .mini i{display:block; height:100%; background:#2F5FC9; border-radius:4px;}
.stat b small{font-size:13px; color:var(--muted); font-weight:600;}
.doc.st-ON{border-left:5px solid #1E6A49;} .doc.st-WATCH{border-left:5px solid #C98A12;} .doc.st-CHECK{border-left:5px solid #B3261E;}
.rank{display:inline-flex; align-items:center; justify-content:center; width:30px; height:30px; border-radius:50%;
      background:var(--soft); color:var(--ink); font:700 14px 'Barlow Semi Condensed',sans-serif; margin-right:10px; vertical-align:middle;}
.rank.r1{background:#E9C46A; color:#4A3A07;} .rank.r2{background:#CFD6DA; color:#33413A;} .rank.r3{background:#D9A47A; color:#4A2A10;}
.made.chips-row{display:flex; flex-wrap:wrap; gap:6px;}
.chip-i b{font-weight:700; margin-left:3px; opacity:.7;}
.board{display:flex; gap:12px; flex-wrap:wrap; margin:4px 0 16px;}
.board .b{flex:1; min-width:200px; background:var(--card); border:1px solid #E4E9E6; border-radius:14px; padding:12px 16px; display:flex; align-items:center; gap:12px;}
.board .b .nm{font-weight:700; color:var(--ink);} .board .b .sm{font-size:12.5px; color:var(--muted);}
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
.bR{background:#7D8A83; color:#fff;} .bX{background:#E07B39; color:#fff;}
.ball.warn{box-shadow:0 0 0 2px #fff, 0 0 0 4px #D62D20;}
.bb.bR{background:#7D8A83;} .bb.bX{background:#E07B39;}
.chip-i.ref{background:#FDEBDD; color:#9A4A14;}
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
def _secret(name, default=""):
    try:
        if name in st.secrets:
            return str(st.secrets[name])
    except Exception:  # no secrets file
        pass
    return os.environ.get(name, default)


# ---------------------------------------------------------------- keep the last report (S3, else a local file)
import hashlib  # noqa: E402
import json  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402

UAE = timezone(timedelta(hours=4))
S3_PREFIX = (_secret("S3_BASE_PREFIX").strip("/") + "/" if _secret("S3_BASE_PREFIX") else "") + "emc_scorecard/"
LOCAL_DIR = Path(__file__).resolve().parent / ".emc_last_report"


def _s3():
    bucket = _secret("S3_BUCKET_NAME")
    if not bucket:
        return None, None
    try:
        import boto3
        kw = {"region_name": _secret("AWS_REGION") or None}
        if _secret("AWS_ACCESS_KEY_ID"):
            kw.update(aws_access_key_id=_secret("AWS_ACCESS_KEY_ID"), aws_secret_access_key=_secret("AWS_SECRET_ACCESS_KEY"))
        return boto3.client("s3", **kw), bucket
    except Exception:  # noqa: BLE001
        return None, None


def save_bundle(proc, proc_name, refs):
    """Save the ProcedureDetails report and any referral reports as the page's current data."""
    now = datetime.now(UAE)
    meta = {"name": proc_name, "uploaded_at": now.strftime("%d-%m-%Y %I:%M %p"),
            "refs": [n for _, n in refs]}
    s3, bucket = _s3()
    if s3:
        try:
            s3.put_object(Bucket=bucket, Key=S3_PREFIX + "latest/report.xlsx", Body=proc)
            for i, (data, _) in enumerate(refs):
                s3.put_object(Bucket=bucket, Key=f"{S3_PREFIX}latest/referral_{i}.xlsx", Body=data)
            s3.put_object(Bucket=bucket, Key=S3_PREFIX + "latest/meta.json", Body=json.dumps(meta).encode())
            s3.put_object(Bucket=bucket, Key=f"{S3_PREFIX}history/{now:%Y-%m-%d}/{now:%H%M}_{proc_name}", Body=proc)
            for data, n in refs:
                s3.put_object(Bucket=bucket, Key=f"{S3_PREFIX}history/{now:%Y-%m-%d}/{now:%H%M}_referral_{n}", Body=data)
            return "S3", meta
        except Exception as e:  # noqa: BLE001
            st.warning(f"Could not save to S3 ({e}). Saved on the app server instead.")
    LOCAL_DIR.mkdir(exist_ok=True)
    (LOCAL_DIR / "report.xlsx").write_bytes(proc)
    for i, (data, _) in enumerate(refs):
        (LOCAL_DIR / f"referral_{i}.xlsx").write_bytes(data)
    (LOCAL_DIR / "meta.json").write_text(json.dumps(meta))
    return "server", meta


def load_bundle():
    s3, bucket = _s3()
    if s3:
        try:
            meta = json.loads(s3.get_object(Bucket=bucket, Key=S3_PREFIX + "latest/meta.json")["Body"].read())
            proc = s3.get_object(Bucket=bucket, Key=S3_PREFIX + "latest/report.xlsx")["Body"].read()
            refs = [(s3.get_object(Bucket=bucket, Key=f"{S3_PREFIX}latest/referral_{i}.xlsx")["Body"].read(), n)
                    for i, n in enumerate(meta.get("refs", []))]
            return proc, meta, refs
        except Exception:  # noqa: BLE001
            pass
    try:
        meta = json.loads((LOCAL_DIR / "meta.json").read_text())
        refs = [((LOCAL_DIR / f"referral_{i}.xlsx").read_bytes(), n) for i, n in enumerate(meta.get("refs", []))]
        return (LOCAL_DIR / "report.xlsx").read_bytes(), meta, refs
    except Exception:  # noqa: BLE001
        return None, None, []


if "bundle" not in st.session_state:
    st.session_state["bundle"] = load_bundle()
report_bytes, report_meta, ref_files = st.session_state["bundle"]

# ---------------------------------------------------------------- upload (hidden once processed) + check time
up_col, chk_col = st.columns([3, 2], vertical_alignment="top")
with up_col:
    with st.expander("Upload reports" if report_bytes is None else "Upload new reports",
                     expanded=report_bytes is None):
        with st.form("upload_form", clear_on_submit=True, border=False):
            f_proc = st.file_uploader("1 · HIS ProcedureDetails report", type=["xlsx", "xls"],
                                      help="Coded or not coded. The file is corrected automatically.")
            f_ref_in = st.file_uploader("2 · Referral report: Family Medicine (optional)", type=["xlsx", "xls"],
                                        help="HIS Referral report for referrals to Family Medicine.")
            f_ref_out = st.file_uploader("3 · Referral report: outside hospitals (optional)", type=["xlsx", "xls"],
                                         help="HIS Referral report for referrals to Lifecare and other hospitals.")
            go = st.form_submit_button("Process reports", type="primary")
        f_refs = [f for f in (f_ref_in, f_ref_out) if f] if go else []
        if go:
            if not f_proc:
                st.error("Add the ProcedureDetails report first.")
            else:
                try:
                    L.read_report(f_proc.getvalue(), f_proc.name)
                    for f in f_refs or []:
                        L.read_referrals(f.getvalue(), f.name)
                except Exception as e:  # noqa: BLE001
                    st.error(f"Could not read the files. {e}")
                else:
                    refs_in = [(f.getvalue(), f.name) for f in f_refs or []]
                    where, meta_new = save_bundle(f_proc.getvalue(), f_proc.name, refs_in)
                    st.session_state["bundle"] = (f_proc.getvalue(), meta_new, refs_in)
                    st.toast(f"Processed and saved ({where}). Stays on the page until new reports are uploaded.")
                    st.rerun()
with chk_col:
    if hasattr(st, "segmented_control"):
        check = st.segmented_control("Check", list(L.PACE), default="Closing") or "Closing"
    else:
        check = st.radio("Check", list(L.PACE), index=3, horizontal=True)

lines, refs = None, []
if report_bytes is not None:
    try:
        lines = L.read_report(report_bytes, report_meta["name"])
        for data, n in ref_files:
            refs += L.read_referrals(data, n)
    except Exception as e:  # noqa: BLE001
        st.error(f'Could not read the saved reports. {e}')
        lines = None

if lines is None:
    st.markdown("""
    <div class="hero"><div><h1>EMC Revenue Scorecard</h1>
    <p>Every patient is a ball. Dot = consultation only · 4 = one lab or procedure · 6 = two or more.</p></div>
    <div class="chips"><span class="chip">Daman level 3</span><span class="chip">Others level 2</span><span class="chip">Insurance money after copay</span></div></div>
    <div class="empty"><b>Upload today's reports</b>
    Add the ProcedureDetails report (and the referral reports if you have them) above, then press Process reports.</div>
    """, unsafe_allow_html=True)
    st.stop()

visits, logdf, dates = L.correct(lines)
ref_matched = L.apply_referrals(visits, refs) if refs else 0
ddf, idf, itdf, strips = L.summarize(visits, L.PACE[check])
meta = f"Date {', '.join(dates)} · {len(visits)} patients · file {report_meta['name']} · uploaded {report_meta['uploaded_at']}"
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


def ball_html(v):
    r = v.get("ref")
    if r:
        cls = ("bX" if r["external"] else "bR") + (" warn" if v.get("ref_given") else "")
        given = items_text({"items": v.get("ref_given", [])})
        tip = (f'Referred to {r["to"]}{" (" + r["dept"] + ")" if r["dept"] else ""} · EMR {v.get("emr")} · {v["insurance"]}'
               + (f' · GP gave: {given}' if given else "") + (f' · {r["notes"][:120]}' if r["notes"] else ""))
        return f'<i class="ball {cls}" title="{E(tip)}">R</i>'
    tip = f'{v["insurance"]} · EMR {v.get("emr") or v["inv"]} · {items_text(v) or "consultation only"} · {fmt(v["runs"])} AED'
    return f'<i class="ball b{v["ball"]}" title="{E(tip)}">{v["ball"] if v["ball"] else ""}</i>'


def price_groups(vs):
    g = {}
    for v in vs:
        for c in v["items"]:
            nm = L.item_name(c["code"], c["name"])
            pr = round(c["ins"], 2)
            g.setdefault(nm, {})
            g[nm][pr] = g[nm].get(pr, 0) + 1
    return g


def top_chips(vs, n=8):
    g = {}
    for v in vs:
        for c in v["items"]:
            nm = L.item_name(c["code"], c["name"])
            kind = "lab" if c["type"] in ("LAB", "RADIOLOGY") else "proc"
            e = g.setdefault(nm, {"kind": kind, "prices": set(), "n": 0})
            e["prices"].add(round(c["ins"], 2)); e["n"] += 1
    out = []
    for nm, e in sorted(g.items(), key=lambda x: -x[1]["n"])[:n]:
        pl = " / ".join(money(pr) for pr in sorted(e["prices"], reverse=True))
        out.append(f'<span class="chip-i {e["kind"]}">{E(nm)} <em>{pl}</em>' + (f'<b>×{e["n"]}</b>' if e["n"] > 1 else "") + "</span>")
    more = len(g) - n
    if more > 0:
        out.append(f'<span class="chip-i" style="background:#EEF1EF;color:#5D6A62">+{more} more</span>')
    return "".join(out)


def top_items(vs, n=6):
    g = price_groups(vs)
    out = []
    for nm, prices in sorted(g.items(), key=lambda x: -sum(x[1].values()))[:n]:
        plist = " / ".join(money(pr) for pr in sorted(prices, reverse=True))
        out.append((f"{nm} ({plist})", sum(prices.values())))
    return out


st.markdown(f"""
<div class="hero"><div><h1>EMC Revenue Scorecard</h1>
<p>{E(', '.join(dates))} &nbsp;·&nbsp; {len(visits)} patients &nbsp;·&nbsp; {len(docs)} doctors &nbsp;·&nbsp; {E(check)} check</p></div>
<div class="chips"><span class="chip">{len(logdf)} corrections applied</span><span class="chip">{E(report_meta["name"])}</span><span class="chip">Uploaded {E(report_meta["uploaded_at"])}</span></div></div>
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
    <span><i class="ball b4">4</i>One lab or procedure</span><span><i class="ball b6">6</i>Two or more</span>
    <span><i class="ball bR">R</i>Referred to Family Medicine</span><span><i class="ball bX">R</i>Referred outside</span>
    <span><i class="ball bR warn">R</i>Referred but GP gave a lab or procedure</span></div>""",
                unsafe_allow_html=True)
    ranked = docs.sort_values(["% of day", "Scoring"], ascending=False).reset_index(drop=True)
    board = ""
    for i, d in ranked.head(3).iterrows():
        board += (f'<div class="b"><span class="rank r{i+1}">{i+1}</span><div><div class="nm">{E(str(d["Doctor"]).replace(" (FM)", ""))}</div>'
                  f'<div class="sm">{fmt(d["Runs"])} runs · {d["% of day"]}% of target · {d["Scoring"]} scoring</div></div></div>')
    st.markdown(f'<div class="board">{board}</div>', unsafe_allow_html=True)
    cards = ""
    for rank, d in ranked.iterrows():
        key = str(d["Doctor"]).replace(" (FM)", "")
        vs = doc_visits.get(key, [])
        strip = "".join(ball_html(v) for v in vs)
        rv = [v for v in vs if v.get("ref")]
        if rv:
            dest = {}
            for v in rv:
                nm = "Family Medicine" if not v["ref"]["external"] else (v["ref"]["to"].title() + (f' ({v["ref"]["dept"]})' if v["ref"]["dept"] else ""))
                dest[nm] = dest.get(nm, 0) + 1
            ref_line = "Referrals: " + " · ".join(f"<b>{k}</b> to {E(n)}" for n, k in dest.items())
            nwarn = sum(1 for v in rv if v["ref_given"])
            if nwarn:
                ref_line += f' · <span style="color:#B3261E"><b>{nwarn}</b> given a lab or procedure</span>'
        else:
            ref_line = ""
        made = top_chips(vs) or '<span style="color:var(--muted)">No labs or procedures yet</span>'
        sc_need = int(d["Scoring needed"]) or 1
        sc_ratio = min(d["Scoring"] / sc_need, 1)
        st_cls = str(d["Status"]).split()[0]
        need = int(d["Scoring still needed"]) if d["Scoring still needed"] not in ("", None) else 0
        ratio = d["Runs"] / max(d["Runs needed"], 1)
        need_txt = (f"Needs <b>{need} more scoring balls</b> by {E(check)}" if need
                    else f"Scoring on pace for {E(check)}")
        cards += f"""
        <div class="doc st-{st_cls}">
          <div class="top"><div><div class="name"><span class="rank r{rank+1}">{rank+1}</span>{E(key)}</div>
            <div class="role">{"Family Medicine" if "(FM)" in str(d["Doctor"]) else "General Practice"} · target {fmt(d["Runs target (day)"])} a day</div></div>
            <span class="pill p-{st_cls}" title="ON TRACK = runs and scoring at pace · CLOSE = runs at 80% of pace or more · BEHIND = under 80%">{ {"ON":"ON TRACK","WATCH":"CLOSE","CHECK":"BEHIND"}.get(st_cls, E(str(d["Status"]))) }</span></div>
          <div class="score"><span class="runs">{fmt(d["Runs"])}</span><span class="of">runs of {fmt(d["Runs needed"])} needed by {E(check)} · {d["% of day"]}% of day target</span></div>
          <div class="bar"><i style="width:{min(ratio,1)*100:.0f}%"></i></div>
          <div class="stats">
            <div class="stat"><b>{d["Balls"]}</b><span>Balls</span></div>
            <div class="stat"><b>{d["Dots"]}</b><span>Dots</span></div>
            <div class="stat r"><b>{d["Referrals"]}</b><span>Referral</span></div>
            <div class="stat f"><b>{d["4s"]}</b><span>4s</span></div>
            <div class="stat s"><b>{d["6s"]}</b><span>6s</span></div>
            <div class="stat"><b>{d["Scoring"]}<small>/{int(d["Scoring needed"])}</small></b><i class="mini"><i style="width:{sc_ratio*100:.0f}%"></i></i><span>Scoring</span></div>
          </div>
          <div class="strip">{strip}</div>
          <div class="made chips-row">{made}</div>
          {f'<div class="made">{ref_line}</div>' if ref_line else ""}
          <div class="need">{need_txt} · {fmt(d["Runs"] / max(d["Balls"],1))} AED per ball</div>
        </div>"""
    cards = "".join(ln.strip() for ln in cards.splitlines())   # no blank/indented lines, or Markdown shows raw HTML
    st.markdown(f'<div class="docs">{cards}</div>', unsafe_allow_html=True)
    st.markdown('<div class="note" style="margin-top:8px">Hover a ball to see the insurance, EMR number, items and runs.</div>',
                unsafe_allow_html=True)

    warn = [v for v in visits if v.get("ref") and v.get("ref_given")]
    if refs:
        st.markdown(f'<div class="note" style="margin-top:6px">{len(refs)} referrals in the referral reports · '
                    f'{ref_matched} matched to a patient in this report (by EMR number and date).</div>', unsafe_allow_html=True)
    if warn:
        st.markdown(f'<div class="sec" style="color:#B3261E">Referred patients given a lab or procedure ({len(warn)})</div>'
                    '<div class="note">Tell the GP: when the patient is referred, leave the tests and treatment to the specialist.</div>',
                    unsafe_allow_html=True)
        rows = ""
        for v in sorted(warn, key=lambda x: x["doctor"]):
            r = v["ref"]
            rows += (f'<div class="sr"><span class="bb {"bX" if r["external"] else "bR"}">R</span>'
                     f'<div class="sr-id"><b>EMR {E(v.get("emr") or "–")}</b><span>{E(v["doctor"])} · {E(v["insurance"])}</span></div>'
                     f'<div class="sr-items"><span class="chip-i ref">to {E(r["to"].title())}</span>{chips({"items": v["ref_given"]})}</div>'
                     f'<div class="sr-runs">{fmt(v["runs"])}<span>runs</span></div></div>')
        st.markdown(f'<div class="sl">{rows}</div>', unsafe_allow_html=True)

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
    st.markdown(table(ddf, ["Doctor", "Balls", "Referrals", "Dots", "4s", "6s", "Scoring", "Scoring needed", "Runs", "Runs needed",
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
                     f'<td class="cr">{sum(1 for v in ivs if v.get("ref")) or "–"}</td>'
                     f'<td class="c4">{len(f4)}</td><td class="nm">{E(agg_names(f4)) or "–"}</td>'
                     f'<td class="c6">{len(f6)}</td><td class="nm">{E(agg_names(f6)) or "–"}</td>'
                     f'<td>{fmt(runs)}</td><td>{fmt(runs / len(ivs))}</td></tr>')
        f4 = [v for v in vs if v["ball"] == 4]
        f6 = [v for v in vs if v["ball"] == 6]
        runs = sum(v["runs"] for v in vs)
        rows += (f'<tr class="tot"><td>Total</td><td>{len(vs)}</td><td>{sum(1 for v in vs if v["ball"] == 0)}</td>'
                 f'<td class="cr">{sum(1 for v in vs if v.get("ref"))}</td>'
                 f'<td class="c4">{len(f4)}</td><td class="nm"></td><td class="c6">{len(f6)}</td><td class="nm"></td>'
                 f'<td>{fmt(runs)}</td><td>{fmt(runs / max(len(vs), 1))}</td></tr>')
        st.markdown(f'<div class="sec">{E(doc)}</div>', unsafe_allow_html=True)
        st.markdown('<table class="tbl ins"><thead><tr><th>Insurance</th><th>Balls</th><th>Dots</th>'
                    '<th>Referral</th><th>4s</th><th class="nm">What the 4s were</th><th>6s</th><th class="nm">What the 6s were</th>'
                    f'<th>Runs</th><th>Runs per ball</th></tr></thead><tbody>{rows}</tbody></table>',
                    unsafe_allow_html=True)

# ---------------------------------------------------------------- labs and procedures
with tab3:
    st.markdown('<div class="note">Blood collection (36415) is part of the lab and is not counted as a ball. '
                'Price = insurance share per item (copay out). The same item paid at a different price '
                '(e.g. Almadallah tariff) shows on its own line.</div>', unsafe_allow_html=True)
    any_items = False
    for doc in sorted(doc_visits):
        rowsd = {}
        for v in doc_visits[doc]:
            for c in v["items"]:
                key = (L.item_name(c["code"], c["name"]), "Lab" if c["type"] in ("LAB", "RADIOLOGY") else "Procedure",
                       c["code"], round(c["ins"], 2))
                r = rowsd.setdefault(key, {"n": 0, "ins": set()})
                r["n"] += 1
                r["ins"].add(v["insurance"])
        if not rowsd:
            continue
        any_items = True
        body = ""
        tot_n = tot_r = 0
        for (nm, typ, code, pr), r in sorted(rowsd.items(), key=lambda x: (x[0][1], -x[1]["n"], x[0][0])):
            tot_n += r["n"]
            tot_r += pr * r["n"]
            body += (f'<tr><td>{E(nm)}</td><td>{typ}</td><td>{E(code)}</td><td class="nm">{E(", ".join(sorted(r["ins"])))}</td>'
                     f'<td><b>{money(pr)}</b></td><td>{r["n"]}</td><td>{fmt(pr * r["n"])}</td></tr>')
        body += f'<tr class="tot"><td>Total</td><td></td><td></td><td class="nm"></td><td></td><td>{tot_n}</td><td>{fmt(tot_r)}</td></tr>'
        st.markdown(f'<div class="sec">{E(doc)}</div>', unsafe_allow_html=True)
        st.markdown('<table class="tbl"><thead><tr><th>Item</th><th>Type</th><th>Code</th><th class="nm">Insurance</th>'
                    f'<th>Price</th><th>Count</th><th>Runs</th></tr></thead><tbody>{body}</tbody></table>',
                    unsafe_allow_html=True)
    if not any_items:
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

# ---------------------------------------------------------------- colourful Excel (no corrections sheet)
def build_excel():
    import io
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.formatting.rule import DataBarRule
    from openpyxl.utils import get_column_letter

    G_DARK, G, G_SOFT, SOFT, LINE = "16492F", "1E6A49", "E3F1E9", "F2F5F1", "D5DCD6"
    BLUE, BLUE_SOFT, GREY, ORNG, RED = "2F5FC9", "E8EEFB", "7D8A83", "E07B39", "D62D20"
    STF = {"ON": ("ON TRACK", "1E7A45", "E2F3E8"), "WATCH": ("CLOSE", "9A6200", "FBF0D9"), "CHECK": ("BEHIND", "B3261E", "FBE4E1")}
    MEDAL = {1: "E9C46A", 2: "CFD6DA", 3: "D9A47A"}
    fill = lambda c: PatternFill("solid", start_color=c, end_color=c)
    thin = Side(style="thin", color=LINE)
    box = Border(left=thin, right=thin, top=thin, bottom=thin)
    center = Alignment(horizontal="center", vertical="center")
    left = Alignment(horizontal="left", vertical="center", wrap_text=True)

    def banner(ws, row, text, ncols, sub=None):
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=ncols)
        c = ws.cell(row, 1, text); c.font = Font(bold=True, size=16, color="FFFFFF"); c.fill = fill(G); c.alignment = Alignment(vertical="center", indent=1)
        ws.row_dimensions[row].height = 30
        for col in range(2, ncols + 1):
            ws.cell(row, col).fill = fill(G)
        if sub:
            ws.merge_cells(start_row=row + 1, start_column=1, end_row=row + 1, end_column=ncols)
            s = ws.cell(row + 1, 1, sub); s.font = Font(size=10, color="FFFFFF"); s.alignment = Alignment(vertical="center", indent=1)
            for col in range(1, ncols + 1):
                ws.cell(row + 1, col).fill = fill(G_DARK)
            ws.row_dimensions[row + 1].height = 20

    def header(ws, row, names, color=G):
        for i, n in enumerate(names, 1):
            c = ws.cell(row, i, n)
            c.font = Font(bold=True, color="FFFFFF", size=10); c.fill = fill(color); c.alignment = center; c.border = box
        ws.row_dimensions[row].height = 22

    def body_cell(ws, r, col, val, fmt=None, color=None, bold=False, bg=None, align=center):
        c = ws.cell(r, col, val); c.border = box; c.alignment = align
        c.font = Font(color=color or "18211C", bold=bold, size=10.5)
        if bg:
            c.fill = fill(bg)
        if fmt:
            c.number_format = fmt
        return c

    wb = Workbook()
    sub = f"{', '.join(dates)}  ·  {len(visits)} patients  ·  {check} check  ·  uploaded {report_meta['uploaded_at']}"

    # ---- Scorecard
    ws = wb.active; ws.title = "Scorecard"; ws.sheet_view.showGridLines = False
    cols = ["#", "Doctor", "Role", "Balls", "Dots", "Referral", "4s", "6s", "Scoring", "Scoring needed",
            "Runs", "Runs needed", "% of day target", "Runs per ball", "Status"]
    banner(ws, 1, "EMC Revenue Scorecard", len(cols), sub)
    header(ws, 4, cols)
    r = 5
    for rank, d in ranked.iterrows():
        bg = SOFT if rank % 2 else None
        n = rank + 1
        body_cell(ws, r, 1, n, bold=True, bg=MEDAL.get(n, bg))
        body_cell(ws, r, 2, str(d["Doctor"]).replace(" (FM)", ""), bold=True, bg=bg, align=left)
        body_cell(ws, r, 3, "Family Medicine" if "(FM)" in str(d["Doctor"]) else "General Practice", color="5D6A62", bg=bg)
        body_cell(ws, r, 4, int(d["Balls"]), bg=bg)
        body_cell(ws, r, 5, int(d["Dots"]), bg=bg)
        body_cell(ws, r, 6, int(d["Referrals"]), color=GREY, bold=True, bg=bg)
        body_cell(ws, r, 7, int(d["4s"]), color=BLUE, bold=True, bg=bg)
        body_cell(ws, r, 8, int(d["6s"]), color=G, bold=True, bg=bg)
        body_cell(ws, r, 9, int(d["Scoring"]), bold=True, bg=bg)
        body_cell(ws, r, 10, int(d["Scoring needed"]), color="5D6A62", bg=bg)
        body_cell(ws, r, 11, float(d["Runs"]), "#,##0", bold=True, bg=bg)
        body_cell(ws, r, 12, float(d["Runs needed"]), "#,##0", color="5D6A62", bg=bg)
        body_cell(ws, r, 13, d["% of day"] / 100, "0%", bold=True, bg=bg)
        body_cell(ws, r, 14, d["Runs"] / max(d["Balls"], 1), "#,##0", bg=bg)
        lab, fg, sbg = STF.get(str(d["Status"]).split()[0], (str(d["Status"]), "5D6A62", SOFT))
        body_cell(ws, r, 15, lab, color=fg, bold=True, bg=sbg)
        ws.row_dimensions[r].height = 21
        r += 1
    last = r - 1
    vals = ["", "Clinic", "", int(clinic["Balls"]), int(clinic["Dots"]), int(clinic["Referrals"]), int(clinic["4s"]), int(clinic["6s"]),
            int(clinic["Scoring"]), int(clinic["Scoring needed"]), float(clinic["Runs"]), float(clinic["Runs needed"]),
            clinic["% of day"] / 100, clinic["Runs"] / max(clinic["Balls"], 1), ""]
    fmts = {11: "#,##0", 12: "#,##0", 13: "0%", 14: "#,##0"}
    for i, v in enumerate(vals, 1):
        c = body_cell(ws, r, i, v, fmts.get(i), color="FFFFFF", bold=True, bg=G_DARK, align=left if i == 2 else center)
    ws.row_dimensions[r].height = 22
    if last >= 5:
        ws.conditional_formatting.add(f"M5:M{last}", DataBarRule(start_type="num", start_value=0, end_type="num", end_value=1, color="5FA37F"))
        ws.conditional_formatting.add(f"I5:I{last}", DataBarRule(start_type="num", start_value=0, end_type="num", end_value=22, color="7B9BE0"))
    widths = [5, 26, 17, 8, 8, 10, 7, 7, 10, 10, 11, 12, 15, 12, 12]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w

    ws.freeze_panes = "C5"
    # ball strips on their own sheet
    ws = wb.create_sheet("Balls"); ws.sheet_view.showGridLines = False
    maxb = max([len(v) for v in doc_visits.values()] + [10])
    banner(ws, 1, "Every patient is a ball", min(maxb + 2, 40), sub)
    r = 4
    legend = [("·", "FFFFFF", "9AA79F", "Dot · consultation only"), ("4", BLUE, "FFFFFF", "One lab or procedure"),
              ("6", G, "FFFFFF", "Two or more"), ("R", GREY, "FFFFFF", "Referred to Family Medicine"),
              ("R", ORNG, "FFFFFF", "Referred outside")]
    leg_rows = []
    for sym, bgc, fgc, txt in legend:
        leg_rows.append((sym, bgc, fgc, txt))
    first_ball_col = 3
    for rank, d in ranked.iterrows():
        key = str(d["Doctor"]).replace(" (FM)", "")
        body_cell(ws, r, 2, key, bold=True, align=left)
        for j, v in enumerate(doc_visits.get(key, [])):
            ref = v.get("ref")
            if ref:
                sym, bgc, fgc = "R", (ORNG if ref["external"] else GREY), "FFFFFF"
            elif v["ball"] == 0:
                sym, bgc, fgc = "·", "FFFFFF", "9AA79F"
            else:
                sym, bgc, fgc = int(v["ball"]), (BLUE if v["ball"] == 4 else G), "FFFFFF"
            c = ws.cell(r, first_ball_col + j, sym)
            c.fill = fill(bgc); c.font = Font(bold=True, color=fgc, size=9); c.alignment = center
            c.border = Border(left=Side(style="thin", color="FFFFFF"), right=Side(style="thin", color="FFFFFF"),
                              top=Side(style="thin", color="FFFFFF"), bottom=Side(style="thin", color="FFFFFF"))
            if ref and v.get("ref_given"):
                red = Side(style="medium", color=RED)
                c.border = Border(left=red, right=red, top=red, bottom=red)
            ws.column_dimensions[get_column_letter(first_ball_col + j)].width = 3.4
        ws.row_dimensions[r].height = 19
        r += 1
    r += 1
    ws.cell(r, 2, "Key").font = Font(bold=True, size=11, color=G)
    r += 1
    for sym, bgc, fgc, txt in leg_rows:
        t = ws.cell(r, 2, txt); t.font = Font(size=10, color="5D6A62"); t.alignment = Alignment(horizontal="right", vertical="center")
        c = ws.cell(r, 3, int(sym) if sym.isdigit() else sym)
        c.fill = fill(bgc); c.font = Font(bold=True, color=fgc, size=9); c.alignment = center
        if bgc == "FFFFFF":
            c.border = box
        ws.row_dimensions[r].height = 18
        r += 1
    ws.column_dimensions["A"].width = 2
    ws.column_dimensions["B"].width = 28
    ws.freeze_panes = "C4"

    # ---- By insurance
    wi = wb.create_sheet("By insurance"); wi.sheet_view.showGridLines = False
    icols = ["Insurance", "Balls", "Dots", "Referral", "4s", "What the 4s were", "6s", "What the 6s were", "Runs", "Runs per ball"]
    banner(wi, 1, "Each doctor by insurance", len(icols), sub)
    r = 4
    for doc in [str(d["Doctor"]).replace(" (FM)", "") for _, d in ranked.iterrows()]:
        vs = doc_visits.get(doc, [])
        if not vs:
            continue
        wi.merge_cells(start_row=r, start_column=1, end_row=r, end_column=len(icols))
        c = wi.cell(r, 1, doc); c.font = Font(bold=True, size=12, color=G_DARK); c.fill = fill(G_SOFT)
        for k in range(1, len(icols) + 1):
            wi.cell(r, k).fill = fill(G_SOFT)
        wi.row_dimensions[r].height = 22
        r += 1
        header(wi, r, icols, G); r += 1
        by = {}
        for v in vs:
            by.setdefault(v["insurance"], []).append(v)
        rows = sorted(by.items(), key=lambda x: -len(x[1])) + [("Total", vs)]
        for k, (ins, ivs) in enumerate(rows):
            tot = ins == "Total"
            bg = G_DARK if tot else (SOFT if k % 2 else None)
            fc = "FFFFFF" if tot else None
            f4 = [v for v in ivs if v["ball"] == 4]; f6 = [v for v in ivs if v["ball"] == 6]
            runs = sum(v["runs"] for v in ivs)
            body_cell(wi, r, 1, ins, color=fc, bold=True, bg=bg, align=left)
            body_cell(wi, r, 2, len(ivs), color=fc, bold=tot, bg=bg)
            body_cell(wi, r, 3, sum(1 for v in ivs if v["ball"] == 0), color=fc, bold=tot, bg=bg)
            body_cell(wi, r, 4, sum(1 for v in ivs if v.get("ref")), color=fc or GREY, bold=True, bg=bg)
            body_cell(wi, r, 5, len(f4), color=fc or BLUE, bold=True, bg=bg)
            body_cell(wi, r, 6, "" if tot else (agg_names(f4) or "–"), color=fc or "2546A0", bg=bg if tot else (BLUE_SOFT if f4 else bg), align=left)
            body_cell(wi, r, 7, len(f6), color=fc or G, bold=True, bg=bg)
            body_cell(wi, r, 8, "" if tot else (agg_names(f6) or "–"), color=fc or "17553A", bg=bg if tot else (G_SOFT if f6 else bg), align=left)
            body_cell(wi, r, 9, runs, "#,##0", color=fc, bold=True, bg=bg)
            body_cell(wi, r, 10, runs / max(len(ivs), 1), "#,##0", color=fc, bg=bg)
            r += 1
        r += 1
    for i, w in enumerate([18, 8, 8, 10, 6, 44, 6, 44, 10, 12], 1):
        wi.column_dimensions[get_column_letter(i)].width = w

    # ---- Labs and procedures
    wl = wb.create_sheet("Labs and procedures"); wl.sheet_view.showGridLines = False
    lcols = ["Doctor", "Item", "Type", "Code", "Price (insurance share)", "Count", "Runs"]
    banner(wl, 1, "Labs and procedures", len(lcols), sub)
    header(wl, 4, lcols)
    agg = {}
    for v in visits:
        for c in v["items"]:
            k = (v["doctor"], L.item_name(c["code"], c["name"]), "Lab" if c["type"] in ("LAB", "RADIOLOGY") else "Procedure", c["code"], round(c["ins"], 2))
            agg[k] = agg.get(k, 0) + 1
    r = 5
    for (doc, item, typ, code, pr), n in sorted(agg.items(), key=lambda x: (x[0][0], x[0][2], -x[1])):
        lab = typ == "Lab"
        bg = BLUE_SOFT if lab else G_SOFT
        fc = "2546A0" if lab else "17553A"
        body_cell(wl, r, 1, doc, bold=True, align=left)
        body_cell(wl, r, 2, item, color=fc, bold=True, bg=bg, align=left)
        body_cell(wl, r, 3, typ, color=fc, bg=bg)
        body_cell(wl, r, 4, code, color="5D6A62")
        body_cell(wl, r, 5, pr, "#,##0.00")
        body_cell(wl, r, 6, n, bold=True)
        body_cell(wl, r, 7, pr * n, "#,##0", bold=True)
        r += 1
    if r > 5:
        wl.conditional_formatting.add(f"G5:G{r - 1}", DataBarRule(start_type="min", end_type="max", color="5FA37F"))
    wl.freeze_panes = "A5"
    for i, w in enumerate([24, 30, 12, 10, 20, 8, 10], 1):
        wl.column_dimensions[get_column_letter(i)].width = w

    del wb["Balls"]   # not wanted in the Excel
    for s in wb.worksheets:
        s.sheet_properties.tabColor = {"Scorecard": G, "Balls": GREY, "By insurance": BLUE, "Labs and procedures": ORNG}[s.title]
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


xlsx = build_excel()
fname = f"EMC_Scorecard_{dates[0] if dates else ''}_{check.replace(' ', '')}.xlsx"

# ---------------------------------------------------------------- email

# ---------------------------------------------------------------- email (same look as the dashboard, inline styles for mail apps)
def email_dashboard_html():
    """Outlook-safe email: tables + bgcolor everywhere (Outlook desktop ignores div backgrounds, % widths on divs, margins on spans)."""
    F = "font-family:Segoe UI,Arial,Helvetica,sans-serif;"
    INK, MUT, SOFT, LINE, EDGE = "#18211C", "#5D6A62", "#F2F5F1", "#E1E6E0", "#C9D2CB"
    FOUR, SIX, GREY, ORNG, RED = "#2F5FC9", "#1E6A49", "#7D8A83", "#E07B39", "#D62D20"
    ST = {"ON": ("ON TRACK", "#1E7A45", "#E2F3E8"), "WATCH": ("CLOSE", "#9A6200", "#FBF0D9"), "CHECK": ("BEHIND", "#B3261E", "#FBE4E1")}
    MEDAL = {1: ("#E9C46A", "#4A3A07"), 2: ("#CFD6DA", "#33413A"), 3: ("#D9A47A", "#4A2A10")}
    W = 760
    T = 'role="presentation" cellpadding="0" cellspacing="0" border="0"'

    def bar(ratio, color, h=10):
        pct = int(round(max(0, min(ratio, 1)) * 100))
        cells = ""
        if pct > 0:
            cells += f'<td width="{pct}%" bgcolor="{color}" style="background:{color};height:{h}px;font-size:1px;line-height:1px;">&nbsp;</td>'
        if pct < 100:
            cells += f'<td width="{100 - pct}%" bgcolor="{LINE}" style="background:{LINE};height:{h}px;font-size:1px;line-height:1px;">&nbsp;</td>'
        return f'<table {T} width="100%"><tr>{cells}</tr></table>'

    def ball_cell(v):
        base = (f"width:18px;height:18px;border-radius:50%;text-align:center;vertical-align:middle;"
                f"font:bold 10px Arial,sans-serif;color:#ffffff;mso-line-height-rule:exactly;line-height:18px;")
        r = v.get("ref")
        if r:
            bg = ORNG if r["external"] else GREY
            ring = f"border:2px solid {RED};" if v.get("ref_given") else ""
            return f'<td width="18" height="18" bgcolor="{bg}" style="{base}background:{bg};{ring}">R</td>'
        if v["ball"] == 0:
            return f'<td width="18" height="18" bgcolor="#ffffff" style="{base}background:#ffffff;border:2px solid #C3CCC5;color:#ffffff;">&nbsp;</td>'
        bg = FOUR if v["ball"] == 4 else SIX
        return f'<td width="18" height="18" bgcolor="{bg}" style="{base}background:{bg};">{v["ball"]}</td>'

    def balls(vs, per_row=26):
        if not vs:
            return ""
        rows = ""
        for i in range(0, len(vs), per_row):
            rows += "<tr>" + "".join(ball_cell(v) for v in vs[i:i + per_row]) + "</tr>"
        return f'<table {T.replace("cellspacing=\"0\"", "cellspacing=\"4\"")}>{rows}</table>'

    def rank_cell(n, size=30):
        bg, fg = MEDAL.get(n, (SOFT, INK))
        return (f'<td width="{size}" height="{size}" bgcolor="{bg}" style="background:{bg};color:{fg};border-radius:50%;text-align:center;'
                f'font:bold 14px Arial,sans-serif;border:1px solid {EDGE};">{n}</td>')

    def chips(vs, n=8):
        g = {}
        for v in vs:
            for c in v["items"]:
                nm = L.item_name(c["code"], c["name"])
                e = g.setdefault(nm, {"lab": c["type"] in ("LAB", "RADIOLOGY"), "p": set(), "n": 0})
                e["p"].add(round(c["ins"], 2)); e["n"] += 1
        if not g:
            return f'<span style="color:{MUT};font-size:13px;">No labs or procedures yet</span>'
        cells = []
        for nm, e in sorted(g.items(), key=lambda x: -x[1]["n"])[:n]:
            bg, fg, bd = ("#E8EEFB", "#2546A0", "#C5D3F3") if e["lab"] else ("#E3F1E9", "#17553A", "#BFDCCB")
            pl = " / ".join(money(x) for x in sorted(e["p"], reverse=True))
            cells.append(f'<td bgcolor="{bg}" style="background:{bg};color:{fg};border:1px solid {bd};border-radius:14px;padding:5px 11px;'
                         f'font-size:12.5px;white-space:nowrap;">{E(nm)} <b>{pl}</b>' + (f' &times;{e["n"]}' if e["n"] > 1 else "") + "</td>")
        if len(g) > n:
            cells.append(f'<td style="color:{MUT};font-size:12.5px;padding:5px 8px;">+{len(g) - n} more</td>')
        rows = "".join(f"<tr>{''.join(cells[i:i + 3])}</tr>" for i in range(0, len(cells), 3))
        return f'<table {T.replace("cellspacing=\"0\"", "cellspacing=\"6\"")} style="margin-left:-6px;">{rows}</table>'

    def stat(val, label, color=INK, extra=""):
        return (f'<td width="16%" bgcolor="{SOFT}" align="center" style="background:{SOFT};border:1px solid {EDGE};border-radius:10px;padding:10px 4px;">'
                f'<div style="font:bold 22px Arial,sans-serif;color:{color};white-space:nowrap;">{val}</div>{extra}'
                f'<div style="font-size:10px;color:{MUT};letter-spacing:1px;text-transform:uppercase;padding-top:4px;">{label}</div></td>')

    def kpi(lbl, val, small, sub, b=""):
        return (f'<td width="25%" valign="top" bgcolor="#ffffff" style="background:#ffffff;border:1px solid {EDGE};border-radius:12px;padding:14px 14px;">'
                f'<div style="font-size:10.5px;letter-spacing:1px;text-transform:uppercase;color:{MUT};font-weight:bold;">{lbl}</div>'
                f'<div style="font:bold 26px Arial,sans-serif;color:{INK};padding-top:4px;white-space:nowrap;">{val}'
                f'<span style="font-size:13px;color:{MUT};font-weight:normal;">&nbsp;{small}</span></div>'
                f'<div style="font-size:12px;color:{MUT};padding:4px 0 8px;">{sub}</div>{b}</td>')

    def section(title):
        return (f'<tr><td style="padding:26px 0 8px;"><table {T} width="100%"><tr>'
                f'<td style="font:bold 19px Arial,sans-serif;color:{INK};border-bottom:3px solid {SIX};padding-bottom:6px;">{title}</td></tr></table></td></tr>')

    runs_r = clinic["Runs"] / max(clinic["Runs needed"], 1)
    sc_r = clinic["Scoring"] / max(clinic["Scoring needed"], 1)
    out = [f'<table {T} width="100%" bgcolor="#EEF1ED" style="background:#EEF1ED;{F}"><tr><td align="center" style="padding:18px 10px;">'
           f'<table {T} width="{W}" style="width:{W}px;max-width:100%;{F}color:{INK};">']

    # header
    out.append(f'<tr><td bgcolor="#1E6A49" style="background:#1E6A49;background-image:linear-gradient(135deg,#16492F,#1E6A49 60%,#2A8A5E);'
               f'border-radius:16px;padding:22px 26px;color:#ffffff;">'
               f'<div style="font:bold 26px Arial,sans-serif;color:#ffffff;">EMC Revenue Scorecard</div>'
               f'<div style="font-size:14px;color:#DDEFE5;padding-top:6px;">{E(", ".join(dates))} &nbsp;·&nbsp; {len(visits)} patients &nbsp;·&nbsp; {len(docs)} doctors &nbsp;·&nbsp; <b style="color:#ffffff;">{E(check)} check</b></div>'
               f'<div style="font-size:12px;color:#BFE0CE;padding-top:8px;">{len(logdf)} corrections applied &nbsp;·&nbsp; uploaded {E(report_meta["uploaded_at"])}</div></td></tr>')
    # KPIs
    out.append(f'<tr><td style="padding-top:12px;"><table {T.replace("cellspacing=\"0\"", "cellspacing=\"8\"")} width="100%" style="margin:0 -8px;"><tr>'
               + kpi("Clinic runs", fmt(clinic["Runs"]), f'/ {fmt(clinic["Runs needed"])}', f'{runs_r:.0%} of the {E(check)} pace', bar(runs_r, SIX, 8))
               + kpi("Scoring balls", int(clinic["Scoring"]), f'/ {int(clinic["Scoring needed"])}', f'{int(clinic["4s"])} fours · {int(clinic["6s"])} sixes', bar(sc_r, FOUR, 8))
               + kpi("Balls faced", int(clinic["Balls"]), "", f'{int(clinic["Dots"])} dots · {int(clinic["Referrals"])} referrals')
               + kpi("Runs per ball", f'{clinic["Runs"] / max(clinic["Balls"], 1):,.0f}', "AED", "Insurance money per patient")
               + '</tr></table></td></tr>')
    # legend
    def lg(v, t):
        return (f'<td style="padding-right:4px;"><table {T}><tr>{ball_cell(v)}</tr></table></td>'
                f'<td style="font-size:12px;color:{MUT};padding-right:14px;white-space:nowrap;">{t}</td>')
    out.append(f'<tr><td style="padding:10px 0 4px;"><table {T}><tr>'
               + lg({"ball": 0}, "Dot · consultation only") + lg({"ball": 4}, "One lab or procedure") + lg({"ball": 6}, "Two or more")
               + '</tr></table><table ' + T + ' style="margin-top:6px;"><tr>'
               + lg({"ball": 0, "ref": {"external": False}}, "Referred to Family Medicine") + lg({"ball": 0, "ref": {"external": True}}, "Referred outside")
               + lg({"ball": 0, "ref": {"external": False}, "ref_given": [1]}, "Referred but GP gave a lab or procedure")
               + '</tr></table></td></tr>')
    # top 3
    out.append(section("Top of the table"))
    out.append(f'<tr><td><table {T.replace("cellspacing=\"0\"", "cellspacing=\"8\"")} width="100%" style="margin:0 -8px;"><tr>')
    for i, d in ranked.head(3).iterrows():
        out.append(f'<td width="33%" bgcolor="#ffffff" style="background:#ffffff;border:1px solid {EDGE};border-radius:12px;padding:12px;">'
                   f'<table {T}><tr>{rank_cell(i + 1)}<td style="padding-left:10px;font:bold 14px Arial,sans-serif;">{E(str(d["Doctor"]).replace(" (FM)", ""))}</td></tr></table>'
                   f'<div style="font-size:12px;color:{MUT};padding-top:6px;">{fmt(d["Runs"])} runs · {d["% of day"]}% of target · {d["Scoring"]} scoring</div></td>')
    out.append('</tr></table></td></tr>')

    # doctor cards
    out.append(section("Doctor scorecards"))
    for rank, d in ranked.iterrows():
        key = str(d["Doctor"]).replace(" (FM)", "")
        vs = doc_visits.get(key, [])
        lab, fg, bg = ST.get(str(d["Status"]).split()[0], (str(d["Status"]), MUT, SOFT))
        ratio = d["Runs"] / max(d["Runs needed"], 1)
        scn = int(d["Scoring needed"]) or 1
        rv = [v for v in vs if v.get("ref")]
        ref_line = ""
        if rv:
            dest = {}
            for v in rv:
                nm = "Family Medicine" if not v["ref"]["external"] else v["ref"]["to"].title()
                dest[nm] = dest.get(nm, 0) + 1
            ref_line = "Referrals: " + " · ".join(f"<b>{k}</b> to {E(n)}" for n, k in dest.items())
            nw = sum(1 for v in rv if v.get("ref_given"))
            if nw:
                ref_line += f' · <b style="color:#B3261E">{nw} given a lab or procedure</b>'
        need = int(d["Scoring still needed"]) if d["Scoring still needed"] not in ("", None) else 0
        need_txt = f"Needs <b style='color:{INK}'>{need} more scoring balls</b> by {E(check)}" if need else f"<b style='color:{SIX}'>Scoring on pace</b> for {E(check)}"
        out.append(
            f'<tr><td style="padding-bottom:14px;"><table {T} width="100%" bgcolor="#ffffff" style="background:#ffffff;border:1px solid {EDGE};border-radius:14px;">'
            f'<tr><td width="6" bgcolor="{fg}" style="background:{fg};border-radius:14px 0 0 14px;font-size:1px;">&nbsp;</td>'
            f'<td style="padding:18px 20px;">'
            # name row
            f'<table {T} width="100%"><tr><td><table {T}><tr>{rank_cell(rank + 1)}'
            f'<td style="padding-left:10px;font:bold 22px Arial,sans-serif;color:{INK};">{E(key)}</td></tr></table>'
            f'<div style="font-size:12.5px;color:{MUT};padding-top:4px;">{"Family Medicine" if "(FM)" in str(d["Doctor"]) else "General Practice"} · target {fmt(d["Runs target (day)"])} a day</div></td>'
            f'<td align="right" valign="top"><table {T}><tr><td bgcolor="{bg}" style="background:{bg};color:{fg};border:1px solid {fg};border-radius:14px;'
            f'padding:5px 12px;font:bold 11px Arial,sans-serif;letter-spacing:1px;">{lab}</td></tr></table></td></tr></table>'
            # runs
            f'<table {T} style="margin-top:12px;"><tr><td style="font:bold 40px Arial,sans-serif;color:{INK};padding-right:12px;">{fmt(d["Runs"])}</td>'
            f'<td valign="bottom" style="font-size:13.5px;color:{MUT};padding-bottom:6px;">runs of <b style="color:{INK}">{fmt(d["Runs needed"])}</b> needed by {E(check)}'
            f' &nbsp;·&nbsp; <b style="color:{fg}">{d["% of day"]}%</b> of day target</td></tr></table>'
            f'<div style="padding:8px 0 4px;">{bar(ratio, SIX, 10)}</div>'
            # stats
            f'<table {T.replace("cellspacing=\"0\"", "cellspacing=\"6\"")} width="100%" style="margin:6px -6px 4px;"><tr>'
            + stat(d["Balls"], "Balls") + stat(d["Dots"], "Dots") + stat(d["Referrals"], "Referral", GREY)
            + stat(d["4s"], "4s", FOUR) + stat(d["6s"], "6s", SIX)
            + stat(f'{d["Scoring"]}<span style="font-size:13px;color:{MUT};">/{scn}</span>', "Scoring", INK,
                   f'<div style="padding:5px 8px 0;">{bar(d["Scoring"] / scn, FOUR, 5)}</div>')
            + '</tr></table>'
            f'<div style="padding:8px 0 6px;">{balls(vs)}</div>'
            f'<div style="border-top:1px solid {LINE};padding-top:8px;">{chips(vs)}</div>'
            + (f'<div style="font-size:13px;color:{MUT};padding-top:6px;">{ref_line}</div>' if ref_line else "")
            + f'<div style="font-size:13px;color:{MUT};padding-top:8px;">{need_txt} &nbsp;·&nbsp; {fmt(d["Runs"] / max(d["Balls"], 1))} AED per ball</div>'
            '</td></tr></table></td></tr>')

    # by insurance
    out.append(section("Each doctor by insurance"))
    th = f'bgcolor="{SOFT}" style="background:{SOFT};color:{MUT};font-size:10.5px;letter-spacing:1px;text-transform:uppercase;padding:9px 10px;text-align:right;border-bottom:2px solid {EDGE};"'
    thl = th.replace("text-align:right", "text-align:left")
    td = f'style="padding:8px 10px;border-bottom:1px solid {LINE};text-align:right;font-size:13px;"'
    tdl = td.replace("text-align:right", "text-align:left")
    for doc in sorted(doc_visits):
        vs = doc_visits[doc]
        by = {}
        for v in vs:
            by.setdefault(v["insurance"], []).append(v)

        def row(name, ivs, tot=False):
            f4 = [v for v in ivs if v["ball"] == 4]; f6 = [v for v in ivs if v["ball"] == 6]
            runs = sum(v["runs"] for v in ivs); nref = sum(1 for v in ivs if v.get("ref"))
            tr = f' bgcolor="{SOFT}" style="background:{SOFT};font-weight:bold;"' if tot else ""
            return (f'<tr{tr}><td {tdl}>{E(name)}</td><td {td}>{len(ivs)}</td><td {td}>{sum(1 for v in ivs if v["ball"] == 0)}</td>'
                    f'<td {td}><b style="color:{GREY};">{nref if (nref or tot) else "–"}</b></td>'
                    f'<td {td}><b style="color:{FOUR};">{len(f4)}</b></td>'
                    f'<td {tdl}><span style="font-size:12px;color:{MUT};">{"" if tot else (E(agg_names(f4)) or "–")}</span></td>'
                    f'<td {td}><b style="color:{SIX};">{len(f6)}</b></td>'
                    f'<td {tdl}><span style="font-size:12px;color:{MUT};">{"" if tot else (E(agg_names(f6)) or "–")}</span></td>'
                    f'<td {td}>{fmt(runs)}</td><td {td}>{fmt(runs / max(len(ivs), 1))}</td></tr>')
        rows = "".join(row(ins, ivs) for ins, ivs in sorted(by.items(), key=lambda x: -len(x[1]))) + row("Total", vs, True)
        out.append(f'<tr><td style="font:bold 15px Arial,sans-serif;padding:14px 0 6px;color:{INK};">{E(doc)}</td></tr>'
                   f'<tr><td><table {T} width="100%" bgcolor="#ffffff" style="background:#ffffff;border:1px solid {EDGE};border-collapse:collapse;">'
                   f'<tr><th {thl}>Insurance</th><th {th}>Balls</th><th {th}>Dots</th><th {th}>Referral</th><th {th}>4s</th>'
                   f'<th {thl}>What the 4s were</th><th {th}>6s</th><th {thl}>What the 6s were</th><th {th}>Runs</th><th {th}>Per ball</th></tr>'
                   f'{rows}</table></td></tr>')

    out.append(f'<tr><td style="font-size:12px;color:{MUT};padding:20px 0 0;">Runs = insurance share after copay on corrected prices. '
               f'{len(logdf)} corrections applied – details in the attached Excel file. '
               f'Sent from the EMC Revenue Scorecard, {datetime.now(UAE):%d-%m-%Y %I:%M %p}.</td></tr>')
    out.append('</table></td></tr></table>')
    return "".join(out)


with tab5:
    smtp = {"host": _secret("SMTP_HOST"), "port": _secret("SMTP_PORT", "465"),
            "user": _secret("SMTP_USER"), "password": _secret("SMTP_PASS")}
    if not (smtp["host"] and smtp["user"] and smtp["password"]):
        smtp = {}
    c1, c2 = st.columns(2)
    to = c1.text_input("Send to (comma separated)", value=_secret("EMAIL_TO"))
    cc = c2.text_input("CC (comma separated)", value=_secret("EMAIL_CC"))
    subject = st.text_input("Subject", value=f"EMC Revenue Scorecard - {', '.join(dates)} - {check} check")
    html = email_dashboard_html()
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
