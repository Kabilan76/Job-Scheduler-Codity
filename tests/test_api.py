import pytest
from httpx import AsyncClient
from backend.app.main import app
from backend.app.db import get_db
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from backend.app.db import Base

@pytest.mark.asyncio
async def test_auth_and_idempotency_api():
    """
    Test user registration, login, refresh tokens, and idempotency key handling
    via the FastAPI API.
    """
    # Initialize separate test db for API test
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        
    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False
    )
    
    # Override get_db dependency in app
    async def override_get_db():
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()
                
    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(app=app, base_url="http://test") as ac:
        # --- TEST REGISTER ---
        reg_payload = {
            "email": "api-test@example.com",
            "password": "password123",
            "name": "API Tester"
        }
        res_reg = await ac.post("/api/v1/auth/register", json=reg_payload)
        assert res_reg.status_code == 201
        user_data = res_reg.json()
        assert user_data["email"] == "api-test@example.com"
        
        # Try register again (duplicate check)
        res_reg_dup = await ac.post("/api/v1/auth/register", json=reg_payload)
        assert res_reg_dup.status_code == 400

        # --- TEST LOGIN ---
        login_payload = {
            "email": "api-test@example.com",
            "password": "password123"
        }
        res_login = await ac.post("/api/v1/auth/login", json=login_payload)
        assert res_login.status_code == 200
        tokens = res_login.json()
        assert "access_token" in tokens
        assert "refresh_token" in tokens
        
        access_token = tokens["access_token"]
        refresh_token = tokens["refresh_token"]

        # --- TEST REFRESH ---
        res_refresh = await ac.post(
            "/api/v1/auth/refresh", 
            json={"refresh_token": refresh_token}
        )
        assert res_refresh.status_code == 200
        new_tokens = res_refresh.json()
        assert "access_token" in new_tokens
        
        auth_headers = {"Authorization": f"Bearer {new_tokens['access_token']}"}

        # --- TEST GET ORG & PROJECT (Auto created on Register) ---
        res_orgs = await ac.get("/api/v1/organizations", headers=auth_headers)
        assert res_orgs.status_code == 200
        orgs = res_orgs.json()
        assert len(orgs) > 0
        org_id = orgs[0]["id"]
        
        res_projs = await ac.get(f"/api/v1/projects?org_id={org_id}", headers=auth_headers)
        assert res_projs.status_code == 200
        projects = res_projs.json()
        assert len(projects) > 0
        project_id = projects[0]["id"]

        # --- TEST QUEUE CREATION ---
        queue_payload = {
            "project_id": project_id,
            "name": "api-queue",
            "priority": 5,
            "max_concurrency": 2
        }
        res_queue = await ac.post("/api/v1/queues", json=queue_payload, headers=auth_headers)
        assert res_queue.status_code == 201
        queue = res_queue.json()
        queue_id = queue["id"]

        # --- TEST JOB CREATION & IDEMPOTENCY KEY ---
        job_payload = {
            "queue_id": queue_id,
            "project_id": project_id,
            "type": "immediate",
            "payload": {"test": "data"},
            "priority": 10,
            "idempotency_key": "unique_idemp_key_123",
            "max_attempts": 3
        }
        
        # First creation
        res_job1 = await ac.post("/api/v1/jobs", json=job_payload, headers=auth_headers)
        assert res_job1.status_code == 201
        job1 = res_job1.json()
        assert job1["idempotency_key"] == "unique_idemp_key_123"
        
        # Second creation with SAME idempotency key
        res_job2 = await ac.post("/api/v1/jobs", json=job_payload, headers=auth_headers)
        # Should return HTTP 200 and the SAME job record (same ID)
        assert res_job2.status_code == 200
        job2 = res_job2.json()
        assert job1["id"] == job2["id"]
        assert job2["idempotency_key"] == "unique_idemp_key_123"

    # Clean up overrides and engine
    app.dependency_overrides.clear()
    await engine.dispose()
