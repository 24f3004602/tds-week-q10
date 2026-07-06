import os
import time
import uuid
from collections import defaultdict

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

# ── Assigned values ──
ASSIGNED_ORIGIN = "https://app-08d5ki.example.com"
RATE_LIMIT = 10
WINDOW_SECONDS = 10

# Build allowlist: assigned origin + exam page origin (from env var)
EXAM_ORIGIN = os.getenv("EXAM_ORIGIN", "")
ALLOWED_ORIGINS = [ASSIGNED_ORIGIN]
if EXAM_ORIGIN:
    ALLOWED_ORIGINS.append(EXAM_ORIGIN)

# ── Middleware 1: Request Context (innermost) ──
@app.middleware("http")
async def request_context_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID")
    if not request_id:
        request_id = str(uuid.uuid4())
    request.state.request_id = request_id

    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response

# ── Middleware 2: Per-Client Rate Limiting ──
buckets = defaultdict(lambda: {"start": 0.0, "count": 0})

@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    if request.method == "OPTIONS":
        return await call_next(request)

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
            headers={"Retry-After": str(retry_after)},
        )
    else:
        bucket["count"] += 1

    return await call_next(request)

# ── Middleware 3: CORS (outermost) ──
# Using FastAPI's built-in CORSMiddleware is more reliable than raw ASGI
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "OPTIONS"],
    allow_headers=["X-Request-ID", "X-Client-Id", "Content-Type"],
    expose_headers=["X-Request-ID"],
)

# ── Endpoint ──
@app.get("/ping")
def ping(request: Request):
    return {
        "email": os.getenv("USER_EMAIL", "user@example.com"),
        "request_id": request.state.request_id,
    }
