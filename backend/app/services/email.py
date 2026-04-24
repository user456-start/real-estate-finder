"""
Email service — sends HTML digests via Gmail SMTP + App Password.

No third-party packages needed; uses Python's built-in smtplib + ssl.

Setup (one-time):
    1. Enable 2-Step Verification on your Google account.
    2. Visit myaccount.google.com/apppasswords
    3. Create an App Password for "Mail".
    4. Set GMAIL_ADDRESS and GMAIL_APP_PASSWORD in backend/.env
"""

import logging
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.config import settings

logger = logging.getLogger(__name__)

_GMAIL_SMTP_HOST = "smtp.gmail.com"
_GMAIL_SMTP_PORT = 465  # SSL


def send_email_digest(html_body: str, subject: str = "Your Dubai Property Digest") -> bool:
    """
    Send an HTML email via Gmail SMTP.

    Returns True on success, False on failure (logs the error but never raises,
    so a send failure never crashes the pipeline).
    """
    if not settings.GMAIL_ADDRESS or not settings.GMAIL_APP_PASSWORD:
        logger.error(
            "Gmail credentials not configured. Set GMAIL_ADDRESS and "
            "GMAIL_APP_PASSWORD in backend/.env"
        )
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.GMAIL_ADDRESS
    msg["To"] = settings.EMAIL_TO

    # Attach plain-text fallback first, HTML second (email clients prefer last)
    plain = _html_to_plain(html_body)
    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(_GMAIL_SMTP_HOST, _GMAIL_SMTP_PORT, context=context) as server:
            server.login(settings.GMAIL_ADDRESS, settings.GMAIL_APP_PASSWORD)
            server.sendmail(settings.GMAIL_ADDRESS, settings.EMAIL_TO, msg.as_string())
        logger.info("Digest email sent to %s", settings.EMAIL_TO)
        return True
    except smtplib.SMTPAuthenticationError:
        logger.error(
            "Gmail authentication failed. Make sure you're using an App Password "
            "(not your regular Gmail password) and that 2FA is enabled."
        )
        return False
    except Exception as exc:
        logger.error("Failed to send digest email: %s", exc)
        return False


def _html_to_plain(html: str) -> str:
    """Very simple HTML → plain text strip for the fallback part."""
    import re
    text = re.sub(r"<[^>]+>", "", html)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
