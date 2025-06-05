from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from datetime import datetime
from core.firebase import get_db
from core.models import energy_monitoring
from datetime import datetime

router = APIRouter()

@router.post("/energy")
def record_energy(data: energy_monitoring):
    db = get_db()

    # Fallback to current UTC if timestamp not provided
    timestamp = data.timestamp or datetime.utcnow()

    doc_ref = db.collection("energy").document(data.device_id).collection("readings").document()
    doc_ref.set({
        "watts": data.watts,
        "timestamp": timestamp,
        "device_id": data.device_id
    })
    return {"message": "Successfully monitoring energy."}

@router.get("/energy/{device_id}")
def get_energy_data(device_id: str):
    db = get_db()
    readings_ref = db.collection("energy").document(device_id).collection("readings")
    readings = sorted(
        [doc.to_dict() for doc in readings_ref.stream()],
        key=lambda x: x["timestamp"]
    )
    return {
        "device_id": device_id,
        "labels": [r["timestamp"].isoformat() for r in readings],
        "data": [r["watts"] for r in readings]
    }