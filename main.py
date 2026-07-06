import os
import time
import uuid
from collections import defaultdict

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI()

# ── Config ──
ASSIGNED_ORIGIN = "https://app-08d5ki.example.com"
EXAM_ORIGIN = "https://exam.sanand.workers.dev"
RATE_LIMIT = 10
WINDOW_SECONDS = 10

ALLOWED_ORIGINS = {ASSIGNED_ORIGIN, EXAM_ORIGIN}

# ── Rate limit buckets: client_id -> {start, count} ──
buckets = defaultdict(lambda: {"start": 0.0, "count": 0})

# ── Single middleware: CORS (outermost) + Rate Limit + Request Context ──
@app.middleware("http")
async def middleware_stack(request: Request, call_next):
    origin = request.headers.get("Origin")
    request_id = request.headers.get("X-Request-ID")
    if not request_id:
        request_id = str(uuid.uuid4())
    request.state.request_id = request_id

    # ── CORS Preflight ──
    if request.method == "OPTIONS":
        response = JSONResponse(content={})
        if origin in ALLOWED_ORIGINS:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
            response.headers["Access-Control-Allow-Headers"] = "X-Request-ID, X-Client-Id, Content-Type"
            response.headers["Access-Control-Expose-Headers"] = "X-Request-ID"
            response.headers["Vary"] = "Origin"
        return response

    # ── Rate Limiting (skip OPTIONS) ──
    client_id = request.headers.get("X-Client-Id", "default")
    now = time.time()
    bucket = buckets[client_id]

    rate_limited = False
    retry_after = 0

    if now - bucket["start"] >= WINDOW_SECONDS:
        bucket["start"] = now
        bucket["count"] = 1
    elif bucket["count"] >= RATE_LIMIT:
        rate_limited = True
        retry_after = int(WINDOW_SECONDS - (now - bucket["start"])) + 1
    else:
        bucket["count"] += 1

    if rate_limited:
        response = JSONResponse(
            status_code=429,
            content={"detail": "Rate limit exceeded"},
        )
        response.headers["Retry-After"] = str(retry_after)
    else:
        response = await call_next(request)

    # ── CORS headers on ALL responses (including 429) ──
    if origin in ALLOWED_ORIGINS:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Expose-Headers"] = "X-Request-ID, Retry-After"
        response.headers["Vary"] = "Origin"

    # ── Request ID in response header ──
    response.headers["X-Request-ID"] = request_id
    return response

@app.get("/ping")
def ping(request: Request):
    return {
        "email": os.getenv("USER_EMAIL", "user@example.com"),
        "request_id": request.state.request_id,
    }
