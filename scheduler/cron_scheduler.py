import asyncio
import os
import sys
import signal
from datetime import datetime, timezone
from sqlalchemy.future import select
from sqlalchemy import update
from croniter import croniter

# Ensure backend folder is in path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.app.config import settings
from backend.app.db import engine, async_session_maker
from backend.app.models import ScheduledJob, Job
from backend.app.api.websocket import publish_job_status

class CronScheduler:
    def __init__(self):
        self.shutdown_requested = False

    async def run(self):
        # Register signals
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self.handle_signal)
            
        print("[Scheduler] Cron Scheduler Service started.")
        while not self.shutdown_requested:
            try:
                await self.tick()
            except Exception as e:
                print(f"[Scheduler] Error during tick: {e}")
                
            # Scan every 5 seconds
            await asyncio.sleep(5)
            
        print("[Scheduler] Cron Scheduler Service stopped.")

    def handle_signal(self):
        print("[Scheduler] Shutdown signal received. Stopping scheduler...")
        self.shutdown_requested = True

    async def tick(self):
        now = datetime.now(timezone.utc)
        async with async_session_maker() as session:
            # 1. Fetch active scheduled jobs where next_run_at <= now
            query = select(ScheduledJob).where(
                (ScheduledJob.is_active == True) & 
                (ScheduledJob.next_run_at <= now)
            )
            res = await session.execute(query)
            due_jobs = res.scalars().all()
            
            if not due_jobs:
                return
                
            print(f"[Scheduler] Found {len(due_jobs)} scheduled jobs due for execution.")
            
            for sched in due_jobs:
                try:
                    # 2. Spawn job row
                    tmpl = sched.job_template
                    
                    new_job = Job(
                        queue_id=tmpl["queue_id"],
                        project_id=sched.project_id,
                        type="immediate",  # Spawned instance runs immediately
                        payload=tmpl["payload"],
                        status="queued",
                        priority=tmpl.get("priority", 0),
                        retry_policy_id=tmpl.get("retry_policy_id"),
                        attempt_count=0,
                        max_attempts=tmpl.get("max_attempts", 3),
                        run_at=now,
                        created_at=now,
                        updated_at=now
                    )
                    session.add(new_job)
                    await session.flush()
                    
                    # 3. Calculate next run time
                    # Calculate from old next_run_at to avoid skew
                    iter = croniter(sched.cron_expression, sched.next_run_at)
                    next_run = iter.get_next(datetime)
                    
                    # 4. Update ScheduledJob state
                    sched.next_run_at = next_run
                    sched.last_triggered_at = now
                    
                    await session.commit()
                    print(f"[Scheduler] Triggered scheduled job {sched.id}, next run: {next_run}")
                    
                    # Notify WebSocket clients
                    await publish_job_status(new_job.id, "queued")
                except Exception as e:
                    print(f"[Scheduler] Error triggering scheduled job {sched.id}: {e}")
                    await session.rollback()
                    
if __name__ == "__main__":
    scheduler = CronScheduler()
    try:
        asyncio.run(scheduler.run())
    except KeyboardInterrupt:
        print("[Scheduler] KeyboardInterrupt. Exiting.")
