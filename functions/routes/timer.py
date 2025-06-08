from fastapi import APIRouter, HTTPException, Depends
from core.auth import verify_firebase_token
from core.firebase import get_db
from core.timeout_manager import timeout_manager
from core.utils import get_current_utc_datetime, ensure_timezone_aware, format_timeout_display, calculate_total_seconds
from core.models import TimeoutRequest, AutoTimeoutToggleRequest
from firebase_admin import firestore
from datetime import timedelta
import logging

logger = logging.getLogger(__name__)

router = APIRouter()

#THis is for setting the timer
@router.put("/timer")
async def set_light_timeout(data: TimeoutRequest, user=Depends(verify_firebase_token)):
    user_id = user["uid"]
    email = user["email"]

    total_seconds = calculate_total_seconds(data.hours, data.minutes, data.seconds)

    if total_seconds == 0:
        raise HTTPException(status_code=400, detail="Timeout must be greater than 0")
    if total_seconds > 86400:
        raise HTTPException(status_code=400, detail="Timeout cannot exceed 24 hours")

    db = get_db()
    user_ref = db.collection("users").document(user_id)
    user_doc = user_ref.get()

    if not user_doc.exists:
        raise HTTPException(status_code=404, detail="User not found")

    # Save timeout + force auto_timeout_enabled = True
    user_ref.update({
        "light_timeout_seconds": total_seconds,
        "timeout_updated": firestore.SERVER_TIMESTAMP,
        "auto_timeout_enabled": True,  # force ON when setting timer
        "auto_timeout_updated": firestore.SERVER_TIMESTAMP
    })

    # Cancel any existing timeout tasks
    await timeout_manager.cancel_all(email)

    # Schedule turn-off for currently ON lights
    light_ref = db.collection("users").document(user_id).collection("light")
    now = get_current_utc_datetime()

    for light_doc in light_ref.stream():
        light = light_doc.to_dict()
        light_id = light_doc.id

        if light.get("status") == "ON" and light.get("timestamp"):
            on_time = ensure_timezone_aware(light["timestamp"])
            elapsed = (now - on_time).total_seconds()
            remaining = total_seconds - elapsed

            if remaining > 0:
                deadline = now + timedelta(seconds=remaining)

                light_ref.document(light_id).update({
                    "light_timeout_deadline": deadline
                })

                await timeout_manager.schedule_light_turnoff(email, user_id, remaining, light_id)
                logger.info(f"Scheduled timeout for light {light_id} with {remaining:.1f} seconds remaining. Deadline set at {deadline.isoformat()}.")
            else:
                await timeout_manager._turn_off_light(email, user_id, light_id)
                logger.info(f"Light {light_id} timeout already expired — turned OFF immediately.")

    return {
        "message": f"Light timeout set to {format_timeout_display(total_seconds)} for {email}",
        "timeout": {
            "total_seconds": total_seconds,
            "display": format_timeout_display(total_seconds)
        },
        "auto_timeout_enabled": True  # <--- optional: also return this for frontend convenience!
    }

@router.get("/timer")
def get_light_timeout(user=Depends(verify_firebase_token)):
    user_id = user["uid"]
    email = user["email"]

    db = get_db()
    user_ref = db.collection("users").document(user_id)
    user_doc = user_ref.get()

    if not user_doc.exists:
        raise HTTPException(status_code=404, detail="User not found")

    user_data = user_doc.to_dict()
    seconds = user_data.get("light_timeout_seconds", 600)

    return {
        "email": email,
        "auto_timeout_enabled": user_data.get("auto_timeout_enabled", True),
        "timeout": {
            "total_seconds": seconds,
            "display": format_timeout_display(seconds)
        }
    }

# THis is for the if the timer  is enabled or not 
@router.put("/auto-timeout")
async def toggle_auto_timeout(data: AutoTimeoutToggleRequest, user=Depends(verify_firebase_token)):
    user_id = user["uid"]
    email = user["email"]

    db = get_db()
    user_ref = db.collection("users").document(user_id)
    user_doc = user_ref.get()

    if not user_doc.exists:
        raise HTTPException(status_code=404, detail="User not found")

    # Update user-level auto_timeout_enabled + timestamp
    user_ref.update({
        "auto_timeout_enabled": data.auto_timeout_enabled,
        "auto_timeout_updated": firestore.SERVER_TIMESTAMP
    })

    light_ref = db.collection("users").document(user_id).collection("light")
    user_data = user_doc.to_dict()
    total_seconds = user_data.get("light_timeout_seconds", 600)
    now = get_current_utc_datetime()

    if not data.auto_timeout_enabled:
        # 1️⃣ Cancel all running background tasks
        await timeout_manager.cancel_all(email)

        # 2️⃣ Clear light_timeout_deadline in all lights
        for light_doc in light_ref.stream():
            light_ref.document(light_doc.id).update({
                "light_timeout_deadline": firestore.DELETE_FIELD
            })
        logger.info(f"Cleared light_timeout_deadline for all lights of {email} (auto-timeout disabled).")

    else:
        # 1️⃣ Cancel any old tasks (safety)
        await timeout_manager.cancel_all(email)

        # 2️⃣ Schedule deadlines for ON lights
        for light_doc in light_ref.stream():
            light = light_doc.to_dict()
            light_id = light_doc.id

            if light.get("status") == "ON" and light.get("timestamp"):
                on_time = ensure_timezone_aware(light["timestamp"])
                elapsed = (now - on_time).total_seconds()
                remaining = total_seconds - elapsed

                if remaining > 0:
                    deadline = now + timedelta(seconds=remaining)
                    light_ref.document(light_id).update({
                        "light_timeout_deadline": deadline
                    })
                    await timeout_manager.schedule_light_turnoff(email, user_id, remaining, light_id)
                    logger.info(f"(Auto-timeout ON) Scheduled timeout for light {light_id} with {remaining:.1f} seconds remaining. Deadline set at {deadline.isoformat()}.")
                else:
                    # If already expired turn OFF
                    await timeout_manager._turn_off_light(email, user_id, light_id)
                    logger.info(f"(Auto-timeout ON) Light {light_id} timeout already expired — turned OFF immediately.")

    return {
        "message": f"Auto-timeout {'enabled' if data.auto_timeout_enabled else 'disabled'} for {email}",
        "auto_timeout_enabled": data.auto_timeout_enabled
    }


@router.get("/timer_status")
def get_auto_timeout_status(user=Depends(verify_firebase_token)):
    user_id = user["uid"]
    email = user["email"]

    db = get_db()
    user_ref = db.collection("users").document(user_id)
    user_doc = user_ref.get()

    if not user_doc.exists:
        raise HTTPException(status_code=404, detail="User not found")

    enabled = user_doc.to_dict().get("auto_timeout_enabled", True)

    return {
        "email": email,
        "auto_timeout_enabled": enabled,
        "message": f"Auto-timeout is {'enabled' if enabled else 'disabled'}"
    }
