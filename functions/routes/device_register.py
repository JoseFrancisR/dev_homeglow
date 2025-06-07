import os
from fastapi import APIRouter, HTTPException, Query
from core.firebase import get_db
from datetime import datetime
from typing import Optional, List

router = APIRouter()

@router.post("/register-light")
def register_light(
    light_id: str = Query(...),
    email: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None)
):
    db = get_db()

    if user_id:
        user_ref = db.collection("users").document(user_id)
        user_doc = user_ref.get()
    elif email:
        user_docs = db.collection("users").where("email", "==", email).stream()
        user_doc = next(user_docs, None)
        if user_doc:
            user_ref = db.collection("users").document(user_doc.id)
    else:
        raise HTTPException(status_code=400, detail="Must provide either user_id or email")

    if not user_doc or not user_doc.exists:
        raise HTTPException(status_code=404, detail="User not found")

    light_ref = user_ref.collection("light").document(light_id)
    if light_ref.get().exists:
        return {"message": f"Light '{light_id}' already registered."}

    light_ref.set({
        "status": "OFF",
        "light_id": light_id,
        "registered_by": "arduino",
        "registered_at": datetime.utcnow()
    })

    return {"message": f"Light '{light_id}' registered successfully."}


@router.get("/device-status")
def device_light_status(
    device_id: str = Query(...),
    light_ids: Optional[List[str]] = Query(None)
):
    db = get_db()

    # Find the user by device_id
    users = db.collection("users").where("device_id", "==", device_id).stream()
    user_doc = next(users, None)
    if not user_doc:
        raise HTTPException(status_code=404, detail="Device not paired to any user.")

    user_id = user_doc.id
    user_ref = db.collection("users").document(user_id)

    # Prepare response
    response = {}

    if not light_ids:
        light_docs = user_ref.collection("light").stream()
        light_ids = [doc.id for doc in light_docs]

    for light_id in light_ids:
        light_ref = user_ref.collection("light").document(light_id)
        light_doc = light_ref.get()

        if not light_doc.exists:
            response[light_id] = {
                "status": "OFF",
                "message": "No previous light data found"
            }
            continue

        light_data = light_doc.to_dict()

        response[light_id] = {
            "status": light_data.get("status", "OFF")
        }

    return response
