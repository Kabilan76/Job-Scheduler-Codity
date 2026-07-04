from typing import List
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func
from backend.app.db import get_db
from backend.app.models import Queue, Project, RetryPolicy, User, Job
from backend.app.schemas import QueueCreate, QueueOut, RetryPolicyCreate, RetryPolicyOut
from backend.app.api.auth import get_current_user

router = APIRouter(tags=["queues & retry policies"])

# --- QUEUES ENDPOINTS ---

@router.get("/queues/stats", response_model=List[dict])
async def list_queues_with_stats(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # Verify project exists
    proj_res = await db.execute(select(Project).where(Project.id == project_id))
    if not proj_res.scalars().first():
        raise HTTPException(status_code=404, detail="Project not found")
        
    # Fetch queues
    queues_res = await db.execute(select(Queue).where(Queue.project_id == project_id))
    queues = queues_res.scalars().all()
    
    stats = []
    for queue in queues:
        # Status counts
        status_query = (
            select(Job.status, func.count(Job.id))
            .where(Job.queue_id == queue.id)
            .group_by(Job.status)
        )
        status_res = await db.execute(status_query)
        counts = {"queued": 0, "running": 0, "completed": 0, "failed": 0}
        for status_name, count in status_res.all():
            if status_name in ("queued", "scheduled"):
                counts["queued"] += count
            elif status_name in ("running", "claimed"):
                counts["running"] += count
            elif status_name == "completed":
                counts["completed"] += count
            elif status_name in ("failed", "dead_letter"):
                counts["failed"] += count
                
        # Count active workers on this queue
        active_workers_query = (
            select(func.count(Job.id))
            .where((Job.queue_id == queue.id) & (Job.status == "running") & (Job.claimed_by.isnot(None)))
        )
        active_workers_res = await db.execute(active_workers_query)
        active_workers = active_workers_res.scalar() or 0
        
        stats.append({
            "id": str(queue.id),
            "name": queue.name,
            "priority": queue.priority,
            "max_concurrency": queue.max_concurrency,
            "is_paused": queue.is_paused,
            "default_retry_policy_id": str(queue.default_retry_policy_id) if queue.default_retry_policy_id else None,
            "created_at": queue.created_at,
            "stats": {
                "queued": counts["queued"],
                "running": counts["running"],
                "completed": counts["completed"],
                "failed": counts["failed"],
                "active_workers": active_workers
            }
        })
    return stats

@router.post("/queues", response_model=QueueOut, status_code=status.HTTP_201_CREATED)
async def create_queue(
    queue_in: QueueCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # Verify project exists
    proj_res = await db.execute(select(Project).where(Project.id == queue_in.project_id))
    project = proj_res.scalars().first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
        
    # Check default retry policy if supplied
    if queue_in.default_retry_policy_id:
        policy_res = await db.execute(
            select(RetryPolicy).where(RetryPolicy.id == queue_in.default_retry_policy_id)
        )
        if not policy_res.scalars().first():
            raise HTTPException(status_code=404, detail="Retry policy not found")
            
    new_queue = Queue(
        project_id=queue_in.project_id,
        name=queue_in.name,
        priority=queue_in.priority,
        max_concurrency=queue_in.max_concurrency,
        is_paused=False,
        default_retry_policy_id=queue_in.default_retry_policy_id
    )
    db.add(new_queue)
    await db.commit()
    await db.refresh(new_queue)
    return new_queue

@router.get("/queues", response_model=List[QueueOut])
async def list_queues(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # Verify project exists
    proj_res = await db.execute(select(Project).where(Project.id == project_id))
    if not proj_res.scalars().first():
        raise HTTPException(status_code=404, detail="Project not found")
        
    result = await db.execute(select(Queue).where(Queue.project_id == project_id))
    queues = result.scalars().all()
    return queues

@router.post("/queues/{queue_id}/pause", response_model=QueueOut)
async def pause_queue(
    queue_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    result = await db.execute(select(Queue).where(Queue.id == queue_id))
    queue = result.scalars().first()
    if not queue:
        raise HTTPException(status_code=404, detail="Queue not found")
        
    queue.is_paused = True
    await db.commit()
    await db.refresh(queue)
    return queue

@router.post("/queues/{queue_id}/resume", response_model=QueueOut)
async def resume_queue(
    queue_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    result = await db.execute(select(Queue).where(Queue.id == queue_id))
    queue = result.scalars().first()
    if not queue:
        raise HTTPException(status_code=404, detail="Queue not found")
        
    queue.is_paused = False
    await db.commit()
    await db.refresh(queue)
    return queue

# --- RETRY POLICY ENDPOINTS ---

@router.post("/retry-policies", response_model=RetryPolicyOut, status_code=status.HTTP_201_CREATED)
async def create_retry_policy(
    policy_in: RetryPolicyCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    new_policy = RetryPolicy(
        name=policy_in.name,
        strategy=policy_in.strategy,
        base_delay_seconds=policy_in.base_delay_seconds,
        max_retries=policy_in.max_retries,
        max_delay_seconds=policy_in.max_delay_seconds
    )
    db.add(new_policy)
    await db.commit()
    await db.refresh(new_policy)
    return new_policy

@router.get("/retry-policies", response_model=List[RetryPolicyOut])
async def list_retry_policies(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    result = await db.execute(select(RetryPolicy))
    policies = result.scalars().all()
    return policies
