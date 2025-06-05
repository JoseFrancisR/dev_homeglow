from fastapi import APIRouter, HTTPException, Depends, Query
from core.auth import verify_firebase_token
from core.firebase import get_db
from core.scheduler import set_light_schedule, get_light_schedule

router = APIRouter()

@router.put("/schedule")
async def update_light_schedule(
    wake_up: str = Query(default=None),
    sleep: str = Query(default=None),
    user=Depends(verify_firebase_token)
):
    if not wake_up and not sleep:
        raise HTTPException(status_code=400, detail="At least one of 'wake_up' or 'sleep' must be provided")

    email = user.get("email")
    db = get_db()
    user_docs = db.collection("users").where("email", "==", email).stream()
    user_doc = next(user_docs, None)

    if not user_doc:
        raise HTTPException(status_code=404, detail="User not found")

    user_id = user_doc.id
    set_light_schedule(user_id, wake_up, sleep)
    return {"message": "Schedule updated", "wake_up": wake_up, "sleep": sleep}


@router.get("/schedule")
async def fetch_light_schedule(user=Depends(verify_firebase_token)):
    email = user.get("email")
    db = get_db()
    user_docs = db.collection("users").where("email", "==", email).stream()
    user_doc = next(user_docs, None)
    if not user_doc:
        raise HTTPException(status_code=404, detail="User not found")
    user_id = user_doc.id
    schedule = get_light_schedule(user_id)
    return {"email": email, "schedule": schedule}
