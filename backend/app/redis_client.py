import redis.asyncio as aioredis
from backend.app.config import settings

# Global Redis Client
redis_client = None
IS_REDIS_AVAILABLE = False

async def init_redis():
    global redis_client, IS_REDIS_AVAILABLE
    try:
        redis_client = aioredis.from_url(
            settings.REDIS_URL, 
            encoding="utf-8", 
            decode_responses=True,
            socket_connect_timeout=1.0
        )
        # Ping to check connection
        await redis_client.ping()
        IS_REDIS_AVAILABLE = True
        print("[INFO] Redis connection successful. Using Redis Pub/Sub.")
    except Exception as e:
        IS_REDIS_AVAILABLE = False
        redis_client = None
        print(f"[WARNING] Redis is not running: {e}. Falling back to In-Memory Pub/Sub.")

async def close_redis():
    global redis_client
    if redis_client:
        await redis_client.close()
