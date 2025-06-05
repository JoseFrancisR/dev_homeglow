import os
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail
import logging

logger = logging.getLogger(__name__)

SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")
FROM_EMAIL = os.getenv("NOTIFY_FROM_EMAIL", "noreply@example.com")


def send_light_on_notification(to_email: str, username: str = None, duration_minutes: int = None):
    if not SENDGRID_API_KEY:
        logger.error("SENDGRID_API_KEY is not set")
        return

    name_part = username or to_email.split("@")[0]
    subject = "Your light has been ON too long WEDOWEDOWEDOWEDOWEDO"
    
    duration_str = f"{duration_minutes} minutes" if duration_minutes else "several minutes"
    message = f"""
Hi {name_part},

Your light has been ON for {duration_str}. 
If this was unintentional, you can turn it off on the application

Thanks,
Mga Sobrang Bait and Humble
"""

    try:
        email = Mail(
            from_email=FROM_EMAIL,
            to_emails=to_email,
            subject=subject,
            plain_text_content=message.strip(),
        )
        sendg = SendGridAPIClient(SENDGRID_API_KEY)
        response = sendg.send(email)
        logger.info(f"Notification email sent to {to_email}")
    except Exception as e:
        logger.error(f"OH NOOOOO, Failed to send notification to {to_email}")
