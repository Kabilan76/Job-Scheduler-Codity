from datetime import datetime
from typing import List, Optional, Any, Dict
from uuid import UUID
from pydantic import BaseModel, EmailStr, Field

# --- AUTH SCHEMAS ---

class UserRegister(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=6)
    name: str = Field(..., min_length=1)

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class UserOut(BaseModel):
    id: UUID
    email: EmailStr
    name: str
    created_at: datetime

    class Config:
        from_attributes = True

class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"

class RefreshTokenRequest(BaseModel):
    refresh_token: str

# --- ORGANIZATION & PROJECT SCHEMAS ---

class OrganizationCreate(BaseModel):
    name: str = Field(..., min_length=1)

class OrganizationOut(BaseModel):
    id: UUID
    name: str
    owner_id: UUID
    created_at: datetime

    class Config:
        from_attributes = True

class ProjectCreate(BaseModel):
    org_id: UUID
    name: str = Field(..., min_length=1)

class ProjectOut(BaseModel):
    id: UUID
    org_id: UUID
    name: str
    created_at: datetime

    class Config:
        from_attributes = True

# --- RETRY POLICY SCHEMAS ---

class RetryPolicyCreate(BaseModel):
    name: str = Field(..., min_length=1)
    strategy: str = Field(..., pattern="^(fixed|linear|exponential)$")
    base_delay_seconds: int = Field(default=5, ge=1)
    max_retries: int = Field(default=3, ge=0)
    max_delay_seconds: int = Field(default=3600, ge=1)

class RetryPolicyOut(BaseModel):
    id: UUID
    name: str
    strategy: str
    base_delay_seconds: int
    max_retries: int
    max_delay_seconds: int

    class Config:
        from_attributes = True

# --- QUEUE SCHEMAS ---

class QueueCreate(BaseModel):
    project_id: UUID
    name: str = Field(..., min_length=1)
    priority: int = Field(default=0)
    max_concurrency: int = Field(default=1, ge=1)
    default_retry_policy_id: Optional[UUID] = None

class QueueOut(BaseModel):
    id: UUID
    project_id: UUID
    name: str
    priority: int
    max_concurrency: int
    is_paused: bool
    default_retry_policy_id: Optional[UUID]
    created_at: datetime

    class Config:
        from_attributes = True

# --- JOB SCHEMAS ---

class JobCreate(BaseModel):
    queue_id: UUID
    project_id: UUID
    type: str = Field(..., pattern="^(immediate|delayed|scheduled|recurring|batch)$")
    payload: Dict[str, Any]
    priority: int = Field(default=0)
    idempotency_key: Optional[str] = None
    depends_on_ids: Optional[List[UUID]] = Field(default_factory=list)
    retry_policy_id: Optional[UUID] = None
    max_attempts: Optional[int] = 3
    run_at: Optional[datetime] = None  # for delayed jobs
    cron_expression: Optional[str] = None  # for scheduled/recurring jobs

class JobOut(BaseModel):
    id: UUID
    queue_id: UUID
    project_id: UUID
    type: str
    payload: Dict[str, Any]
    status: str
    priority: int
    retry_policy_id: Optional[UUID]
    attempt_count: int
    max_attempts: int
    run_at: datetime
    cron_expression: Optional[str]
    batch_id: Optional[UUID]
    idempotency_key: Optional[str]
    claimed_by: Optional[UUID]
    claimed_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class JobExecutionOut(BaseModel):
    id: UUID
    job_id: UUID
    worker_id: Optional[UUID]
    attempt_number: int
    started_at: datetime
    finished_at: Optional[datetime]
    status: str
    error_message: Optional[str]
    duration_ms: Optional[int]

    class Config:
        from_attributes = True

class JobLogOut(BaseModel):
    id: UUID
    job_id: UUID
    execution_id: UUID
    ts: datetime
    level: str
    message: str

    class Config:
        from_attributes = True

# --- BATCH SCHEMA ---

class BatchProgressOut(BaseModel):
    batch_id: UUID
    status: str
    total_jobs: int
    completed_jobs: int
    failed_jobs: int
    running_jobs: int
    queued_jobs: int
    jobs: List[JobOut]

# --- WORKER SCHEMAS ---

class WorkerOut(BaseModel):
    id: UUID
    hostname: str
    status: str
    last_seen_at: datetime
    current_job_id: Optional[UUID]
    started_at: datetime

    class Config:
        from_attributes = True

# --- METRICS SCHEMAS ---

class DashboardMetricsOut(BaseModel):
    status_counts: Dict[str, int]
    active_workers_count: int
    avg_execution_time_ms: float
    throughput_series: List[Dict[str, Any]]
