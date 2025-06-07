from fastapi import APIRouter, HTTPException, Depends, Query
from core.auth import verify_firebase_token
from core.firebase import get_db
from core.models import LightCommand
from core.timeout_manager import timeout_manager
from core.utils import get_current_utc_datetime
from typing import List, Optional
from datetime import datetime, timedelta
from core.utils import ensure_timezone_aware

router = APIRouter()

@router.post("/control")
async def control_light(command: LightCommand, user=Depends(verify_firebase_token)):
    print("DEBUG command received:", command)
    print("DEBUG command.dict():", command.dict())

    user_id = user["uid"]
    email = user["email"]

    light_id = command.light_id or "main"

    if command.status not in ("ON", "OFF"):
        raise HTTPException(status_code=400, detail="Only 'ON' or 'OFF' allowed")

    db = get_db()
    user_ref = db.collection("users").document(user_id)
    user_doc = user_ref.get()

    if not user_doc.exists:
        raise HTTPException(status_code=404, detail="User not found")

    user_data = user_doc.to_dict()

    # Check if the light ID exists for this user
    light_ref = db.collection("users").document(user_id).collection("light").document(light_id)
    light_doc = light_ref.get()

    if not light_doc.exists:
        raise HTTPException(status_code=404, detail="Light ID does not exist. It must be registered by the device (Arduino).")

    update_payload = {"status": command.status}

    if command.status == "ON":
        update_payload.update({
            "timestamp": datetime.utcnow(),
            "auto_turned_off": False,
            "notification_sent": False
        })
        light_ref.set(update_payload, merge=True)

        if user_data.get("auto_timeout_enabled", True):
            timeout_seconds = user_data.get("light_timeout_seconds", 600)
            await timeout_manager.schedule_light_turnoff(email, user_id, timeout_seconds, light_id)

    else:
        await timeout_manager.cancel_timeout_for_light(email, light_id)
        update_payload.update({
            "manually_turned_off": True,
            "turned_off_at": datetime.utcnow(),
            "notification_sent": False
        })
        light_ref.set(update_payload, merge=True)

    return {"message": f"{email}'s light '{light_id}' updated to {command.status}"}

@router.get("/status")
def get_light_status(
    user=Depends(verify_firebase_token),
    light_ids: Optional[List[str]] = Query(None)
):
    user_id = user["uid"]
    email = user["email"]

    db = get_db()

    user_ref = db.collection("users").document(user_id)
    user_doc = user_ref.get()

    if not user_doc.exists:
        raise HTTPException(status_code=404, detail="User not found")

    user_data = user_doc.to_dict()
    auto_timeout_enabled = user_data.get("auto_timeout_enabled", True)
    timeout_seconds = user_data.get("light_timeout_seconds", 600)

    response = {}

    if not light_ids:
        light_docs = user_ref.collection("light").stream()
        light_ids = [doc.id for doc in light_docs]
        print(f"No light_ids provided — returning all lights: {light_ids}")

    for light_id in light_ids:
        light_ref = user_ref.collection("light").document(light_id)
        light_doc = light_ref.get()

        if not light_doc.exists:
            response[light_id] = {
                "status": "OFF",
                "message": "No previous light data found",
                "auto_timeout_enabled": auto_timeout_enabled
            }
            continue

        light_data = light_doc.to_dict()
        light_data["auto_timeout_enabled"] = auto_timeout_enabled

        if (
            light_data.get("status") == "ON"
            and auto_timeout_enabled
            and light_data.get("timestamp")
        ):
            timestamp = ensure_timezone_aware(light_data["timestamp"])
            now = get_current_utc_datetime()
            elapsed = (now - timestamp).total_seconds()
            remaining = max(0, timeout_seconds - elapsed)

            light_data["timeout_info"] = {
                "total_timeout_seconds": timeout_seconds,
                "elapsed_seconds": int(elapsed),
                "remaining_seconds": int(remaining),
                "will_turn_off_at": (timestamp + timedelta(seconds=timeout_seconds)).isoformat()
            }

        response[light_id] = light_data

    return response

@router.get("/list")
async def list_lights(user_data: dict = Depends(verify_firebase_token)):
    try:
        user_id = user_data["uid"]

        db = get_db()
        # Fetch lights subcollection
        lights_ref = db.collection("users").document(user_id).collection("light")
        lights_docs = lights_ref.stream()

        # Extract document IDs as light IDs
        light_ids = [doc.id for doc in lights_docs]

        return { "lights": light_ids }

    except Exception as e:
        print(f"Error listing lights: {e}")
        raise HTTPException(status_code=500, detail="Failed to list lights")