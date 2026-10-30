import smtplib
import ssl
from email.message import EmailMessage

from app.config import Settings


class MailError(RuntimeError):
    pass


def mail_configured(settings: Settings) -> bool:
    return bool(settings.smtp_host and settings.smtp_from)


def send_mail(settings: Settings, to: str, subject: str, body: str) -> None:
    if not mail_configured(settings):
        raise MailError("Email isn't set up (Settings → Email)")
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = settings.smtp_from, to, subject
    msg.set_content(body)
    context = ssl.create_default_context()
    try:
        if settings.smtp_security == "ssl":
            server = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=15, context=context)
        else:
            server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15)
        with server:
            if settings.smtp_security == "starttls":
                server.starttls(context=context)
            if settings.smtp_username:
                server.login(settings.smtp_username, settings.smtp_password or "")
            server.send_message(msg)
    except (OSError, smtplib.SMTPException) as exc:
        raise MailError(f"Sending failed: {exc}") from exc
