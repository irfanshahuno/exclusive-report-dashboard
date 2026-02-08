import os, pickle
from datetime import datetime, timedelta
import pandas as pd

import boto3
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


def _dfs_to_html_premium(dfs: dict, picked_label: str) -> str:
    # SIMPLE: start with KPI + show income tables (you can paste your premium HTML later)
    parts = []
    parts.append(f"<h2 style='margin:0'>EMC Management Summary</h2>")
    parts.append(f"<div style='color:#555;margin:6px 0 14px 0'><b>{picked_label}</b></div>")

    kpi = dfs.get("KPI")
    if isinstance(kpi, pd.DataFrame) and not kpi.empty:
        parts.append("<h3>KPIs</h3>")
        parts.append(kpi.to_html(index=False, border=0))

    for key in ["Income | Doctor Wise Revenue", "Income | Insurance Wise Revenue", "Income | Doctor x Insurance Revenue"]:
        df = dfs.get(key)
        if isinstance(df, pd.DataFrame) and not df.empty:
            parts.append(f"<h3>{key}</h3>")
            parts.append(df.to_html(index=False, border=0))

    style = """<style>
    body{font-family:Arial,Helvetica,sans-serif;font-size:13px}
    table{border-collapse:collapse;width:100%}
    th,td{padding:6px 8px;border:1px solid #ddd;text-align:left}
    th{background:#f5f5f5}
    </style>"""
    return style + "<body>" + "".join(parts) + "</body>"


def _send_email_smtp(subject: str, html_body: str) -> None:
    host = os.getenv("SMTP_HOST", "")
    port = int(os.getenv("SMTP_PORT", "465"))
    user = os.getenv("SMTP_USER", "")
    pwd  = os.getenv("SMTP_PASS", "")
    to_addr = os.getenv("EMAIL_TO", "")
    cc_addr = os.getenv("EMAIL_CC", "")

    if not (host and user and pwd and to_addr):
        raise ValueError("Missing SMTP env vars (SMTP_HOST/SMTP_PORT/SMTP_USER/SMTP_PASS/EMAIL_TO).")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = to_addr
    if cc_addr:
        msg["Cc"] = cc_addr

    msg.attach(MIMEText(html_body, "html"))

    recipients = [x.strip() for x in (to_addr.split(",") + (cc_addr.split(",") if cc_addr else [])) if x.strip()]

    with smtplib.SMTP_SSL(host, port) as s:
        s.login(user, pwd)
        s.sendmail(user, recipients, msg.as_string())


def s3_key(*parts: str) -> str:
    return "/".join([p.strip("/").strip() for p in parts if p and str(p).strip()])


def main():
    # ---- compute yesterday ----
    yday = (datetime.now() - timedelta(days=1)).date().isoformat()

    # ---- env vars (set in GitHub Secrets) ----
    bucket = os.getenv("S3_BUCKET_NAME", "")
    region = os.getenv("AWS_REGION", "")
    center = os.getenv("CENTER_KEY", "")
    base_prefix = (os.getenv("S3_BASE_PREFIX", "") or "").strip().strip("/")

    if not (bucket and region and center):
        raise ValueError("Missing S3_BUCKET_NAME / AWS_REGION / CENTER_KEY env vars.")

    s3 = boto3.client(
        "s3",
        region_name=region,
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID", ""),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY", ""),
    )

    root = s3_key(base_prefix, "registration", center)
    summary_key = s3_key(root, yday, "summary.pkl")

    obj = s3.get_object(Bucket=bucket, Key=summary_key)
    dfs = pickle.loads(obj["Body"].read())

    picked_label = f"Yesterday ({yday})"
    subject = f"EMC Daily Summary + Income Analysis — {yday}"
    html = _dfs_to_html_premium(dfs, picked_label)

    _send_email_smtp(subject, html)
    print("✅ Email sent:", subject)


if __name__ == "__main__":
    main()
