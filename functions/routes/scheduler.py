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
    # Safe extraction of user_id
    user_id = user_data.get("uid") or user_data.get("sub")
    if not user_id:
        raise HTTPException(status_code=400, detail="Invalid token: no user ID found")

    # Always build full schedule_data (even if some fields are None)
    schedule_data = {
        "wake_up": schedule.wake_up,
        "wake_up_light_id": schedule.wake_up_light_id,
        "sleep": schedule.sleep,
        "sleep_light_id": schedule.sleep_light_id,
    }

    # Check if at least one time field is provided
    if schedule.wake_up is None and schedule.sleep is None:
        raise HTTPException(status_code=400, detail="At least one of 'wake_up' or 'sleep' must be provided.")

    db = get_db()
    user_ref = db.collection("users").document(user_id)
    settings_ref = user_ref.collection("settings").document("light_schedule")
    
    # Save the full schedule object — this prevents Firestore mismatch
    settings_ref.set({"schedule": schedule_data}, merge=True)

    return {"message": "Schedule updated successfully."}

@router.get("/schedule")
async def get_schedule(user_data: dict = Depends(verify_firebase_token)):
    # Safe extraction of user_id
    user_id = user_data.get("uid") or user_data.get("sub")
    if not user_id:
        raise HTTPException(status_code=400, detail="Invalid token: no user ID found")

    db = get_db()
    user_ref = db.collection("users").document(user_id)
    settings_ref = user_ref.collection("settings").document("light_schedule")
    doc = settings_ref.get()

    # Always return inner "schedule" object
    if doc.exists:
        schedule_data = doc.to_dict().get("schedule", {})
    else:
        schedule_data = {}

    return {"schedule": schedule_data}
