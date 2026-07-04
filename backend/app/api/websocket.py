import json
import asyncio
from typing import Dict, List, Union
from uuid import UUID
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from backend.app.redis_client import redis_client, IS_REDIS_AVAILABLE

router = APIRouter(prefix="/ws", tags=["websockets"])

class ConnectionManager:
    def __init__(self):
        # Key: channel name (e.g. "job:status:UUID"), Value: list of WebSockets
        self.active_connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, channel: str):
        await websocket.accept()
        if channel not in self.active_connections:
            self.active_connections[channel] = []
        self.active_connections[channel].append(websocket)

    def disconnect(self, websocket: WebSocket, channel: str):
        if channel in self.active_connections:
            if websocket in self.active_connections[channel]:
                self.active_connections[channel].remove(websocket)
            if not self.active_connections[channel]:
                del self.active_connections[channel]

    async def broadcast(self, channel: str, message: dict):
        if channel in self.active_connections:
            # Create a copy of connections to avoid modification issues during iteration
            for connection in list(self.active_connections[channel]):
                try:
                    await connection.send_json(message)
                except Exception:
                    self.disconnect(connection, channel)

# Connection Managers
ws_manager = ConnectionManager()

# Helper publication functions
async def publish_job_status(job_id: Union[str, UUID], status: str):
    channel = f"job:status:{job_id}"
    message = {"type": "status_update", "job_id": str(job_id), "status": status}
    
    # Send locally (for instant SQLite/In-memory fallback clients)
    await ws_manager.broadcast(channel, message)
    
    # Publish to Redis if available
    if IS_REDIS_AVAILABLE and redis_client:
        try:
            await redis_client.publish(channel, json.dumps(message))
        except Exception as e:
            print(f"[ERROR] Failed publishing status to Redis: {e}")

async def publish_job_log(job_id: Union[str, UUID], level: str, message_text: str):
    channel = f"job:logs:{job_id}"
    message = {
        "type": "log_line", 
        "job_id": str(job_id), 
        "level": level, 
        "message": message_text,
        "ts": datetime.utcnow().isoformat() if 'datetime' in globals() else ""
    }
    # Add datetime handling locally
    from datetime import datetime
    message["ts"] = datetime.utcnow().isoformat()
    
    # Send locally
    await ws_manager.broadcast(channel, message)
    
    # Publish to Redis if available
    if IS_REDIS_AVAILABLE and redis_client:
        try:
            await redis_client.publish(channel, json.dumps(message))
        except Exception as e:
            print(f"[ERROR] Failed publishing log to Redis: {e}")

async def publish_dashboard_update(project_id: Union[str, UUID]):
    channel = f"dashboard:{project_id}"
    message = {"type": "dashboard_refresh", "project_id": str(project_id)}
    
    # Send locally
    await ws_manager.broadcast(channel, message)
    
    # Publish to Redis if available
    if IS_REDIS_AVAILABLE and redis_client:
        try:
            await redis_client.publish(channel, json.dumps(message))
        except Exception as e:
            print(f"[ERROR] Failed publishing dashboard update to Redis: {e}")

# WebSockets Router

@router.websocket("/jobs/{job_id}/logs")
async def websocket_job_logs(websocket: WebSocket, job_id: str):
    # Channel contains both logs and status updates for a single job
    channel_status = f"job:status:{job_id}"
    channel_logs = f"job:logs:{job_id}"
    
    await websocket.accept()
    
    # We add to status and log channels locally
    if channel_status not in ws_manager.active_connections:
        ws_manager.active_connections[channel_status] = []
    ws_manager.active_connections[channel_status].append(websocket)
    
    if channel_logs not in ws_manager.active_connections:
        ws_manager.active_connections[channel_logs] = []
    ws_manager.active_connections[channel_logs].append(websocket)
    
    try:
        while True:
            # Just keep connection alive, read client messages if any
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        ws_manager.disconnect(websocket, channel_status)
        ws_manager.disconnect(websocket, channel_logs)

@router.websocket("/dashboard")
async def websocket_dashboard(websocket: WebSocket, project_id: str):
    channel = f"dashboard:{project_id}"
    await ws_manager.connect(websocket, channel)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        ws_manager.disconnect(websocket, channel)

# Background Subscriber for Redis
async def redis_subscribe_loop():
    """
    Subscribes to Redis channels and pipes updates to local connection manager.
    """
    if not IS_REDIS_AVAILABLE or not redis_client:
        return
        
    pubsub = redis_client.pubsub()
    try:
        # Subscribe to pattern
        await pubsub.psubscribe("job:*", "dashboard:*")
        print("[INFO] Redis Pub/Sub background listener started.")
        
        async for message in pubsub.listen():
            if message["type"] == "pmessage":
                channel = message["channel"]
                try:
                    data = json.loads(message["data"])
                    await ws_manager.broadcast(channel, data)
                except Exception as e:
                    pass
    except asyncio.CancelledError:
        pass
    except Exception as e:
        print(f"[ERROR] Redis listener encountered error: {e}")
    finally:
        await pubsub.punsubscribe()
        await pubsub.close()
