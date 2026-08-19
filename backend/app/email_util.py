"""Best-effort SMTP delivery for scheduled report runs.

No-ops silently if no SMTP host is configured (Admin -> Setup), so scheduled
reports still run (and update their history) even with no mail server set up.
"""
import smtplib
from email.mime.text import MIMEText

from app import store


def send_email(recipients: list[str], subject: str, body: str) -> None:
    settings = store.get_app_settings_raw()
    smtp_host = settings["smtp_host"]
    if not smtp_host or not recipients:
        return

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = settings["smtp_from"] or settings["smtp_user"] or "quickinsights@localhost"
    msg["To"] = ", ".join(recipients)

    with smtplib.SMTP(smtp_host, settings["smtp_port"], timeout=10) as server:
        server.starttls()
        if settings["smtp_user"]:
            server.login(settings["smtp_user"], settings["smtp_password"])
        server.sendmail(msg["From"], recipients, msg.as_string())
