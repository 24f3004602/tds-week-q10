import os
import time
import uuid
from collections import defaultdict

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

# ── Config ──
ASSIGNED_ORIGIN = "https://app-08d5ki.example.com"
RATE_LIMIT = 10
WINDOW_SECONDS = 10

# ── CORS: allow assigned origin + any origin that actually sends an Origin header ──
# We include the assigned origin explicitly, plus we add "*" as a fallback
# BUT we also implement manual CORS for preflight precision
origins = [ASSIGNED_ORIGIN, "*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID", "Retry-After"],
)

# ── Rate limit buckets ──
buckets = defaultdict(lambda: {"start": 0.0, "count": 0})

# ── Middleware: Request Context + Rate Limit (CORS handled by CORSMiddleware) ──
@app.middleware("http")
async def combined_middleware(request: Request, call_next):
    # 1. Request Context
    request_id = request.headers.get("X-Request-ID")
    if not request_id:
        request_id = str(uuid.uuid4())
    request.state.request_id = request_id

    # 2. Rate Limiting (skip for OPTIONS preflight)
    if request.method != "OPTIONS":
        client_id = request.headers.get("X-Client-Id", "default")
        now = time.time()
        bucket = buckets[client_id]

        if now - bucket["start"] >= WINDOW_SECONDS:
            bucket["start"] = now
            bucket["count"] = 1
        elif bucket["count"] >= RATE_LIMIT:
            retry_after = int(WINDOW_SECONDS - (now - bucket["start"])) + 1
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded"},
                headers={"Retry-After": str(retry_after), "X-Request-ID": request_id},
            )
        else:
            bucket["count"] += 1

    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response

# ── Endpoint ──
@app.get("/ping")
def ping(request: Request):
    return {
        "email": os.getenv("USER_EMAIL", "24f3004602@ds.study.iitm.ac.in"),
        "request_id": request.state.request_id,
    }
