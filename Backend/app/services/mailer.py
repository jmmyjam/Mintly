"""Outbound email over plain SMTP (stdlib only — no mail library).

Configured entirely by env vars in Backend/.env, so switching providers is a
.env edit, not a code change:

    SMTP_HOST=smtp.gmail.com     # unset = "dev mode": messages print to the console
    SMTP_PORT=587                # 587 = STARTTLS (default); 465 = implicit TLS
    SMTP_USER=you@gmail.com
    SMTP_PASSWORD=app-password
    MAIL_FROM=you@gmail.com      # defaults to SMTP_USER

With no SMTP_HOST set, send_email prints the full message to the server console
instead of sending — the reset flow stays testable offline (grab the link from
the uvicorn output), and tests never need a network. send_email raises on a
real send failure; callers that must not leak success/failure (the forgot-
password endpoint's anti-enumeration contract) catch and log.
"""

import os
import smtplib
from email.message import EmailMessage

from dotenv import load_dotenv

load_dotenv()

SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
MAIL_FROM = os.getenv("MAIL_FROM", SMTP_USER)


def is_configured() -> bool:
    return bool(SMTP_HOST and MAIL_FROM)


def send_email(to: str, subject: str, body: str) -> None:
    if not is_configured():
        print(f"[mailer] SMTP not configured — printing instead of sending\n"
              f"To: {to}\nSubject: {subject}\n\n{body}", flush=True)
        return
    msg = EmailMessage()
    msg["From"] = MAIL_FROM
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    if SMTP_PORT == 465:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=15) as smtp:
            if SMTP_USER:
                smtp.login(SMTP_USER, SMTP_PASSWORD)
            smtp.send_message(msg)
    else:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as smtp:
            smtp.starttls()
            if SMTP_USER:
                smtp.login(SMTP_USER, SMTP_PASSWORD)
            smtp.send_message(msg)
