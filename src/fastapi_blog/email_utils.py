from email.message import EmailMessage

import aiosmtplib

from .config import settings


async def send_email(to_email: str, subject: str, plain_text: str) -> None:
    message = EmailMessage()
    message["From"] = settings.mail_from
    message["To"] = to_email
    message["Subject"] = subject

    message.set_content(plain_text)

    ## aiosmtplib.send call
    await aiosmtplib.send(
        message,
        hostname=settings.mail_server,
        port=settings.mail_port,
        username=settings.mail_username if settings.mail_username else None,
        password=settings.mail_password.get_secret_value() or None,
        start_tls=settings.mail_use_tls,
    )


async def send_password_reset_mail(to_email: str, username: str, token: str) -> None:
    plain_text = f"""Hi {username},

You requested to reset your password. Click the link below to set a new password:

'Https://www.website.com/reset_password/?token={token}'

This link will expire in 1 hour.

If you didn't request this, you can safely ignore this email.

Best regards,
The FastAPI Blog Team
"""
    await send_email(to_email, subject='Reset Your Password - FastAPI Blog',plain_text=plain_text)
