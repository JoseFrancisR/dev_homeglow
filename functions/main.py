# main.py

# Setup root logger FIRST — for Cloud Functions & Cloud Run compatibility
import logging

logging.basicConfig(
    level=logging.INFO,  # Change to logging.DEBUG for full verbose logs
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger()  # Use root logger

# Optional: force propagate for uvicorn loggers (for local + Cloud Run cases)
uvicorn_logger = logging.getLogger("uvicorn")
uvicorn_logger.propagate = True
uvicorn_logger.setLevel(logging.INFO)

# Now import everything else AFTER logger is configured
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routes import lights
from routes import scheduler, timer, energy_monitory, device_register, arduino_check, pair, device_info, notification_settings
from core.timeout_manager import timeout_manager
from firebase_functions import https_fn, scheduler_fn
from firebase_functions.https_fn import Request, Response
from fastapi.testclient import TestClient
import json
from cloud.light_timeout_checker import scheduled_light_timeout_checker
from cloud.light_wake_sleep_scheduler import scheduled_light_wake_sleep_checker

# Create FastAPI app
app = FastAPI(title="Light Control API", docs_url=None)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Contains the endpoints of the API
app.include_router(lights.router, prefix="/light", tags=["Light Controls"])
app.include_router(scheduler.router, prefix="/light", tags=["Light Schedule"])
app.include_router(timer.router, tags=["Timer"])
app.include_router(energy_monitory.router, tags=["Energy Monitor"])
app.include_router(device_register.router, tags=["Device Register"])
app.include_router(arduino_check.router, tags=["Arduino LED Check"])
app.include_router(pair.router, tags=["Device Pairing"])
app.include_router(device_info.router, tags=["Device Info"])
app.include_router(notification_settings.router, tags=["Notification Settings"])

@app.middleware("http")
async def log_requests(request, call_next):
    logger.info(f"🚀 Incoming request: {request.method} {request.url}")
    logger.info(f"Headers: {dict(request.headers)}")
    try:
        response = await call_next(request)
        logger.info(f"✅ Response status: {response.status_code} for {request.url}")
        return response
    except Exception as e:
        logger.error(f"❌ Exception while processing request {request.url}: {str(e)}")
        raise e

@app.on_event("startup")
async def startup_event():
    await timeout_manager.start_monitoring()

@app.on_event("shutdown")
async def shutdown_event():
    await timeout_manager.stop_monitoring()

# Firebase Functions HTTP entrypoint
@https_fn.on_request(timeout_sec=60, memory=256, max_instances=10)
def apiEntrypoint(request: Request) -> Response:
    logger.info(f"Received request: {request.method} {request.path}")
    from core.firebase import get_db
    get_db()

    client = TestClient(app)

    method = request.method.upper()
    path = request.path or "/"
    if path.startswith("/apiEntrypoint"):
        path = path[len("/apiEntrypoint"):]

    # Safe query_string handling
    query_string = ""
    if hasattr(request, "args") and request.args:
        query_string = "&".join(
            f"{key}={str(value)}"
            for key in request.args
            for value in request.args.getlist(key)
        )
    elif hasattr(request, "query_string") and request.query_string:
        query_string = request.query_string.decode() if isinstance(request.query_string, bytes) else str(request.query_string)
    elif hasattr(request, "url") and "?" in str(request.url):
        query_string = str(request.url).split("?", 1)[1]
    elif hasattr(request, "environ") and "QUERY_STRING" in request.environ:
        query_string = request.environ["QUERY_STRING"]

    full_url = path + (f"?{query_string}" if query_string else "")
    data = request.get_data() if hasattr(request, "get_data") else request.data or b""
    headers = dict(request.headers) if hasattr(request, "headers") else {}

    try:
        if method == "GET":
            response = client.get(full_url, headers=headers)
        elif method == "POST":
            response = client.post(full_url, headers=headers, content=data)
        elif method == "PUT":
            response = client.put(full_url, headers=headers, content=data)
        elif method == "DELETE":
            response = client.delete(full_url, headers=headers, content=data)
        else:
            response = client.request(method, full_url, headers=headers, content=data)

        safe_headers = {k: str(v) for k, v in response.headers.items()}

        return Response(
            response=response.content,
            status=response.status_code,
            headers=safe_headers,
        )
    except Exception as e:
        logger.error(f"FastAPI processing error: {str(e)}")
        return Response(
            response=json.dumps({"error": f"Internal server error: {str(e)}"}),
            status=500,
            headers={"Content-Type": "application/json"},
        )

# Scheduler functions for timeout, wake/sleep, and notifications
@scheduler_fn.on_schedule(schedule="every 1 minutes")
def run_light_timeout_checker(event):
    logger.info("⏰ Cloud Scheduler: Running scheduled_light_timeout_checker...")
    import asyncio
    asyncio.run(scheduled_light_timeout_checker())

@scheduler_fn.on_schedule(schedule="every 1 minutes")
def run_light_wake_sleep_checker(event):
    logger.info("⏰ Cloud Scheduler: Running scheduled_light_wake_sleep_checker...")
    import asyncio
    try:
        asyncio.run(scheduled_light_wake_sleep_checker())
    except Exception as e:
        logger.error(f"❌ Exception in scheduled_light_wake_sleep_checker: {e}", exc_info=True)

# Debug print all routes
for route in app.routes:
    print(route.path, route.methods)

# Local test runner
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
