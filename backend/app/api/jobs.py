import uuid
from uuid import UUID
from datetime import datetime, timezone
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import update, func, desc
from croniter import croniter

from backend.app.db import get_db
from backend.app.models import Job, Queue, Project, JobExecution, JobLog, ScheduledJob, User
from backend.app.schemas import JobCreate, JobOut, JobExecutionOut, JobLogOut, BatchProgressOut
from backend.app.api.auth import get_current_user
from backend.app.db import IS_POSTGRES

# Simple pubsub stub or imported redis (we will build redis publisher helper later)
# For now, let's write a pubsub publisher helper that will handle redis and fallback pubsub.
from backend.app.api.websocket import publish_job_status, publish_job_log

router = APIRouter(prefix="/jobs", tags=["jobs pipeline"])

@router.post("", response_model=JobOut, status_code=status.HTTP_201_CREATED)
async def create_job(
    job_in: JobCreate,
    response: Response,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # Verify project exists
    proj_res = await db.execute(select(Project).where(Project.id == job_in.project_id))
    if not proj_res.scalars().first():
        raise HTTPException(status_code=404, detail="Project not found")

    # Verify queue exists
    queue_res = await db.execute(select(Queue).where(Queue.id == job_in.queue_id))
    queue = queue_res.scalars().first()
    if not queue:
        raise HTTPException(status_code=404, detail="Queue not found")

    # 1. Idempotency Key check (Gap #2)
    if job_in.idempotency_key:
        idemp_query = select(Job).where(
            (Job.project_id == job_in.project_id) & 
            (Job.idempotency_key == job_in.idempotency_key)
        )
        idemp_res = await db.execute(idemp_query)
        existing_job = idemp_res.scalars().first()
        if existing_job:
            # Return existing job with 200 OK
            response.status_code = status.HTTP_200_OK
            return existing_job

    # Resolve retry policy
    policy_id = job_in.retry_policy_id or queue.default_retry_policy_id

    # Parse and schedule run_at
    job_status = "queued"
    run_at = datetime.now(timezone.utc)
    
    if job_in.type == "delayed":
        if not job_in.run_at:
            raise HTTPException(status_code=400, detail="run_at is required for delayed jobs")
        run_at = job_in.run_at
        job_status = "scheduled"
    elif job_in.type == "scheduled" or job_in.type == "recurring":
        if not job_in.cron_expression:
            raise HTTPException(status_code=400, detail="cron_expression is required for scheduled/recurring jobs")
        if not croniter.is_valid(job_in.cron_expression):
            raise HTTPException(status_code=400, detail="Invalid cron expression")
        
        # Calculate next_run_at
        iter = croniter(job_in.cron_expression, datetime.now(timezone.utc))
        next_run = iter.get_next(datetime)
        
        # We create a scheduled_job configuration
        new_sched = ScheduledJob(
            project_id=job_in.project_id,
            job_template={
                "queue_id": str(job_in.queue_id),
                "type": job_in.type,
                "payload": job_in.payload,
                "priority": job_in.priority,
                "retry_policy_id": str(policy_id) if policy_id else None,
                "max_attempts": job_in.max_attempts
            },
            cron_expression=job_in.cron_expression,
            next_run_at=next_run,
            is_active=True
        )
        db.add(new_sched)
        await db.flush()
        
        # Also create the first scheduled job instance in jobs list (optional, but requested in lifecycle)
        run_at = next_run
        job_status = "scheduled"

    # Create Job Object
    batch_id = None
    if job_in.type == "batch":
        batch_id = uuid.uuid4()
        
        # Child jobs from payload "jobs"
        child_jobs = job_in.payload.get("jobs", [])
        if not child_jobs:
            raise HTTPException(status_code=400, detail="batch job payload must contain a list of 'jobs'")
            
        for child in child_jobs:
            child_job = Job(
                queue_id=job_in.queue_id,
                project_id=job_in.project_id,
                type="immediate", # child jobs run immediately
                payload=child.get("payload", {}),
                status="queued",
                priority=child.get("priority", job_in.priority),
                retry_policy_id=policy_id,
                max_attempts=job_in.max_attempts,
                run_at=datetime.now(timezone.utc),
                batch_id=batch_id
            )
            db.add(child_job)
            
        # Parent job representation
        # Parent payload stores subjobs count & details
        job_in.payload["batch_id"] = str(batch_id)
        job_in.payload["total_jobs"] = len(child_jobs)

    new_job = Job(
        queue_id=job_in.queue_id,
        project_id=job_in.project_id,
        type=job_in.type,
        payload=job_in.payload,
        status=job_status,
        priority=job_in.priority,
        retry_policy_id=policy_id,
        attempt_count=0,
        max_attempts=job_in.max_attempts or 3,
        run_at=run_at,
        cron_expression=job_in.cron_expression,
        batch_id=batch_id,
        idempotency_key=job_in.idempotency_key,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc)
    )
    
    db.add(new_job)
    await db.flush()
    
    # Handle DAG dependencies if provided
    if job_in.depends_on_ids:
        # Verify dependencies exist
        for dep_id in job_in.depends_on_ids:
            dep_res = await db.execute(select(Job).where(Job.id == dep_id))
            dep = dep_res.scalars().first()
            if not dep:
                raise HTTPException(status_code=404, detail=f"Dependency job {dep_id} not found")
            # If depends_on is not completed, this job cannot be queued yet
            # It should start in scheduled state
            new_job.status = "scheduled"
            
            # Associate dependency (insert into job_dependencies helper table)
            from backend.app.models import job_dependencies as job_deps_table
            await db.execute(job_deps_table.insert().values(job_id=new_job.id, depends_on_job_id=dep.id))

    await db.commit()
    await db.refresh(new_job)
    
    # Pub/Sub status change (initial queue status)
    await publish_job_status(new_job.id, new_job.status)
    
    return new_job

@router.get("/batch/{batch_id}", response_model=BatchProgressOut)
async def get_batch_progress(
    batch_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # Fetch all jobs in this batch
    query = select(Job).where(Job.batch_id == batch_id)
    res = await db.execute(query)
    jobs = res.scalars().all()
    
    if not jobs:
        raise HTTPException(status_code=404, detail="Batch not found")
        
    total_jobs = 0
    completed_jobs = 0
    failed_jobs = 0
    running_jobs = 0
    queued_jobs = 0
    
    # Filter child jobs vs parent job. Child jobs have batch_id and type != 'batch'
    child_jobs = [j for j in jobs if j.type != "batch"]
    
    for job in child_jobs:
        total_jobs += 1
        if job.status == "completed":
            completed_jobs += 1
        elif job.status in ("dead_letter", "failed"):
            failed_jobs += 1
        elif job.status in ("running", "claimed"):
            running_jobs += 1
        elif job.status in ("queued", "scheduled"):
            queued_jobs += 1
            
    # Calculate batch aggregate status
    # Completed: all child jobs are completed
    # Failed: any child job is dead_letter/failed (meaning failed all attempts)
    # Running: at least one child job running or claimed
    # Queued: everything is queued
    if total_jobs == 0:
        batch_status = "completed"
    elif completed_jobs == total_jobs:
        batch_status = "completed"
    elif failed_jobs > 0:
        batch_status = "failed"
    elif running_jobs > 0 or (completed_jobs > 0 and completed_jobs < total_jobs):
        batch_status = "running"
    else:
        batch_status = "queued"
        
    # Optional: Update the parent job status in the database to keep it synced
    parent_job = next((j for j in jobs if j.type == "batch"), None)
    if parent_job and parent_job.status != batch_status:
        parent_job.status = batch_status
        await db.commit()

    return {
        "batch_id": batch_id,
        "status": batch_status,
        "total_jobs": total_jobs,
        "completed_jobs": completed_jobs,
        "failed_jobs": failed_jobs,
        "running_jobs": running_jobs,
        "queued_jobs": queued_jobs,
        "jobs": child_jobs
    }

@router.get("", response_model=List[JobOut])
async def list_jobs(
    project_id: Optional[UUID] = None,
    queue_id: Optional[UUID] = None,
    status: Optional[str] = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    query = select(Job)
    
    if project_id:
        query = query.where(Job.project_id == project_id)
    if queue_id:
        query = query.where(Job.queue_id == queue_id)
    if status:
        query = query.where(Job.status == status)
        
    # Default order by created_at DESC
    query = query.order_by(desc(Job.created_at))
    
    # Pagination offset
    offset = (page - 1) * page_size
    query = query.offset(offset).limit(page_size)
    
    res = await db.execute(query)
    jobs = res.scalars().all()
    return jobs

@router.get("/{job_id}", response_model=JobOut)
async def get_job(
    job_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    res = await db.execute(select(Job).where(Job.id == job_id))
    job = res.scalars().first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job

@router.get("/{job_id}/executions", response_model=List[JobExecutionOut])
async def get_job_executions(
    job_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    res = await db.execute(
        select(JobExecution).where(JobExecution.job_id == job_id).order_by(JobExecution.attempt_number)
    )
    return res.scalars().all()

@router.get("/{job_id}/logs", response_model=List[JobLogOut])
async def get_job_logs(
    job_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    res = await db.execute(
        select(JobLog).where(JobLog.job_id == job_id).order_by(JobLog.ts)
    )
    return res.scalars().all()

@router.post("/{job_id}/retry", response_model=JobOut)
async def retry_job(
    job_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    res = await db.execute(select(Job).where(Job.id == job_id))
    job = res.scalars().first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
        
    if job.status not in ("dead_letter", "failed"):
        raise HTTPException(
            status_code=400, 
            detail=f"Only failed or dead_letter jobs can be retried. Current status: {job.status}"
        )
        
    # Manual retry resets attempt_count and schedules job immediately
    job.attempt_count = 0
    job.status = "queued"
    job.run_at = datetime.now(timezone.utc)
    job.claimed_by = None
    job.claimed_at = None
    
    # Save a log entry
    log_entry = JobLog(
        job_id=job.id,
        execution_id=uuid.uuid4(), # dummy execution ID or null
        ts=datetime.now(timezone.utc),
        level="INFO",
        message="Manual retry triggered. Resetting attempts and requeuing job."
    )
    db.add(log_entry)
    
    await db.commit()
    await db.refresh(job)
    
    # Notify status change & log
    await publish_job_status(job.id, "queued")
    await publish_job_log(job.id, "INFO", "Manual retry triggered. Resetting attempts and requeuing job.")
    
    return job
