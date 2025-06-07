from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from core.firebase import get_db
from google.cloud import firestore
from core.models import PairDeviceRequest
from google.cloud import firestore

router = APIRouter()

@router.post("/pair-device")
def pair_device(payload: PairDeviceRequest):
    db = get_db()

    # Find the user by email
    user_docs = db.collection("users").where("email", "==", payload.email).stream()
    user_doc = next(user_docs, None)

    if not user_doc:
        raise HTTPException(status_code=404, detail="User not found")

    user_id = user_doc.id
    user_ref = db.collection("users").document(user_id)

    # Save the device in the subcollection
    device_ref = user_ref.collection("devices").document(payload.device_id)
    device_ref.set({
        "device_id": payload.device_id,
        "email": payload.email
    })

    # Update the main user document with device_id
    user_ref.update({
        "device_id": payload.device_id,
        "device_paired_at": firestore.SERVER_TIMESTAMP
    })

    return {"message": f"Device '{payload.device_id}' paired with user '{payload.email}'"}
