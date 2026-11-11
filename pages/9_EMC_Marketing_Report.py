"""EMC Marketing Report - Streamlit page (separate from the Revenue Scorecard).

Upload the HIS Registration List (and optionally the ProcedureDetails report for revenue).
Shows which companies and camps the patients come from: today, month so far, growing / dropping / lost companies.
Marketing team sees patient counts only; management also sees revenue per company.
"""
import difflib
import html as _h
import io
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import streamlit as st

for _p in (Path(__file__).resolve().parent, Path(__file__).resolve().parents[1]):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

st.set_page_config(page_title="EMC Marketing Report", page_icon="📣", layout="wide")
UAE = timezone(timedelta(hours=4))
E = lambda s: _h.escape(str(s))                                        # noqa: E731


def fmt(n):
    try:
        return f"{float(n):,.0f}"
    except Exception:  # noqa: BLE001
        return str(n)


def _secret(name, default=""):
    try:
        if name in st.secrets:
            return str(st.secrets[name])
    except Exception:  # noqa: BLE001
        pass
    return os.environ.get(name, default)


# ---------------------------------------------------------------- style
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Barlow+Semi+Condensed:wght@500;600;700&family=IBM+Plex+Sans:wght@400;500;600&display=swap');
:root{--ink:#18211C; --muted:#5D6A62; --line:#E1E6E0; --soft:#F2F5F1; --card:#fff; --brand:#1F4E8C; --brand-soft:#E8EEF8;
      --ok:#1E7A45; --ok-bg:#E2F3E8; --bad:#B3261E; --bad-bg:#FBE4E1; --warn:#9A6200; --warn-bg:#FBF0D9;}
html, body, [class*="css"], .stMarkdown, p, li, label, input, button, textarea {font-family:'IBM Plex Sans', system-ui, sans-serif;}
.block-container{padding-top:3.8rem; max-width:1280px;}
h1,h2,h3{font-family:'Barlow Semi Condensed','Arial Narrow',sans-serif !important;}
.hero{background:linear-gradient(135deg,#16335C 0%,#1F4E8C 70%,#2C66B0 100%); color:#fff; border-radius:16px; padding:24px 28px;
      display:flex; justify-content:space-between; align-items:flex-end; flex-wrap:wrap; gap:14px; margin-bottom:16px;}
.hero h1{color:#fff !important; font-size:36px; margin:0; line-height:1.05; padding:0;}
.hero p{color:#D6E2F3; margin:6px 0 0; font-size:14px;}
.chip{background:rgba(255,255,255,.14); border:1px solid rgba(255,255,255,.25); color:#fff; padding:5px 12px; border-radius:999px; font-size:12.5px;}
.kpis{display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr)); gap:14px; margin:4px 0 16px;}
.kpi{background:var(--card); border:1px solid var(--line); border-radius:14px; padding:15px 18px;}
.kpi.m{border:1.5px solid var(--brand); background:#FAFCFF;}
.kpi .lbl{font-size:11px; text-transform:uppercase; letter-spacing:.09em; color:var(--muted); font-weight:600;}
.kpi .val{font-family:'Barlow Semi Condensed',sans-serif; font-size:34px; font-weight:700; color:var(--ink); line-height:1.1; margin-top:4px;}
.kpi .val small{font-size:16px; color:var(--muted); font-weight:500;}
.kpi .sub{font-size:12.5px; color:var(--muted); margin-top:3px;}
.warnline{color:var(--warn); font-weight:600; font-size:12.5px; margin-top:6px;}
.sec{font-family:'Barlow Semi Condensed',sans-serif; font-size:21px; font-weight:700; color:var(--ink); margin:18px 0 8px;}
.note{font-size:12.5px; color:var(--muted); margin:4px 0 10px;}
.tbl{width:100%; border-collapse:separate; border-spacing:0; background:var(--card); border:1px solid var(--line); border-radius:12px; overflow:hidden; font-size:13.5px;}
.tbl th{background:var(--soft); color:var(--muted); font-size:11px; text-transform:uppercase; letter-spacing:.06em; text-align:right; padding:9px 12px; border-bottom:1px solid var(--line);}
.tbl td{padding:8px 12px; border-bottom:1px solid var(--line); text-align:right; font-variant-numeric:tabular-nums;}
.tbl th:first-child,.tbl td:first-child{text-align:left;} .tbl tr:last-child td{border-bottom:0;}
.tbl td.nm{font-weight:600; color:var(--ink); text-align:left;} .tbl th.l{text-align:left;}
.dwrap{overflow-x:auto; border-radius:12px;} .dd td,.dd th{padding:7px 8px; white-space:nowrap;} .dd td.nm{position:sticky; left:0; background:#fff; z-index:1; min-width:220px; white-space:normal;}
.dd th:first-child{position:sticky; left:0; z-index:2;} .dd tr.tot td{background:var(--brand-soft); font-weight:700;} .dd td.z{color:#C9D2CB;} .dd td.hi{background:#E8EEF8; font-weight:700;} .tbl .rank{color:var(--muted); width:28px;}
.up{color:var(--ok); font-weight:700;} .down{color:var(--bad); font-weight:700;} .flat{color:var(--muted);}
.barc{display:inline-block; height:8px; background:var(--brand); border-radius:4px; vertical-align:middle; margin-right:6px;}
.empty{background:var(--soft); border:1px dashed #C9D2CB; border-radius:12px; padding:14px 16px; color:var(--muted); font-size:13.5px;}
.tag{display:inline-block; padding:2px 8px; border-radius:999px; font-size:11px; font-weight:700;}
.t-new{background:#E8EEF8; color:#1F4E8C;} .t-lost{background:var(--bad-bg); color:var(--bad);}
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------- company baseline
# Saved from the full Registration List 1 Jan 2024 – 11 Nov 2026 (unique patients by EMR No, company spellings merged).
# rows: [company, unique patients, unique last 12 months, avg patients a month (last 12 months), visits, last visit]
BASE = json.loads('{"from":"2024-01-01","asof":"2026-11-11","tot":30532,"tot12":15915,"companies":1208,"ones":608,"top10":15085,"bands":[["1",608,608],["2–9",363,1282],["10–49",154,3234],["50–199",58,5902],["200–999",19,7794],["1,000+",6,12048]],"rows":[["Arco Electromechanical",2611,2066,623,20933,"2026-11-11"],["Exceed Precast",2604,1993,492,13824,"2026-11-11"],["Hilal Bil Badi and Partners Cont Co Hilalco",2478,1562,313,17763,"2026-11-11"],["Tirhal Employment",1780,1385,225,2923,"2026-11-11"],["Sawaeed",1437,6,1,3210,"2026-11-02"],["Qamra Transport and Gen. Cont. Est",1138,746,166,7604,"2026-11-11"],["China State Construction",981,19,4,2523,"2026-06-07"],["Efs Facilities Management Services",743,200,35,2739,"2026-11-11"],["Agility Engineering and Contracting Company",677,273,32,3172,"2026-11-11"],["Professional Security Systems",636,329,25,903,"2026-11-11"],["Gulf Industrial Services Company - Gisco",552,250,47,2097,"2026-11-11"],["G 4S Secure Solutions",455,37,4,628,"2026-11-03"],["Alryum Contracting General Transport",406,234,48,2605,"2026-11-11"],["M4 Contracting S A R I Abu Dhabi",394,183,36,1873,"2026-11-09"],["Arco General Contracting",349,199,39,2144,"2026-11-10"],["Emirates Gateway Security Services",343,248,35,1080,"2026-11-06"],["Fibrex Branch 1",336,18,4,924,"2026-10-18"],["Profile Recruitment",321,110,16,856,"2026-11-11"],["Voltas Limited",252,155,27,1705,"2026-08-04"],["Asgc Construction",250,8,1,624,"2026-10-05"],["Nmdc Energy",237,237,27,375,"2026-11-11"],["Innovo Build",237,137,18,528,"2026-11-11"],["Alkaline Electromechanical",212,196,33,715,"2026-11-11"],["Tecton Engineeing & Construction",207,62,9,459,"2026-11-09"],["A D C Energy Systems",206,74,11,710,"2026-11-07"],["Al Geemi Contracting Company",184,146,25,520,"2026-11-11"],["Innovo Mep Electromechanical Works",180,71,10,367,"2026-11-10"],["Arabian Gulf Steel Industries",177,95,13,712,"2026-11-11"],["A G Facilities Solutions For Building",170,39,6,621,"2026-11-08"],["Sawaeed Employment",167,3,1,271,"2026-10-24"],["Gulf Contractors Co",166,123,23,663,"2026-11-11"],["Alshafar United For Electromechanical Engineering",162,4,1,281,"2026-08-11"],["Emirates Electrical and Instrumentation",156,116,16,361,"2026-11-11"],["Almuthalath Alsharqi Security Guard Services",155,102,8,161,"2026-10-27"],["Tanzifco Emirates",154,101,13,352,"2026-11-10"],["Alba Tec Employment",152,75,10,443,"2026-10-10"],["Al Geemi & Partners Contracting Company",147,50,8,531,"2026-11-08"],["National Catering Company",143,79,14,499,"2026-11-11"],["Okool Manpower Recruitment Service",140,82,12,300,"2026-11-11"],["Mfour Building Contracting",137,78,17,596,"2026-11-05"],["Emarat Aloula Contracting Co",133,12,3,250,"2026-09-30"],["Arco Intl Contracting Company",127,59,11,861,"2026-11-09"],["Arabian Construction Co",125,125,42,136,"2026-11-11"],["Oil and Gas Construction",124,51,8,665,"2026-11-09"],["Sbk Holding ( )",120,59,9,358,"2026-11-07"],["Power Recruitment",119,6,2,216,"2026-11-01"],["Combined Group Contracting Emirates",116,17,2,272,"2026-11-01"],["International Decor Co",115,24,4,473,"2026-11-11"],["Noor Al Sahara Gen Contracting",108,82,11,260,"2026-11-10"],["Cylingas Company",105,39,7,429,"2026-11-11"],["Six Sigma Middle East Constructions",102,48,11,426,"2026-11-11"],["Shapoorji Pallonji Mideast",102,102,52,108,"2026-11-10"],["Alba Tec",96,31,7,588,"2026-11-03"],["Emirates Landscape",96,5,1,201,"2026-10-29"],["Space Age Switchgear Elect Co",91,29,5,331,"2026-10-02"],["Star Services",84,17,3,225,"2026-11-01"],["Ali and Sons Contracting Company",83,2,2,126,"2026-01-31"],["Hassan Allam Construction",82,76,10,190,"2026-11-10"],["Construction General Contracting House Ltd",80,11,2,172,"2026-11-08"],["Danway Electrical &Mechanical Engineering",79,79,14,228,"2026-11-09"],["Noor Alsahraa International General",79,65,10,193,"2026-11-08"],["Al Bayader Irrigation and Contracting",75,38,6,411,"2026-11-09"],["Albatec Const and Development",71,50,15,649,"2026-11-10"],["Census International Company",71,14,3,296,"2026-10-23"],["Dolphin Oilfield Equipment Services Co",69,64,15,309,"2026-11-11"],["Gulf Eagle Contracting Company",69,29,5,281,"2026-11-07"],["Mosayed Bin Hafeez Cont Gen Transport",69,1,1,197,"2026-02-03"],["Mq Peael Engineering",67,67,23,310,"2026-11-09"],["Gulf Tunneling Company",65,62,14,286,"2026-11-11"],["Efs Investment",65,49,8,225,"2026-11-03"],["Qamara Carpentry",64,38,8,482,"2026-11-10"],["Pivot Engineering and General Contracting Co",59,24,3,134,"2026-11-05"],["National Innovative General Maintnance",59,45,7,169,"2026-10-31"],["Sibca Electronic Equipment Company Limited",58,58,13,228,"2026-11-07"],["Hafilat General Transport",58,56,20,344,"2026-11-11"],["Al Bahiya Trading and Services",57,25,3,145,"2026-11-03"],["Elite Star Catering",56,7,2,154,"2026-08-04"],["Noor Al Sahara General Transportation",56,50,7,125,"2026-11-10"],["Shj Environment Co Beeah Br Abu Dhabi",54,15,2,100,"2026-09-28"],["Verger Delporte Uae Ltd Co",52,5,1,116,"2026-10-02"],["Qamra Aluminium Works Est",51,28,6,322,"2026-11-07"],["Qamara Electromechanicla Contractin Est",51,37,8,353,"2026-11-09"],["Marina Facilities Management",50,9,2,79,"2026-10-04"],["Ag Facilities Solutions Buildings Maintenance",48,26,4,182,"2026-11-04"],["Emirates Link Maltauro Company",48,8,1,117,"2026-08-25"],["Paragon Employment Services",48,2,1,111,"2026-11-08"],["Pioneer Precast Concrete",48,40,11,468,"2026-11-09"],["Focus Security Services",47,41,6,147,"2026-09-29"],["Hyssna International",46,33,6,246,"2026-11-07"],["Abudhabi Berkeley Services",45,17,3,170,"2026-10-05"],["M 4 Contrcting Abu Dhabi",44,20,3,205,"2026-11-06"],["Western Bainoona Group",43,9,2,78,"2026-08-08"],["Express Facilities Mangment",42,10,2,115,"2026-11-10"],["Tecton Engineering",42,7,2,130,"2026-08-14"],["Al Masood National General Contracting",41,2,2,141,"2026-10-05"],["Potential Contracting",41,0,0,124,"2025-03-14"],["E L M C Contracting",41,21,4,139,"2026-11-02"],["Gulf Star Cooling Services",41,13,2,195,"2026-10-26"],["Star Security Services Ll",40,8,1,70,"2026-11-03"],["Combined Group Contracting Co Ksc Abudhabi",39,3,1,95,"2026-10-28"],["Falcon Zinc Metal Industries",39,26,4,187,"2026-11-08"],["Al Rawai Contracting & General Maint. Est",39,22,4,210,"2026-10-09"],["Gift Action Trading",38,32,5,224,"2026-11-10"],["We One Fze",38,3,1,51,"2026-11-05"],["Wade Adams Contracting",37,32,4,94,"2026-11-09"],["Nazim Maintenanc General Contracting",35,21,6,250,"2026-11-11"],["Excellent Medical Centerq",35,20,6,386,"2026-11-10"],["Optimum Engineering Sal Abu Dhabi",35,14,5,221,"2026-11-09"],["Promang Technical Services",35,19,4,113,"2026-09-19"],["Seven Days Manpower Supply",32,13,3,74,"2026-10-26"],["Tools Man General Maintenance",31,12,2,129,"2026-10-27"],["Al Matooq Building Insulation Works",30,28,7,134,"2026-11-11"],["Al Saif Graphics",30,30,6,106,"2026-11-10"],["Musaied Bin Hafeedh For Cont.& Gen. Transportation",30,2,2,66,"2025-12-30"],["Mas Geotechnical & Material Testing Laboratory",30,30,8,110,"2026-10-20"],["International Foundation Group",30,0,0,40,"2025-09-08"],["Exeed National General Contracting",29,29,5,71,"2026-11-11"],["Al Shoumokh Manpower",29,27,6,96,"2026-10-22"],["United Mazaya General Contracting",28,17,5,171,"2026-11-10"],["Howdra Employment Services Owned",28,0,0,65,"2025-03-24"],["Bilfinger Deutsche Babcock Emirates",28,17,2,95,"2026-11-08"],["Qumra For Decoration and Interior Design",28,18,4,189,"2026-11-10"],["Mohammed Abdulmohsin Al Kharafi & Sons ( .) Dubai Branch",27,16,3,65,"2026-11-01"],["Control and Application Emirates",27,7,2,76,"2026-10-17"],["Gulf Contracting & Landscaping",26,26,6,67,"2026-10-30"],["Great Mart General Trading",26,18,2,72,"2026-11-03"],["House Engineering Contracting",26,3,1,81,"2026-11-11"],["Indman Recruitment",26,0,0,51,"2025-07-27"],["Soundlines Skilled Manpower",26,2,2,41,"2026-04-21"],["The Designer Advertsing and Publishing",26,26,6,94,"2026-09-28"],["Tamouh Employment",25,21,5,83,"2026-10-08"],["Optimum Services Decor",25,10,3,91,"2026-11-05"],["Guard Fire Fighting Equipment Manufacturers - - O.P.C",25,25,4,54,"2026-11-07"],["Seattle International Services",24,9,2,39,"2026-10-14"],["A.M.C Protection ( )",24,5,3,70,"2026-11-02"],["Qurma Transport and General",24,16,4,73,"2026-09-20"],["Electra Power Electromechanical Contracting",23,5,1,73,"2026-10-05"],["Adeeb Electrical and Electronics Services",23,8,2,98,"2026-11-09"],["Gisco",23,2,1,91,"2026-09-09"],["Amana Contracting Steel Building Company",23,0,0,34,"2025-10-26"],["Ishtar Decor Factor",22,12,2,101,"2026-08-20"],["Exeed Litecrete",22,21,4,133,"2026-11-02"],["Zublin Construction",22,17,3,72,"2026-11-11"],["Spaceage Gen Contracting",21,9,2,35,"2026-10-05"],["Alsarh Recruitment",21,0,0,30,"2025-08-09"],["Perfect Step General Contracting & Maintenance",20,14,3,113,"2026-11-02"],["Modern Building General Contracting",20,19,4,102,"2026-11-01"],["National Projects Services-Ll",19,19,5,62,"2026-10-15"],["Abu Dhabi Berkeley Services",19,8,2,59,"2026-10-27"],["Alryum",19,9,3,184,"2026-11-05"],["Gulf Snipe Engineering Constructions",18,12,2,43,"2026-11-10"],["Polensky & Zoellner Company Abu Dhabi",18,18,5,76,"2026-10-31"],["Exeed Aswar",18,13,3,63,"2026-11-06"],["Engie Cofely Energy Services -Dubai Branch (Lsb)",18,1,1,62,"2025-12-27"],["Dhafir Development and Contracting",18,18,3,28,"2026-11-05"],["Securiguard Middle East",17,8,2,73,"2026-11-05"],["Albarrak Electrical Contracting Company",17,8,2,107,"2026-10-27"],["Maplin For Agricultural Projects",17,1,1,137,"2026-10-11"],["Bgc International General Contracting",17,16,3,31,"2026-10-12"],["Almco Engineering Construction",17,14,5,78,"2026-11-11"],["World Security Fze",17,2,1,60,"2026-09-10"],["Emirates Link Contracting",17,3,1,45,"2026-09-14"],["Alkaline General Maintanance",17,11,3,209,"2026-11-11"],["Granite Construction Company",17,0,0,25,"2025-10-18"],["Optimum Decore Gen Cont Maint",16,4,2,94,"2026-11-05"],["Ducast Factory",16,2,1,35,"2026-09-20"],["Ohana Real Estate Development and Construction",16,16,3,59,"2026-11-11"],["Mazrui and Hawi Painting Company",16,16,3,42,"2026-11-11"],["Alba Tec Modern Construction",15,7,2,134,"2026-11-05"],["Aleshoush Real Estate Investment",15,13,3,61,"2026-11-06"],["United Security Group",15,8,2,58,"2026-11-01"],["Amana Steel Building Contracting Co",15,1,1,30,"2026-09-26"],["Snipe Oil and Gas Equipment",15,10,2,42,"2026-10-26"],["Galaxy Universal General Contracting",15,4,2,49,"2026-10-19"],["Alba Tec Modern Consturction and Development",15,10,2,83,"2026-10-26"],["National Food Products Company (Nfpc)",14,8,3,89,"2026-11-04"],["Al Jazeera Factory For Const Materials",14,8,2,115,"2026-10-25"],["Infotech For Employment",14,2,1,23,"2026-08-10"],["Ezz El Arab Recruitment",14,14,2,16,"2026-11-11"],["Switchgear Electro Mechanical",13,3,1,53,"2026-05-10"],["West Coast Saubermacher Environmental",13,0,0,19,"2024-12-15"],["Royal Gardens Agricultural Contracting",13,3,2,35,"2026-10-20"],["Asgc Contracting Collc",13,0,0,23,"2025-11-01"],["Khidmah",13,0,0,16,"2025-11-02"],["Injaz National General Enterprises",13,8,2,43,"2026-10-24"],["Snipe Instrumentation Control",13,9,2,34,"2026-08-24"],["Tamas Projects Company",13,2,2,26,"2025-12-29"],["The Designer Advert.& Publishing Prod.Factory",13,13,3,35,"2026-09-29"],["Ag Facilities Solutions For Contracting and General Maintenance",13,10,1,19,"2026-11-07"],["Alwathba Cement Industries",12,6,2,45,"2026-09-06"],["Gulf Preacast Concrate",12,2,1,22,"2026-04-24"],["Elite Village Real Estate",12,1,1,28,"2026-07-29"],["Bloom Landscape",12,2,1,32,"2026-11-05"],["Shaw Emirates Pipes Manufacturing",12,7,2,19,"2026-08-25"],["Alkaline Saintary Work",12,7,2,96,"2026-10-28"],["Power Spray Electromechanical",12,6,2,13,"2026-10-12"],["Igg For Military and Formal Garments",12,9,3,40,"2026-08-19"],["Knights Bridge Global Security",12,4,1,14,"2026-10-14"],["Kayan Almostqbal Contracting and Gen Maintenance",12,12,2,37,"2026-10-04"],["Sky Promoters Maintenace and General",12,12,4,57,"2026-09-23"],["Career Line For Employment",12,0,0,26,"2024-10-26"],["M L Manpower -O.P.C",12,12,4,30,"2026-08-18"],["Reliable Employment Services",12,5,1,23,"2026-10-19"],["Delmon Autoclaved Aerated Concrete",12,9,2,73,"2026-10-31"],["G S C Employees Provision Services",11,10,2,22,"2026-10-21"],["Blue Line Establishment",11,4,2,45,"2026-02-27"],["Saif Bin Darwish",11,3,1,35,"2026-10-18"],["A D C Contracting",11,8,2,59,"2026-11-07"],["Al Melehy Human Resource Services - - S.P.C",11,9,2,38,"2026-10-30"],["International Development Company Metal",11,8,1,20,"2026-11-02"],["Johnson Arabia",11,2,1,25,"2026-11-02"],["Alruym Contracting",11,6,1,69,"2026-10-31"],["Eden Gardens",11,6,2,24,"2026-11-11"],["Timishuara Electrical & Mech. Cont. Co. . Temco",11,10,3,47,"2026-11-08"],["Green Ston Landscaping - .-Opc",11,4,1,17,"2026-04-23"],["National Projects and Constructions",11,7,2,16,"2026-10-02"],["Al Nasr Contracting Co",11,4,1,25,"2026-08-21"],["Exeed Precast",11,11,3,17,"2026-11-11"],["Waves Power",10,1,1,22,"2025-12-26"],["Al Shoumoukh Manpower Recruitment",10,10,3,28,"2026-11-11"],["Burtplace General Contracting S.P",10,10,3,21,"2026-10-01"],["Cleanpro Cleaning Services",10,1,1,25,"2026-09-14"],["Cat International Limited Abu Dhabi",10,8,2,20,"2026-11-09"],["Crown Decor Factory",10,8,2,41,"2026-11-06"],["Timishu Ara Electrical and Mechanical",10,7,2,23,"2026-09-18"],["Al Diera Constructions",10,1,1,42,"2026-01-30"],["Macro Vantage Levant Dmcc",10,10,3,25,"2026-08-22"],["Al Ain General Contracting Company Abu Dahbi",10,0,0,16,"2025-03-19"],["Exceed Premium Dry Mortar",10,4,1,35,"2026-10-30"],["Sawaeed Invenstment",10,2,1,14,"2026-05-06"],["Ibuild Construction",10,2,1,28,"2026-11-10"],["Lahori Chaska Restaurant",10,5,1,58,"2026-10-27"],["Modern Plastic Co",10,4,1,36,"2026-10-29"],["Arco",10,4,1,17,"2026-08-24"],["Al Geemi Partners",10,3,1,40,"2026-09-23"],["M 4 Fm Facilities Management - O.P.C",10,9,2,29,"2026-10-29"],["Al Mumayyaz Engineering and Contracting",10,0,0,26,"2024-12-13"],["Al Geemi",9,3,1,25,"2026-11-09"],["Sagarmatha Restaurant",9,6,2,30,"2026-08-23"],["Your Tapioca Restaurant",9,4,1,12,"2026-10-09"],["Silver Coast Construction (Br Of Silver Coast Construction & Boring ) (Dubai Branch)",9,1,1,30,"2026-11-09"],["Universal Voltas",9,8,2,21,"2026-08-24"],["Al Ryum Contracting (Br Of Al Ryum)",8,6,2,64,"2026-11-04"],["Grand Nawab Restaurant",8,6,2,44,"2026-11-03"],["Emirates Code Contracting Co.( )",8,0,0,11,"2025-02-12"],["Asasat Al Dhafra Apcc Building",8,2,1,16,"2026-08-05"],["Dp World",8,0,0,12,"2024-07-28"],["Six Construct Ltd Co",8,6,1,13,"2026-06-12"],["United Mazaya General Maintenance",8,8,3,62,"2026-11-02"],["Transguard Group",8,2,1,16,"2026-10-18"],["Map Vision General Contracting",8,2,2,10,"2026-01-31"],["Aqua Engineering",8,2,1,23,"2026-05-30"],["Golden Stitch Tailoring",8,0,0,10,"2024-06-14"],["Fibrex Contracting",8,1,1,31,"2026-04-19"],["Azam Recruitment",8,8,2,15,"2026-09-10"],["Emirates General and Transport Service",8,5,1,10,"2026-07-22"],["Ethpe Contracting",8,0,0,28,"2024-08-19"],["Mountain Gate Proprty Investement",7,6,2,49,"2026-07-30"],["Lahoud Engineering Co",7,7,4,8,"2026-11-10"],["Jeet Construction",7,2,1,27,"2026-02-13"],["Silver Screen General Contracting",7,7,2,40,"2026-10-04"],["Skill Force Security Services",7,1,1,7,"2025-12-17"],["Technical Solutions International Recruitment",7,2,2,26,"2025-12-23"],["Infinity Infra Energy General Contracting",7,7,4,11,"2026-10-17"],["Discovery Employment",7,0,0,13,"2024-11-05"],["Your Tapioca Cafeteria",7,0,0,27,"2025-09-18"],["Bms General Contracting",7,1,1,16,"2026-09-21"],["China Railway Construction Corp",7,1,1,14,"2026-10-20"],["Mace Mech and Civil Engg Contractors Co",7,0,0,8,"2025-04-14"],["Great Right Angle Manpower Supply",7,7,1,9,"2026-09-03"],["Jazal Engineering",7,3,1,20,"2026-08-05"],["Al Namous General Transport Company",7,7,2,23,"2026-09-13"],["Green Housekeeping Co",7,1,1,13,"2026-01-16"],["Exceed Geotexttile",7,4,1,19,"2026-08-14"],["Fibrex Col Lc",7,0,0,9,"2025-03-11"],["Exeed Precast Owned",7,6,1,31,"2026-11-04"],["Nael and Bin Harmal Hydro Export Establishment",7,1,1,16,"2026-10-02"],["La Mer Decor and Maintenance",6,6,2,22,"2026-10-06"],["Business Management Of His Highness Sheikh",6,1,1,11,"2026-07-16"],["Up Star Restaurent",6,3,2,8,"2025-12-31"],["Barkely",6,2,1,17,"2026-09-28"],["Top West General Contracting",6,5,2,35,"2026-10-15"],["I Zone Electromecanical",6,6,3,7,"2026-06-24"],["Intergulf General Contracting",6,6,2,15,"2026-07-24"],["One Place Restaurant",6,2,1,18,"2026-09-18"],["Al Fursan Recruttment",6,0,0,10,"2025-09-03"],["Arabian Company",6,4,2,22,"2026-09-10"],["Horizon International Recruitment Services",6,0,0,13,"2024-10-29"],["Laundristic",6,0,0,9,"2025-05-11"],["Al Nasiya General Contracting Co",6,3,1,24,"2026-08-09"],["Modern Building Maintenance Co",6,0,0,17,"2025-06-13"],["Manaret Aljazeera For Contracting & General Maint",6,4,1,49,"2026-10-01"],["Royal Falcon Security",6,1,1,18,"2026-08-16"],["Solv Building Cleaning Services",6,0,0,12,"2025-02-07"],["Explorer For Employment Services",6,5,2,9,"2026-10-30"],["Solution Investments Services",6,6,1,6,"2026-10-31"],["Falcon Zinc Steel Works",6,4,1,17,"2026-11-02"],["Emirates Link Nitco",6,2,1,28,"2026-02-19"],["Dar Alahd General Contracting Mainteance",6,5,3,8,"2026-10-06"],["Easy Health Medical Clinic - - S.P.C",6,4,1,22,"2026-08-23"],["Khansaheb Civil Engineering ( )",5,2,2,5,"2026-10-09"],["Hemaya Security",5,3,2,16,"2026-01-28"],["Larsen and Toubro Limited Ecc Construction",5,5,1,8,"2026-11-09"],["Professional Fix Facilities Management",5,0,0,20,"2025-10-23"],["Point Blank Interiors",5,5,1,8,"2026-11-08"],["Bhatti Gents Saloon",5,5,1,29,"2026-10-18"],["Al Jazeera Fact Const",5,3,1,22,"2026-11-07"],["Albario Engineering",5,2,1,11,"2026-10-23"],["Falcon Eye Technology Company",5,4,1,9,"2026-08-11"],["Masri Engineering & Contracting - Mec Sal",5,3,1,10,"2026-06-04"],["Sabah Al Shams Bakery",5,4,2,51,"2026-10-30"],["Solv Enviormental Services",5,0,0,16,"2025-04-06"],["Malabar Dawath Reasturant and Grill",5,5,2,28,"2026-10-28"],["First For Security and Safety",5,5,2,8,"2026-10-06"],["Silvana Cleaning Services",5,0,0,5,"2025-06-29"],["China Cilvil Engineering Construction",5,5,2,6,"2026-11-04"],["The Benz Contracting",5,0,0,9,"2025-05-27"],["Me Fitout Industries",5,5,2,5,"2026-07-27"],["Adeeb Facilities Manage Ment",5,1,1,14,"2026-08-05"],["Strabag Dubai",5,2,2,7,"2026-11-11"],["Emirates Steel Wool Manufacturing Establishment",5,0,0,13,"2024-10-28"],["Advanced Pipeline Services Limited",5,0,0,8,"2025-05-19"],["Basatin Landscaping",5,1,1,17,"2026-11-02"],["United Mazaya Blacksmith& Reinfornce Carpentry",5,4,2,18,"2026-10-14"],["Taj Al Warda Cleaning Services",5,0,0,5,"2025-06-29"],["Bin Jamal Recruitment Services",5,1,1,7,"2026-04-08"],["Golden Dynamic Technical Services",5,5,2,9,"2026-11-04"]]}')

# ---------------------------------------------------------------- storage (own folder, separate from the revenue scorecard)
PREFIX = (_secret("S3_BASE_PREFIX").strip("/") + "/" if _secret("S3_BASE_PREFIX") else "") + "emc_marketing/"
LOCAL = Path(__file__).resolve().parent / ".emc_marketing"


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


def put(key, data: bytes):
    s3, b = _s3()
    if s3:
        try:
            s3.put_object(Bucket=b, Key=PREFIX + key, Body=data)
            return "cloud"
        except Exception:  # noqa: BLE001
            pass
    f = LOCAL / key
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(data)
    return "local"


def get(key):
    s3, b = _s3()
    if s3:
        try:
            return s3.get_object(Bucket=b, Key=PREFIX + key)["Body"].read()
        except Exception:  # noqa: BLE001
            pass
    f = LOCAL / key
    return f.read_bytes() if f.exists() else None


def get_json(key, default):
    raw = get(key)
    try:
        return json.loads(raw) if raw else default
    except Exception:  # noqa: BLE001
        return default


# ---------------------------------------------------------------- reading the reports
def _clean(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    return re.sub(r"\s+", " ", str(v).replace("\t", " ")).strip()


FM_DOCTORS = ("SANTDAS",)                  # Family Medicine: referred patients are not new patients


def read_registration(data, name=""):
    engine = "xlrd" if name.lower().endswith(".xls") else None
    raw = pd.read_excel(io.BytesIO(data), header=None, engine=engine, dtype=object)
    hdr = None
    for i in range(min(len(raw), 30)):
        vals = [_clean(v).upper() for v in raw.iloc[i].tolist()]
        if "EMR NO" in vals and "EMPLOYER NAME" in vals:
            hdr = i
            break
    if hdr is None:
        raise ValueError('This is not the Registration List: no "EMR No" and "Employer Name" columns.')
    col = {}
    for j, v in enumerate(raw.iloc[hdr].tolist()):
        v = _clean(v).upper()
        if v and v not in col:
            col[v] = j
    g = lambda r, n: _clean(r[col[n]]) if n in col else ""          # noqa: E731
    rows = []
    for _, r in raw.iloc[hdr + 1:].iterrows():
        r = r.tolist()
        emr = g(r, "EMR NO")
        if not emr:
            continue
        dt = g(r, "REG:DATE")[:10]
        try:
            datetime.strptime(dt, "%d-%m-%Y")
        except ValueError:
            continue
        rows.append({"emr": emr, "date": dt, "employer": g(r, "EMPLOYER NAME"),
                     "camp": g(r, "ADDRESS 1") or g(r, "ADDRESS 2"), "nat": g(r, "NATIONALITY").title() or "Unknown",
                     "new": g(r, "PATIENT TYPE").upper().startswith("NEW"), "fu": "FOLLOW" in g(r, "VISIT TYPE").upper(),
                     "user": g(r, "REG:USER").upper() or "–",
                     "fm": any(x in re.sub(r"[^A-Z]", "", g(r, "DOCTOR").upper()) for x in FM_DOCTORS)})
    if not rows:
        raise ValueError("No visits found in the Registration List.")
    return rows


def revenue_map(data, name):
    """(EMR, date) -> insurance share after the scorecard's price corrections."""
    import emc_logic as L
    visits, _, _ = L.correct(L.read_report(data, name))
    out = {}
    for v in visits:
        k = (str(v.get("emr", "")).strip(), v["date"])
        out[k] = out.get(k, 0.0) + v["runs"]
    return out


# ---------------------------------------------------------------- name clean-up (companies spelled many ways)
LEGAL = r"\b(L ?L ?C|S ?P ?C|W ?L ?L|P ?J ?S ?C|PJSC|LTD|LIMITED|EST|ESTABLISHMENT|CO|COMPANY|SOLE|PROPRIETORSHIP|PROPRITERSHIP|BRANCH|BR|LSB|AUH|ABU DHABI|DUBAI)\b"


def company_key(s):
    s = _clean(s).upper()
    if not s or s in ("N/A", "NA", "-", "NIL", "NONE", "0"):
        return ""
    s = re.sub(r"OWNED BY.*", "", s)
    s = s.replace("&", " AND ")
    s = re.sub(r"\bCONT\b", "CONTRACTING", s)
    s = re.sub(r"\bGEN\b", "GENERAL", s)
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    s = re.sub(LEGAL, " ", s)
    s = re.sub(r"\s+", "", s)
    return s


CAMP_STOP = r"\b(AL|EL|CAMP|CHAMAP|VILLAGE|LABOUR|LABOR|ACCOMMODATION|AREA)\b"


CAMPS = [(r"NA+S+[AEI]+R|NASSR", "Al Nasser Camp"), (r"RA+H+A?|RAAH", "Al Raha"), (r"LAB+OT+[AE]?L", "Labotel"),
         (r"JA+B+[AE]R", "Al Jaber"), (r"MOU?N?A?T[AI]*N|MOUTIN|MOUNTAIN", "Mountain Gate"), (r"SAWA+E*D", "Al Sawaeed"),
         (r"ESH?OUSE", "Eshouse"), (r"RAZEEM", "Razeem"), (r"RAYAN", "Al Rayan"), (r"GEEMI", "Al Geemi")]


def camp_canon(s):
    k = camp_key(s)
    for pat, name in CAMPS:
        if re.search(pat, k):
            return name
    return ""


def camp_key(s):
    s = re.sub(r"[^A-Z0-9 ]", " ", _clean(s).upper())
    s = re.sub(CAMP_STOP, " ", s)
    return re.sub(r"\s+", "", s)


def build_names(raws, keyfn, aliases, threshold=0.84):
    """raw text -> one display name. Similar spellings are merged; the most common spelling is shown.
    'aliases' (raw or display -> chosen name) always wins."""
    count = {}
    for r, n in raws.items():
        count[r] = count.get(r, 0) + n
    clusters = []                                   # [key, {raw: n}]
    for r in sorted(count, key=lambda x: -count[x]):
        k = keyfn(r)
        if keyfn is camp_key and camp_canon(r):
            k = "CANON:" + camp_canon(r)
            hit = next((c for c in clusters if c[0] == k), None)
            if hit:
                hit[1][r] = count[r]
            else:
                clusters.append([k, {r: count[r]}])
            continue
        if not k:
            continue
        best = None
        for c in clusters:
            ck = c[0]
            if ck.startswith("CANON:"):
                continue
            if min(len(k), len(ck)) >= 8 and (k.startswith(ck) or ck.startswith(k)):
                best = c
                break
            if 2 * min(len(k), len(ck)) / (len(k) + len(ck)) < threshold:
                continue
            sm = difflib.SequenceMatcher(None, k, ck)
            if sm.real_quick_ratio() >= threshold and sm.quick_ratio() >= threshold and sm.ratio() >= threshold:
                best = c
                break
        if best:
            best[1][r] = count[r]
        else:
            clusters.append([k, {r: count[r]}])
    out = {}
    up = {k.upper(): v for k, v in aliases.items()}
    for _, members in clusters:
        disp = max(members, key=lambda x: members[x])
        if keyfn is camp_key and camp_canon(disp):
            disp = camp_canon(disp)
        else:
            disp = re.sub(r"OWNED BY.*", "", disp, flags=re.I)
            disp = re.sub(r"[-,]?\s*\bSOLE\b.*$", " ", disp, flags=re.I)
            disp = re.sub(r"\bL\.?\s?L\.?\s?C\.?\b|\bS\s?P\s?C\b|\bW\.?\s?L\.?\s?L\b|\bP\.?J\.?S\.?C\.?", " ", disp, flags=re.I)
            disp = re.sub(r"\s*-\s*(DUBAI|ABU DHABI|AUH|LSB)?\s*(BRANCH)?\s*$", "", disp, flags=re.I)
            disp = re.sub(r"\s+", " ", disp).strip(" -,.&").title()
            disp = re.sub(r"\bAnd\b", "and", disp)
        for r in members:
            out[r] = up.get(r.upper(), up.get(disp.upper(), disp))
    return out


# ---------------------------------------------------------------- daily ledger (per day, per company: counts and revenue)
def day_totals(rows, rev):
    days = {}
    seen = set()
    for r in sorted(rows, key=lambda x: x["fm"]):     # GP visit first, so a referred patient is counted once
        d = days.setdefault(r["date"], {"co": {}, "camp": {}, "nat": {}, "users": {}, "n": 0, "new": 0, "fu": 0,
                                        "blank": 0, "rev": 0.0, "has_rev": rev is not None, "fm": 0, "fm_ref": 0})
        if r["fm"]:
            d["fm"] += 1
            fe = r["employer"] if company_key(r["employer"]) else "(not filled)"
            d.setdefault("co_fm", {})[fe] = d.setdefault("co_fm", {}).get(fe, 0) + 1
        if (r["emr"], r["date"]) in seen:              # same patient again that day (e.g. referred to Family Medicine)
            d["fm_ref"] += r["fm"]
            continue
        seen.add((r["emr"], r["date"]))
        runs = (rev or {}).pop((r["emr"], r["date"]), 0.0)      # each bill counted once, even if registered twice
        d["n"] += 1; d["new"] += r["new"]; d["fu"] += r["fu"]; d["rev"] += runs
        emp = r["employer"] if company_key(r["employer"]) else ""
        if not emp:
            d["blank"] += 1
        c = d["co"].setdefault(emp or "(not filled)", [0, 0, 0, 0.0])
        c[0] += 1; c[1] += r["new"]; c[2] += r["fu"]; c[3] += runs
        cp = r["camp"] if camp_key(r["camp"]) else "(not filled)"
        d["camp"][cp] = d["camp"].get(cp, 0) + 1
        d["nat"][r["nat"]] = d["nat"].get(r["nat"], 0) + 1
        u = d["users"].setdefault(r["user"], [0, 0])
        u[0] += bool(emp); u[1] += 1
    for (emr, dt), runs in (rev or {}).items():      # bills with no matching registration: keep the day total right
        if dt in days and runs:
            days[dt]["rev"] += runs
            days[dt]["co"].setdefault("(not filled)", [0, 0, 0, 0.0])[3] += runs
    return days


def update_ledger(days):
    by_month = {}
    for dt, val in days.items():
        k = datetime.strptime(dt, "%d-%m-%Y")
        by_month.setdefault(f"{k:%Y-%m}", {})[f"{k:%Y-%m-%d}"] = val
    for ym, vals in by_month.items():
        led = get_json(f"ledger/{ym}.json", {})
        for k, v in vals.items():
            if not v["has_rev"] and k in led and led[k].get("has_rev") and led[k]["n"] == v["n"]:
                # keep revenue already stored for the same day when this upload has no ProcedureDetails
                for name, c in v["co"].items():
                    c[3] = led[k]["co"].get(name, [0, 0, 0, 0.0])[3]
                v["rev"], v["has_rev"] = led[k]["rev"], True
            led[k] = v
        put(f"ledger/{ym}.json", json.dumps(led).encode())


def sum_days(led, keys):
    tot = {"co": {}, "camp": {}, "nat": {}, "users": {}, "n": 0, "new": 0, "fu": 0, "blank": 0, "rev": 0.0, "days": 0, "rev_days": 0,
           "fm": 0, "fm_ref": 0, "co_fm": {}}
    for k in keys:
        d = led.get(k)
        if not d:
            continue
        tot["days"] += 1; tot["rev_days"] += bool(d.get("has_rev"))
        for f in ("n", "new", "fu", "blank", "rev"):
            tot[f] += d[f]
        for f in ("fm", "fm_ref"):
            tot[f] += d.get(f, 0)
        for name, n in d.get("co_fm", {}).items():
            tot["co_fm"][name] = tot["co_fm"].get(name, 0) + n
        for name, c in d["co"].items():
            t = tot["co"].setdefault(name, [0, 0, 0, 0.0])
            for i in range(4):
                t[i] += c[i]
        for f in ("camp", "nat"):
            for name, n in d[f].items():
                tot[f][name] = tot[f].get(name, 0) + n
        for u, (a, b) in d["users"].items():
            t = tot["users"].setdefault(u, [0, 0]); t[0] += a; t[1] += b
    return tot


# ---------------------------------------------------------------- helpers
@st.cache_data(show_spinner=False)
def cached_names(items, kind, alias_items):
    return build_names(dict(items), company_key if kind == "co" else camp_key, dict(alias_items),
                       threshold=0.84 if kind == "co" else 0.72)


def process(reg, reg_name, proc, proc_name):
    rows_ = read_registration(reg, reg_name)
    rev_ = revenue_map(proc, proc_name) if proc else None
    days_ = day_totals(rows_, dict(rev_) if rev_ else None)
    update_ledger(days_)
    return sorted(days_, key=lambda x: datetime.strptime(x, "%d-%m-%Y"))


# ---------------------------------------------------------------- upload
if "mk" not in st.session_state:
    st.session_state["mk"] = (get("latest/registration.xlsx"), get_json("latest/meta.json", {}), get("latest/procedure.xlsx"))
reg_bytes, meta, proc_bytes = st.session_state["mk"]

with st.expander("Upload new reports", expanded=reg_bytes is None):
    with st.form("mk_up", clear_on_submit=True):
        f_reg = st.file_uploader("1 · Registration List (required)", type=["xlsx", "xls"])
        f_proc = st.file_uploader("2 · ProcedureDetails (optional – adds revenue for the management view)", type=["xlsx", "xls"])
        go = st.form_submit_button("Process reports", type="primary")
    if go:
        if not f_reg and reg_bytes is None:
            st.error("Add the Registration List first.")
        elif not (f_reg or f_proc):
            st.info("No new file added. The saved reports are already showing.")
        else:
            try:
                with st.spinner("Reading and saving…"):
                    rb = f_reg.getvalue() if f_reg else reg_bytes
                    rn = f_reg.name if f_reg else meta.get("reg", "x.xlsx")
                    pb = f_proc.getvalue() if f_proc else (None if f_reg else proc_bytes)
                    pn = f_proc.name if f_proc else meta.get("proc", "x.xlsx")
                    dts = process(rb, rn, pb, pn)
            except Exception as e:  # noqa: BLE001
                st.error(f"Could not read the files. {e}")
            else:
                now = datetime.now(UAE)
                new_meta = dict(meta)
                new_meta["dates"] = dts
                if f_reg:
                    put("latest/registration.xlsx", f_reg.getvalue())
                    new_meta.update(reg=f_reg.name, uploaded_at=now.strftime("%d-%m-%Y %I:%M %p"))
                    if not f_proc:
                        new_meta["proc"] = ""
                if f_proc:
                    put("latest/procedure.xlsx", f_proc.getvalue())
                    new_meta["proc"] = f_proc.name
                put("latest/meta.json", json.dumps(new_meta).encode())
                st.session_state["mk"] = (f_reg.getvalue() if f_reg else reg_bytes, new_meta,
                                          f_proc.getvalue() if f_proc else (None if f_reg else proc_bytes))
                st.rerun()
    if reg_bytes is not None:
        st.caption(f"Saved now: Registration List {meta.get('reg', '')}"
                   + (f" · ProcedureDetails {meta['proc']}" if meta.get("proc") else " · no ProcedureDetails (revenue not shown)")
                   + ". A new Registration List starts a new day; add the ProcedureDetails of the same day for revenue.")

if reg_bytes is None:
    st.markdown('<div class="empty"><b>No report yet.</b> Upload the HIS Registration List above and press Process reports.</div>',
                unsafe_allow_html=True)
    st.stop()

days = {}


def _old_saved(m):
    """True when the saved days were counted before 'one patient a day + Family Medicine' (no 'fm' field)."""
    try:
        d_ = datetime.strptime(m["dates"][-1], "%d-%m-%Y")
        return "fm" not in get_json(f"ledger/{d_:%Y-%m}.json", {}).get(f"{d_:%Y-%m-%d}", {})
    except Exception:  # noqa: BLE001
        return True


if meta.get("dates") and not _old_saved(meta):
    dates = meta["dates"]
else:                                              # older saved report: count it again once
    try:
        rows = read_registration(reg_bytes, meta.get("reg", "x.xlsx"))
        rev = revenue_map(proc_bytes, meta.get("proc", "x.xlsx")) if proc_bytes else None
    except Exception as e:  # noqa: BLE001
        st.error(f"Could not read the saved reports. {e}")
        st.stop()
    days = day_totals(rows, dict(rev) if rev else None)
    dates = sorted(days, key=lambda s: datetime.strptime(s, "%d-%m-%Y"))
    try:
        update_ledger(days)
        meta["dates"] = dates
        put("latest/meta.json", json.dumps(meta).encode())
    except Exception:  # noqa: BLE001
        pass
last = datetime.strptime(dates[-1], "%d-%m-%Y")
ym = f"{last:%Y-%m}"
led = get_json(f"ledger/{ym}.json", {})
for k, v in days.items():                         # make sure today is in, even if saving failed
    led.setdefault(f"{datetime.strptime(k, '%d-%m-%Y'):%Y-%m-%d}", v)
prev_last = last.replace(day=1) - timedelta(days=1)
led_prev = get_json(f"ledger/{prev_last:%Y-%m}.json", {})

span = [f"{last.replace(day=i):%Y-%m-%d}" for i in range(1, last.day + 1)]
DAY_OPTS = ["ALL"] + [k for k in reversed(span) if k in led]
_pick = st.session_state.get("mk_day", DAY_OPTS[1] if len(DAY_OPTS) > 1 else "ALL")
if _pick not in DAY_OPTS:
    _pick = DAY_OPTS[1] if len(DAY_OPTS) > 1 else "ALL"
st.session_state["mk_day"] = _pick
if _pick == "ALL":
    today = sum_days(led, span)
    LBL, SEL = "All days", None
else:
    today = sum_days(led, [_pick])
    SEL = datetime.strptime(_pick, "%Y-%m-%d")
    LBL = "Today" if SEL.date() == last.date() else f"{SEL:%a %d %b}"
month = sum_days(led, span)
missing = [datetime.strptime(k, "%Y-%m-%d") for k in span if k not in led]
same_prev = [f"{prev_last.replace(day=i):%Y-%m-%d}" for i in range(1, min(last.day, prev_last.day) + 1)]
prev_part = sum_days(led_prev, same_prev)
prev_full = sum_days(led_prev, list(led_prev))
has_prev = prev_part["days"] > 0

aliases = get_json("aliases.json", {})
all_co = {}
for src in (month, prev_full):
    for name, c in src["co"].items():
        all_co[name] = all_co.get(name, 0) + c[0]
all_co.pop("(not filled)", None)
CO = cached_names(tuple(sorted(all_co.items())), "co", tuple(sorted(aliases.items())))
all_camp = {}
for src in (month, prev_full):
    for name, n in src["camp"].items():
        all_camp[name] = all_camp.get(name, 0) + n
all_camp.pop("(not filled)", None)
CAMP = cached_names(tuple(sorted(all_camp.items())), "camp", ())


def group(src, mapping, field="co"):
    out = {}
    for name, val in src[field].items():
        disp = mapping.get(name, name)
        if field == "co":
            t = out.setdefault(disp, [0, 0, 0, 0.0])
            for i in range(4):
                t[i] += val[i]
        else:
            out[disp] = out.get(disp, 0) + val
    return out


co_today, co_month = group(today, CO), group(month, CO)
fm_today, fm_month = group(today, CO, "co_fm"), group(month, CO, "co_fm")
co_prev, co_prevfull = group(prev_part, CO), group(prev_full, CO)
camp_today, camp_month = group(today, CAMP, "camp"), group(month, CAMP, "camp")
camp_prev = group(prev_part, CAMP, "camp")
REV_OK = month["rev_days"] > 0
PERIOD = f"1–{last:%d %b %Y}"
DAY = f"All days 1–{last:%d %b %Y}" if SEL is None else f"{SEL:%a %d %b %Y}"


def trend(now, before):
    if not has_prev:
        return ""
    if before == 0 and now > 0:
        return '<span class="tag t-new">NEW</span>'
    d = now - before
    if d > 0:
        return f'<span class="up">▲ {d}</span>'
    if d < 0:
        return f'<span class="down">▼ {-d}</span>'
    return '<span class="flat">→</span>'


lost = sorted(((n, c[0]) for n, c in co_prevfull.items() if n != "(not filled)" and c[0] >= 2 and co_month.get(n, [0])[0] == 0),
              key=lambda x: -x[1])

# ---------------------------------------------------------------- page
st.markdown(f"""
<div class="hero"><div><h1>EMC Marketing Report</h1>
<p>{E(DAY)} &nbsp;·&nbsp; month so far {E(PERIOD)} &nbsp;·&nbsp; where our patients come from</p></div>
<div style="display:flex;gap:8px;flex-wrap:wrap"><span class="chip">{E(meta.get('reg', ''))}</span>
<span class="chip">Uploaded {E(meta.get('uploaded_at', ''))}</span></div></div>""", unsafe_allow_html=True)

_c1, _c2 = st.columns([3, 2])
with _c1:
    view = st.segmented_control("View", ["Marketing (patient counts)", "Management (with revenue)"],
                                default="Marketing (patient counts)", key="mk_view") or "Marketing (patient counts)"
with _c2:
    st.selectbox("Day", DAY_OPTS, key="mk_day",
                 format_func=lambda k: f"All days · 1–{last:%d %b}" if k == "ALL" else
                 f"{datetime.strptime(k, '%Y-%m-%d'):%a %d %b}" + (f" · {led[k]['n']} patients"))
MGMT = view.startswith("Management")
if MGMT and not REV_OK:
    st.info("Revenue needs the ProcedureDetails report for the same day. Upload it as file 2 to see revenue here.")


def pct(a, b):
    return f"{a / b:.0%}" if b else "–"


miss_txt = ""
if missing:
    miss_txt = (f"data for {month['days']} of {len(span)} days · missing: "
                + ", ".join(f"{d:%a %d}" for d in missing[:6]) + (f" +{len(missing) - 6} more" if len(missing) > 6 else ""))
named_today = len([n for n in co_today if n != "(not filled)"])
named_month = len([n for n in co_month if n != "(not filled)"])
st.markdown(f"""
<div class="kpis">
 <div class="kpi"><div class="lbl">Patients · {E(LBL)}</div><div class="val">{today['n']}</div>
  <div class="sub">{today['new']} new · {today['n'] - today['new']} returning · {today['fu']} follow-ups</div>
  <div class="sub">Family Medicine (Dr. Sant Das): {today['fm']} seen · {today['fm_ref']} referred by GP, counted once</div></div>
 <div class="kpi"><div class="lbl">Companies · {E(LBL)}</div><div class="val">{named_today}</div>
  <div class="sub">employer filled for {pct(today['n'] - today['blank'], today['n'])} of patients</div></div>
 <div class="kpi m"><div class="lbl">Month so far · {E(PERIOD)}</div><div class="val">{month['n']:,}</div>
  <div class="sub">{month['new']} new · {named_month} companies{f" · last month same days {prev_part['n']:,}" if has_prev else ""}</div>
  {f'<div class="warnline">⚠ {E(miss_txt)}</div>' if miss_txt else ""}</div>
 {f'<div class="kpi m"><div class="lbl">Revenue · month so far</div><div class="val">{fmt(month["rev"])} <small>AED</small></div><div class="sub">{E(LBL.lower())} {fmt(today["rev"])} · {fmt(month["rev"] / max(month["n"], 1))} per patient</div></div>' if MGMT and REV_OK else ""}
 {f'<div class="kpi"><div class="lbl">Companies lost</div><div class="val" style="color:#B3261E">{len(lost)}</div><div class="sub">came last month (2+ patients), none this month</div></div>' if has_prev else ""}
</div>""", unsafe_allow_html=True)


def company_table(n=None):
    items = sorted(((k, v) for k, v in co_month.items()), key=lambda x: (x[0] == "(not filled)", -x[1][0]))
    if n:
        items = items[:n]
    top = max([v[0] for k, v in items if k != "(not filled)"] or [1])
    head = (f"<tr><th>#</th><th class='l'>Company</th><th>{E(LBL)}</th><th>Month</th><th>New</th><th>Follow-ups</th><th>Family Medicine</th>"
            + ("<th>vs last month</th>" if has_prev else "")
            + ("<th>Revenue today</th><th>Revenue month</th><th>Per patient</th>" if MGMT and REV_OK else "") + "</tr>")
    body = ""
    for i, (name, v) in enumerate(items, 1):
        t = co_today.get(name, [0, 0, 0, 0.0])
        bar = f'<span class="barc" style="width:{int(60 * v[0] / top)}px"></span>' if name != "(not filled)" else ""
        body += (f'<tr><td class="rank">{i}</td><td class="nm">{E(name)}</td><td>{t[0] or "–"}</td><td>{bar}<b>{v[0]}</b></td>'
                 f'<td>{v[1] or "–"}</td><td>{v[2] or "–"}</td><td>{fm_month.get(name, 0) or "–"}</td>'
                 + (f'<td>{trend(v[0], co_prev.get(name, [0])[0])}</td>' if has_prev else "")
                 + (f'<td>{fmt(t[3]) if t[0] else "–"}</td><td><b>{fmt(v[3])}</b></td><td>{fmt(v[3] / max(v[0], 1))}</td>' if MGMT and REV_OK else "")
                 + "</tr>")
    return f'<table class="tbl">{head}{body}</table>'


def camp_table():
    items = sorted(camp_month.items(), key=lambda x: (x[0] == "(not filled)", -x[1]))
    top = max([v for k, v in items if k != "(not filled)"] or [1])
    body = "".join(f'<tr><td class="nm">{E(k)}</td><td>{camp_today.get(k, 0) or "–"}</td>'
                   f'<td><span class="barc" style="width:{int(80 * v / top) if k != "(not filled)" else 0}px"></span><b>{v}</b></td>'
                   + (f'<td>{trend(v, camp_prev.get(k, 0))}</td>' if has_prev else "") + "</tr>" for k, v in items)
    return (f'<table class="tbl"><tr><th class="l">Camp / area</th><th>{E(LBL)}</th><th>Month</th>{"<th>vs last month</th>" if has_prev else ""}</tr>'
            f'{body}</table>')


t1, t8, t7, t2, t3, t4, t5, t6 = st.tabs(["Companies", "Company profile", "Day by day", "Camps and areas", "Growing · dropping · lost", "Nationality", "Data quality", "Email"])
with t1:
    st.markdown(f'<div class="note">Month so far {E(PERIOD)}, biggest first. "New" = new patients registered. '
                + ("Trend compares with the same days of last month. " if has_prev else "Trend starts once last month's data is saved. ")
                + 'Different spellings of the same company are merged (fix any in Data quality).</div>' + company_table(),
                unsafe_allow_html=True)
with t8:
    asof = datetime.strptime(BASE["asof"], "%Y-%m-%d")
    st.markdown(f"""<div class="kpis">
 <div class="kpi m"><div class="lbl">Unique patients · Jan 2024–{asof:%d %b %Y}</div><div class="val">{BASE['tot']:,}</div>
  <div class="sub">{BASE['tot12']:,} in the last 12 months · each patient counted once</div></div>
 <div class="kpi"><div class="lbl">Companies</div><div class="val">{BASE['companies']:,}</div>
  <div class="sub">average {BASE['tot'] / BASE['companies']:.0f} patients each · {BASE['ones']} sent only 1</div></div>
 <div class="kpi"><div class="lbl">Top 10 companies</div><div class="val">{BASE['top10'] / BASE['tot']:.0%}</div>
  <div class="sub">of all patients ({BASE['top10']:,})</div></div></div>""", unsafe_allow_html=True)
    brow = "".join(f'<tr><td class="nm">{b[0]}</td><td>{b[1]}</td><td>{b[2]:,}</td><td>{pct(b[2], BASE["tot"])}</td></tr>' for b in BASE["bands"])
    st.markdown('<div class="sec">Company size bands</div><table class="tbl"><tr><th class="l">Unique patients</th><th>Companies</th>'
                f'<th>Patients from them</th><th>Share</th></tr>{brow}</table>', unsafe_allow_html=True)
    st.markdown(f'<div class="sec">Companies – unique patients and likely workforce</div>'
                f'<div class="note">Saved from the full Registration List, Jan 2024 to {asof:%d %b %Y} (companies with 5+ patients). '
                f'"This month" comes from your daily uploads. Likely workers near us = unique patients in the last 12 months '
                f'÷ 60% to ÷ 40% (about 40–60% of camp workers visit a nearby clinic in a year – an assumption, not data). '
                f'Type the real headcount from HR in the last column and press Save.</div>', unsafe_allow_html=True)
    keys = {company_key(n): n for n in co_month if n != "(not filled)"}
    heads = get_json("headcount.json", {})
    recs = []
    for name, u, u12, avgm, vis, lv in BASE["rows"]:
        k = company_key(name)
        live = keys.get(k)
        if live is None:
            m_ = difflib.get_close_matches(k, list(keys), n=1, cutoff=0.84)
            live = keys[m_[0]] if m_ else None
        now_m = co_month.get(live, [0])[0] if live else 0
        lvd = datetime.strptime(lv, "%Y-%m-%d")
        if now_m:
            status = "Active"
        else:
            gap = (last - lvd).days
            status = "Active" if gap <= 90 else "Quiet 3–6 months" if gap <= 180 else "Lost 6+ months"
        hc = heads.get(name)
        recs.append({"Company": name, "Unique patients": u, "Last 12 months": u12, "Avg / month": avgm,
                     f"This month ({PERIOD})": now_m, "Visits per patient": round(vis / u, 1),
                     "Likely workers near us": f"{round(u12 / 0.6, -1):,.0f}–{round(u12 / 0.4, -1):,.0f}" if u12 >= 10 else "–",
                     "Last visit": lvd.strftime("%d %b %Y") if not now_m else "this month", "Status": status,
                     "Headcount (from HR)": int(hc) if hc else None, "We serve": f"{u12 / hc:.0%}" if hc else ""})
    dfp = pd.DataFrame(recs)
    flt = st.radio("Show", ["All", "Active", "Quiet 3–6 months", "Lost 6+ months"], horizontal=True, key="mk_prof_f")
    if flt != "All":
        dfp = dfp[dfp["Status"] == flt]
    edited = st.data_editor(dfp, hide_index=True, key=f"mk_prof_ed_{flt}",
                            disabled=[c for c in dfp.columns if c != "Headcount (from HR)"],
                            column_config={"Headcount (from HR)": st.column_config.NumberColumn(min_value=0, step=1)})
    if st.button("Save headcounts"):
        new = dict(heads)
        for _, r in edited.iterrows():
            v = r["Headcount (from HR)"]
            if pd.notna(v) and v:
                new[r["Company"]] = int(v)
            else:
                new.pop(r["Company"], None)
        put("headcount.json", json.dumps(new).encode())
        st.success("Headcounts saved.")
        st.rerun()
with t7:
    dkeys = [k for k in span if k in led]
    what = st.radio("Show", ["Companies", "Camps and areas"], horizontal=True, key="mk_dd")
    top_n = st.select_slider("Rows", options=[10, 25, 50, 100, "All"], value=25, key="mk_ddn")
    per = {}
    for k in dkeys:
        one = sum_days(led, [k])
        g = group(one, CO) if what == "Companies" else group(one, CAMP, "camp")
        for name, v in g.items():
            per.setdefault(name, {})[k] = v[0] if what == "Companies" else v
    tot = {n: sum(d.values()) for n, d in per.items()}
    names = sorted(tot, key=lambda n: (n == "(not filled)", -tot[n]))
    if top_n != "All":
        names = names[:top_n]
    day_n = {k: led[k]["n"] for k in dkeys}
    day_new = {k: led[k]["new"] for k in dkeys}
    cols = "".join(f'<th>{datetime.strptime(k, "%Y-%m-%d"):%a}<br>{datetime.strptime(k, "%Y-%m-%d").day}</th>' for k in span)
    head = f'<tr><th class="l">{"Company" if what == "Companies" else "Camp / area"}</th>{cols}<th>Total</th><th>Avg / day</th></tr>'

    def cells(d):
        out = ""
        for k in span:
            if k not in led:
                out += '<td class="z" title="no data">·</td>'
            else:
                v = d.get(k, 0)
                out += f'<td class="{"z" if not v else ""}">{v or "–"}</td>'
        return out

    nd = max(len(dkeys), 1)
    body = (f'<tr class="tot"><td class="nm">All patients</td>{cells(day_n)}<td>{sum(day_n.values()):,}</td><td>{sum(day_n.values()) / nd:.0f}</td></tr>'
            f'<tr class="tot"><td class="nm">New patients</td>{cells(day_new)}<td>{sum(day_new.values()):,}</td><td>{sum(day_new.values()) / nd:.0f}</td></tr>')
    day_fm = {k: led[k].get("fm", 0) for k in dkeys}
    body += (f'<tr class="tot"><td class="nm">Family Medicine (Dr. Sant Das)</td>{cells(day_fm)}<td>{sum(day_fm.values()):,}</td>'
             f'<td>{sum(day_fm.values()) / nd:.0f}</td></tr>')
    for n in names:
        d = per[n]
        best = max(d.values()) if d else 0
        row = ""
        for k in span:
            if k not in led:
                row += '<td class="z">·</td>'
            else:
                v = d.get(k, 0)
                row += f'<td class="{"z" if not v else "hi" if v == best and best >= 3 else ""}">{v or "–"}</td>'
        body += f'<tr><td class="nm">{E(n)}</td>{row}<td><b>{tot[n]}</b></td><td>{tot[n] / nd:.1f}</td></tr>'
    st.markdown(f'<div class="note">Every day of {E(PERIOD)}. · = no report for that day. Shaded = that row\'s best day. '
                f'Sorted by month total.</div><div class="dwrap"><table class="tbl dd">{head}{body}</table></div>',
                unsafe_allow_html=True)
with t2:
    st.markdown('<div class="note">From the patient address (Address 1). Spellings like "Al Naser / Al Nasser / Alnasir" are merged.</div>'
                + camp_table(), unsafe_allow_html=True)
with t3:
    if not has_prev:
        st.markdown('<div class="empty">Trends start next month, once last month\'s days are saved here. '
                    'To start now, upload last month\'s Registration List (one file for the whole month) once.</div>',
                    unsafe_allow_html=True)
    else:
        moves = [(n, v[0], co_prev.get(n, [0])[0]) for n, v in co_month.items() if n != "(not filled)"]
        grow = sorted([m for m in moves if m[1] > m[2]], key=lambda m: -(m[1] - m[2]))[:10]
        drop = sorted([(n, co_month.get(n, [0])[0], p[0]) for n, p in co_prev.items()
                       if n != "(not filled)" and p[0] > co_month.get(n, [0])[0]], key=lambda m: -(m[2] - m[1]))[:10]
        rowsf = lambda L_, cls: "".join(f'<tr><td class="nm">{E(n)}</td><td>{b}</td><td>{a}</td><td class="{cls}">{"+" if a >= b else ""}{a - b}</td></tr>'
                                        for n, a, b in L_) or '<tr><td colspan="4">–</td></tr>'           # noqa: E731
        h = f"<tr><th>Company</th><th>Last month 1–{min(last.day, prev_last.day)}</th><th>This month</th><th>Change</th></tr>"
        st.markdown('<div class="sec">Growing ▲</div><table class="tbl">' + h + rowsf(grow, "up") + '</table>'
                    '<div class="sec">Dropping ▼</div><table class="tbl">' + h + rowsf(drop, "down") + '</table>',
                    unsafe_allow_html=True)
        lost_rows = "".join(f'<tr><td class="nm">{E(n)}</td><td>{c}</td></tr>' for n, c in lost) or '<tr><td colspan="2">None</td></tr>'
        st.markdown(f'<div class="sec">Lost companies – follow up</div><div class="note">Came last month with 2 or more patients, '
                    f'no patient yet this month.</div><table class="tbl"><tr><th>Company</th><th>Patients last month</th></tr>{lost_rows}</table>',
                    unsafe_allow_html=True)
with t4:
    nat = sorted(month["nat"].items(), key=lambda x: -x[1])
    top = max([v for _, v in nat] or [1])
    st.markdown('<div class="note">Useful for the language of flyers and WhatsApp messages.</div><table class="tbl">'
                f'<tr><th>Nationality</th><th>{E(LBL)}</th><th>Month</th><th>Share</th></tr>'
                + "".join(f'<tr><td class="nm">{E(k)}</td><td>{today["nat"].get(k, 0) or "–"}</td>'
                          f'<td><span class="barc" style="width:{int(80 * v / top)}px"></span><b>{v}</b></td><td>{pct(v, month["n"])}</td></tr>'
                          for k, v in nat) + '</table>', unsafe_allow_html=True)
with t5:
    users = sorted(month["users"].items(), key=lambda x: -x[1][1])
    st.markdown(f'<div class="note">Employer filled for <b>{pct(month["n"] - month["blank"], month["n"])}</b> of patients this month. '
                'Reception should fill Employer Name and Address for every patient.</div><table class="tbl">'
                '<tr><th>Registered by</th><th>Patients</th><th>Employer filled</th><th>%</th></tr>'
                + "".join(f'<tr><td class="nm">{E(u)}</td><td>{b}</td><td>{a}</td>'
                          f'<td class="{"up" if b and a / b >= 0.95 else "down"}">{pct(a, b)}</td></tr>' for u, (a, b) in users)
                + '</table>', unsafe_allow_html=True)
    st.markdown('<div class="sec">Company name fixes</div><div class="note">Similar spellings are merged automatically. '
                'If two companies are merged wrongly, or one company still shows twice, write one line per fix: '
                '<b>spelling as it shows = name to use</b>.</div>', unsafe_allow_html=True)
    groups = {}
    for raw, disp in CO.items():
        groups.setdefault(disp, []).append(raw)
    with st.expander("See which spellings were merged"):
        st.markdown("".join(f"<div style='font-size:13px;margin-bottom:6px'><b>{E(d)}</b> ← {E(' | '.join(r))}</div>"
                            for d, r in sorted(groups.items()) if len(r) > 1) or "Nothing merged.", unsafe_allow_html=True)
    txt = st.text_area("Fixes", value="\n".join(f"{k} = {v}" for k, v in aliases.items()), height=120,
                       placeholder="ARCO GENERAL CONTRACTNG = Arco General Contracting LLC")
    if st.button("Save fixes"):
        new = {}
        for line in txt.splitlines():
            if "=" in line:
                a, b = line.split("=", 1)
                if a.strip() and b.strip():
                    new[a.strip()] = b.strip()
        put("aliases.json", json.dumps(new).encode())
        st.success(f"Saved {len(new)} fixes.")
        st.rerun()


# ---------------------------------------------------------------- email (Outlook-safe tables)
def email_html(mgmt):
    F = "font-family:Segoe UI,Arial,Helvetica,sans-serif;"
    INK, MUT, LINE, SOFT, EDGE, BR = "#18211C", "#5D6A62", "#E1E6E0", "#F2F5F1", "#C9D2CB", "#1F4E8C"
    T = 'role="presentation" cellpadding="0" cellspacing="0" border="0"'
    show_rev = mgmt and REV_OK
    th = f'bgcolor="{SOFT}" style="background:{SOFT};color:{MUT};font-size:10.5px;letter-spacing:1px;text-transform:uppercase;padding:8px 10px;text-align:right;border-bottom:2px solid {EDGE};"'
    thl = th.replace("text-align:right", "text-align:left")
    td = f'style="padding:7px 10px;border-bottom:1px solid {LINE};text-align:right;font-size:13px;"'
    tdl = td.replace("text-align:right", "text-align:left")

    def box(lbl, val, sub, w="25%", strong=False):
        return (f'<td width="{w}" valign="top" bgcolor="#ffffff" style="background:#ffffff;border:{"2px" if strong else "1px"} solid {BR if strong else EDGE};'
                f'border-radius:12px;padding:12px 14px;"><div style="font-size:10.5px;letter-spacing:1px;text-transform:uppercase;'
                f'color:{BR if strong else MUT};font-weight:bold;">{lbl}</div><div style="font:bold 26px Arial,sans-serif;color:{INK};padding-top:4px;">{val}</div>'
                f'<div style="font-size:12px;color:{MUT};padding-top:3px;">{sub}</div></td>')

    def section(t):
        return (f'<tr><td style="padding:22px 0 8px;"><table {T} width="100%"><tr><td style="font:bold 18px Arial,sans-serif;color:{INK};'
                f'border-bottom:3px solid {BR};padding-bottom:6px;">{t}</td></tr></table></td></tr>')

    def trend_e(now, before):
        if not has_prev:
            return ""
        if before == 0 and now > 0:
            return f'<b style="color:{BR}">NEW</b>'
        d = now - before
        return (f'<b style="color:#1E7A45">&#9650; {d}</b>' if d > 0 else f'<b style="color:#B3261E">&#9660; {-d}</b>' if d < 0
                else f'<span style="color:{MUT}">&#8594;</span>')

    out = [f'<table {T} width="100%" bgcolor="#EEF1F5" style="background:#EEF1F5;{F}"><tr><td align="center" style="padding:18px 10px;">'
           f'<table {T} width="760" style="width:760px;max-width:100%;{F}color:{INK};">'
           f'<tr><td bgcolor="{BR}" style="background:{BR};border-radius:16px;padding:22px 26px;">'
           f'<div style="font:bold 26px Arial,sans-serif;color:#ffffff;">EMC Marketing Report{" · Management" if mgmt else ""}</div>'
           f'<div style="font-size:14px;color:#D6E2F3;padding-top:6px;">{E(DAY)} &nbsp;·&nbsp; month so far {E(PERIOD)}</div></td></tr>'
           f'<tr><td style="padding-top:12px;"><table {T.replace("cellspacing=\"0\"", "cellspacing=\"8\"")} width="100%" style="margin:0 -8px;"><tr>'
           + box(f"Patients · {LBL}", today["n"], f'{today["new"]} new · {today["fu"]} follow-ups<br>Family Medicine {today["fm"]} '
                 f'({today["fm_ref"]} referred by GP, counted once)')
           + box(f"Companies · {LBL}", named_today, f'employer filled {pct(today["n"] - today["blank"], today["n"])}')
           + box(f"Month so far · {PERIOD}", f'{month["n"]:,}',
                 f'{month["new"]} new · {named_month} companies' + (f' · last month same days {prev_part["n"]:,}' if has_prev else "")
                 + (f'<br><b style="color:#9A6200">&#9888; {E(miss_txt)}</b>' if miss_txt else ""), "30%", True)
           + (box("Revenue · month so far", f'{fmt(month["rev"])} <span style="font-size:13px;color:{MUT}">AED</span>',
                  f'today {fmt(today["rev"])} · {fmt(month["rev"] / max(month["n"], 1))} per patient', "20%", True) if show_rev else
              (box("Companies lost", len(lost), "came last month, none yet this month", "20%") if has_prev else ""))
           + '</tr></table></td></tr>']
    # companies
    out.append(section("Top companies"))
    items = sorted(((k, v) for k, v in co_month.items() if k != "(not filled)"), key=lambda x: -x[1][0])[:25]
    head = (f'<tr><th {thl}>Company</th><th {th}>{E(LBL)}</th><th {th}>Month</th><th {th}>New</th><th {th}>Family Med.</th>'
            + (f'<th {th}>vs last month</th>' if has_prev else "")
            + (f'<th {th}>Revenue month</th><th {th}>Per patient</th>' if show_rev else "") + '</tr>')
    body = ""
    for name, v in items:
        t = co_today.get(name, [0])
        body += (f'<tr><td {tdl}><b>{E(name)}</b></td><td {td}>{t[0] or "–"}</td><td {td}><b>{v[0]}</b></td><td {td}>{v[1] or "–"}</td><td {td}>{fm_month.get(name, 0) or "–"}</td>'
                 + (f'<td {td}>{trend_e(v[0], co_prev.get(name, [0])[0])}</td>' if has_prev else "")
                 + (f'<td {td}><b>{fmt(v[3])}</b></td><td {td}>{fmt(v[3] / max(v[0], 1))}</td>' if show_rev else "") + '</tr>')
    nf = co_month.get("(not filled)", [0])[0]
    out.append(f'<tr><td><table {T} width="100%" bgcolor="#ffffff" style="background:#ffffff;border:1px solid {EDGE};border-collapse:collapse;">'
               f'{head}{body}</table>'
               + (f'<div style="font-size:12px;color:{MUT};padding-top:6px;">{nf} patients this month with no employer filled. '
                  f'Full list in the attached Excel.</div>' if nf else "") + '</td></tr>')
    # camps
    out.append(section("Camps and areas"))
    citems = sorted(((k, v) for k, v in camp_month.items() if k != "(not filled)"), key=lambda x: -x[1])[:12]
    out.append(f'<tr><td><table {T} width="100%" bgcolor="#ffffff" style="background:#ffffff;border:1px solid {EDGE};border-collapse:collapse;">'
               f'<tr><th {thl}>Camp / area</th><th {th}>{E(LBL)}</th><th {th}>Month</th>{f"<th {th}>vs last month</th>" if has_prev else ""}</tr>'
               + "".join(f'<tr><td {tdl}><b>{E(k)}</b></td><td {td}>{camp_today.get(k, 0) or "–"}</td><td {td}><b>{v}</b></td>'
                         + (f'<td {td}>{trend_e(v, camp_prev.get(k, 0))}</td>' if has_prev else "") + '</tr>' for k, v in citems)
               + '</table></td></tr>')
    # lost
    if has_prev and lost:
        out.append(section("Lost companies – follow up"))
        out.append(f'<tr><td><table {T} width="100%" bgcolor="#ffffff" style="background:#ffffff;border:1px solid {EDGE};border-collapse:collapse;">'
                   f'<tr><th {thl}>Company</th><th {th}>Patients last month</th><th {th}>This month</th></tr>'
                   + "".join(f'<tr><td {tdl}><b>{E(n)}</b></td><td {td}>{c}</td><td {td}><b style="color:#B3261E">0</b></td></tr>' for n, c in lost[:15])
                   + '</table></td></tr>')
    # nationality
    nat = sorted(month["nat"].items(), key=lambda x: -x[1])[:8]
    out.append(section("Nationality"))
    out.append(f'<tr><td style="font-size:13.5px;color:{INK};">' + " &nbsp;·&nbsp; ".join(f'<b>{E(k)}</b> {v} ({pct(v, month["n"])})' for k, v in nat) + '</td></tr>')
    out.append(f'<tr><td style="font-size:12px;color:{MUT};padding:20px 0 0;">From the HIS Registration List. Company spellings are merged; '
               f'patient names and contact details are not included. Sent {datetime.now(UAE):%d-%m-%Y %I:%M %p}.</td></tr>')
    out.append('</table></td></tr></table>')
    return "".join(out)


def build_excel(mgmt):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter
    show_rev = mgmt and REV_OK
    wb = Workbook()
    thin = Side(style="thin", color="D5DCD6")
    box = Border(left=thin, right=thin, top=thin, bottom=thin)
    fill = lambda c: PatternFill("solid", start_color=c, end_color=c)      # noqa: E731

    def sheet(ws, title, headers, rows, widths):
        ws.sheet_view.showGridLines = False
        ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(headers))
        c = ws.cell(1, 1, title); c.font = Font(bold=True, size=14, color="FFFFFF"); c.fill = fill("1F4E8C")
        for j in range(2, len(headers) + 1):
            ws.cell(1, j).fill = fill("1F4E8C")
        ws.row_dimensions[1].height = 26
        for j, h in enumerate(headers, 1):
            c = ws.cell(3, j, h); c.font = Font(bold=True, color="FFFFFF"); c.fill = fill("1F4E8C"); c.border = box
            c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        for i, r in enumerate(rows, 4):
            for j, v in enumerate(r, 1):
                c = ws.cell(i, j, v); c.border = box
                if i % 2:
                    c.fill = fill("F2F5F1")
                if isinstance(v, float):
                    c.number_format = "#,##0"
        for j, w in enumerate(widths, 1):
            ws.column_dimensions[get_column_letter(j)].width = w
        ws.freeze_panes = "A4"

    ws = wb.active; ws.title = "Companies"
    hdr = ["Company", LBL, f"Month {PERIOD}", "New", "Follow-ups", "Family Medicine"] + (["Last month same days"] if has_prev else []) \
        + (["Revenue today", "Revenue month", "Per patient"] if show_rev else [])
    rows_ = []
    for name, v in sorted(co_month.items(), key=lambda x: (x[0] == "(not filled)", -x[1][0])):
        t = co_today.get(name, [0, 0, 0, 0.0])
        r = [name, t[0], v[0], v[1], v[2], fm_month.get(name, 0)] + ([co_prev.get(name, [0])[0]] if has_prev else [])
        if show_rev:
            r += [float(round(t[3])), float(round(v[3])), float(round(v[3] / max(v[0], 1)))]
        rows_.append(r)
    sheet(ws, f"Companies · {PERIOD}", hdr, rows_, [48, 9, 14, 8, 11, 15] + ([16] if has_prev else []) + ([14, 15, 12] if show_rev else []))
    ws2 = wb.create_sheet("Camps and areas")
    sheet(ws2, f"Camps and areas · {PERIOD}", ["Camp / area", LBL, "Month"] + (["Last month same days"] if has_prev else []),
          [[k, camp_today.get(k, 0), v] + ([camp_prev.get(k, 0)] if has_prev else [])
           for k, v in sorted(camp_month.items(), key=lambda x: -x[1])], [34, 9, 10, 18])
    if has_prev:
        ws3 = wb.create_sheet("Lost companies")
        sheet(ws3, "Lost companies – follow up", ["Company", "Patients last month", "This month"], [[n, c, 0] for n, c in lost], [48, 18, 12])
    dk = [k for k in span if k in led]
    per = {}
    for k in dk:
        for name, v in group(sum_days(led, [k]), CO).items():
            per.setdefault(name, {})[k] = v[0]
    ws5 = wb.create_sheet("Day by day")
    hdr5 = ["Company"] + [f"{datetime.strptime(k, '%Y-%m-%d'):%d %b}" for k in dk] + ["Total"]
    rows5 = [["All patients"] + [led[k]["n"] for k in dk] + [sum(led[k]["n"] for k in dk)],
             ["Family Medicine (Dr. Sant Das)"] + [led[k].get("fm", 0) for k in dk] + [sum(led[k].get("fm", 0) for k in dk)]]
    for n in sorted(per, key=lambda n: (n == "(not filled)", -sum(per[n].values()))):
        rows5.append([n] + [per[n].get(k, 0) for k in dk] + [sum(per[n].values())])
    sheet(ws5, f"Day by day · {PERIOD}", hdr5, rows5, [44] + [8] * len(dk) + [9])
    ws4 = wb.create_sheet("Nationality")
    sheet(ws4, f"Nationality · {PERIOD}", ["Nationality", LBL, "Month"],
          [[k, today["nat"].get(k, 0), v] for k, v in sorted(month["nat"].items(), key=lambda x: -x[1])], [24, 9, 10])
    buf = io.BytesIO(); wb.save(buf)
    return buf.getvalue()


with t6:
    smtp = {"host": _secret("SMTP_HOST"), "port": _secret("SMTP_PORT", "465"), "user": _secret("SMTP_USER"), "password": _secret("SMTP_PASS")}
    if not (smtp["host"] and smtp["user"] and smtp["password"]):
        smtp = {}
    who = st.selectbox("Send", ["Marketing team – patient counts only", "Management – with revenue"])
    mgmt_mail = who.startswith("Management")
    c1, c2 = st.columns(2)
    to = c1.text_input("Send to (comma separated)", key=f"mk_to_{who}",
                       value=_secret("EMAIL_TO") if mgmt_mail else _secret("MARKETING_EMAIL_TO"))
    cc = c2.text_input("CC (comma separated)", key=f"mk_cc_{who}", value=_secret("EMAIL_CC") if mgmt_mail else "")
    subject = st.text_input("Subject", key=f"mk_sub_{who}",
                            value=f"EMC Marketing Report{' (management)' if mgmt_mail else ''} - {last:%d-%m-%Y}")
    html = email_html(mgmt_mail)
    xbytes = build_excel(mgmt_mail)
    xname = f"EMC_Marketing_{'Management_' if mgmt_mail else ''}{last:%d-%m-%Y}.xlsx"
    with st.expander("Preview email"):
        st.html(html)
    b1, b2 = st.columns([1, 3])
    b2.download_button("Download Excel", xbytes, file_name=xname,
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    if mgmt_mail and not REV_OK:
        st.caption("No ProcedureDetails uploaded, so the management email has no revenue yet.")
    if not smtp:
        st.warning("Email is not set up. It uses the same SMTP secrets as the Revenue Scorecard; add MARKETING_EMAIL_TO for the marketing team.")
    elif b1.button("Send", type="primary"):
        rcp = [x.strip() for x in to.split(",") if x.strip()]
        if not rcp:
            st.error("Add at least one email address.")
        else:
            try:
                import emc_logic as L
                L.send_email(smtp, rcp, subject, html, xbytes, xname, [x.strip() for x in cc.split(",") if x.strip()])
                st.success(f"Sent to {', '.join(rcp)}.")
            except Exception as e:  # noqa: BLE001
                st.error(f"Email not sent: {e}")
