from fastapi import Header, HTTPException
from firebase_admin import auth as admin_auth

def verify_firebase_token(authorization: str = Header(...)):
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid Authorization header format")
    token = authorization.split("Bearer ")[-1].strip()
    try:
        decoded_token = admin_auth.verify_id_token(token)
        return {
            "uid": decoded_token["uid"],
            "email": decoded_token.get("email", "")
        }
    except Exception as e:
        raise HTTPException(status_code=401, detail="Invalid or expired Firebase ID token")
