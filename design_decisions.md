# Design Decisions Document

This document outlines key technical decisions, architectural trade-offs, and rationale behind design choices made during the implementation of the Distributed Job Scheduler.

## 1. Concurrency & Locking Strategy

### Choice: PostgreSQL `SELECT ... FOR UPDATE SKIP LOCKED` vs. Redis-based Distributed Locks (Redlock)
- **Decision:** We use PostgreSQL row-level locking via `SELECT ... FOR UPDATE SKIP LOCKED`.
- **Rationale:**
  - **Single Source of Truth:** Placing both queue metadata, job states, and lock states in the same ACID-compliant database guarantees strict consistency. We avoid complex synchronization bugs where Redis distributed locks and Postgres records drift out of sync.
  - **No Lock Orphaning:** Postgres automatically releases row locks if a worker's connection/transaction dies. With Redis locks, a worker crash requires wait times for TTL expiration or manual intervention.
  - **Efficiency:** `SKIP LOCKED` allows multiple workers to query the `jobs` table simultaneously without blocking each other. Each worker skips locked rows and immediately grabs the next available job, scaling throughput linearly with worker count.

---

## 2. Retry Policy & Backoff Math

### Choice: Multi-strategy Retry Engine
- **Strategies Supported:** `fixed`, `linear`, `exponential`.
- **Formulas:**
  - **Fixed:** `delay = base_delay`
  - **Linear:** `delay = base_delay * attempt_count`
  - **Exponential:** `delay = base_delay * (2 ^ (attempt_count - 1))`
- **Capping & Limits:**
  - All calculated delays are capped at `max_delay_seconds` to prevent infinite/runaway delays.
  - If `attempt_count >= max_attempts`, the job transitions to `dead_letter` and enters the Dead Letter Queue.

---

## 3. Database Integrity & Cascade/Delete Behavior

- **Organizations & Projects:** Deleting an organization cascades to its projects, queues, and jobs. This ensures no orphan configuration data remains.
- **Queues:** Deleting a queue cascades to its jobs (`ON DELETE CASCADE`). If a queue is deleted, we assume all jobs within it are cancelled.
- **Workers:** Deleting a worker sets the job's `claimed_by` FK to `NULL` (`ON DELETE SET NULL`). This is a critical safety feature: if a worker process is decommissioned or hard-killed, its currently running jobs will be freed to be claimed by other active workers, rather than being orphaned in a `claimed` state forever.
- **Job Executions & Logs:** Deleted jobs cascade to delete their logs and executions. This keeps the database clean, though in a production setup, these would be archived.

---

## 4. Database Portability & Fallback Mode (SQLite & In-Memory Redis Mock)

To ensure the system is immediately runnable on host environments where Docker Desktop or native PostgreSQL/Redis are not installed, the application features an automatic **Fallback Mode**:

1. **Database Fallback:**
   - If the database URL starts with `sqlite`, the application initializes SQLite.
   - For job claiming, since SQLite does not support `FOR UPDATE SKIP LOCKED`, we implement a **Compare-And-Swap (CAS)** mechanism within a serialized transaction:
     ```sql
     -- Step 1: Select candidate
     SELECT id FROM jobs WHERE status = 'queued' AND queue_id = :queue_id AND run_at <= :now ORDER BY priority DESC, created_at ASC LIMIT 1;
     -- Step 2: Attempt claim
     UPDATE jobs SET status = 'claimed', claimed_by = :worker_id, claimed_at = :now WHERE id = :id AND status = 'queued';
     ```
     If the update row count is `1`, the claim is successful. If `0` (another worker claimed it first), we retry or skip.
   - For PostgreSQL, the backend natively executes the single-step `SELECT ... FOR UPDATE SKIP LOCKED` query.

2. **Redis & Pub/Sub Fallback:**
   - If the Redis server is unreachable, the system falls back to an **In-Memory Pub/Sub system** (using Python `asyncio.Queue` and shared memory structures) for real-time WebSockets status and log streaming.
   - This allows local development and full automated testing to run out-of-the-box without external dependencies.

