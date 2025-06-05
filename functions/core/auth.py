from fastapi import Request, HTTPException
from firebase_admin import auth as admin_auth

#For the security of our app this requires a token so that the functions of the app could be used 
def verify_firebase_token(request: Request):
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    id_token = auth_header.split("Bearer ")[1]
    try:
        decoded_token = admin_auth.verify_id_token(id_token)
        return decoded_token
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired Firebase ID token")
