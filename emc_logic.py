"""EMC Revenue Scorecard - correction and scoring logic.

Reads the raw HIS "ProcedureDetails" report (coded or not coded), corrects it and scores
each doctor like cricket: every patient is a ball.
  Dot = consultation only, 4 = one lab or procedure, 6 = two or more.
  Runs = insurance money after copay, on corrected prices. Cash visits are priced like other insurers (patient pays all).
"""
import io
import re
from datetime import datetime

import pandas as pd

# ---------------- Rules (edit here) ----------------
CONSULT = {
    "daman": {"est": (95.0, "99213"), "new": (142.0, "99203")},   # Daman always level 3
    "other": {"est": (56.0, "99212"), "new": (98.0, "99202")},    # all other insurers level 2
}
FOLLOW_UP_BELOW = 30.0      # insurance consult billed under this = free / copay-only follow-up, left as billed
LAB_COPAY = 0.20            # copay used when a zero-priced lab gets priced
SKIP_SCORING = {"36415"}    # blood collection: part of the lab, not a ball
# Full-care targets per day. Consultation base uses real new/established mix from Oct-2026 claims:
# GP: 5 referrals x 75 + 17 Daman x 80.37 + 12 non-Daman x 46.24 = 2,296 + labs/procedures 1,342 = 3,639
# FM: 5 referrals x 75 + 15 Daman x 105.95 + 10 non-Daman x 69.01 = 2,654 + 1,342 = 3,997
TARGETS = {"gp": {"balls": 34, "scoring": 22, "runs": 3639},
           "fm": {"balls": 30, "scoring": 22, "runs": 3997}}
PACE = {"12 PM": 0.25, "4 PM": 0.50, "8 PM": 0.75, "Closing": 1.00}

# Procedure prices billed to insurers (used to price cash visits)
PROC_PRICES = {"96372": 20, "96374": 20, "96360": 71, "96361": 20, "96365": 86, "94640": 32, "93000": 65,
               "51-01": 25, "82948": 11, "10060": 341, "12001": 253, "12002": 253, "11730": 226,
               "69210": 122, "69209": 106, "36415": 0}
# Deck lab prices (insurance money, after copay and lab company share) - used for non-Daman labs billed at 0 and cash
DECK_LAB = {"85025": 18.58, "86140": 12.61, "81001": 7.30, "80051": 23.89, "80061": 43.13, "83036": 23.22,
            "80053": 128.06, "80069": 112.14, "80076": 82.28}
DECK_RATIO = 0.6636         # deck price = Daman gross x 0.6636 (used for lab codes not in the deck)
LAB_PRICES = {"80051": 36, "80061": 65, "80069": 169, "81001": 11, "82565": 18, "83036": 35,
              "84520": 14, "84550": 16, "85025": 28, "86140": 19}   # Daman lab gross prices; add X-ray prices when known


def deck_lab(code, lab_price):
    if code in DECK_LAB:
        return DECK_LAB[code]
    g = lab_price.get(code)
    return round(g * DECK_RATIO, 2) if g else None

SHORT = {"85025": "CBC", "80061": "Lipid panel", "83036": "HbA1c", "82565": "Creatinine", "84520": "Urea",
         "81001": "Urinalysis", "80051": "Electrolytes", "80069": "Renal panel", "84550": "Uric acid",
         "86140": "CRP", "80053": "CMP", "80076": "Liver panel", "36415": "Blood collection", "93000": "ECG",
         "96360": "IV drip, first hour", "96361": "IV drip, each extra hour", "96372": "IM / SC injection",
         "96374": "IV push injection", "94640": "Nebulizer", "69209": "Ear wax removal", "69210": "Ear wax removal",
         "71045": "Chest X-ray", "73560": "Knee X-ray", "10060": "Incision and drainage",
         "12002": "Wound repair, small", "16020": "Burn dressing", "11730": "Nail removal"}
DOC_ALIAS = {"MDERSHADUL ALAM": "Dr. Ershadul Alam", "SYED BILAL HAIDER": "Dr. Syed Bilal Haider",
             "SANA ULLAH AFRIDI": "Dr. Sana Ullah Afridi", "SAAD HABIB": "Dr. Saad Habib", "SANT DAS": "Dr. Sant Das"}
INS_NAMES = [("DAMAN", "Daman"), ("E CARE", "E Care"), ("NAS ADMIN", "NAS"), ("INAYAH", "Inayah"), ("FMC", "FMC"),
             ("OMAN", "Oman Insurance"), ("ALMADALLAH", "Almadallah"), ("NEXTCARE", "Nextcare"), ("AAFIYA", "Aafiya"),
             ("ABU DHABI NATIONAL INS", "ADNIC"), ("ADNIC", "ADNIC"), ("MEDNET", "MedNet"), ("GLOBEMED", "GlobeMed"),
             ("NEURON", "Neuron")]


def _clean(x):
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return ""
    s = re.sub(r"\s+", " ", str(x)).strip()
    return s[:-2] if re.fullmatch(r"\d+\.0", s) else s


def _num(x):
    try:
        v = float(x)
        return 0.0 if pd.isna(v) else v
    except (TypeError, ValueError):
        return 0.0


def doc_name(d):
    d = _clean(d).upper()
    return DOC_ALIAS.get(d, "Dr. " + d.title() if d else "Unknown doctor")


def ins_name(s):
    s = _clean(s).upper()
    if not s:
        return "Cash"
    for key, name in INS_NAMES:
        if key in s:
            return name
    return " ".join(s.split()[:2]).title()


def item_name(code, name):
    if code in SHORT:
        return SHORT[code]
    name = _clean(name)
    return name if len(name) <= 46 else name[:44] + "…"


# ---------------- Read ----------------
def read_report(file_bytes, filename=""):
    """Return a list of line dicts from a ProcedureDetails .xlsx / .xls file."""
    engine = "xlrd" if filename.lower().endswith(".xls") else None
    raw = pd.read_excel(io.BytesIO(file_bytes), header=None, engine=engine, dtype=object)
    hdr = None
    for i in range(min(len(raw), 30)):
        vals = [_clean(v) for v in raw.iloc[i].tolist()]
        if "Invoice No" in vals and "CPT:Type" in vals:
            hdr = i
            break
    if hdr is None:
        raise ValueError('This is not a ProcedureDetails report: no "Invoice No" and "CPT:Type" columns found.')
    cols = {}
    for j, v in enumerate(raw.iloc[hdr].tolist()):
        v = _clean(v)
        if v and v not in cols:
            cols[v] = j
    for need in ["Invoice No", "Procedure Code", "CPT:Type", "Doctor", "Gross Amount", "Ins: Amount", "Pat share"]:
        if need not in cols:
            raise ValueError(f'Column "{need}" is missing from the report.')

    def g(row, name):
        return row[cols[name]] if name in cols else None

    lines = []
    for _, r in raw.iloc[hdr + 1:].iterrows():
        r = r.tolist()
        if "SL No" in cols and _num(g(r, "SL No")) == 0 and _clean(g(r, "SL No")) in ("", "nan"):
            continue
        inv = _clean(g(r, "Invoice No"))
        if not inv:
            continue
        lines.append({"date": _clean(g(r, "Date")), "inv": inv, "code": _clean(g(r, "Procedure Code")),
                      "name": _clean(g(r, "Procedure Name")), "qty": _num(g(r, "Quantity")), "ins": _num(g(r, "Ins: Amount")),
                      "pat": _num(g(r, "Pat share")), "gross": _num(g(r, "Gross Amount")),
                      "dept": _clean(g(r, "Department")), "doctor": _clean(g(r, "Doctor")),
                      "type": _clean(g(r, "CPT:Type")).upper(), "insurance": _clean(g(r, "Insurance"))})
    if not lines:
        raise ValueError("The report has no rows.")
    return lines


# ---------------- Correct ----------------
def correct(lines):
    log = []
    lab_price = dict(LAB_PRICES)
    for l in lines:
        if l["type"] in ("LAB", "RADIOLOGY") and l["gross"] > 0 and l["code"] not in lab_price:
            lab_price[l["code"]] = l["gross"]

    # medicine unit prices as billed to non-Daman insurers (Daman UPP price as fallback) - used for cash visits
    med_unit, med_unit_daman = {}, {}
    for l in lines:
        if l["type"] == "MEDICINES" and l["insurance"] and l["gross"] > 0 and l.get("qty", 0) > 0:
            target = med_unit_daman if "DAMAN" in l["insurance"].upper() else med_unit
            target.setdefault(l["code"], []).append(l["gross"] / l["qty"])
    med_unit = {k: sorted(v)[len(v) // 2] for k, v in med_unit.items()}
    for k, v in med_unit_daman.items():
        med_unit.setdefault(k, sorted(v)[len(v) // 2])

    proc_price = dict(PROC_PRICES)
    for l in lines:
        if l["type"] == "PROCEDURE" and l["insurance"] and l["gross"] > 0 and l["code"] not in proc_price:
            proc_price[l["code"]] = l["gross"]

    by_inv = {}
    for l in lines:
        by_inv.setdefault(l["inv"], []).append(l)

    visits = []
    for inv, ls in by_inv.items():
        f = ls[0]
        v = {"inv": inv, "date": f["date"], "doctor": doc_name(f["doctor"]), "fm": "FAMILY" in f["dept"].upper(),
             "insurance": ins_name(f["insurance"]), "cash": not f["insurance"], "lines": []}
        daman = v["insurance"] == "Daman"

        def note(kind, code, before, after, label=""):
            log.append({"Correction": kind, "Doctor": v["doctor"], "Insurance": v["insurance"], "Invoice": inv,
                        "Item": f"{label} ({code})" if label else code, "Before": before,
                        "After": "removed" if after is None else after})

        cons = [l for l in ls if l["type"] == "CONSULTATION"]
        keep = max(cons, key=lambda l: l["gross"]) if cons else None
        for l in cons:
            if l is not keep:
                note("Extra consultation line removed", l["code"], l["gross"], None)

        for l in ls:
            if l["type"] == "CONSULTATION" and l is not keep:
                continue
            c = dict(l)
            if v["cash"]:
                # cash: price like other insurers, patient pays all
                price = None
                if l["type"] == "CONSULTATION" and l["gross"] > 0:
                    price, code = CONSULT["other"]["new" if l["code"].startswith("9920") else "est"]
                    c["code"] = code
                elif l["type"] in ("LAB", "RADIOLOGY"):
                    price = deck_lab(l["code"], lab_price)
                    if price is None and l["gross"] == 0:
                        note("No price found (left at 0)", l["code"], 0, 0, item_name(l["code"], l["name"]))
                elif l["type"] == "PROCEDURE":
                    price = proc_price.get(l["code"])
                elif l["type"] == "MEDICINES" and l["code"] in med_unit and l.get("qty", 0) > 0:
                    price = round(med_unit[l["code"]] * l["qty"], 2)
                if price is not None and abs(price - l["gross"]) > 0.01:
                    note("Cash priced as other insurers", l["code"], l["gross"], price, item_name(l["code"], l["name"]))
                    c.update(gross=price)
                c.update(pat=c["gross"], ins=0.0)
            elif l["type"] == "CONSULTATION" and l["gross"] >= FOLLOW_UP_BELOW:
                is_new = l["code"].startswith("9920")
                price, code = CONSULT["daman" if daman else "other"]["new" if is_new else "est"]
                if abs(l["gross"] - price) > 0.01 or l["code"] != code:
                    if daman:
                        pat = min(l["pat"] if l["pat"] > 0 else 20.0, price)
                    elif l["gross"] > 0 and abs(l["pat"] / l["gross"] - 0.2) < 0.006:
                        pat = round(price * 0.2, 2)
                    else:
                        pat = min(l["pat"], price)
                    note("Daman consultation set to level 3" if daman else "Consultation set to level 2",
                         f'{l["code"]} → {code}', l["gross"], price)
                    c.update(code=code, gross=price, pat=pat, ins=round(price - pat, 2))
            elif l["type"] in ("LAB", "RADIOLOGY") and l["gross"] == 0 and not daman:
                dp = deck_lab(l["code"], lab_price)
                if dp:
                    c.update(gross=dp, pat=0.0, ins=dp)
                    note("Non-Daman lab at 0 priced (deck price)", l["code"], 0, dp, item_name(l["code"], l["name"]))
                else:
                    note("No price found (left at 0)", l["code"], 0, 0, item_name(l["code"], l["name"]))
            elif l["type"] in ("LAB", "RADIOLOGY") and l["gross"] == 0:
                lp = lab_price.get(l["code"])
                if lp:
                    pat = round(lp * LAB_COPAY, 2)
                    c.update(gross=lp, pat=pat, ins=round(lp - pat, 2))
                    note("Daman lab at 0 priced", l["code"], 0, lp, item_name(l["code"], l["name"]))
                else:
                    note("No price found (left at 0)", l["code"], 0, 0, item_name(l["code"], l["name"]))
            v["lines"].append(c)

        v["items"] = [c for c in v["lines"] if c["type"] in ("LAB", "RADIOLOGY", "PROCEDURE")
                      and c["code"] not in SKIP_SCORING]
        n = len(v["items"])
        v["ball"] = 0 if n == 0 else 4 if n == 1 else 6
        v["runs"] = round(sum(c["gross"] if v["cash"] else c["ins"] for c in v["lines"]), 2)
        v["billed_ins"] = 0.0 if v["cash"] else round(sum(l["ins"] for l in ls), 2)
        visits.append(v)
    dates = sorted({l["date"] for l in lines})
    return visits, pd.DataFrame(log), dates


# ---------------- Score ----------------
def summarize(visits, pace=1.0):
    """Return (doctors_df, by_insurance_df, items_df, strips) for the given pace (0.25 / 0.5 / 0.75 / 1)."""
    docs, ins, items, strips = {}, {}, {}, {}
    for v in visits:
        d = docs.setdefault(v["doctor"], {"Doctor": v["doctor"], "FM": False, "Balls": 0, "Dots": 0, "4s": 0, "6s": 0, "Runs": 0.0})
        d["FM"] = d["FM"] or v["fm"]
        key = "Dots" if v["ball"] == 0 else "4s" if v["ball"] == 4 else "6s"
        d["Balls"] += 1; d[key] += 1; d["Runs"] += v["runs"]
        strips.setdefault(v["doctor"], []).append(v["ball"])
        i = ins.setdefault((v["doctor"], v["insurance"]), {"Doctor": v["doctor"], "Insurance": v["insurance"],
                                                           "Balls": 0, "Dots": 0, "4s": 0, "6s": 0, "Runs": 0.0})
        i["Balls"] += 1; i[key] += 1; i["Runs"] += v["runs"]
        for c in v["items"]:
            it = items.setdefault((v["doctor"], c["type"], c["code"]), {"Doctor": v["doctor"], "Item": item_name(c["code"], c["name"]),
                                                                          "Type": c["type"].title(), "Code": c["code"], "Count": 0, "Runs": 0.0})
            it["Count"] += 1
            it["Runs"] += c["gross"] if v["cash"] else c["ins"]

    rows = []
    for name in sorted(docs):
        d = docs[name]
        t = TARGETS["fm" if d["FM"] else "gp"]
        scoring = d["4s"] + d["6s"]
        runs_need, score_need = round(t["runs"] * pace), round(t["scoring"] * pace)
        status = ("ON TRACK" if d["Runs"] >= runs_need and scoring >= score_need
                  else "WATCH" if d["Runs"] >= 0.8 * runs_need else "CHECK")
        rows.append({"Doctor": name + (" (FM)" if d["FM"] else ""), "Balls": d["Balls"], "Balls target": t["balls"],
                     "Dots": d["Dots"], "4s": d["4s"], "6s": d["6s"], "Scoring": scoring, "Scoring needed": score_need,
                     "Runs": round(d["Runs"]), "Runs needed": runs_need, "Runs target (day)": t["runs"],
                     "% of day": round(d["Runs"] / t["runs"] * 100), "Status": status,
                     "Scoring still needed": max(0, score_need - scoring)})
    ddf = pd.DataFrame(rows)
    if len(ddf):
        tot = {"Doctor": "Clinic", "Balls": ddf["Balls"].sum(), "Balls target": ddf["Balls target"].sum(),
               "Dots": ddf["Dots"].sum(), "4s": ddf["4s"].sum(), "6s": ddf["6s"].sum(), "Scoring": ddf["Scoring"].sum(),
               "Scoring needed": ddf["Scoring needed"].sum(), "Runs": ddf["Runs"].sum(), "Runs needed": ddf["Runs needed"].sum(),
               "Runs target (day)": ddf["Runs target (day)"].sum(), "Status": "", "Scoring still needed": None}
        tot["% of day"] = round(tot["Runs"] / tot["Runs target (day)"] * 100)
        ddf = pd.concat([ddf, pd.DataFrame([tot])], ignore_index=True)

    idf = pd.DataFrame(list(ins.values()))
    if len(idf):
        idf["Runs"] = idf["Runs"].round()
        idf["Runs per ball"] = (idf["Runs"] / idf["Balls"]).round()
        idf = idf.sort_values(["Doctor", "Balls"], ascending=[True, False]).reset_index(drop=True)
    itdf = pd.DataFrame(list(items.values()))
    if len(itdf):
        itdf["Runs"] = itdf["Runs"].round()
        itdf = itdf.sort_values(["Doctor", "Type", "Count"], ascending=[True, True, False]).reset_index(drop=True)
    return ddf, idf, itdf, strips


def strip_text(balls):
    return " ".join("·" if b == 0 else str(b) for b in balls)


# ---------------- Outputs ----------------
def to_excel(ddf, idf, itdf, logdf, meta):
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        pd.DataFrame({"": [f"EMC Revenue Scorecard - {meta}"]}).to_excel(xw, sheet_name="Scorecard", index=False, header=False)
        ddf.to_excel(xw, sheet_name="Scorecard", index=False, startrow=2)
        idf.to_excel(xw, sheet_name="By insurance", index=False)
        itdf.to_excel(xw, sheet_name="Labs and procedures", index=False)
        (logdf if len(logdf) else pd.DataFrame({"Correction": ["None"]})).to_excel(xw, sheet_name="Corrections", index=False)
        for ws in xw.book.worksheets:
            for col in ws.columns:
                width = max(len(str(c.value)) if c.value is not None else 0 for c in col)
                ws.column_dimensions[col[0].column_letter].width = min(max(10, width + 2), 45)
    return buf.getvalue()


STATUS_COLORS = {"ON TRACK": ("#E2F3E8", "#1E7A45"), "WATCH": ("#FBF0D9", "#9A6200"), "CHECK": ("#FBE4E1", "#B3261E")}


def _table(df, cols, money=()):
    th = "".join(f'<th style="padding:6px 10px;background:#EDF1EC;border:1px solid #DDE3DC;font-size:12px;text-align:{"left" if i == 0 else "right"}">{c}</th>'
                 for i, c in enumerate(cols))
    body = ""
    for _, r in df.iterrows():
        last = str(r[cols[0]]) in ("Clinic", "Total")
        tds = ""
        for i, c in enumerate(cols):
            val = r[c]
            if c in money and val not in ("", None) and not pd.isna(val):
                val = f"{val:,.0f}"
            elif val is None or (isinstance(val, float) and pd.isna(val)):
                val = "–"
            style = f'padding:6px 10px;border:1px solid #DDE3DC;font-size:13px;text-align:{"left" if i == 0 else "right"};'
            if last:
                style += "font-weight:bold;background:#F5F6F2;"
            if c == "Status" and val in STATUS_COLORS:
                bg, fg = STATUS_COLORS[val]
                val = f'<span style="background:{bg};color:{fg};padding:2px 8px;border-radius:10px;font-weight:bold;font-size:11px">{val}</span>'
            tds += f'<td style="{style}">{val}</td>'
        body += f"<tr>{tds}</tr>"
    return f'<table style="border-collapse:collapse;margin:6px 0 18px">{"<tr>" + th + "</tr>"}{body}</table>'


def email_html(ddf, idf, itdf, logdf, meta, check):
    clinic = ddf[ddf["Doctor"] == "Clinic"].iloc[0] if len(ddf) else None
    head = ""
    if clinic is not None:
        head = (f'<p style="font-size:15px"><b>Clinic:</b> {int(clinic["Balls"])} patients · '
                f'{int(clinic["Scoring"])} scoring balls of {int(clinic["Scoring needed"])} needed · '
                f'<b>{clinic["Runs"]:,.0f} runs</b> of {clinic["Runs needed"]:,.0f} needed by {check} '
                f'({clinic["% of day"]}% of the day target)</p>')
    cols = ["Doctor", "Balls", "Dots", "4s", "6s", "Scoring", "Scoring needed", "Runs", "Runs needed", "% of day", "Status"]
    html = (f'<div style="font-family:Segoe UI,Arial,sans-serif;color:#18211C">'
            f'<h2 style="margin:0 0 4px">EMC Revenue Scorecard - {check} check</h2>'
            f'<p style="color:#5D6A62;margin:0 0 12px">{meta}</p>{head}'
            f'<h3 style="margin:14px 0 4px">Doctor scorecard</h3>{_table(ddf, cols, money=("Runs", "Runs needed"))}'
            f'<p style="font-size:12px;color:#5D6A62">Dot = consultation only · 4 = one lab or procedure · 6 = two or more. '
            f'Runs = insurance money after copay on corrected prices (Daman level 3, other insurers level 2, medicine as billed). Cash visits priced as other insurers.</p>')
    if len(idf):
        html += '<h3 style="margin:14px 0 4px">Each doctor by insurance</h3>'
        html += _table(idf, ["Doctor", "Insurance", "Balls", "Dots", "4s", "6s", "Runs", "Runs per ball"], money=("Runs", "Runs per ball"))
    if len(itdf):
        html += '<h3 style="margin:14px 0 4px">Labs and procedures</h3>'
        html += _table(itdf, ["Doctor", "Item", "Type", "Code", "Count", "Runs"], money=("Runs",))
    html += (f'<p style="font-size:12px;color:#5D6A62">{len(logdf)} corrections applied - details in the attached Excel file.</p>'
             f'<p style="font-size:12px;color:#5D6A62">Sent from the EMC Revenue Scorecard, {datetime.now():%d-%m-%Y %H:%M}.</p></div>')
    return html


def send_email(smtp_cfg, to_list, subject, html, attachment=None, attachment_name="EMC_Scorecard.xlsx", cc_list=None):
    """smtp_cfg keys: host, port, user, password, sender (optional). Port 465 uses SSL, others STARTTLS."""
    import smtplib
    import ssl
    from email.message import EmailMessage
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = smtp_cfg.get("sender") or smtp_cfg["user"]
    msg["To"] = ", ".join(to_list)
    if cc_list:
        msg["Cc"] = ", ".join(cc_list)
    msg.set_content("Please view this email in HTML.")
    msg.add_alternative(html, subtype="html")
    if attachment:
        msg.add_attachment(attachment, maintype="application",
                           subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet", filename=attachment_name)
    port = int(smtp_cfg.get("port") or 465)
    ctx = ssl.create_default_context()
    if port == 465:
        with smtplib.SMTP_SSL(smtp_cfg["host"], port, context=ctx, timeout=30) as s:
            s.login(smtp_cfg["user"], smtp_cfg["password"])
            s.send_message(msg)
    else:
        with smtplib.SMTP(smtp_cfg["host"], port, timeout=30) as s:
            s.starttls(context=ctx)
            s.login(smtp_cfg["user"], smtp_cfg["password"])
            s.send_message(msg)
