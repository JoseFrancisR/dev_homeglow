from firebase_admin import firestore
from core.firebase import get_db
from core.utils import ensure_timezone_aware, get_current_utc_datetime
import logging

logger = logging.getLogger(__name__)


#Background checker  for the timer 
async def scheduled_light_timeout_checker():
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

        # Check user-level auto-timeout enabled
        if not user_data.get("auto_timeout_enabled", True):
            continue

        light_ref = db.collection("users").document(user_id).collection("light")
        for light_doc in light_ref.stream():
            light_data = light_doc.to_dict()
            light_id = light_doc.id

            if light_data.get("status") != "ON":
                continue

            if light_data.get("manually_turned_off", False):
                logger.info(f"[CloudFn] Light {light_id} for user {email} is ON but manually_turned_off=True — resetting flag.")
                light_ref.document(light_id).update({
                    "manually_turned_off": False
                })
                continue

            # Check timeout deadline
            deadline = light_data.get("light_timeout_deadline")
            if deadline:
                deadline_dt = ensure_timezone_aware(deadline)
                if now >= deadline_dt:
                    # Auto-turn OFF the light
                    light_ref.document(light_id).update({
                        "status": "OFF",
                        "timestamp": firestore.SERVER_TIMESTAMP,
                        "light_timeout_deadline": firestore.DELETE_FIELD,
                        "auto_turned_off": True,
                        "turned_off_at": firestore.SERVER_TIMESTAMP
                    })
                    logger.info(f"[CloudFn] Auto-turned OFF light {light_id} for user {email} (deadline passed).")
                else:
                    logger.info(f"[CloudFn] Light {light_id} for user {email} — deadline not yet reached.")
            else:
                logger.info(f"[CloudFn] Light {light_id} for user {email} ON but no deadline set — skipping.")
