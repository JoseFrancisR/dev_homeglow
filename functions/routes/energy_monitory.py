from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from datetime import datetime
from core.firebase import get_db
from core.models import energy_monitoring

router = APIRouter()

@router.post("/energy")
def record_energy(data: energy_monitoring):
    db = get_db()
    doc_ref = db.collection("energy").document(data.device_id).collection("readings").document()
    doc_ref.set({
        "watts": data.watts,
        "timestamp": data.timestamp,
        "device_id": data.device_id
    })
    return {"message": "Energy reading saved."}
