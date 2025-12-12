# streamlit_app.py — Upload → Process → Download (no DataFrame)
import sys, tempfile, shutil, subprocess
from pathlib import Path
import streamlit as st

st.set_page_config(page_title="Exclusive Report (No-Crash Mode)", layout="centered")
st.title("📦 Exclusive Report — Upload → Process → Download")

CENTERS = {
    "Easy Health (MF8031)": ("easyhealth", "exclusive_report_with_aging_final.py", "report.xlsx"),
    "Excellent Medical Center (MF4777)": ("excellent", "exclusive_report_with_aging_final.py", "report.xlsx"),
    "Excellent Pharmacy (PF3205)": ("excellent_pharmacy", "pharmacy_exclusive_report_with_aging.py",
                                    "Pharmacy_Exclusive_Report_with_Aging.xlsx"),
}
YEARS = [2025, 2024]

center_label = st.selectbox("Center", list(CENTERS.keys()))
year = st.selectbox("Year", YEARS, index=0)
upload = st.file_uploader("Upload source (.xlsb/.xlsx/.xlsm)", type=["xlsb", "xlsx", "xlsm"])

base = Path(__file__).parent
key, gen_script, out_name = CENTERS[center_label]
out_dir = base / "data" / key / str(year)
out_dir.mkdir(parents=True, exist_ok=True)
out_path = out_dir / out_name

def run_generator(src_path: Path, out_path: Path):
    py = sys.executable
    # try both arg orders for safety
    cmds = [
        [py, str(base / gen_script), "--out", str(out_path), str(src_path)],
        [py, str(base / gen_script), str(src_path), "--out", str(out_path)],
    ]
    for cmd in cmds:
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode == 0:
            return True, res.stdout.strip() or "OK", res.stderr.strip()
    return False, res.stdout.strip(), res.stderr.strip()

if upload:
    # save upload to a temp file first (robust & fast)
    suffix = Path(upload.name).suffix.lower()
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tf:
        shutil.copyfileobj(upload, tf)
        src_tmp = Path(tf.name)

    st.info("Processing… please wait.")
    ok, out, err = run_generator(src_tmp, out_path)
    if ok and out_path.exists():
        st.success("✅ Report built successfully.")
        st.download_button("⬇️ Download report (.xlsx)",
                           data=out_path.read_bytes(),
                           file_name=out_path.name,
                           use_container_width=True)
        if out:
            st.code(out, language="bash")
    else:
        st.error("❌ Failed to build report. See logs below.")
        if out: st.code(out, language="bash")
        if err: st.code(err, language="bash")
