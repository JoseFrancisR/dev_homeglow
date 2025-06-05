from fastapi import APIRouter, HTTPException, Query
from core.firebase import get_db

router = APIRouter()

@router.get("/device/status")
def get_device_light_status(device_id: str = Query(...)):
    db = get_db()

    # Look across all users for matching device_id
    user_docs = db.collection("users").stream()
    for user_doc in user_docs:
        lights_ref = user_doc.reference.collection("light")
        for light_doc in lights_ref.stream():
            light_data = light_doc.to_dict()
            if light_data.get("device_id") == device_id:
                # collect status for all lights tied to this device
                device_lights_ref = db.collection("users").document(user_doc.id).collection("light")
                result = {}
                for doc in device_lights_ref.stream():
                    d = doc.to_dict()
                    if d.get("device_id") == device_id:
                        result[doc.id] = d.get("status", "OFF")
                return result

    raise HTTPException(status_code=404, detail="Device ID not found")
