from dotenv import load_dotenv
import os
from datetime import datetime, timedelta, timezone
import asyncio
from typing import Dict, Optional
import logging

load_dotenv()

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from firebase_admin import initialize_app, credentials, firestore, auth as admin_auth
from firebase_functions import https_fn
from firebase_functions.https_fn import Request, Response
from pydantic import BaseModel, validator
import firebase_admin
import json

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Firebase
_db = None
_app_initialized = False

def get_db():
    global _db, _app_initialized
    if _db is None:
        if not _app_initialized:
            initialize_firebase()
        _db = firestore.client()
    return _db

def initialize_firebase():
    global _app_initialized
    if not _app_initialized and not firebase_admin._apps:
        try:
            initialize_app()
            logger.info("Firebase Admin initialized successfully")
            _app_initialized = True
        except Exception as e:
            logger.error(f"Failed to initialize Firebase Admin: {e}")
            raise

# Background Task Manager for Light Timeouts
class LightTimeoutManager:
    def __init__(self):
        self.active_tasks: Dict[str, asyncio.Task] = {}
        self.monitoring_task: Optional[asyncio.Task] = None
        self.is_running = False
        self.lock = asyncio.Lock()
    
    async def start_monitoring(self):
        """Start the background monitoring task"""
        if not self.is_running:
            self.is_running = True
            self.monitoring_task = asyncio.create_task(self._monitor_lights())
            logger.info("Light timeout monitoring started")
    
    async def stop_monitoring(self):
        """Stop the background monitoring task"""
        self.is_running = False
        if self.monitoring_task:
            self.monitoring_task.cancel()
            try:
                await self.monitoring_task
            except asyncio.CancelledError:
                pass
        
        # Cancel all active timeout tasks
        async with self.lock:
            for task in self.active_tasks.values():
                task.cancel()
            self.active_tasks.clear()
        
        logger.info("Light timeout monitoring stopped")
    
    async def _monitor_lights(self):
        """Background task that monitors all lights every 30 seconds"""
        while self.is_running:
            try:
                await self._check_all_lights()
                await asyncio.sleep(30)  # Check every 30 seconds
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in light monitoring: {str(e)}")
                await asyncio.sleep(30)  # Continue monitoring even after errors
    
    async def _check_all_lights(self):
        """Check all lights in the database and schedule turn-offs if needed"""
        try:
            db = get_db()
            users_ref = db.collection("users")
            users = users_ref.stream()
            
            for user_doc in users:
                user_data = user_doc.to_dict()
                user_id = user_doc.id
                email = user_data.get("email")
                
                if not email:
                    continue
                
                # Skip if auto-timeout is disabled
                if not user_data.get("auto_timeout_enabled", True):
                    continue
                
                # Check light status
                light_ref = db.collection("users").document(user_id).collection("light").document("status")
                light_doc = light_ref.get()
                
                if light_doc.exists:
                    light_data = light_doc.to_dict()
                    status = light_data.get("status")
                    timestamp = light_data.get("timestamp")
                    
                    if status == "ON" and timestamp:
                        # Calculate if light should be turned off
                        timeout_seconds = user_data.get("light_timeout_seconds", 600)  # Default 10 minutes
                        
                        # Handle both datetime objects and timestamps
                        turn_on_time = ensure_timezone_aware(timestamp)
                        current_time = get_current_utc_datetime()
                        time_diff = (current_time - turn_on_time).total_seconds()
                        
                        if time_diff >= timeout_seconds:
                            # Light should be turned off
                            await self._turn_off_light(email, user_id)
                            logger.info(f"Auto-turned off light for {email} after {time_diff:.1f} seconds")
                        else:
                            # Schedule turn-off if not already scheduled
                            remaining_time = timeout_seconds - time_diff
                            await self.schedule_light_turnoff(email, user_id, remaining_time)
                
        except Exception as e:
            logger.error(f"Error checking all lights: {str(e)}")
    
    async def schedule_light_turnoff(self, email: str, user_id: str, delay_seconds: float):
        """Schedule a light to be turned off after delay_seconds"""
        async with self.lock:
            # Cancel existing task for this user if any
            if email in self.active_tasks:
                self.active_tasks[email].cancel()
            
            # Only schedule if delay is positive and reasonable
            if delay_seconds > 0 and delay_seconds <= 86400:  # Max 24 hours
                task = asyncio.create_task(
                    self._delayed_light_turnoff(email, user_id, delay_seconds)
                )
                self.active_tasks[email] = task
                logger.info(f"Scheduled light turn-off for {email} in {delay_seconds:.1f} seconds")
    
    async def _delayed_light_turnoff(self, email: str, user_id: str, delay_seconds: float):
        """Turn off light after a delay"""
        try:
            await asyncio.sleep(delay_seconds)
            await self._turn_off_light(email, user_id)
            logger.info(f"Auto-turned off light for {email} after scheduled delay")
        except asyncio.CancelledError:
            logger.info(f"Light turn-off cancelled for {email}")
        except Exception as e:
            logger.error(f"Error in delayed light turn-off for {email}: {str(e)}")
        finally:
            # Clean up the task reference
            async with self.lock:
                if email in self.active_tasks:
                    del self.active_tasks[email]
    
    async def _turn_off_light(self, email: str, user_id: str):
        """Turn off the light for a specific user"""
        try:
            db = get_db()
            light_ref = db.collection("users").document(user_id).collection("light").document("status")
            
            # Check if light is still ON before turning off
            light_doc = light_ref.get()
            if light_doc.exists and light_doc.to_dict().get("status") == "ON":
                light_ref.set({
                    "status": "OFF",
                    "auto_turned_off": True,
                    "turned_off_at": datetime.utcnow()
                })
                logger.info(f"Successfully auto-turned off light for {email}")
            
        except Exception as e:
            logger.error(f"Error turning off light for {email}: {str(e)}")
    
    async def cancel_timeout(self, email: str):
        """Cancel the timeout for a specific user"""
        async with self.lock:
            if email in self.active_tasks:
                self.active_tasks[email].cancel()
                del self.active_tasks[email]
                logger.info(f"Cancelled light timeout for {email}")

# Global timeout manager instance
timeout_manager = LightTimeoutManager()

# FastAPI app
app = FastAPI(title="Light Control API", docs_url=None)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["Content-Type", "Authorization"],
)

# Startup and shutdown events
@app.on_event("startup")
async def startup_event():
    """Start the background timeout monitoring when the app starts"""
    await timeout_manager.start_monitoring()

@app.on_event("shutdown")
async def shutdown_event():
    """Clean up when the app shuts down"""
    await timeout_manager.stop_monitoring()

# Pydantic models
class LightCommand(BaseModel):
    email: str
    status: str

class AuthRequest(BaseModel):
    email: str
    password: str
    username: Optional[str] = None

class LoginRequest(BaseModel):
    email: str
    password: str

class TimeoutRequest(BaseModel):
    email: str
    hours: Optional[int] = 0
    minutes: Optional[int] = 0
    seconds: Optional[int] = 0
    
    @validator('hours')
    def validate_hours(cls, v):
        if v is None:
            return 0
        if v < 0 or v > 23:
            raise ValueError('Hours must be between 0 and 23')
        return v
    
    @validator('minutes')
    def validate_minutes(cls, v):
        if v is None:
            return 0
        if v < 0 or v > 59:
            raise ValueError('Minutes must be between 0 and 59')
        return v
    
    @validator('seconds')
    def validate_seconds(cls, v):
        if v is None:
            return 0
        if v < 0 or v > 59:
            raise ValueError('Seconds must be between 0 and 59')
        return v

class AutoTimeoutToggleRequest(BaseModel):
    email: str
    enabled: bool

def get_current_utc_datetime():
    """Get current UTC datetime that's timezone-aware"""
    return datetime.now(timezone.utc)

def ensure_timezone_aware(dt):
    """Ensure datetime object is timezone-aware"""
    if dt is None:
        return None
    
    # If it's a Firebase timestamp, convert to datetime
    if hasattr(dt, 'timestamp'):
        return dt
    
    # If it's already timezone-aware, return as is
    if dt.tzinfo is not None:
        return dt
    
    # If it's naive, assume it's UTC
    return dt.replace(tzinfo=timezone.utc)

def calculate_total_seconds(hours: int, minutes: int, seconds: int) -> int:
    """Calculate total seconds from hours, minutes, and seconds"""
    return (hours or 0) * 3600 + (minutes or 0) * 60 + (seconds or 0)

def format_timeout_display(total_seconds: int) -> str:
    """Convert total seconds back to readable format"""
    hours = total_seconds // 3600
    remaining_seconds = total_seconds % 3600
    minutes = remaining_seconds // 60
    seconds = remaining_seconds % 60
    
    parts = []
    if hours > 0:
        parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
    if minutes > 0:
        parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
    if seconds > 0:
        parts.append(f"{seconds} second{'s' if seconds != 1 else ''}")
    
    if len(parts) == 0:
        return "0 seconds"
    elif len(parts) == 1:
        return parts[0]
    elif len(parts) == 2:
        return f"{parts[0]} and {parts[1]}"
    else:
        return f"{parts[0]}, {parts[1]}, and {parts[2]}"

@app.post("/signup")
def userSignup(data: AuthRequest):  
    email = data.email
    password = data.password
    username = data.username
    
    try:
        logger.info(f"Starting signup for: {email}")
        
        # Use Firebase Admin to create user
        user_record = admin_auth.create_user(
            email=email,
            password=password,
            display_name=username
        )
        
        logger.info(f"Firebase user created: {user_record.uid}")
        
        # Store user data in Firestore
        db = get_db()
        user_data = {
            "email": email,
            "username": username,
            "light_timeout_seconds": 600,  # Default 10 minutes in seconds
            "auto_timeout_enabled": True,   # Auto-timeout enabled by default
            "account_created": firestore.SERVER_TIMESTAMP
        }
        
        db.collection("users").document(user_record.uid).set(user_data)
        logger.info(f"User data stored in Firestore for: {email}")
        
        return {
            "message": "User created successfully", 
            "user_id": user_record.uid,
            "email": email
        }
    except admin_auth.EmailAlreadyExistsError:
        logger.error(f"Email already exists: {email}")
        raise HTTPException(status_code=400, detail="This email already exists")
    except Exception as e:
        logger.error(f"Signup error for {email}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error: Failed to create user. {str(e)}")

@app.post("/login")
def user_login(data: LoginRequest): 
    try:
        logger.info(f"Login attempt for: {data.email}")
        
        db = get_db()
        users = db.collection("users").where("email", "==", data.email).stream()
        user_doc = next(users, None)
        if not user_doc:
            raise HTTPException(status_code=401, detail="Invalid credentials")
        
        user_id = user_doc.id
        
        try:
            custom_token = admin_auth.create_custom_token(user_id)
            logger.info(f"User logged in successfully: {data.email}")
            
            return {
                "message": "Login successful", 
                "user": {
                    "localId": user_id,
                    "email": data.email,
                    "idToken": custom_token.decode('utf-8'),
                    "expiresIn": "3600"
                }
            }
        except Exception as e:
            logger.error(f"Token creation error: {str(e)}")
            raise HTTPException(status_code=500, detail="Login failed")
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected login error: {str(e)}")
        raise HTTPException(status_code=500, detail="Login failed")

@app.post("/light/control")
async def control_light(command: LightCommand):  
    if command.status not in ("ON", "OFF"):
        raise HTTPException(status_code=400, detail="Invalid status, must be 'ON' or 'OFF'")

    try:
        db = get_db()
        users = db.collection("users").where("email", "==", command.email).stream()
        user_doc = next(users, None)
        if not user_doc:
            raise HTTPException(status_code=404, detail="User not found")

        user_id = user_doc.id
        user_data = user_doc.to_dict()
        user_doc_ref = db.collection("users").document(user_id).collection("light").document("status")
        
        update_data = {"status": command.status}
        
        if command.status == "ON":
            # Light is being turned ON - set timestamp
            update_data["timestamp"] = get_current_utc_datetime()
            update_data["auto_turned_off"] = False
            
            # Only schedule auto turn-off if auto-timeout is enabled
            if user_data.get("auto_timeout_enabled", True):
                timeout_seconds = user_data.get("light_timeout_seconds", 600)  # Default 10 minutes
                await timeout_manager.schedule_light_turnoff(command.email, user_id, timeout_seconds)
                logger.info(f"Light for {command.email} turned ON with auto-timeout in {timeout_seconds} seconds")
            else:
                logger.info(f"Light for {command.email} turned ON without auto-timeout")
            
        elif command.status == "OFF":
            # Light is being turned OFF manually - cancel any scheduled turn-off
            await timeout_manager.cancel_timeout(command.email)
            update_data["manually_turned_off"] = True
            update_data["turned_off_at"] = get_current_utc_datetime()
            logger.info(f"Light for {command.email} turned OFF manually")

        user_doc_ref.set(update_data)

        return {"message": f"Light turned {command.status} for {command.email}"}
    except Exception as e:
        logger.error(f"Error controlling light: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# Replace your get_light_status endpoint with this debug version temporarily
@app.get("/light/status")
def get_light_status(email: str = Query(None)): 
    # Return debug info directly in the response so you can see it immediately
    debug_info = {
        "debug": {
            "received_email": email,
            "email_type": str(type(email)),
            "email_is_none": email is None,
            "email_length": len(email) if email else 0,
            "raw_email_repr": repr(email),
        }
    }
    
    # If no email provided, return debug info with error
    if not email:
        debug_info["error"] = "No email parameter received"
        debug_info["status_code"] = 422
        return debug_info
    
    try:
        db = get_db()
        users = db.collection("users").where("email", "==", email).stream()
        user_doc = next(users, None)
        if not user_doc:
            debug_info["error"] = f"User not found with email: {email}"
            debug_info["status_code"] = 404
            return debug_info

        user_id = user_doc.id
        user_data = user_doc.to_dict()
        doc_ref = db.collection("users").document(user_id).collection("light").document("status")
        doc = doc_ref.get()

        if doc.exists:
            data = doc.to_dict()
            
            # Add auto-timeout information
            auto_timeout_enabled = user_data.get("auto_timeout_enabled", True)
            data["auto_timeout_enabled"] = auto_timeout_enabled
            
            # If light is ON and auto-timeout is enabled, calculate remaining time
            if data.get("status") == "ON" and auto_timeout_enabled and data.get("timestamp"):
                timeout_seconds = user_data.get("light_timeout_seconds", 600)
                timestamp = ensure_timezone_aware(data["timestamp"])
                current_time = get_current_utc_datetime()
                elapsed_seconds = (current_time - timestamp).total_seconds()
                remaining_seconds = max(0, timeout_seconds - elapsed_seconds)
                
                data["timeout_info"] = {
                    "total_timeout_seconds": timeout_seconds,
                    "elapsed_seconds": int(elapsed_seconds),
                    "remaining_seconds": int(remaining_seconds),
                    "will_turn_off_at": (timestamp + timedelta(seconds=timeout_seconds)).isoformat()
                }
            
            # Add debug info to successful response
            data["debug"] = debug_info["debug"]
            return data
        else:
            result = {
                "status": "OFF", 
                "message": "No previous light data found",
                "auto_timeout_enabled": user_data.get("auto_timeout_enabled", True),
                "debug": debug_info["debug"]
            }
            return result
            
    except Exception as e:
        debug_info["error"] = f"Exception occurred: {str(e)}"
        debug_info["status_code"] = 500
        return debug_info

# Also add a simple test endpoint
@app.get("/test-simple")
def test_simple(email: str = Query(None)):
    """Very simple test endpoint"""
    return {
        "message": "Test endpoint reached",
        "email_received": email,
        "email_type": str(type(email)) if email else "None",
        "timestamp": get_current_utc_datetime().isoformat()
    }

@app.put("/light/timeout")
async def set_light_timeout(timeout_data: TimeoutRequest):
    """Set the light timeout with hours, minutes, and seconds for a user"""
    try:
        # Calculate total seconds
        total_seconds = calculate_total_seconds(
            timeout_data.hours, 
            timeout_data.minutes, 
            timeout_data.seconds
        )
        
        if total_seconds == 0:
            raise ValueError('Total timeout must be greater than 0 seconds')
        if total_seconds > 86400: 
            raise ValueError('Total timeout cannot exceed 24 hours')
        
        db = get_db()
        users = db.collection("users").where("email", "==", timeout_data.email).stream()
        user_doc = next(users, None)
        if not user_doc:
            raise HTTPException(status_code=404, detail="User not found")

        user_id = user_doc.id
        user_data = user_doc.to_dict()
        user_doc_ref = db.collection("users").document(user_id)
        
        # Update the timeout
        user_doc_ref.update({
            "light_timeout_seconds": total_seconds,
            "timeout_updated": firestore.SERVER_TIMESTAMP
        })
        
        # If light is currently ON and auto-timeout is enabled, reschedule the turn-off with new timeout
        if user_data.get("auto_timeout_enabled", True):
            light_ref = db.collection("users").document(user_id).collection("light").document("status")
            light_doc = light_ref.get()
            
            if light_doc.exists and light_doc.to_dict().get("status") == "ON":
                light_data = light_doc.to_dict()
                timestamp = ensure_timezone_aware(light_data.get("timestamp"))
                
                if timestamp:
                    current_time = get_current_utc_datetime()
                    elapsed_seconds = (current_time - timestamp).total_seconds()
                    remaining_seconds = max(0, total_seconds - elapsed_seconds)
                    
                    if remaining_seconds > 0:
                        await timeout_manager.schedule_light_turnoff(timeout_data.email, user_id, remaining_seconds)
                    else:
                        # Timeout has already passed, turn off immediately
                        await timeout_manager._turn_off_light(timeout_data.email, user_id)
        
        timeout_display = format_timeout_display(total_seconds)
        logger.info(f"Light timeout for {timeout_data.email} set to {timeout_display}")
        
        return {
            "message": f"Light timeout set to {timeout_display} for {timeout_data.email}",
            "timeout": {
                "hours": timeout_data.hours or 0,
                "minutes": timeout_data.minutes or 0,
                "seconds": timeout_data.seconds or 0,
                "total_seconds": total_seconds,
                "display": timeout_display
            }
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error setting light timeout: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/light/timeout")
def get_light_timeout(email: str):
    """Get the current light timeout setting for a user"""
    try:
        db = get_db()
        users = db.collection("users").where("email", "==", email).stream()
        user_doc = next(users, None)
        if not user_doc:
            raise HTTPException(status_code=404, detail="User not found")

        user_data = user_doc.to_dict()
        
        # Handle both old format (minutes) and new format (seconds)
        if "light_timeout_seconds" in user_data:
            total_seconds = user_data["light_timeout_seconds"]
        elif "light_timeout" in user_data:
            # Convert old minutes format to seconds
            total_seconds = user_data["light_timeout"] * 60
        else:
            total_seconds = 600  # Default 10 minutes
        
        # Convert back to hours, minutes, seconds
        hours = total_seconds // 3600
        remaining_seconds = total_seconds % 3600
        minutes = remaining_seconds // 60
        seconds = remaining_seconds % 60
        
        timeout_display = format_timeout_display(total_seconds)
        auto_timeout_enabled = user_data.get("auto_timeout_enabled", True)
        
        return {
            "email": email,
            "auto_timeout_enabled": auto_timeout_enabled,
            "timeout": {
                "hours": hours,
                "minutes": minutes,
                "seconds": seconds,
                "total_seconds": total_seconds,
                "display": timeout_display
            },
            "message": f"Current light timeout is {timeout_display} ({'enabled' if auto_timeout_enabled else 'disabled'})"
        }
    except Exception as e:
        logger.error(f"Error getting light timeout: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/light/auto-timeout")
async def toggle_auto_timeout(toggle_data: AutoTimeoutToggleRequest):
    """Enable or disable auto-timeout for a user's lights"""
    try:
        db = get_db()
        users = db.collection("users").where("email", "==", toggle_data.email).stream()
        user_doc = next(users, None)
        if not user_doc:
            raise HTTPException(status_code=404, detail="User not found")

        user_id = user_doc.id
        user_doc_ref = db.collection("users").document(user_id)
        
        # Update the auto-timeout setting
        user_doc_ref.update({
            "auto_timeout_enabled": toggle_data.enabled,
            "auto_timeout_updated": firestore.SERVER_TIMESTAMP
        })
        
        if not toggle_data.enabled:
            # If disabling auto-timeout, cancel any active timeout for this user
            await timeout_manager.cancel_timeout(toggle_data.email)
            logger.info(f"Auto-timeout disabled and cancelled for {toggle_data.email}")
        else:
            # If enabling auto-timeout and light is currently ON, schedule turn-off
            user_data = user_doc.to_dict()
            light_ref = db.collection("users").document(user_id).collection("light").document("status")
            light_doc = light_ref.get()
            
            if light_doc.exists and light_doc.to_dict().get("status") == "ON":
                light_data = light_doc.to_dict()
                timestamp = ensure_timezone_aware(light_data.get("timestamp"))
                
                if timestamp:
                    timeout_seconds = user_data.get("light_timeout_seconds", 600)
                    current_time = get_current_utc_datetime()
                    elapsed_seconds = (current_time - timestamp).total_seconds()
                    remaining_seconds = max(0, timeout_seconds - elapsed_seconds)
                    
                    if remaining_seconds > 0:
                        await timeout_manager.schedule_light_turnoff(toggle_data.email, user_id, remaining_seconds)
                    else:
                        # Timeout has already passed, turn off immediately
                        await timeout_manager._turn_off_light(toggle_data.email, user_id)
            
            logger.info(f"Auto-timeout enabled for {toggle_data.email}")
        
        status = "enabled" if toggle_data.enabled else "disabled"
        return {
            "message": f"Auto-timeout {status} for {toggle_data.email}",
            "auto_timeout_enabled": toggle_data.enabled
        }
    except Exception as e:
        logger.error(f"Error toggling auto-timeout: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/light/auto-timeout")
def get_auto_timeout_status(email: str):
    """Get the auto-timeout status for a user"""
    try:
        db = get_db()
        users = db.collection("users").where("email", "==", email).stream()
        user_doc = next(users, None)
        if not user_doc:
            raise HTTPException(status_code=404, detail="User not found")

        user_data = user_doc.to_dict()
        auto_timeout_enabled = user_data.get("auto_timeout_enabled", True)
        
        return {
            "email": email,
            "auto_timeout_enabled": auto_timeout_enabled,
            "message": f"Auto-timeout is {'enabled' if auto_timeout_enabled else 'disabled'} for {email}"
        }
    except Exception as e:
        logger.error(f"Error getting auto-timeout status: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
def health_check():
    return {"status": "healthy", "timestamp": get_current_utc_datetime().isoformat()}

@app.get("/debug/timeouts")
async def debug_timeouts():
    """Debug endpoint to see active timeout tasks"""
    async with timeout_manager.lock:
        active_emails = list(timeout_manager.active_tasks.keys())
    
    return {
        "active_timeout_tasks": len(active_emails),
        "emails_with_active_timeouts": active_emails,
        "monitoring_active": timeout_manager.is_running
    }

# Firebase Functions entry point
@https_fn.on_request(
    timeout_sec=60,    
    memory=256,        
    max_instances=10 
)
def apiEntrypoint(request: Request) -> Response:
    try:
        from fastapi.testclient import TestClient
        
        # Initialize Firebase early
        logger.info(f"Processing request: {request.method} {request.path}")
        get_db()
        
        # Use TestClient to handle the request
        client = TestClient(app)
        
        # Extract request data
        method = request.method.upper()
        path = request.path or "/"
        query_string = request.query_string or ""
        headers = dict(request.headers) if request.headers else {}
        data = request.get_data() or b""
        
        # Build full URL
        url = path
        if query_string:
            url += f"?{query_string}"
        
        # Make request to FastAPI app
        if method == "GET":
            response = client.get(url, headers=headers)
        elif method == "POST":
            response = client.post(url, content=data, headers=headers)
        elif method == "PUT":
            response = client.put(url, content=data, headers=headers)
        else:
            response = client.request(method, url, content=data, headers=headers)
        
        logger.info(f"Response status: {response.status_code}")
        
        return Response(
            response=response.content,
            status=response.status_code,
            headers=dict(response.headers)
        )
        
    except Exception as e:
        logger.error(f"Error in API entrypoint: {str(e)}")
        import traceback
        logger.error(f"Full traceback: {traceback.format_exc()}")
        
        return Response(
            response=json.dumps({"error": f"Internal server error: {str(e)}"}),
            status=500,
            headers={'Content-Type': 'application/json'}
        )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)