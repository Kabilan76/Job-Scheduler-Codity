import asyncio
import pytest
from datetime import datetime, timezone
from sqlalchemy.future import select
from sqlalchemy import update, func
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from backend.app.db import Base
from backend.app.models import User, Organization, OrgMember, Project, Queue, Job, Worker

@pytest.mark.asyncio
async def test_concurrent_job_claiming():
    """
    Test that multiple concurrent workers claiming from the same queue
    never claim the same job (no duplicate execution).
    """
    # 1. Setup file-based test database to ensure concurrent connections have isolated transactions
    import os
    db_file = "test_concurrency.db"
    if os.path.exists(db_file):
        try:
            os.remove(db_file)
        except Exception:
            pass
            
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        
    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False
    )
    
    # 2. Seed project, queue, and 20 queued jobs
    async with session_factory() as session:
        user = User(email="test@example.com", hashed_password="pw", name="Tester")
        session.add(user)
        await session.flush()
        
        org = Organization(name="Test Org", owner_id=user.id)
        session.add(org)
        await session.flush()
        
        proj = Project(org_id=org.id, name="Test Project")
        session.add(proj)
        await session.flush()
        
        queue = Queue(project_id=proj.id, name="concurrency-queue", max_concurrency=10)
        session.add(queue)
        await session.flush()
        
        # Insert 20 immediate queued jobs
        for i in range(20):
            job = Job(
                queue_id=queue.id,
                project_id=proj.id,
                type="immediate",
                payload={"job_num": i},
                status="queued",
                priority=0,
                run_at=datetime.now(timezone.utc)
            )
            session.add(job)
            
        await session.commit()
        queue_id = queue.id
        project_id = proj.id

    # 3. Define simulated worker claim function
    claimed_records = [] # thread-safe/asyncio-safe list

    async def simulate_worker_claiming(worker_name, num_attempts):
        # Register worker
        async with session_factory() as session:
            worker = Worker(hostname=worker_name, status="active")
            session.add(worker)
            await session.commit()
            worker_id = worker.id

        # Attempt claiming loop
        for _ in range(num_attempts):
            async with session_factory() as session:
                try:
                    # Select candidates
                    now = datetime.now(timezone.utc)
                    candidates_res = await session.execute(
                        select(Job.id)
                        .where(
                            (Job.status == "queued") & 
                            (Job.queue_id == queue_id) & 
                            (Job.run_at <= now)
                        )
                    )
                    candidates = [r[0] for r in candidates_res.all()]
                    
                    for cid in candidates:
                        # Attempt Compare-And-Swap (CAS) update
                        update_res = await session.execute(
                            update(Job)
                            .where((Job.id == cid) & (Job.status == "queued"))
                            .values(
                                status="claimed",
                                claimed_by=worker_id,
                                claimed_at=now
                            )
                        )
                        if update_res.rowcount == 1:
                            await session.commit()
                            claimed_records.append((cid, worker_id))
                            # Yield control to encourage interleaving
                            await asyncio.sleep(0.005)
                            break
                        else:
                            await session.rollback()
                except Exception as e:
                    await session.rollback()
            await asyncio.sleep(0.001)

    # 4. Spawn 4 workers running concurrently to claim the 20 jobs
    workers_tasks = [
        simulate_worker_claiming(f"worker-{i}", 15) for i in range(4)
    ]
    await asyncio.gather(*workers_tasks)

    # 5. Assertions
    print("\n--- CLAIMED RECORDS ---")
    print(claimed_records)
    print("-----------------------\n")
    
    # Total claims must not exceed 20
    assert len(claimed_records) <= 20
    
    # Verify no job ID is claimed twice!
    job_ids_claimed = [cid for cid, wid in claimed_records]
    assert len(job_ids_claimed) == len(set(job_ids_claimed)), "Duplicate claiming detected!"
    
    # Check in DB that all claimed jobs have claimed_by set correctly
    async with session_factory() as session:
        claimed_db_res = await session.execute(
            select(Job.id, Job.status, Job.claimed_by).where(Job.queue_id == queue_id)
        )
        db_rows = claimed_db_res.all()
        for jid, status, claimed_by in db_rows:
            if status == "claimed":
                assert claimed_by is not None
                # Verify that it matches our test records
                matching_record = [wid for cid, wid in claimed_records if cid == jid]
                assert len(matching_record) == 1
                assert matching_record[0] == claimed_by

    await engine.dispose()
    if os.path.exists(db_file):
        try:
            os.remove(db_file)
        except Exception:
            pass
