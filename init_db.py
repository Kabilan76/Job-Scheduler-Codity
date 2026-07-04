import asyncio
import os
import sys

# Ensure backend folder is in path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from backend.app.db import engine, Base
# Import models to ensure they are registered with Base.metadata
from backend.app.models import User, Organization, OrgMember, Project, RetryPolicy, Queue, Worker, Job, JobExecution, JobLog, DeadLetterQueue, WorkerHeartbeat, ScheduledJob

async def init_db():
    print("Initializing database...")
    async with engine.begin() as conn:
        # Drop all tables if we want clean slate during development
        # For development, we can create if they don't exist
        await conn.run_sync(Base.metadata.create_all)
    print("Database initialized successfully!")

if __name__ == "__main__":
    asyncio.run(init_db())
