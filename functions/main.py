from dotenv import load_dotenv
import os
from datetime import datetime, timedelta

load_dotenv()  

# DEBUG: Print environment variable load status
print("Loaded EMAIL_SENDER:", os.getenv("EMAIL_SENDER"))
print("Loaded EMAIL_PASSWORD:", "Yes" if os.getenv("EMAIL_PASSWORD") else "Missing")

from fastapi import FastAPI, HTTPException, BackgroundTasks
from firebase_admin import initialize_app, credentials, firestore, auth as admin_auth
from firebase_functions import https_fn
from a2wsgi import ASGIMiddleware
from pydantic import BaseModel
import firebase_admin
import pyrebase
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# This part is for sending email notificatons to the user 
def send_email_notification(recipient_email: str, light_status: str, duration_minutes: int):
    sender_email = os.getenv("EMAIL_SENDER")
    sender_password = os.getenv("EMAIL_PASSWORD")

    print("[Email] Preparing to send email")
    print("[Email] Sender:", sender_email)
    print("[Email] Recipient:", recipient_email)
    print("[Email] Light Status:", light_status)
    print("[Email] Duration (min):", duration_minutes)

    subject = "Light Alert WEDOWEDOWEDOWEDO"
    body = (
        f"The light has been left {light_status} a little too long.\n\n"
        f"It has been ON for approximately {duration_minutes} minutes.\n"
        f"We just wanted to remind you"
    )

    msg = MIMEMultipart()
    msg["From"] = sender_email
    msg["To"] = recipient_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            print("[Email] Logging in to SMTP server...")
            server.login(sender_email, sender_password)
            print("[Email] Logged in and sending...")
            server.send_message(msg)
            print("[Email] Email sent to:", recipient_email)
    except Exception as e:
        print(f"[Email] Error sending email: {e}")

# Emulator settings
os.environ["FIREBASE_AUTH_EMULATOR_HOST"] = "localhost:9099"
os.environ["WATCHDOG_USE_POLLING"] = "true"
os.environ["FLASK_ENV"] = "production"

# Initialize Firebase Admin
if not firebase_admin._apps:
    cred = credentials.Certificate("homeglow-4b33c-firebase-adminsdk-fbsvc-aa7dd3c904.json")
    initialize_app(cred)

db = firestore.client()

# FastAPI app
app = FastAPI(
    description="This is a simple app to show Firebase Auth with FastAPI",
    title="Firebase backend",
    docs_url="/"
)

# Firebase config
firebaseConfig = {
    "apiKey": os.getenv("API_KEY"),
    "authDomain": os.getenv("AUTH_DOMAIN"),
    "databaseURL": os.getenv("DATABASE_URL"),
    "projectId": os.getenv("PROJECT_ID"),
    "storageBucket": os.getenv("STORAGE_BUCKET"),
    "messagingSenderId": os.getenv("MESSAGING_SENDER_ID"),
    "appId": os.getenv("APP_ID"),
    "measurementId": os.getenv("MEASUREMENT_ID"),
}

firebase = pyrebase.initialize_app(firebaseConfig)
auth = firebase.auth()

# Models
class LightCommand(BaseModel):
    status: str

class AuthRequest(BaseModel):
    email: str
    password: str

@app.get("/")
def root():
    return {"message": "FastAPI working via Firebase Emulator!"}

@app.get("/ping")
def ping():
    return {"ping": "pong"}

@app.post("/signup")
async def signup(data: AuthRequest):
    try:
        user = auth.create_user_with_email_and_password(data.email, data.password)
        db.collection("users").document(user['localId']).set({
            "email": data.email,
            "light_timeout": 10,
            "created_at": firestore.SERVER_TIMESTAMP
        })
        return {"message": "User created successfully", "user": user}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/login")
async def login(data: AuthRequest):
    try:
        user = auth.sign_in_with_email_and_password(data.email, data.password)
        return {"message": "Login successful :)", "user": user}
    except Exception as e:
        raise HTTPException(status_code=401, detail="Invalid credentials :(")

@app.get("/validate")
async def validate(token: str):
    try:
        decoded = auth.get_account_info(token)
        return {"message": "Token is valid", "user_info": decoded}
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")

@app.post("/light/control")
def control_light(command: LightCommand, background_tasks: BackgroundTasks):
    if command.status not in ("ON", "OFF"):
        raise HTTPException(status_code=400, detail="Invalid status, must be 'ON' or 'OFF'")

    doc_ref = db.collection("devices").document("arduino_light")
    update_data = {"status": command.status}

    if command.status == "ON":
        update_data["timestamp"] = datetime.utcnow()

    doc_ref.set(update_data)
    print(f"[Control] Light turned {command.status}")

    if command.status == "ON":
        print("[Control] Scheduling timeout check task...")
        background_tasks.add_task(check_light_timeout)

    return {"message": f"Light turned {command.status}"}

def check_light_timeout():
    print("[Timeout Check] Running check_light_timeout()")
    doc_ref = db.collection("devices").document("arduino_light")
    doc = doc_ref.get()
    if doc.exists:
        data = doc.to_dict()
        status = data.get("status")
        timestamp = data.get("timestamp")

        if status == "ON" and timestamp:
            print("[Timeout Check] Light is ON, checking time...")
            users_ref = db.collection("users").stream()
            for user_doc in users_ref:
                user_data = user_doc.to_dict()
                timeout_minutes = user_data.get("light_timeout", 10)
                user_email = user_data.get("email")

                time_on = timestamp.replace(tzinfo=None)
                now = datetime.utcnow()
                elapsed = now - time_on
                elapsed_minutes = int(elapsed.total_seconds() / 60)

                print(f"[Timeout Check] Email: {user_email} | Timeout: {timeout_minutes} min | Elapsed: {elapsed_minutes} min")

                if elapsed_minutes >= timeout_minutes:
                    print(f"[Notify] Timeout exceeded. Notifying {user_email}")
                    send_email_notification(user_email, status, elapsed_minutes)

@app.get("/light/status")
def get_light_status():
    doc_ref = db.collection("devices").document("arduino_light")
    doc = doc_ref.get()
    if doc.exists:
        return doc.to_dict()
    else:
        raise HTTPException(status_code=404, detail="Light status not found")

# Firebase Functions wrapper
wrapped_app = ASGIMiddleware(app)

@https_fn.on_request()
def api_entrypoint(request):
    return wrapped_app(request.environ, lambda *args: None)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
