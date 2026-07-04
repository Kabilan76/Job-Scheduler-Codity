import pytest
import uuid
from datetime import datetime, timezone, timedelta
from sqlalchemy.future import select
from backend.app.models import User, Organization, Project, Queue, Job, RetryPolicy, DeadLetterQueue
from worker.worker import JobWorker

@pytest.mark.asyncio
async def test_retry_and_dlq_transitions(test_session):
    """
    Test that a failing job correctly applies retry policy backoffs
    and transitions to the Dead Letter Queue when attempts are exhausted.
    """
    # 1. Seed base data
    user = User(email="test2@example.com", hashed_password="pw", name="Tester")
    test_session.add(user)
    await test_session.flush()
    
    org = Organization(name="Test Org 2", owner_id=user.id)
    test_session.add(org)
    await test_session.flush()
    
    proj = Project(org_id=org.id, name="Test Project 2")
    test_session.add(proj)
    await test_session.flush()
    
    # Create exponential retry policy: base=3s, max_retries=2 (total 3 attempts)
    policy = RetryPolicy(
        name="test-exp-policy",
        strategy="exponential",
        base_delay_seconds=3,
        max_retries=2,
        max_delay_seconds=3600
    )
    test_session.add(policy)
    await test_session.flush()
    
    queue = Queue(project_id=proj.id, name="retry-test-queue")
    test_session.add(queue)
    await test_session.flush()
    
    job = Job(
        queue_id=queue.id,
        project_id=proj.id,
        type="immediate",
        payload={"action": "fail"},
        status="queued",
        priority=0,
        retry_policy_id=policy.id,
        attempt_count=0,
        max_attempts=3, # 2 retries + 1 initial attempt
        run_at=datetime.now(timezone.utc)
    )
    test_session.add(job)
    await test_session.commit()

    # Instantiate mock worker
    worker = JobWorker()
    worker.worker_id = user.id # dummy worker ID
    dummy_exec_id = uuid.uuid4()
    
    # --- SIMULATE ATTEMPT 1 FAILURE ---
    async with test_session.begin_nested() as transaction:
        # Load job
        job_db = (await test_session.execute(select(Job).where(Job.id == job.id))).scalars().first()
        job_db.attempt_count = 1
        # Apply retry
        await worker.apply_retry_policy(test_session, job_db, dummy_exec_id, "Simulated Error 1")
    await test_session.commit()
    
    # Verify state after attempt 1
    job_db = (await test_session.execute(select(Job).where(Job.id == job.id))).scalars().first()
    assert job_db.status == "queued"
    assert job_db.claimed_by is None
    # Delay for attempt 1 (exp): 3 * (2 ^ (1 - 1)) = 3 seconds
    expected_delay = 3
    assert job_db.run_at > datetime.now(timezone.utc)
    assert job_db.run_at <= datetime.now(timezone.utc) + timedelta(seconds=expected_delay + 2)

    # --- SIMULATE ATTEMPT 2 FAILURE ---
    async with test_session.begin_nested() as transaction:
        job_db = (await test_session.execute(select(Job).where(Job.id == job.id))).scalars().first()
        job_db.attempt_count = 2
        await worker.apply_retry_policy(test_session, job_db, dummy_exec_id, "Simulated Error 2")
    await test_session.commit()
    
    # Verify state after attempt 2
    job_db = (await test_session.execute(select(Job).where(Job.id == job.id))).scalars().first()
    assert job_db.status == "queued"
    # Delay for attempt 2 (exp): 3 * (2 ^ (2 - 1)) = 6 seconds
    expected_delay = 6
    assert job_db.run_at <= datetime.now(timezone.utc) + timedelta(seconds=expected_delay + 2)

    # --- SIMULATE ATTEMPT 3 FAILURE (EXHAUSTED) ---
    async with test_session.begin_nested() as transaction:
        job_db = (await test_session.execute(select(Job).where(Job.id == job.id))).scalars().first()
        job_db.attempt_count = 3 # 3 attempts completed
        await worker.apply_retry_policy(test_session, job_db, dummy_exec_id, "Final Fatal Error")
    await test_session.commit()
    
    # Verify state after attempt 3
    job_db = (await test_session.execute(select(Job).where(Job.id == job.id))).scalars().first()
    assert job_db.status == "dead_letter"
    assert job_db.claimed_by is None
    
    # Verify entry exists in dead_letter_queue
    dlq_res = await test_session.execute(select(DeadLetterQueue).where(DeadLetterQueue.job_id == job.id))
    dlq_entry = dlq_res.scalars().first()
    assert dlq_entry is not None
    assert dlq_entry.final_error == "Final Fatal Error"
    assert dlq_entry.original_payload == {"action": "fail"}
