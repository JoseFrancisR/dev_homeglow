from fastapi import APIRouter, Depends, HTTPException
from core.firebase import get_db
from core.auth import verify_firebase_token
from pydantic import BaseModel, conint
import logging

logger = logging.getLogger(__name__)

router = APIRouter()

# Pydantic model for request
class NotificationSettingsUpdate(BaseModel):
    notify_duration: conint(gt=0)

@router.get("/notification-settings")
def get_notification_settings(user=Depends(verify_firebase_token)):
    user_id = user["uid"]
    email = user["email"]

    db = get_db()
    # Fetch first light to get notify_duration (assuming user wants same value for all lights)
    lights_ref = db.collection("users").document(user_id).collection("light")
    lights = list(lights_ref.stream())

    if not lights:
        logger.error(f"❌ No lights found for user_id={user_id}")
        raise HTTPException(status_code=404, detail="No lights found for user")

    first_light = lights[0].to_dict()
    notify_duration = first_light.get("notify_duration", 1200)

    logger.info(f"✅ GET notify_duration for user_id={user_id}, email={email}: {notify_duration} seconds")

    return {"notify_duration": notify_duration}

@router.put("/notification-settings")
def update_notification_settings(
    update: NotificationSettingsUpdate,
    user=Depends(verify_firebase_token)
):
    user_id = user["uid"]
    email = user["email"]

    db = get_db()
    lights_ref = db.collection("users").document(user_id).collection("light")
    lights = list(lights_ref.stream())

    if not lights:
        logger.error(f"❌ No lights found for user_id={user_id}")
        raise HTTPException(status_code=404, detail="No lights found for user")

    notify_duration = update.notify_duration

    # Update notify_duration in each light document
    batch = db.batch()
    for light_doc in lights:
        light_ref = light_doc.reference
        batch.update(light_ref, {"notify_duration": notify_duration})

    batch.commit()

    logger.info(f"✅ Updated notify_duration for ALL lights of user_id={user_id}, email={email}: {notify_duration} seconds")

    return {"message": "Notification settings updated for all lights", "notify_duration": notify_duration}
