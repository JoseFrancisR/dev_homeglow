from firebase_admin import firestore
from core.firebase import get_db
from core.utils import ensure_timezone_aware, get_current_utc_datetime
from core.email import send_light_on_notification
import logging

logger = logging.getLogger(__name__)

# Background checker for light ON notification
async def scheduled_light_notification_checker():
    db = get_db()
    users_ref = db.collection("users")
    users = users_ref.stream()
    now = get_current_utc_datetime()

    for user_doc in users:
        user_data = user_doc.to_dict()
        user_id = user_doc.id
        email = user_data.get("email")

        if not email:
            continue

        light_ref = db.collection("users").document(user_id).collection("light")
        for light_doc in light_ref.stream():
            light_data = light_doc.to_dict()
            light_id = light_doc.id

            if light_data.get("status") != "ON":
                # Reset notification_sent flag if light is OFF
                if light_data.get("notification_sent", False):
                    light_ref.document(light_id).update({
                        "notification_sent": False
                    })
                    logger.info(f"[NotifChecker] Reset notification_sent for light {light_id} of user {email} (light is OFF).")
                continue

            # Read notify_duration and timestamp
            notify_duration = light_data.get("notify_duration", 1200)  
            light_on_timestamp = light_data.get("timestamp")

            if not light_on_timestamp:
                logger.warning(f"[NotifChecker] Light {light_id} of user {email} ON but no timestamp — skipping.")
                continue

            light_on_dt = ensure_timezone_aware(light_on_timestamp)
            time_elapsed_seconds = (now - light_on_dt).total_seconds()

            # Check if notification needs to be sent
            if time_elapsed_seconds >= notify_duration:
                if light_data.get("notification_sent", False):
                    logger.info(f"[NotifChecker] Light {light_id} of user {email} already notified — skipping.")
                    continue
                try:
                    send_light_on_notification(
                        to_email=email,
                        username=email.split("@")[0],
                        duration_minutes=int(time_elapsed_seconds // 60)
                    )
                    logger.info(f"[NotifChecker] Email sent to {email} for light {light_id} ON too long.")
                except Exception as e:
                    logger.error(f"[NotifChecker] Failed to send email to {email}: {e}")

                # Update notification_sent flag
                light_ref.document(light_id).update({
                    "notification_sent": True,
                    "last_notification_sent_at": firestore.SERVER_TIMESTAMP
                })
            else:
                logger.info(f"[NotifChecker] Light {light_id} of user {email} — ON for {time_elapsed_seconds:.0f}s, notify after {notify_duration}s.")
