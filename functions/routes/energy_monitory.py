
from fastapi import APIRouter, HTTPException, Query
from typing import List, Optional
from core.firebase import get_db
from core.models import EnergyMonitoring
from datetime import datetime
from google.cloud import firestore

router = APIRouter()

# POST energy per-light → this is the correct POST your Arduino is using
@router.post("/energy")
def record_energy(data: EnergyMonitoring):
    db = get_db()

    user_query = db.collection("users").where("device_id", "==", data.device_id).stream()
    user_doc = next(user_query, None)

    if not user_doc:
        raise HTTPException(status_code=404, detail="Device not registered for user.")

    user_id = user_doc.id

    energy_ref = db.collection("users").document(user_id) \
                  .collection("energy").document(data.light_id) \
                  .collection("readings").document()

    energy_ref.set({
        "energy_wh": data.energy_wh,
        "timestamp": firestore.SERVER_TIMESTAMP,   
        "light_id": data.light_id
    })

    return {"message": "Successfully recorded per-light energy."}


# GET energy data for frontend chart
@router.get("/energy-data")
def get_energy_data(email: str = Query(...)):
    db = get_db()

    # 1️⃣ Find user by email
    users = db.collection("users").where("email", "==", email).stream()
    user_doc = next(users, None)
    if not user_doc:
        raise HTTPException(status_code=404, detail="User not found.")
    
    user_id = user_doc.id

    # 2️⃣ Get all light documents under /users/{userId}/energy
    energy_docs = db.collection("users").document(user_id).collection("energy").list_documents()

    data = []

    # 3️⃣ For each light, get its /readings subcollection
    for light_doc in energy_docs:
        light_id = light_doc.id
        readings_ref = light_doc.collection("readings").order_by("timestamp", direction=firestore.Query.DESCENDING).limit(50)
        
        readings = readings_ref.stream()

        for doc in readings:
            reading = doc.to_dict()

            # 4️⃣ Handle Firestore timestamp format if present
            timestamp_value = reading.get("timestamp")
            if isinstance(timestamp_value, firestore.SERVER_TIMESTAMP.__class__):
                # If somehow SERVER_TIMESTAMP placeholder — skip (rare)
                continue
            elif hasattr(timestamp_value, "to_datetime"):
                timestamp_value = timestamp_value.to_datetime().isoformat()
            elif hasattr(timestamp_value, "isoformat"):
                timestamp_value = timestamp_value.isoformat()
            else:
                timestamp_value = str(timestamp_value)

            # 5️⃣ Add to data
            data.append({
                "light_id": light_id,
                "energy_wh": reading.get("energy_wh", 0),
                "timestamp": timestamp_value
            })

    # 6️⃣ Return to frontend
    return {"energy_readings": data}
