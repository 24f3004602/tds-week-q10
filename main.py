import os
import time
import uuid
from collections import defaultdict

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI()

# ── Assigned values ──
ASSIGNED_ORIGIN = "https://app-08d5ki.example.com"
RATE_LIMIT = 10          # requests per window
WINDOW_SECONDS = 10        # seconds

# Optional: set EXAM_ORIGIN env var if the exam page origin differs from the assigned one
ALLOWED_ORIGINS = [ASSIGNED_ORIGIN]
_exam_origin = os.getenv("EXAM_ORIGIN")
if _exam_origin:
    ALLOWED_ORIGINS.append(_exam_origin)

# ── In-memory rate-limit buckets: client_id -> {start, count} ──
buckets = defaultdict(lambda: {"start": 0.0, "count": 0})

# ── Middleware 1: Request Context (innermost) ──
@app.middleware("http")
async def request_context_middleware(request: Request, call_next):
    # Reuse inbound X-Request-ID or generate a fresh UUID4
    request_id = request.headers.get("X-Request-ID")
    if not request_id:
        request_id = str(uuid.uuid4())
    request.state.request_id = request_id

    response = await call_next(request)
    # Propagate back in response header
    response.headers["X-Request-ID"] = request_id
    return response

# ── Middleware 2: Per-Client Rate Limiting ──
@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    if request.method == "OPTIONS":
        return await call_next(request)

    client_id = request.headers.get("X-Client-Id", "default")
    now = time.time()
    bucket = buckets[client_id]

    # Fixed-window reset
    if now - bucket["start"] >= WINDOW_SECONDS:
        bucket["start"] = now
        bucket["count"] = 1
    elif bucket["count"] >= RATE_LIMIT:
        retry_after = int(WINDOW_SECONDS - (now - bucket["start"])) + 1
        return JSONResponse(
            status_code=429,
            content={"detail": "Rate limit exceeded"},
            headers={"Retry-After": str(retry_after)},
        )
    else:
        bucket["count"] += 1

    return await call_next(request)

# ── Middleware 3: Scoped CORS (outermost) ──
@app.middleware("http")
async def cors_middleware(request: Request, call_next):
    origin = request.headers.get("Origin")

    # Preflight handling
    if request.method == "OPTIONS":
        response = JSONResponse(content={})
        if origin in ALLOWED_ORIGINS:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
            response.headers["Access-Control-Allow-Headers"] = "X-Request-ID, X-Client-Id, Content-Type"
            response.headers["Access-Control-Expose-Headers"] = "X-Request-ID"
            response.headers["Access-Control-Max-Age"] = "86400"
            response.headers["Vary"] = "Origin"
        return response

    response = await call_next(request)

    if origin in ALLOWED_ORIGINS:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Expose-Headers"] = "X-Request-ID"
        response.headers["Vary"] = "Origin"

    return response

# ── Endpoint ──
@app.get("/ping")
def ping(request: Request):
    return {
        "email": os.getenv("USER_EMAIL", "user@example.com"),
        "request_id": request.state.request_id,
    }
