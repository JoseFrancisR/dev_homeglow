# cloud/light_wake_sleep_scheduler.py
import logging
from firebase_admin import firestore
from core.firebase import get_db
from core.utils import get_current_utc_datetime
from datetime import datetime
import pytz

logger = logging.getLogger(__name__)

# Timezone (Asia/Manila)
USER_TIMEZONE = pytz.timezone("Asia/Manila")  # UTC+8

# Helpers
def get_current_user_local_time():
    now_utc = get_current_utc_datetime()
    return now_utc.astimezone(USER_TIMEZONE)

def get_today_date_str():
    local_now = get_current_user_local_time()
    return local_now.strftime("%Y-%m-%d")

def time_matches(target_time_str, current_time_dt, tolerance_minutes=3):
    try:
        target_hour, target_minute = map(int, target_time_str.split(":"))
        target_dt = current_time_dt.replace(hour=target_hour, minute=target_minute, second=0, microsecond=0)
        delta_minutes = abs((current_time_dt - target_dt).total_seconds()) / 60
        return delta_minutes <= tolerance_minutes
    except Exception as e:
        logger.warning(f"[WakeSleepChecker] Invalid time format '{target_time_str}': {e}")
        return False

# Main function
async def scheduled_light_wake_sleep_checker():
    db = get_db()
    users_ref = db.collection("users")
    users = users_ref.stream()

    local_now = get_current_user_local_time()
    today_date_str = get_today_date_str()

    for user_doc in users:
        user_data = user_doc.to_dict()
        user_id = user_doc.id
        email = user_data.get("email", "(unknown)")

        # Fetch light schedule
        settings_ref = db.collection("users").document(user_id).collection("settings").document("light_schedule")
        settings_doc = settings_ref.get()

        if not settings_doc.exists:
            continue  # Skip users without light_schedule

        settings_data = settings_doc.to_dict()
        schedule = settings_data.get("schedule", {})

        wake_up_time = schedule.get("wake_up")
        wake_up_light_id = schedule.get("wake_up_light_id")
        sleep_time = schedule.get("sleep")
        sleep_light_id = schedule.get("sleep_light_id")

        wake_up_last_triggered_at = settings_data.get("wake_up_last_triggered_at")
        sleep_last_triggered_at = settings_data.get("sleep_last_triggered_at")

        # Process Wake-Up trigger
        if wake_up_time and wake_up_light_id:
            if time_matches(wake_up_time, local_now):
                if wake_up_last_triggered_at != today_date_str:
                    logger.info(f"[WakeSleepChecker] Wake-Up trigger for {email}: Turning ON light {wake_up_light_id}")
                    light_ref = db.collection("users").document(user_id).collection("light").document(wake_up_light_id)

                    try:
                        light_ref.set({
                            "status": "ON",
                            "timestamp": firestore.SERVER_TIMESTAMP
                        }, merge=True)

                        settings_ref.update({
                            "wake_up_last_triggered_at": today_date_str
                        })

                        logger.info(f"[WakeSleepChecker] ✅ Light {wake_up_light_id} turned ON.")
                    except Exception as e:
                        logger.error(f"[WakeSleepChecker] ❌ Failed to turn ON light {wake_up_light_id}: {e}")

        # Process Sleep trigger
        if sleep_time and sleep_light_id:
            if time_matches(sleep_time, local_now):
                if sleep_last_triggered_at != today_date_str:
                    logger.info(f"[WakeSleepChecker] Sleep trigger for {email}: Turning OFF light {sleep_light_id}")
                    light_ref = db.collection("users").document(user_id).collection("light").document(sleep_light_id)

                    try:
                        light_ref.set({
                            "status": "OFF",
                            "timestamp": firestore.SERVER_TIMESTAMP
                        }, merge=True)

                        settings_ref.update({
                            "sleep_last_triggered_at": today_date_str
                        })

                        logger.info(f"[WakeSleepChecker] ✅ Light {sleep_light_id} turned OFF.")
                    except Exception as e:
                        logger.error(f"[WakeSleepChecker] ❌ Failed to turn OFF light {sleep_light_id}: {e}")

    logger.info("[WakeSleepChecker] Checker run complete.")
