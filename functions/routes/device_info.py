import os
from fastapi import APIRouter, HTTPException, Query
from core.firebase import get_db

router = APIRouter()

@router.get("/device-info")
def get_device_info(device_id: str = Query(...)):
    db = get_db()

    users = db.collection("users").stream()
    for user_doc in users:
        user_id = user_doc.id
        device_ref = db.collection("users").document(user_id).collection("devices").document(device_id)
        device_doc = device_ref.get()

        if device_doc.exists:
            device_data = device_doc.to_dict()
            email = device_data.get("email")
            if email:
                return {"email": email}

    raise HTTPException(status_code=404, detail="Device not found or no email associated.")
