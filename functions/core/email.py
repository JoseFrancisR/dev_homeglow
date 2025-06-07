import os
import logging
import smtplib
from email.mime.text import MIMEText
from dotenv import load_dotenv

load_dotenv()

# Optional: Import SendGrid if available
try:
    from sendgrid import SendGridAPIClient
    from sendgrid.helpers.mail import Mail
    SENDGRID_AVAILABLE = True
except ImportError:
    SENDGRID_AVAILABLE = False

logger = logging.getLogger(__name__)

# Configurable ENV
SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")
SMTP_SERVER = os.getenv("SMTP_SERVER")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
FROM_EMAIL = os.getenv("NOTIFY_FROM_EMAIL", "noreply@example.com")

def send_light_on_notification(to_email: str, username: str = None, duration_minutes: int = None):
    name_part = username or to_email.split("@")[0]
    subject = "Your light has been ON for too long WEDOWEDOWEDOWEDO ⚠️"

    duration_str = f"{duration_minutes} minutes" if duration_minutes else "several minutes"
    message_body = f"""
Hi {name_part},

Your light has been ON for {duration_str}.
If this was unintentional, you can turn it off on the application.

Thanks,
Mga Sobrang Bait and Humble
"""

    # First try SendGrid if configured
    if SENDGRID_API_KEY and SENDGRID_AVAILABLE:
        try:
            email = Mail(
                from_email=FROM_EMAIL,
                to_emails=to_email,
                subject=subject,
                plain_text_content=message_body.strip(),
            )
            sendg = SendGridAPIClient(SENDGRID_API_KEY)
            response = sendg.send(email)
            logger.info(f"✅ Notification email sent to {to_email} via SendGrid.")
            return
        except Exception as e:
            logger.error(f"❌ Failed to send email to {to_email} via SendGrid: {e}")

    # Fallback to SMTP
    if SMTP_SERVER and SMTP_USERNAME and SMTP_PASSWORD:
        try:
            msg = MIMEText(message_body.strip())
            msg["Subject"] = subject
            msg["From"] = FROM_EMAIL
            msg["To"] = to_email

            with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
                server.starttls()
                server.login(SMTP_USERNAME, SMTP_PASSWORD)
                server.sendmail(FROM_EMAIL, [to_email], msg.as_string())

            logger.info(f"✅ Notification email sent to {to_email} .")
            return
        except Exception as e:
            logger.error(f"❌ Failed to send email to {to_email} via SMTP: {e}")

    logger.error(f"🚫 No email method configured properly. Could not send email to {to_email}.")
