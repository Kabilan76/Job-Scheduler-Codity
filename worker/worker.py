import asyncio
import os
import sys
import socket
import signal
import time
import random
from datetime import datetime, timezone, timedelta
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.future import select
from sqlalchemy import update, func, text, and_

# Ensure backend folder is in path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.app.config import settings
from backend.app.db import engine, async_session_maker, IS_POSTGRES
from backend.app.models import Worker, WorkerHeartbeat, Job, JobExecution, JobLog, DeadLetterQueue, Queue, RetryPolicy
from backend.app.api.websocket import publish_job_status, publish_job_log, publish_dashboard_update

# Try importing psutil for real CPU/memory metrics, fallback to mock if unavailable
try:
    import psutil
except ImportError:
    psutil = None

class JobWorker:
    def __init__(self):
        self.worker_id = None
        self.hostname = socket.gethostname()
        self.running_jobs = {} # job_id -> task
        self.shutdown_requested = False
        self.heartbeat_task = None
        self.main_loop_task = None

    async def register_worker(self):
        async with async_session_maker() as session:
            new_worker = Worker(
                hostname=self.hostname,
                status="active",
                last_seen_at=datetime.now(timezone.utc),
                started_at=datetime.now(timezone.utc)
            )
            session.add(new_worker)
            await session.commit()
            self.worker_id = new_worker.id
            print(f"[Worker] Registered worker with ID: {self.worker_id} on host {self.hostname}")

    async def send_heartbeat(self):
        while not self.shutdown_requested:
            if not self.worker_id:
                await asyncio.sleep(1)
                continue
                
            try:
                # Obtain CPU and memory info
                if psutil:
                    cpu = psutil.cpu_percent()
                    memory = psutil.virtual_memory().used / (1024 * 1024) # MB
                else:
                    cpu = round(random.uniform(5.0, 25.0), 1)
                    memory = round(random.uniform(150.0, 300.0), 1)
                
                async with async_session_maker() as session:
                    # Insert heartbeat record
                    heartbeat = WorkerHeartbeat(
                        worker_id=self.worker_id,
                        ts=datetime.now(timezone.utc),
                        cpu_pct=cpu,
                        memory_mb=memory
                    )
                    session.add(heartbeat)
                    
                    # Update worker status and last_seen
                    await session.execute(
                        update(Worker)
                        .where(Worker.id == self.worker_id)
                        .values(last_seen_at=datetime.now(timezone.utc), status="active")
                    )
                    await session.commit()
            except Exception as e:
                print(f"[Worker] Error sending heartbeat: {e}")
                
            await asyncio.sleep(5)

    async def claim_jobs(self) -> list:
        """
        Polls the database for available jobs.
        Respects queue max_concurrency and paused state.
        """
        claimed_job_objects = []
        async with async_session_maker() as session:
            try:
                # 1. Fetch all active (unpaused) queues
                queues_res = await session.execute(select(Queue).where(Queue.is_paused == False))
                active_queues = queues_res.scalars().all()
                
                for queue in active_queues:
                    # 2. Count current running/claimed jobs in this queue
                    running_count_res = await session.execute(
                        select(func.count(Job.id)).where(
                            (Job.queue_id == queue.id) & 
                            (Job.status.in_(["claimed", "running"]))
                        )
                    )
                    running_count = running_count_res.scalar() or 0
                    
                    # Check concurrency availability
                    slots = queue.max_concurrency - running_count
                    if slots <= 0:
                        continue
                        
                    # 3. Query jobs from this queue matching conditions
                    now = datetime.now(timezone.utc)
                    
                    if IS_POSTGRES:
                        # Postgres row-level locking
                        # SELECT FOR UPDATE SKIP LOCKED
                        stmt = text("""
                            SELECT id FROM jobs
                            WHERE status = 'queued' AND queue_id = :queue_id AND run_at <= :now
                            ORDER BY priority DESC, created_at ASC
                            LIMIT :limit
                            FOR UPDATE SKIP LOCKED;
                        """)
                        candidates_res = await session.execute(
                            stmt, {"queue_id": queue.id, "now": now, "limit": slots}
                        )
                        candidate_ids = [r[0] for r in candidates_res.all()]
                        
                        if candidate_ids:
                            # Mark them as claimed
                            await session.execute(
                                update(Job)
                                .where(Job.id.in_(candidate_ids))
                                .values(
                                    status="claimed", 
                                    claimed_by=self.worker_id, 
                                    claimed_at=now,
                                    updated_at=now
                                )
                            )
                            await session.commit()
                            
                            # Retrieve the full job objects
                            jobs_res = await session.execute(
                                select(Job).where(Job.id.in_(candidate_ids))
                            )
                            claimed_job_objects.extend(jobs_res.scalars().all())
                            
                    else:
                        # SQLite Compare-And-Swap (CAS) Fallback
                        # Step 1: Select candidates
                        candidates_res = await session.execute(
                            select(Job.id)
                            .where(
                                (Job.status == "queued") & 
                                (Job.queue_id == queue.id) & 
                                (Job.run_at <= now)
                            )
                            .order_by(Job.priority.desc(), Job.created_at.asc())
                            .limit(slots)
                        )
                        candidate_ids = [r[0] for r in candidates_res.all()]
                        
                        for cid in candidate_ids:
                            # Step 2: Attempt claim atomically via CAS update
                            update_res = await session.execute(
                                update(Job)
                                .where((Job.id == cid) & (Job.status == "queued"))
                                .values(
                                    status="claimed",
                                    claimed_by=self.worker_id,
                                    claimed_at=now,
                                    updated_at=now
                                )
                            )
                            # In SQLAlchemy Core, rowcount tells us how many rows were updated
                            if update_res.rowcount == 1:
                                await session.commit()
                                # Fetch full job object
                                job_res = await session.execute(select(Job).where(Job.id == cid))
                                claimed_job_objects.append(job_res.scalars().first())
                            else:
                                await session.rollback() # another worker claimed it first
                                
            except Exception as e:
                print(f"[Worker] Error during job claiming: {e}")
                await session.rollback()
                
        return claimed_job_objects

    async def log_for_job(self, session: AsyncSession, job_id, exec_id, level, message):
        log_entry = JobLog(
            job_id=job_id,
            execution_id=exec_id,
            ts=datetime.now(timezone.utc),
            level=level,
            message=message
        )
        session.add(log_entry)
        await session.flush()
        # Broadcast via WebSockets
        await publish_job_log(job_id, level, message)

    async def apply_retry_policy(self, session: AsyncSession, job: Job, exec_id, error_msg: str):
        """
        Calculates retry backoff and schedules or DLQs the job.
        """
        # Determine retry policy
        policy = None
        if job.retry_policy_id:
            policy_res = await session.execute(
                select(RetryPolicy).where(RetryPolicy.id == job.retry_policy_id)
            )
            policy = policy_res.scalars().first()
            
        max_attempts = job.max_attempts
        if policy:
            max_attempts = policy.max_retries + 1 # policy works in retries, so total attempts = retries + 1
            
        if job.attempt_count < max_attempts:
            # Calculate backoff delay
            delay = 5 # default 5 seconds
            if policy:
                if policy.strategy == "fixed":
                    delay = policy.base_delay_seconds
                elif policy.strategy == "linear":
                    delay = policy.base_delay_seconds * job.attempt_count
                elif policy.strategy == "exponential":
                    delay = policy.base_delay_seconds * (2 ** (job.attempt_count - 1))
                
                # Cap delay
                delay = min(delay, policy.max_delay_seconds)
                
            next_run = datetime.now(timezone.utc) + timedelta(seconds=delay)
            job.status = "queued"
            job.run_at = next_run
            job.claimed_by = None
            job.claimed_at = None
            
            await self.log_for_job(
                session, job.id, exec_id, "WARNING",
                f"Job attempt failed. Retrying in {delay} seconds (Attempt {job.attempt_count} of {max_attempts}). Error: {error_msg}"
            )
            await publish_job_status(job.id, "queued")
        else:
            # DLQ move
            job.status = "dead_letter"
            job.claimed_by = None
            job.claimed_at = None
            
            dlq_entry = DeadLetterQueue(
                job_id=job.id,
                final_error=error_msg,
                moved_at=datetime.now(timezone.utc),
                original_payload=job.payload
            )
            session.add(dlq_entry)
            
            await self.log_for_job(
                session, job.id, exec_id, "ERROR",
                f"Job exhausted all {max_attempts} attempts. Moved to Dead Letter Queue (DLQ). Final error: {error_msg}"
            )
            await publish_job_status(job.id, "dead_letter")

    async def update_dependent_jobs(self, session: AsyncSession, completed_job_id):
        """
        Finds scheduled jobs that depend on completed_job_id.
        Triggers them if all their dependencies are completed.
        """
        from backend.app.models import job_dependencies as job_deps_table
        
        # Select all jobs that depend on the completed job
        deps_query = select(job_deps_table.c.job_id).where(
            job_deps_table.c.depends_on_job_id == completed_job_id
        )
        deps_res = await session.execute(deps_query)
        dependent_job_ids = [r[0] for r in deps_res.all()]
        
        for dep_job_id in dependent_job_ids:
            # Check if all dependencies for dep_job_id are completed
            all_deps_query = select(job_deps_table.c.depends_on_job_id).where(
                job_deps_table.c.job_id == dep_job_id
            )
            all_deps_res = await session.execute(all_deps_query)
            all_dep_ids = [r[0] for r in all_deps_res.all()]
            
            # Count completed dependencies
            completed_deps_query = select(func.count(Job.id)).where(
                (Job.id.in_(all_dep_ids)) & (Job.status == "completed")
            )
            completed_deps_res = await session.execute(completed_deps_query)
            completed_count = completed_deps_res.scalar() or 0
            
            if completed_count == len(all_dep_ids):
                # All dependencies are completed! Change status from scheduled to queued
                await session.execute(
                    update(Job)
                    .where((Job.id == dep_job_id) & (Job.status == "scheduled"))
                    .values(status="queued", run_at=datetime.now(timezone.utc))
                )
                await publish_job_status(dep_job_id, "queued")

    async def execute_job(self, job_id):
        """
        Runs a job inside a separate try-except logic.
        """
        exec_id = uuid.uuid4()
        start_time = datetime.now(timezone.utc)
        
        # 1. Update job to running status and create execution record
        async with async_session_maker() as session:
            try:
                # Fetch job
                job_res = await session.execute(select(Job).where(Job.id == job_id))
                job = job_res.scalars().first()
                if not job:
                    return
                
                # Update status
                job.status = "running"
                job.attempt_count += 1
                job.updated_at = start_time
                
                # Update worker table with current job
                await session.execute(
                    update(Worker).where(Worker.id == self.worker_id).values(current_job_id=job.id)
                )
                
                # Create execution record
                execution = JobExecution(
                    id=exec_id,
                    job_id=job.id,
                    worker_id=self.worker_id,
                    attempt_number=job.attempt_count,
                    started_at=start_time,
                    status="running"
                )
                session.add(execution)
                await session.flush()
                
                # Log start
                await self.log_for_job(
                    session, job.id, exec_id, "INFO", 
                    f"Attempt #{job.attempt_count} started execution on worker {self.hostname}."
                )
                await session.commit()
                
                # Broadcast job status update
                await publish_job_status(job.id, "running")
                await publish_dashboard_update(job.project_id)
            except Exception as e:
                print(f"[Worker] Error starting job execution: {e}")
                await session.rollback()
                return

        # 2. Simulate running the payload logic
        # Retrieve payload tasks
        error_msg = None
        try:
            # We fetch job config again to run payload safely
            payload = None
            async with async_session_maker() as session:
                job_res = await session.execute(select(Job).where(Job.id == job_id))
                job = job_res.scalars().first()
                payload = job.payload if job else {}
                
            # Perform action based on payload
            action = payload.get("action", "success")
            duration = payload.get("duration", 2) # execution duration in seconds
            
            # Log progress
            async with async_session_maker() as session:
                await self.log_for_job(
                    session, job_id, exec_id, "INFO", 
                    f"Job payload action is '{action}'. Running for {duration}s..."
                )
                await session.commit()
                
            await asyncio.sleep(duration)
            
            if action == "fail":
                raise Exception(payload.get("error_message", "Simulated execution failure."))
                
        except Exception as e:
            error_msg = str(e)

        # 3. Finalize execution status
        end_time = datetime.now(timezone.utc)
        duration_ms = int((end_time - start_time).total_seconds() * 1000)
        
        async with async_session_maker() as session:
            try:
                # Fetch job and execution
                job_res = await session.execute(select(Job).where(Job.id == job_id))
                job = job_res.scalars().first()
                
                exec_res = await session.execute(select(JobExecution).where(JobExecution.id == exec_id))
                execution = exec_res.scalars().first()
                
                if error_msg:
                    # Fail
                    execution.status = "failed"
                    execution.error_message = error_msg
                    execution.finished_at = end_time
                    execution.duration_ms = duration_ms
                    
                    # Apply retry backoff
                    await self.apply_retry_policy(session, job, exec_id, error_msg)
                else:
                    # Success
                    execution.status = "completed"
                    execution.finished_at = end_time
                    execution.duration_ms = duration_ms
                    
                    job.status = "completed"
                    job.claimed_by = None
                    job.claimed_at = None
                    
                    await self.log_for_job(
                        session, job.id, exec_id, "INFO", 
                        f"Job execution completed successfully in {duration_ms}ms."
                    )
                    await publish_job_status(job.id, "completed")
                    
                    # Process child DAG workflows (dependencies)
                    await self.update_dependent_jobs(session, job.id)
                    
                # Reset worker current job
                await session.execute(
                    update(Worker).where(Worker.id == self.worker_id).values(current_job_id=None)
                )
                
                await session.commit()
                await publish_dashboard_update(job.project_id)
            except Exception as e:
                print(f"[Worker] Error finalizing job execution: {e}")
                await session.rollback()

    async def main_loop(self):
        print("[Worker] Worker claim loop started.")
        while not self.shutdown_requested:
            try:
                claimed_jobs = await self.claim_jobs()
                if claimed_jobs:
                    print(f"[Worker] Claimed {len(claimed_jobs)} jobs. Spawning execution tasks...")
                    for job in claimed_jobs:
                        # Spawn task to execute job asynchronously
                        task = asyncio.create_task(self.execute_job(job.id))
                        self.running_jobs[job.id] = task
                        # Clean up task reference on completion
                        task.add_done_callback(lambda t, j_id=job.id: self.running_jobs.pop(j_id, None))
                
            except Exception as e:
                print(f"[Worker] Error in main loop: {e}")
                
            # Poll every 2 seconds
            await asyncio.sleep(2)

    async def release_claimed_jobs_on_shutdown(self):
        """
        If worker shuts down, release running/claimed jobs back to queued status
        to ensure no orphan jobs.
        """
        # Cancel active execution tasks
        for job_id, task in list(self.running_jobs.items()):
            task.cancel()
            
        async with async_session_maker() as session:
            try:
                # Find all jobs claimed by this worker
                claimed_res = await session.execute(
                    select(Job).where(
                        (Job.claimed_by == self.worker_id) & 
                        (Job.status.in_(["claimed", "running"]))
                    )
                )
                claimed_jobs = claimed_res.scalars().all()
                for job in claimed_jobs:
                    job.status = "queued"
                    job.claimed_by = None
                    job.claimed_at = None
                    # log release
                    log_entry = JobLog(
                        job_id=job.id,
                        execution_id=uuid.uuid4(),
                        ts=datetime.now(timezone.utc),
                        level="WARNING",
                        message=f"Worker hostname {self.hostname} shutting down. Releasing job back to queue."
                    )
                    session.add(log_entry)
                    await publish_job_status(job.id, "queued")
                
                # Set worker status to inactive
                await session.execute(
                    update(Worker).where(Worker.id == self.worker_id).values(status="inactive", current_job_id=None)
                )
                await session.commit()
                print(f"[Worker] Released {len(claimed_jobs)} claimed jobs back to the queue.")
            except Exception as e:
                print(f"[Worker] Error releasing jobs on shutdown: {e}")
                await session.rollback()

    def handle_signal(self, signum, frame):
        print(f"[Worker] Signal {signum} received. Requesting graceful shutdown...")
        self.shutdown_requested = True
        
        # Stop background tasks
        if self.heartbeat_task:
            self.heartbeat_task.cancel()
        if self.main_loop_task:
            self.main_loop_task.cancel()

    async def run(self):
        # Register signals
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, lambda s=sig: asyncio.create_task(self.shutdown_wrapper(s)))
            
        await self.register_worker()
        
        # Spawn heartbeat and main polling loop
        self.heartbeat_task = asyncio.create_task(self.send_heartbeat())
        self.main_loop_task = asyncio.create_task(self.main_loop())
        
        try:
            await asyncio.gather(self.heartbeat_task, self.main_loop_task, return_exceptions=True)
        except asyncio.CancelledError:
            pass
        finally:
            print("[Worker] Shutting down worker...")
            await self.release_claimed_jobs_on_shutdown()

    async def shutdown_wrapper(self, sig):
        print(f"[Worker] Handling signal {sig.name}...")
        self.shutdown_requested = True
        if self.heartbeat_task:
            self.heartbeat_task.cancel()
        if self.main_loop_task:
            self.main_loop_task.cancel()

import uuid

if __name__ == "__main__":
    worker = JobWorker()
    try:
        asyncio.run(worker.run())
    except KeyboardInterrupt:
        print("[Worker] KeyboardInterrupt. Exiting.")
