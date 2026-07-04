import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, APIRouter
from fastapi.middleware.cors import CORSMiddleware

from backend.app.config import settings
from backend.app.redis_client import init_redis, close_redis
from backend.app.api.websocket import redis_subscribe_loop
from backend.app.db import engine, Base

# Import models to ensure they are registered for create_all
from backend.app.models import *
from backend.app.api import auth, orgs_projects, queues, jobs, dashboard, websocket

async def create_tables():
    async with engine.begin() as conn:
        # Create tables if not exists
        await conn.run_sync(Base.metadata.create_all)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    print("[Lifespan] Initializing database schema...")
    await create_tables()
    print("[Lifespan] Initializing Redis Client...")
    await init_redis()
    
    # Run Redis listener in background
    listener_task = asyncio.create_task(redis_subscribe_loop())
    
    yield
    
    # Shutdown
    print("[Lifespan] Stopping Redis subscription loop...")
    listener_task.cancel()
    try:
        await listener_task
    except asyncio.CancelledError:
        pass
    print("[Lifespan] Closing Redis Client...")
    await close_redis()

app = FastAPI(
    title=settings.PROJECT_NAME,
    version="1.0.0",
    lifespan=lifespan
)

from fastapi import Request
from fastapi.responses import JSONResponse
import traceback
import time

@app.middleware("http")
async def log_requests(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    duration = time.time() - start_time
    print(f"[API Request] {request.method} {request.url.path} - Status: {response.status_code} ({duration:.3f}s)")
    return response

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    print(f"[CRITICAL ERROR] {request.method} {request.url.path} failed: {exc}")
    traceback.print_exc()
    return JSONResponse(
        status_code=500,
        content={"detail": "An internal server error occurred. Please contact system support."}
    )

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Base healthcheck route
@app.get("/")
async def health_check():
    return {
        "status": "healthy",
        "service": "Distributed Job Scheduler API",
        "timestamp": datetime.now(timezone.utc).isoformat() if 'datetime' in globals() else ""
    }
# Resolve datetime import
from datetime import datetime, timezone

# Router aggregation
v1_router = APIRouter(prefix="/api/v1")
v1_router.include_router(auth.router)
v1_router.include_router(orgs_projects.router)
v1_router.include_router(queues.router)
v1_router.include_router(jobs.router)
v1_router.include_router(dashboard.router)
v1_router.include_router(websocket.router)

app.include_router(v1_router)

# Reload trigger comment to refresh Uvicorn reloader process
