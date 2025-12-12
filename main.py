# main.py — Upload → Process (clinic/pharmacy) → Show KPIs & tables → Download Excel
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import HTMLResponse, FileResponse
import subprocess, tempfile, shutil
from pathlib import Path
import pandas as pd

app = FastAPI(title="Exclusive Report Service")

@app.get("/", response_class=HTMLResponse)
def home():
    return """
    <h2>Exclusive Report — Upload & View</h2>
    <form action="/process" method="post" enctype="multipart/form-data">
      <label>Type:</label>
      <select name="rtype">
        <option value="clinic">Clinic (EasyHealth / Excellent)</option>
        <option value="pharmacy">Pharmacy</option>
      </select><br/><br/>
      <input type="file" name="file" accept=".xlsb,.xlsx,.xlsm" required><br/><br/>
      <button type="submit">Process</button>
    </form>
    <p>Swagger UI: <a href="/docs">/docs</a></p>
    """

def run_generator(src: Path, rtype: str) -> Path:
    if rtype == "pharmacy":
        script = "pharmacy_exclusive_report_with_aging.py"
        out = src.with_suffix("").with_name("Pharmacy_Exclusive_Report_with_Aging.xlsx")
    else:
        script = "exclusive_report_with_aging_final.py"
        out = src.with_suffix("").with_name("report.xlsx")

    # try both arg orders (your scripts accept either)
    for cmd in (
        ["python", script, "--out", str(out), str(src)],
        ["python", script, str(src), "--out", str(out)],
    ):
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode == 0:
            return out
    raise RuntimeError(f"Generator failed.")

@app.post("/process", response_class=HTMLResponse)
async def process(rtype: str = Form(...), file: UploadFile = File(...)):
    suffix = Path(file.filename).suffix
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tf:
        shutil.copyfileobj(file.file, tf)
        src = Path(tf.name)

    out_path = run_generator(src, rtype)

    # Show KPIs + two tables (small sheets) and a Download link
    totals  = pd.read_excel(out_path, sheet_name="Insurance_Totals", engine="openpyxl")
    summary = pd.read_excel(out_path, sheet_name="Balance_Aging_Summary", engine="openpyxl")

    def drop_gt(df):
        first = df.columns[0]
        return df[~df[first].astype(str).str.contains("grand total", case=False, na=False)]
    def ksum(df, *cols):
        for c in cols:
            if c in df.columns: return float(pd.to_numeric(df[c], errors="coerce").sum())
        return 0.0

    tng = drop_gt(totals)
    kpi = f"""
    <div style="display:flex;gap:16px;font-family:Arial">
      <div><b>Net</b><br>{ksum(tng,'Net Amount','NetAmount','Net'):,.2f}</div>
      <div><b>Paid</b><br>{ksum(tng,'Paid'):,.2f}</div>
      <div><b>Balance</b><br>{ksum(tng,'Balance'):,.2f}</div>
      <div><b>Rejected</b><br>{ksum(tng,'Rejected','Rejection'):,.2f}</div>
      <div><b>Accepted</b><br>{ksum(tng,'Accepted'):,.2f}</div>
    </div>
    """

    html = f"""
      <h2>Result</h2>
      {kpi}
      <p><a href="/download?path={out_path}">⬇️ Download full Excel</a></p>
      <h3>Insurance Totals</h3>
      {totals.to_html(index=False)}
      <h3>Balance Aging Summary</h3>
      {summary.to_html(index=False)}
      <p><a href="/">← New upload</a></p>
    """
    return HTMLResponse(html)

@app.get("/download")
def download(path: str):
    p = Path(path)
    return FileResponse(str(p), filename=p.name)
