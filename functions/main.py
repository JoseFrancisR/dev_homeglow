from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routes import lights
from routes import scheduler, timer, energy_monitory
from core.timeout_manager import timeout_manager
from firebase_functions import https_fn
from firebase_functions.https_fn import Request, Response
from fastapi.testclient import TestClient
import logging
import json


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(title="Light Control API", docs_url=None)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

#Contains the endpoints of the API
app.include_router(lights.router, prefix="/light", tags=["Light Controls"])
app.include_router(scheduler.router, prefix="/light", tags=["Light Schedule"])
app.include_router(timer.router, tags=["Timer"])
app.include_router(energy_monitory.router, tags=["Energy Monitor"])

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
    #Imported this first so that the database is set up immediately
    from core.firebase import get_db
    get_db()

    client = TestClient(app)

    # Added this because it think thats apiEntrypoint is the actual endpoint 
    method = request.method.upper()
    path = request.path or "/"
    if path.startswith("/apiEntrypoint"):
        path = path[len("/apiEntrypoint"):]

    # Handle query params
    query_string = ""
    if hasattr(request, "args") and request.args:
        query_string = "&".join(
            f"{key}={value}" for key in request.args for value in request.args.getlist(key)
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

    # Route the request to FastAPI
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

        return Response(
            response=response.content,
            status=response.status_code,
            headers=dict(response.headers),
        )
    except Exception as e:
        logger.error(f"FastAPI processing error: {str(e)}")
        return Response(
            response=json.dumps({"error": f"Internal server error: {str(e)}"}),
            status=500,
            headers={"Content-Type": "application/json"},
        )

# this is just to test it locally 
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
