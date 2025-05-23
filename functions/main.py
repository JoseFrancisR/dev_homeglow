from fastapi import FastAPI, HTTPException
from firebase_admin import initialize_app, credentials, firestore
from firebase_functions import https_fn
from a2wsgi import ASGIMiddleware
from pydantic import BaseModel
import os

# Optional: point to Auth emulator
os.environ["FIREBASE_AUTH_EMULATOR_HOST"] = "localhost:9099"

os.environ["WATCHDOG_USE_POLLING"] = "true"

# Optional: disable Flask debug reloader if somehow used
os.environ["FLASK_ENV"] = "production"

# Initialize Firebase Admin SDK
try:
    #IKOYYYYY AYUSIN MO YUNG CREDENTIALS bukassss
    # Use default credentials or specify path to your service account key file here if needed:
    cred = credentials.Certificate("homeglow-4b33c-firebase-adminsdk-fbsvc-aa7dd3c904.json")
    initialize_app(cred)
except ValueError:
    pass

# Initialize Firestore client
db = firestore.client()

# FastAPI app
app = FastAPI()

class LightCommand(BaseModel):
    status: str  # expected values: "ON" or "OFF"

@app.get("/")
def root():
    return {"message": "FastAPI working via Firebase Emulator!"}

@app.get("/ping")
def ping():
    return {"ping": "pong"}

@app.post("/light/control")
def control_light(command: LightCommand):
    if command.status not in ("ON", "OFF"):
        raise HTTPException(status_code=400, detail="Invalid status, must be 'ON' or 'OFF'")
    
    # Update Firestore document with light status command
    doc_ref = db.collection("devices").document("arduino_light")
    doc_ref.set({"status": command.status})
    
    return {"message": f"Light turned {command.status}"}

@app.get("/light/status")
def get_light_status():
    doc_ref = db.collection("devices").document("arduino_light")
    doc = doc_ref.get()
    if doc.exists:
        return doc.to_dict()
    else:
        raise HTTPException(status_code=404, detail="Light status not found")

# Wrap FastAPI in WSGI adapter  para ma use yung Firebase Functions
wrapped_app = ASGIMiddleware(app)

@https_fn.on_request()
def api_entrypoint(request):
    return wrapped_app(request.environ, lambda *args: None)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)