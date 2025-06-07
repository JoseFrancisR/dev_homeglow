import firebase_admin
from firebase_admin import credentials, firestore
import datetime
import pytz
import logging
from core.email import send_light_on_notification

# Initialize Firebase if not already initialized
if not firebase_admin._apps:
    cred = credentials.ApplicationDefault()
    firebase_admin.initialize_app(cred)

db = firestore.client()

# Constants
DEFAULT_NOTIFY_SECONDS = 1200  # 20 minutes default if light doesn't have field
TIMEZONE = pytz.utc  # use UTC for consistent comparisons

logger = logging.getLogger(__name__)

def check_lights_and_notify():
    logger.info("Starting light ON check task...")

    users_ref = db.collection('users')
    users = users_ref.stream()

    for user_doc in users:
        user_id = user_doc.id
        user_data = user_doc.to_dict()
        user_email = user_data.get('email', '')

        logger.info(f"Checking lights for user: {user_email}")

        lights_ref = users_ref.document(user_id).collection('light')
        lights = lights_ref.stream()

        for light_doc in lights:
            light_id = light_doc.id
            light_data = light_doc.to_dict()

            status = light_data.get('status', '')
            timestamp = light_data.get('timestamp')
            notification_sent = light_data.get('notification_sent', False)

            # IMPORTANT: Read notify_duration per light
            notify_seconds = light_data.get('notify_duration', DEFAULT_NOTIFY_SECONDS)
            notify_minutes = notify_seconds / 60

            # Safety check: skip if no timestamp or status
            if not timestamp or not status:
                continue

            if status == 'ON':
                light_on_time = timestamp
                now = datetime.datetime.now(tz=TIMEZONE)

                duration = now - light_on_time
                duration_minutes = duration.total_seconds() / 60
                duration_seconds = duration.total_seconds()

                if duration_seconds > notify_seconds and not notification_sent:
                    try:
                        # Send email
                        send_light_on_notification(
                            to_email=user_email,
                            username=user_email.split("@")[0],
                            duration_minutes=int(duration_minutes)
                        )

                        # Mark notification_sent = true
                        lights_ref.document(light_id).update({
                            'notification_sent': True
                        })

                        logger.info(
                            f"✅ Notification sent | user={user_email}, light={light_id}, duration={duration_minutes:.1f} mins"
                        )
                    except Exception as e:
                        logger.error(f"🚨 Error sending notification for user={user_email}, light={light_id}: {e}")
                else:
                    logger.info(
                        f"ℹ️ Light {light_id} ON for {duration_minutes:.1f} mins, notification_sent={notification_sent}, notify_seconds={notify_seconds}"
                    )
            else:
                logger.info(f"Skipping light {light_id}, status={status}")

    logger.info("✅ Light ON check task completed.")
