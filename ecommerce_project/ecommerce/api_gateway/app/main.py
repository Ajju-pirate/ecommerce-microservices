from fastapi import FastAPI, Request, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
import httpx
import os
import time
from collections import defaultdict
from typing import Optional

app = FastAPI(title="API Gateway", version="1.0.0",
              description="Central entry point for all e-commerce services")

# ── CORS — allows the frontend to talk to this gateway ────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # In production: restrict to your frontend domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Service URLs (injected via environment variables) ─────────────────────
USER_URL      = os.getenv("USER_SERVICE_URL",      "http://localhost:8001")
CATALOG_URL   = os.getenv("CATALOG_SERVICE_URL",   "http://localhost:8002")
WAREHOUSE_URL = os.getenv("WAREHOUSE_SERVICE_URL", "http://localhost:8003")
ORDER_URL     = os.getenv("ORDER_SERVICE_URL",     "http://localhost:8004")

# ── Simple in-memory rate limiter ─────────────────────────────────────────
# Key: client IP, Value: list of timestamps of recent requests
request_log: dict = defaultdict(list)
RATE_LIMIT = 60          # max requests
RATE_WINDOW = 60         # per N seconds


def check_rate_limit(client_ip: str):
    now = time.time()
    window_start = now - RATE_WINDOW
    # Keep only requests within the window
    request_log[client_ip] = [t for t in request_log[client_ip] if t > window_start]
    if len(request_log[client_ip]) >= RATE_LIMIT:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded: {RATE_LIMIT} requests per {RATE_WINDOW}s"
        )
    request_log[client_ip].append(now)


async def proxy(request: Request, target_url: str, strip_prefix: str = ""):
    """
    Forward any incoming request to the target service.
    strip_prefix removes a path prefix before forwarding.
    e.g. /catalog/products → /products when strip_prefix="/catalog"
    """
    client_ip = request.client.host
    check_rate_limit(client_ip)

    # Strip the gateway prefix so the downstream service gets the right path
    path = str(request.url.path)
    if strip_prefix and path.startswith(strip_prefix):
        path = path[len(strip_prefix):]
    if not path.startswith("/"):
        path = "/" + path

    async with httpx.AsyncClient(timeout=10.0) as client:
        url = target_url + path + (
            "?" + str(request.url.query) if request.url.query else ""
        )
        headers = dict(request.headers)
        headers.pop("host", None)

        try:
            response = await client.request(
                method=request.method,
                url=url,
                headers=headers,
                content=await request.body(),
            )
            from fastapi.responses import Response
            return Response(
                content=response.content,
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type=response.headers.get("content-type")
            )
        except httpx.RequestError as e:
            raise HTTPException(status_code=503, detail=f"Service unavailable: {str(e)}")
# ── Auth verification helper ──────────────────────────────────────────────

async def verify_token_with_user_service(token: str) -> dict:
    """Ask User Service if this token is valid. Returns user info."""
    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            resp = await client.post(
                f"{USER_URL}/verify-token",
                json={"token": token}
            )
            if resp.status_code != 200:
                raise HTTPException(status_code=401, detail="Invalid token")
            return resp.json()
        except httpx.RequestError:
            raise HTTPException(status_code=503, detail="Auth service unavailable")


# ── PUBLIC routes (no auth required) ─────────────────────────────────────

@app.api_route("/auth/{path:path}", methods=["GET","POST","PUT","PATCH","DELETE"])
async def auth_routes(request: Request):
    """Public auth routes — register and login, no token required."""
    return await proxy(request, USER_URL, strip_prefix="/auth")

@app.api_route("/catalog/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def browse_catalog(request: Request):
    """Anyone can browse the catalog without logging in."""
    return await proxy(request, CATALOG_URL, strip_prefix="/catalog")

# ── PROTECTED routes (JWT required) ──────────────────────────────────────

@app.api_route("/warehouse/{path:path}", methods=["GET","POST","PUT","PATCH","DELETE"])
async def warehouse_routes(request: Request, authorization: Optional[str] = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header required")
    token = authorization.replace("Bearer ", "")
    await verify_token_with_user_service(token)
    return await proxy(request, WAREHOUSE_URL, strip_prefix="/warehouse")



@app.api_route("/orders/{path:path}", methods=["GET","POST","PUT","PATCH","DELETE"])
@app.api_route("/orders", methods=["GET","POST"])
async def order_routes(request: Request, authorization: Optional[str] = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header required")
    token = authorization.replace("Bearer ", "")
    await verify_token_with_user_service(token)
    return await proxy(request, ORDER_URL, strip_prefix="/orders")

# ── Health check ──────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    """Check all downstream services are up."""
    statuses = {}
    async with httpx.AsyncClient(timeout=3.0) as client:
        for name, url in [
            ("user_service", USER_URL),
            ("catalog_service", CATALOG_URL),
            ("warehouse_service", WAREHOUSE_URL),
            ("order_service", ORDER_URL),
        ]:
            try:
                r = await client.get(f"{url}/health")
                statuses[name] = "ok" if r.status_code == 200 else "degraded"
            except Exception:
                statuses[name] = "down"
    return {"gateway": "ok", "services": statuses}
