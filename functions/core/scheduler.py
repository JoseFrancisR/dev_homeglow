from pydantic import BaseModel
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from core.firebase import get_db
from core.auth import verify_firebase_token
from core.models import LightScheduleUpdate

router = APIRouter()

@router.put("/schedule")
async def update_schedule(
    schedule: LightScheduleUpdate,
    user_data: dict = Depends(verify_firebase_token)
):
    # Safe extraction of user_id from token
    user_id = user_data.get("uid") or user_data.get("sub")
    if not user_id:
        raise HTTPException(status_code=400, detail="Invalid token: no user ID found")

    schedule_data = {
        "wake_up": schedule.wake_up,
        "sleep": schedule.sleep,
        "wake_up_light_id": schedule.wake_up_light_id,
        "sleep_light_id": schedule.sleep_light_id,
    }

    # Only save non-None fields
    schedule_data = {k: v for k, v in schedule_data.items() if v is not None}

    # If no fields are provided → return error
    if not schedule_data:
        raise HTTPException(status_code=400, detail="At least one field must be provided.")

    db = get_db()
    user_ref = db.collection("users").document(user_id)
    settings_ref = user_ref.collection("settings").document("light_schedule")
    settings_ref.set({"schedule": schedule_data}, merge=True)

    return {"message": "Schedule updated successfully."}

@router.get("/schedule")
async def get_schedule(user_data: dict = Depends(verify_firebase_token)):
    # Safe extraction of user_id from token
    user_id = user_data.get("uid") or user_data.get("sub")
    if not user_id:
        raise HTTPException(status_code=400, detail="Invalid token: no user ID found")

    db = get_db()
    user_ref = db.collection("users").document(user_id)
    settings_ref = user_ref.collection("settings").document("light_schedule")
    doc = settings_ref.get()

    if doc.exists:
        schedule_data = doc.to_dict()
    else:
        schedule_data = {}

    return schedule_data
