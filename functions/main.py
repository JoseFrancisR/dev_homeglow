from dotenv import load_dotenv
import os
from datetime import datetime, timedelta
import asyncio

load_dotenv()  # Load .env early

import logging
import traceback

# --- Fix emulator env var setup at the top ---
if os.getenv("RUNNING_LOCALLY") == "true":
    os.environ["FIREBASE_AUTH_EMULATOR_HOST"] = "localhost:9099"
    os.environ["FIRESTORE_EMULATOR_HOST"] = "localhost:8085"  # Add Firestore emulator host
else:
    # Ensure these are not set when deployed to cloud
    os.environ.pop("FIREBASE_AUTH_EMULATOR_HOST", None)
    os.environ.pop("FIRESTORE_EMULATOR_HOST", None)

# --- Remove unconditional emulator env var setting below ---
# os.environ["FIREBASE_AUTH_EMULATOR_HOST"] = "localhost:9099"  # REMOVE this line!

# Keep your other environment vars as needed
os.environ["WATCHDOG_USE_POLLING"] = "true"
os.environ["FLASK_ENV"] = "production"

from fastapi import FastAPI, HTTPException, BackgroundTasks
from typing import Optional
from firebase_admin import initialize_app, credentials, firestore, auth as admin_auth
from firebase_functions import https_fn
from firebase_functions.https_fn import Request, Response
from a2wsgi import ASGIMiddleware as AsgiToWsgi
import sys
from io import BytesIO
from pydantic import BaseModel
import firebase_admin
import io
import pyrebase
import smtplib
import schedule
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart


# This uses my ikoygwapo31 email to send notifications 
# Lets make another account later tinatamad pa ako
def send_email_notification(recipient_email: str,  duration_minutes: int):
    sender_email = os.getenv("EMAIL_SENDER")
    sender_password = os.getenv("EMAIL_PASSWORD")
    subject = "Light Alert WEDOWEDOWEDOWEDO"
    body = (
        f"Your light has been left ON a little too long.\n\n it has been on for about {duration_minutes} min"
    )

    msg = MIMEMultipart()
    msg["From"] = sender_email
    msg["To"] = recipient_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(sender_email, sender_password)
            server.send_message(msg)
    except Exception as e:
        print("Error sending email:", str(e))

# This is for the emulator server 
os.environ["FIREBASE_AUTH_EMULATOR_HOST"] = "localhost:9099"
os.environ["WATCHDOG_USE_POLLING"] = "true"
os.environ["FLASK_ENV"] = "production"

if not firebase_admin._apps:
    cred = credentials.Certificate("homeglow-4b33c-firebase-adminsdk-fbsvc-aa7dd3c904.json")
    initialize_app(cred)
else:
    print("Something might be wrong and it has already been initialized")
    pass

db = firestore.client()

# FastAPI app
app = FastAPI(
    title="Firebase backend",
    docs_url="/"
)

# Hidden the firebase config in the.env file hehehehe YALL DONT HAVE IT BUT I HAVE IT
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

# Structure data for lights and auth accounts 
class LightCommand(BaseModel):
    email: str
    status: str

class AuthRequest(BaseModel):
    email: str
    password: str
    username: Optional[str] = None

class UpdateTimeoutRequest(BaseModel):
    email: str
    timeout_minutes: int

class Schedule(BaseModel):
    email: str
    wake: str
    sleep: str
    days: list[str]
    
@app.post("/schedule/set")
async def set_schedule(schedule: Schedule):
    user = db.collection("users").where("email", "==", schedule.email).stream()
    schedule

active_monitoring_tasks = {}

#This is for authentication and signup/login
@app.post("/signup")
async def userSignup(data: AuthRequest):
    email = data.email
    password = data.password
    username = data.username
    try:
        user = auth.create_user_with_email_and_password(email, password)
        db.collection("users").document(user['localId']).set({
            "email": email,
            "username": username,
            "light_timeout": 10,
            "account_created": firestore.SERVER_TIMESTAMP})
        return {"message": "User created successfully", "user": user}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/login")
async def user_login(data: AuthRequest):
    try:
        user = auth.sign_in_with_email_and_password(data.email, data.password)
        return {"message": "Login successful :)", "user": user}
    except Exception as e:
        raise HTTPException(status_code=401, detail="Invalid credentials :(")

# THis is to check 
@app.get("/validate")
async def userValidation(token: str):
    try:
        validated = auth.get_account_info(token)
        return {"message": "Token is valid", "user_info": validated}
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")

"""async def monitor_light_status(user_id: str):
    while True:
        print("Checking light status for user ", user_id)
        
        # Get user data
        user_doc = db.collection("users").document(user_id).get()
        if not user_doc.exists:
            print(f"User {user_id} no longer exists")
            return

        user_data = user_doc.to_dict()
        timeout_minutes = user_data.get("light_timeout", 10)
        user_email = user_data.get("email")

        # Get light status
        light_status_database = db.collection("users").document(user_id).collection("light").document("status")
        light_doc = light_status_database.get()

        if not light_doc.exists:
            print(f"No light document for user {user_id}")
            return

        light_data = light_doc.to_dict()
        status = light_data.get("status")
        timestamp = light_data.get("timestamp")

        if status != "ON" or not timestamp:
            print(f"Light is OFF for user {user_id}")
            return

        # Calculate time elapsed
        time_on = timestamp.replace(tzinfo=None)
        now = datetime.utcnow()
        elapsed = now - time_on
        time_passed = int(elapsed.total_seconds() / 60)

        print(f"{user_email} - Light ON for {time_passed} minutes (timeout: {timeout_minutes})")

        if time_passed >= timeout_minutes:
            print(f"Sending notification to {user_email}")
            send_email_notification(user_email, time_passed)
            return

        # This makes it check every 60 seconds
        try:
            await asyncio.wait_for(asyncio.sleep(60), timeout=60)  # Wait for 60 seconds
        except asyncio.TimeoutError:
            continue"""
# this sends a command to turn on and off the lights
@app.post("/light/control")
async def control_light(command: LightCommand, background_tasks: BackgroundTasks):
    if command.status not in ("ON", "OFF"):
        raise HTTPException(status_code=400, detail="Invalid status, must be 'ON' or 'OFF'")

    # Find user by email
    users = db.collection("users").where("email", "==", command.email).stream()
    user_doc = next(users, None)
    if not user_doc:
        raise HTTPException(status_code=404, detail="User not found")

    user_id = user_doc.id
    user_doc_ref = db.collection("users").document(user_id).collection("light").document("status")
    
    update_data = {"status": command.status}
    if command.status == "ON":
        update_data["timestamp"] = datetime.utcnow()

    user_doc_ref.set(update_data)
    print(f"Light for {command.email} turned {command.status}")

    if command.status == "ON":
        # Cancel any existing monitoring task for this user
        if user_id in active_monitoring_tasks:
            active_monitoring_tasks[user_id].cancel()
        
        # Start new monitoring task
        task = asyncio.create_task(monitor_light_status(user_id))
        active_monitoring_tasks[user_id] = task
    elif command.status == "OFF" and user_id in active_monitoring_tasks:
        # Cancel monitoring when light is turned OFF
        active_monitoring_tasks[user_id].cancel()
        del active_monitoring_tasks[user_id]

    return {"message": f"Light turned {command.status} for {command.email}"}

@app.get("/light/status")
def get_light_status(email: str):
    users = db.collection("users").where("email", "==", email).stream()
    user_doc = next(users, None)
    if not user_doc:
        raise HTTPException(status_code=404, detail="User not found")

    user_id = user_doc.id
    doc_ref = db.collection("users").document(user_id).collection("light").document("status")
    doc = doc_ref.get()

    if doc.exists:
        return doc.to_dict()
    else:
        raise HTTPException(status_code=404, detail="No light data found for this user")

# This sets how long the lights should be on before the user gets notified 
@app.post("/user/light_timeout")
async def update_light_timeout(data: UpdateTimeoutRequest):
    email = data.email
    timout_minutes =data.timeout_minutes
    try:
        users_ref = db.collection("users").where("email", "==", data.email).stream()
        updated = False
        for doc in users_ref:
            doc.reference.update({"light_timeout": timout_minutes})
            updated = True
            print(f"Updated {email} to {timout_minutes} min")

        if not updated:
            raise HTTPException(status_code=404, detail="Error: The code can't find the user")

        return {"message": "Light timeout updated successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) 


wsgi_app = AsgiToWsgi(app)

@https_fn.on_request()
def api_entrypoint(request: Request) -> Response:
    environ = request.environ.copy()
    environ['wsgi.input'] = BytesIO(request.get_data())

    response_body = []
    response_status = None
    response_headers = []

    def start_response(status, headers, exc_info=None):
        nonlocal response_status, response_headers
        response_status = status
        response_headers = headers
        return response_body.append

    result = wsgi_app(environ, start_response)

    try:
        for data in result:
            if data:
                response_body.append(data)
    finally:
        if hasattr(result, "close"):
            result.close()

    status_code = int(response_status.split()[0])
    headers = dict(response_headers)
    body = b"".join(response_body)

    return Response(
        response=body,
        status=status_code,
        headers=headers,
        content_type=headers.get("content-type", "application/octet-stream")
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
