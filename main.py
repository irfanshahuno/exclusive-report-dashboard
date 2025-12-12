from fastapi import FastAPI, File, UploadFile
import pandas as pd
from pathlib import Path
import tempfile

app = FastAPI()

@app.get("/")
def home():
    return {"message": "✅ App is live! Upload Excel files via /process endpoint."}

@app.post("/process")
async def process_file(file: UploadFile = File(...)):
    temp_dir = Path(tempfile.mkdtemp())
    file_path = temp_dir / file.filename
    with open(file_path, "wb") as f:
        f.write(await file.read())

    df = pd.read_excel(file_path)
    return {"rows": len(df), "columns": list(df.columns)}
