import os
from fastapi import APIRouter, HTTPException, Query
from core.firebase import get_db
from datetime import datetime

router = APIRouter()

@router.post("/register-light")
def register_light(light_id: str = Query(...), token: str = Query(...)):
    expected_token = os.getenv("ARDUINO_TOKEN")

    if not expected_token:
        raise HTTPException(status_code=500, detail="Server misconfigured: ARDUINO_TOKEN not set")

    if token != expected_token:
        raise HTTPException(status_code=401, detail="Unauthorized Arduino device")

    db = get_db()
    #This is not an actual email
    arduino_email = "arduino-controller@example.com"
    user_docs = db.collection("users").where("email", "==", arduino_email).stream()
    user_doc = next(user_docs, None)

    if not user_doc:
        raise HTTPException(status_code=404, detail="Arduino controller user not found")

    user_id = user_doc.id
    light_ref = db.collection("users").document(user_id).collection("light").document(light_id)

    if light_ref.get().exists:
        return {"message": f"Light '{light_id}' is already registered."}

    light_ref.set({
        "status": "OFF",
        "light_id": light_id,
        "registered_by": "arduino",
        "registered_at": datetime.utcnow()
    })

    return {"message": f"Light '{light_id}' registered successfully by Arduino."}
