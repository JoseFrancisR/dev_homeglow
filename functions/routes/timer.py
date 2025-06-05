from fastapi import APIRouter, HTTPException, Depends, Query
from typing import Optional
from datetime import timedelta
from core.auth import verify_firebase_token
from core.firebase import get_db
from core.timeout_manager import timeout_manager
from core.utils import get_current_utc_datetime, ensure_timezone_aware, format_timeout_display, calculate_total_seconds
from core.models import TimeoutRequest, AutoTimeoutToggleRequest
from firebase_admin import firestore

router = APIRouter()

# This the timer endpoint updates the timer to one set by the user
@router.put("/timer")
async def set_light_timeout(data: TimeoutRequest, user=Depends(verify_firebase_token)):
    email = user.get("email")
    total_seconds = calculate_total_seconds(data.hours, data.minutes, data.seconds)

    if total_seconds == 0:
        raise HTTPException(status_code=400, detail="Timeout must be greater than 0")
    if total_seconds > 86400:
        raise HTTPException(status_code=400, detail="Timeout cannot exceed 24 hours")

    db = get_db()
    users = db.collection("users").where("email", "==", email).stream()
    user_doc = next(users, None)
    if not user_doc:
        raise HTTPException(status_code=404, detail="User not found")

    user_id = user_doc.id
    user_data = user_doc.to_dict()
    db.collection("users").document(user_id).update({
        "light_timeout_seconds": total_seconds,
        "timeout_updated": firestore.SERVER_TIMESTAMP
    })

    return {
        "message": f"Light timeout set to {format_timeout_display(total_seconds)} for {email}",
        "timeout": {
            "total_seconds": total_seconds,
            "display": format_timeout_display(total_seconds)
        }
    }

#  THis GET will be used to be shown in the front end application
@router.get("/timer")
def get_light_timeout(email: str = Query(...), user=Depends(verify_firebase_token)):
    db = get_db()
    users = db.collection("users").where("email", "==", email).stream()
    user_doc = next(users, None)
    if not user_doc:
        raise HTTPException(status_code=404, detail="User not found")

    user_data = user_doc.to_dict()
    seconds = user_data.get("light_timeout_seconds", 600)

    return {
        "email": email,
        "auto_timeout_enabled": user_data.get("auto_timeout_enabled", True),
        "timeout": {
            "total_seconds": seconds,
            "display": format_timeout_display(seconds)
        }
    }


@router.put("/auto-timeout")
async def toggle_auto_timeout(data: AutoTimeoutToggleRequest, user=Depends(verify_firebase_token)):
    email = data.email
    db = get_db()
    users = db.collection("users").where("email", "==", email).stream()
    user_doc = next(users, None)
    if not user_doc:
        raise HTTPException(status_code=404, detail="User not found")

    user_id = user_doc.id
    db.collection("users").document(user_id).update({
        "auto_timeout_enabled": data.enabled,
        "auto_timeout_updated": firestore.SERVER_TIMESTAMP
    })

    if not data.enabled:
        await timeout_manager.cancel_all(email)

    return {
        "message": f"Auto-timeout {'enabled' if data.enabled else 'disabled'} for {email}",
        "auto_timeout_enabled": data.enabled
    }


@router.get("/timer_status")
def get_auto_timeout_status(email: str = Query(...), user=Depends(verify_firebase_token)):
    db = get_db()
    users = db.collection("users").where("email", "==", email).stream()
    user_doc = next(users, None)
    if not user_doc:
        raise HTTPException(status_code=404, detail="User not found")

    enabled = user_doc.to_dict().get("auto_timeout_enabled", True)
    return {
        "email": email,
        "auto_timeout_enabled": enabled,
        "message": f"Auto-timeout is {'enabled' if enabled else 'disabled'}"
    }
