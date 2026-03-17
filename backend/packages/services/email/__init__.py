"""Email sending service using aiosmtplib."""

from __future__ import annotations

import ssl
from email.message import EmailMessage

import structlog

from packages.core.config import settings

logger = structlog.get_logger(__name__)


async def send_email(
    to: str,
    subject: str,
    body: str,
    from_addr: str | None = None,
    content_type: str = "text/html",
) -> bool:
    """Send an email via SMTP. Supports HTML (default) and plain text."""
    try:
        import aiosmtplib
    except ImportError:
        logger.error("aiosmtplib not installed — email not sent", to=to, subject=subject)
        return False

    sender = from_addr or settings.smtp_from_email
    if not settings.smtp_user or not settings.smtp_password:
        logger.warning("SMTP credentials not configured — email not sent", to=to, subject=subject)
        return False

    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = to
    msg["Subject"] = subject
    if content_type == "text/html":
        msg.set_content("Ваш почтовый клиент не поддерживает HTML. Откройте письмо в браузере.")
        msg.add_alternative(body, subtype="html")
    else:
        msg.set_content(body)

    try:
        tls_context = ssl.create_default_context()

        if settings.smtp_use_tls:
            # Port 465: implicit TLS (SSL)
            await aiosmtplib.send(
                msg,
                hostname=settings.smtp_host,
                port=settings.smtp_port,
                username=settings.smtp_user,
                password=settings.smtp_password,
                use_tls=True,
                tls_context=tls_context,
            )
        else:
            # Port 587: STARTTLS
            await aiosmtplib.send(
                msg,
                hostname=settings.smtp_host,
                port=settings.smtp_port,
                username=settings.smtp_user,
                password=settings.smtp_password,
                start_tls=True,
                tls_context=tls_context,
            )
        logger.info("email_sent", to=to, subject=subject)
        return True
    except Exception as exc:
        logger.error("email_send_failed", to=to, subject=subject, error=str(exc))
        return False
