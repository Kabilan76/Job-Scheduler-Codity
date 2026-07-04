import uuid
from datetime import datetime
from sqlalchemy import (
    Column, String, Boolean, Integer, Float, DateTime, Text, ForeignKey, 
    Index, Table, func, text, JSON
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from backend.app.db import Base

# Dialect-agnostic JSON type (JSONB on PostgreSQL, JSON on others)
JSONType = JSON().with_variant(JSONB, "postgresql")

# Many-to-many relationship helper for DAG dependencies
# job_dependencies: job_id depends on depends_on_job_id
job_dependencies = Table(
    'job_dependencies',
    Base.metadata,
    Column('id', UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
    Column('job_id', UUID(as_uuid=True), ForeignKey('jobs.id', ondelete='CASCADE'), nullable=False),
    Column('depends_on_job_id', UUID(as_uuid=True), ForeignKey('jobs.id', ondelete='CASCADE'), nullable=False),
    Index('idx_job_deps_job_id', 'job_id'),
    Index('idx_job_deps_depends_on', 'depends_on_job_id')
)

class User(Base):
    __tablename__ = "users"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String, unique=True, nullable=False, index=True)
    hashed_password = Column(String, nullable=False)
    name = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    
    # Relationships
    owned_organizations = relationship("Organization", back_populates="owner", cascade="all, delete-orphan")
    memberships = relationship("OrgMember", back_populates="user", cascade="all, delete-orphan")

class Organization(Base):
    __tablename__ = "organizations"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)
    owner_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    
    # Relationships
    owner = relationship("User", back_populates="owned_organizations")
    members = relationship("OrgMember", back_populates="organization", cascade="all, delete-orphan")
    projects = relationship("Project", back_populates="organization", cascade="all, delete-orphan")

class OrgMember(Base):
    __tablename__ = "org_members"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role = Column(String, nullable=False)  # 'owner', 'admin', 'member'
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    
    # Relationships
    organization = relationship("Organization", back_populates="members")
    user = relationship("User", back_populates="memberships")

class Project(Base):
    __tablename__ = "projects"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    name = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    
    # Relationships
    organization = relationship("Organization", back_populates="projects")
    queues = relationship("Queue", back_populates="project", cascade="all, delete-orphan")
    jobs = relationship("Job", back_populates="project", cascade="all, delete-orphan")
    scheduled_jobs = relationship("ScheduledJob", back_populates="project", cascade="all, delete-orphan")

class RetryPolicy(Base):
    __tablename__ = "retry_policies"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)
    strategy = Column(String, nullable=False)  # 'fixed', 'linear', 'exponential'
    base_delay_seconds = Column(Integer, default=5, nullable=False)
    max_retries = Column(Integer, default=3, nullable=False)
    max_delay_seconds = Column(Integer, default=3600, nullable=False)

class Queue(Base):
    __tablename__ = "queues"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    name = Column(String, nullable=False)
    priority = Column(Integer, default=0, nullable=False)  # higher value means higher priority queue
    max_concurrency = Column(Integer, default=1, nullable=False)
    is_paused = Column(Boolean, default=False, nullable=False)
    default_retry_policy_id = Column(UUID(as_uuid=True), ForeignKey("retry_policies.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    
    # Relationships
    project = relationship("Project", back_populates="queues")
    default_retry_policy = relationship("RetryPolicy")
    jobs = relationship("Job", back_populates="queue", cascade="all, delete-orphan")

class Worker(Base):
    __tablename__ = "workers"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    hostname = Column(String, nullable=False)
    status = Column(String, nullable=False)  # 'active', 'inactive', 'dead'
    last_seen_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    current_job_id = Column(UUID(as_uuid=True), nullable=True)
    started_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    
    # Relationships
    heartbeats = relationship("WorkerHeartbeat", back_populates="worker", cascade="all, delete-orphan")
    executions = relationship("JobExecution", back_populates="worker")

class Job(Base):
    __tablename__ = "jobs"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    queue_id = Column(UUID(as_uuid=True), ForeignKey("queues.id", ondelete="CASCADE"), nullable=False)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    type = Column(String, nullable=False)  # 'immediate', 'delayed', 'scheduled', 'recurring', 'batch'
    payload = Column(JSONType, nullable=False)
    status = Column(String, default="queued", nullable=False)  # 'queued', 'scheduled', 'claimed', 'running', 'completed', 'failed', 'dead_letter'
    priority = Column(Integer, default=0, nullable=False)
    retry_policy_id = Column(UUID(as_uuid=True), ForeignKey("retry_policies.id", ondelete="SET NULL"), nullable=True)
    attempt_count = Column(Integer, default=0, nullable=False)
    max_attempts = Column(Integer, default=3, nullable=False)
    run_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    cron_expression = Column(String, nullable=True)
    batch_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    idempotency_key = Column(String, nullable=True)
    claimed_by = Column(UUID(as_uuid=True), ForeignKey("workers.id", ondelete="SET NULL"), nullable=True)
    claimed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    
    # Relationships
    queue = relationship("Queue", back_populates="jobs")
    project = relationship("Project", back_populates="jobs")
    retry_policy = relationship("RetryPolicy")
    worker = relationship("Worker", foreign_keys=[claimed_by])
    
    # Dependencies: this job depends on the returned jobs
    dependencies = relationship(
        "Job",
        secondary=job_dependencies,
        primaryjoin=id==job_dependencies.c.job_id,
        secondaryjoin=id==job_dependencies.c.depends_on_job_id,
        backref="dependent_jobs"
    )
    
    executions = relationship("JobExecution", back_populates="job", cascade="all, delete-orphan")
    logs = relationship("JobLog", back_populates="job", cascade="all, delete-orphan")
    dlq_entry = relationship("DeadLetterQueue", back_populates="job", cascade="all, delete-orphan", uselist=False)

# Composite Index for worker claiming query: status, queue_id, run_at, priority DESC, created_at ASC
Index(
    'idx_jobs_claiming',
    Job.status,
    Job.queue_id,
    Job.run_at,
    Job.priority.desc(),
    Job.created_at.asc()
)

# Partial Unique Index for Idempotency Key within a Project
# Note: we use text because unique constraint with where clause needs text/expression helpers
Index(
    'idx_jobs_idempotency',
    Job.project_id,
    Job.idempotency_key,
    unique=True,
    postgresql_where=text("idempotency_key IS NOT NULL")
)

class JobExecution(Base):
    __tablename__ = "job_executions"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    worker_id = Column(UUID(as_uuid=True), ForeignKey("workers.id", ondelete="SET NULL"), nullable=True)
    attempt_number = Column(Integer, nullable=False)
    started_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    status = Column(String, nullable=False)  # 'running', 'completed', 'failed', 'dead_letter'
    error_message = Column(Text, nullable=True)
    duration_ms = Column(Integer, nullable=True)
    
    # Relationships
    job = relationship("Job", back_populates="executions")
    worker = relationship("Worker", back_populates="executions")
    logs = relationship("JobLog", back_populates="execution", cascade="all, delete-orphan")

class JobLog(Base):
    __tablename__ = "job_logs"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    execution_id = Column(UUID(as_uuid=True), ForeignKey("job_executions.id", ondelete="CASCADE"), nullable=False)
    ts = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    level = Column(String, nullable=False)  # 'INFO', 'WARNING', 'ERROR'
    message = Column(Text, nullable=False)
    
    # Relationships
    job = relationship("Job", back_populates="logs")
    execution = relationship("JobExecution", back_populates="logs")

class DeadLetterQueue(Base):
    __tablename__ = "dead_letter_queue"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    final_error = Column(Text, nullable=False)
    moved_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    original_payload = Column(JSONType, nullable=False)
    
    # Relationships
    job = relationship("Job", back_populates="dlq_entry")

class WorkerHeartbeat(Base):
    __tablename__ = "worker_heartbeats"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    worker_id = Column(UUID(as_uuid=True), ForeignKey("workers.id", ondelete="CASCADE"), nullable=False)
    ts = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    cpu_pct = Column(Float, nullable=False)
    memory_mb = Column(Float, nullable=False)
    
    # Relationships
    worker = relationship("Worker", back_populates="heartbeats")

class ScheduledJob(Base):
    __tablename__ = "scheduled_jobs"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    job_template = Column(JSONType, nullable=False)  # includes queue_id, type, payload, priority, retry_policy_id, max_attempts
    cron_expression = Column(String, nullable=False)
    next_run_at = Column(DateTime(timezone=True), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    last_triggered_at = Column(DateTime(timezone=True), nullable=True)
    
    # Relationships
    project = relationship("Project", back_populates="scheduled_jobs")
