#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import ssl
import smtplib
import pickle
import traceback
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication

import boto3
import pandas as pd


# ---------------------------
# Helpers
# ---------------------------

def _env(name: str, default: str = "") -> str:
    v = os.environ.get(name, default)
    return v.strip() if isinstance(v, str) else v

def _to_list(csv_str: str) -> list[str]:
    if not csv_str:
        return []
    return [x.strip() for x in csv_str.split(",") if x.strip()]

def _uae_yesterday_date_str() -> str:
    # UAE = UTC+4
    uae_tz = timezone(timedelta(hours=4))
    now_uae = datetime.now(uae_tz)
    yday = (now_uae - timedelta(days=1)).date()
    return yday.strftime("%Y-%m-%d")

def _s3_client():
    region = _env("AWS_REGION", "eu-north-1")
    return boto3.client(
        "s3",
        region_name=region,
        aws_access_key_id=_env("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=_env("AWS_SECRET_ACCESS_KEY"),
    )

def _download_s3_bytes(bucket: str, key: str) -> bytes:
    s3 = _s3_client()
    obj = s3.get_object(Bucket=bucket, Key=key)
    return obj["Body"].read()

def _safe_df(obj) -> pd.DataFrame | None:
    return obj if isinstance(obj, pd.DataFrame) else None

def _html_table(df: pd.DataFrame, title: str) -> str:
    if df is None or df.empty:
        return f"<h3>{title}</h3><p><i>No data</i></p>"

    # keep it readable in email
    df2 = df.copy()
    # limit crazy-long tables
    if len(df2) > 40:
        df2 = df2.head(40)

    return f"""
    <h3 style="margin:16px 0 8px 0;">{title}</h3>
    {df2.to_html(index=False, border=0)}
    """

def _build_email_html(center_key: str, day: str, dfs: dict) -> str:
    # Try to pick the most important tables if they exist
    # (Your summary.pkl contains multiple dfs; names can vary, so we check common keys)
    candidates = [
        ("Doctor Wise (Avg Amount | Lab %)", ["doctor_wise", "doctor_wise_avg", "doc_wise"]),
        ("Insurance Wise (Avg Amount | Lab %)", ["insurance_wise", "insurance_wise_avg", "ins_wise"]),
        ("Income Analysis - Doctor Wise", ["income_doc", "income_doctor", "income_analysis_doctor"]),
        ("Income Analysis - Insurance Wise", ["income_ins", "income_insurance", "income_analysis_insurance"]),
        ("Income Analysis - Doctor x Insurance", ["income_doc_ins", "income_doctor_insurance", "income_analysis_docxins"]),
    ]

    body_sections = []
    for title, keys in candidates:
        df_found = None
        for k in keys:
            if k in dfs and isinstance(dfs.get(k), pd.DataFrame) and not dfs[k].empty:
                df_found = dfs[k]
                break
        if df_found is not None:
            body_sections.append(_html_table(df_found, title))

    if not body_sections:
        # fallback: show any first 2 dataframes found
        any_dfs = [(k, v) for k, v in dfs.items() if isinstance(v, pd.DataFrame) and not v.empty]
        for k, v in any_dfs[:2]:
            body_sections.append(_html_table(v, f"Table: {k}"))

    style = """
    <style>
      body { font-family: Arial, sans-serif; }
      table { border-collapse: collapse; width: 100%; }
      th, td { border: 1px solid #e5e7eb; padding: 8px; font-size: 13px; }
      th { background: #f3f4f6; text-align: left; }
      h2 { margin: 0 0 12px 0; }
      .meta { color:#6b7280; margin-bottom: 14px; }
    </style>
    """

    header = f"""
    {style}
    <h2>Registration Summary - {center_key} (Yesterday: {day})</h2>
    <div class="meta">
      Generated automatically by GitHub Actions (Daily 9AM UAE).
    </div>
    """

    return header + "\n".join(body_sections)


def _attach_csv_of_key_tables(msg: MIMEMultipart, dfs: dict, prefix: str):
    """
    Optional: attach up to a few key tables as CSV for easy review.
    """
    attach_keys = []
    for k in ["doctor_wise", "insurance_wise", "income_doc", "income_ins", "income_doc_ins"]:
        if k in dfs and isinstance(dfs.get(k), pd.DataFrame) and not dfs[k].empty:
            attach_keys.append(k)

    # if none match, attach first 1 dataframe found
    if not attach_keys:
        for k, v in dfs.items():
            if isinstance(v, pd.DataFrame) and not v.empty:
                attach_keys.append(k)
                break

    for k in attach_keys[:3]:
        df = dfs[k]
        csv_bytes = df.to_csv(index=False).encode("utf-8")
        part = MIMEApplication(csv_bytes, Name=f"{prefix}_{k}.csv")
        part["Content-Disposition"] = f'attachment; filename="{prefix}_{k}.csv"'
        msg.attach(part)


# ---------------------------
# Main
# ---------------------------

def main():
    # Email env
    smtp_host = _env("SMTP_HOST")
    smtp_port = int(_env("SMTP_PORT", "465") or "465")
    smtp_user = _env("SMTP_USER")
    smtp_pass = _env("SMTP_PASS")
    email_to = _to_list(_env("EMAIL_TO"))
    email_cc = _to_list(_env("EMAIL_CC"))

    # AWS env
    bucket = _env("S3_BUCKET_NAME")
    base_prefix = _env("S3_BASE_PREFIX", "").strip("/")  # optional
    center_key = _env("CENTER_KEY", "excellent")

    if not smtp_host or not smtp_user or not smtp_pass or not email_to:
        raise RuntimeError("Missing required SMTP secrets. Check SMTP_HOST/SMTP_USER/SMTP_PASS/EMAIL_TO.")

    if not bucket:
        raise RuntimeError("Missing S3_BUCKET_NAME secret.")

    # Determine "yesterday" in UAE time
    day_str = _uae_yesterday_date_str()

    # Build S3 key to summary.pkl
    # expected: registration/<center>/<YYYY-MM-DD>/summary.pkl
    parts = []
    if base_prefix:
        parts.append(base_prefix)
    parts += ["registration", center_key, day_str, "summary.pkl"]
    s3_key = "/".join(parts)

    # Load summary.pkl
    raw = _download_s3_bytes(bucket, s3_key)
    obj = pickle.loads(raw)

    # obj can be dict of dataframes, or tuple, etc.
    # We normalize it to dict
    dfs = {}
    if isinstance(obj, dict):
        dfs = obj
    elif isinstance(obj, (list, tuple)):
        # try to convert list/tuple of (name, df)
        for item in obj:
            if isinstance(item, (list, tuple)) and len(item) == 2 and isinstance(item[0], str):
                dfs[item[0]] = item[1]
    else:
        # unknown structure; still try
        dfs = {"summary": obj}

    # Build email
    subject = f"Registration Summary - {center_key} (Yesterday {day_str})"
    html_body = _build_email_html(center_key=center_key, day=day_str, dfs=dfs)

    msg = MIMEMultipart("alternative")
    msg["From"] = smtp_user
    msg["To"] = ", ".join(email_to)
    if email_cc:
        msg["Cc"] = ", ".join(email_cc)
    msg["Subject"] = subject

    msg.attach(MIMEText(html_body, "html", "utf-8"))

    # Attach CSV tables (optional)
    _attach_csv_of_key_tables(msg, dfs, prefix=f"{center_key}_{day_str}")

    recipients = email_to + email_cc

    # IMPORTANT: Port 465 => SMTP_SSL (NO starttls)
    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(smtp_host, smtp_port, context=context, timeout=60) as server:
        server.login(smtp_user, smtp_pass)
        server.sendmail(smtp_user, recipients, msg.as_string())

    print(f"✅ Email sent to {recipients} for day {day_str} using key s3://{bucket}/{s3_key}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("❌ FAILED:", str(e))
        traceback.print_exc()
        raise
