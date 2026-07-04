from datetime import datetime, timedelta, timezone
from typing import List
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func, desc

from backend.app.db import get_db
from backend.app.models import Job, Worker, JobExecution, Project, User
from backend.app.schemas import DashboardMetricsOut, WorkerOut
from backend.app.api.auth import get_current_user

router = APIRouter(prefix="/dashboard", tags=["dashboard metrics"])

@router.get("/workers", response_model=List[WorkerOut])
async def list_workers(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    result = await db.execute(select(Worker).order_by(desc(Worker.last_seen_at)))
    workers = result.scalars().all()
    return workers

@router.get("/metrics", response_model=DashboardMetricsOut)
async def get_dashboard_metrics(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # Verify project exists
    proj_res = await db.execute(select(Project).where(Project.id == project_id))
    if not proj_res.scalars().first():
        raise HTTPException(status_code=404, detail="Project not found")

    # 1. Job status counts
    status_query = (
        select(Job.status, func.count(Job.id))
        .where(Job.project_id == project_id)
        .group_by(Job.status)
    )
    status_res = await db.execute(status_query)
    status_counts = {
        "queued": 0, "scheduled": 0, "claimed": 0, 
        "running": 0, "completed": 0, "failed": 0, "dead_letter": 0
    }
    for status_name, count in status_res.all():
        if status_name in status_counts:
            status_counts[status_name] = count
            
    # 2. Active workers count (heartbeat within 30s)
    threshold_time = datetime.now(timezone.utc) - timedelta(seconds=30)
    # Convert threshold_time to naive if timezone is not stored in DB, but timezone-aware is best.
    # To be safe for both, let's keep threshold_time aware
    worker_query = (
        select(func.count(Worker.id))
        .where((Worker.status == "active") & (Worker.last_seen_at >= threshold_time))
    )
    worker_res = await db.execute(worker_query)
    active_workers_count = worker_res.scalar() or 0

    # 3. Average execution time
    avg_exec_query = (
        select(func.avg(JobExecution.duration_ms))
        .join(Job, JobExecution.job_id == Job.id)
        .where((Job.project_id == project_id) & (JobExecution.status == "completed"))
    )
    avg_exec_res = await db.execute(avg_exec_query)
    avg_execution_time_ms = float(avg_exec_res.scalar() or 0.0)

    # 4. Throughput series (last 12 hours)
    # Fetch completed executions in last 12 hours
    since_time = datetime.now(timezone.utc) - timedelta(hours=12)
    throughput_query = (
        select(JobExecution.finished_at)
        .join(Job, JobExecution.job_id == Job.id)
        .where(
            (Job.project_id == project_id) & 
            (JobExecution.status == "completed") & 
            (JobExecution.finished_at >= since_time)
        )
    )
    throughput_res = await db.execute(throughput_query)
    finished_times = [t[0] for t in throughput_res.all() if t[0] is not None]

    # Initialize last 12 hours buckets
    now = datetime.now(timezone.utc)
    buckets = {}
    for i in range(12):
        bucket_time = now - timedelta(hours=i)
        # Format key as HH:00
        bucket_key = bucket_time.strftime("%H:00")
        buckets[bucket_key] = 0

    # Populate buckets
    for f_time in finished_times:
        # Convert f_time to utc timezone if it is naive
        if f_time.tzinfo is None:
            f_time = f_time.replace(tzinfo=timezone.utc)
        bucket_key = f_time.strftime("%H:00")
        if bucket_key in buckets:
            buckets[bucket_key] += 1

    # Format series as sorted list of objects
    # We sort chronologically (oldest first)
    throughput_series = []
    for i in reversed(range(12)):
        bucket_time = now - timedelta(hours=i)
        bucket_key = bucket_time.strftime("%H:00")
        throughput_series.append({
            "time": bucket_key,
            "completed": buckets[bucket_key]
        })

    return {
        "status_counts": status_counts,
        "active_workers_count": active_workers_count,
        "avg_execution_time_ms": round(avg_execution_time_ms, 2),
        "throughput_series": throughput_series
    }
