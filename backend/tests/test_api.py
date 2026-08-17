"""API 测试：项目 CRUD + 运行 + 任务列表。"""
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

import app.database as db_mod
from app.models import Base
from app.main import app


@pytest.fixture(autouse=True)
async def setup_test_db(tmp_path, monkeypatch):
    """每个 API 测试使用独立临时 DB（monkeypatch 确保所有引用可见）。"""
    db_url = f"sqlite+aiosqlite:///{tmp_path}/api_test.db"
    new_engine = db_mod.create_async_engine(db_url, echo=False)
    new_factory = db_mod.async_sessionmaker(new_engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(db_mod, "engine", new_engine)
    monkeypatch.setattr(db_mod, "async_session_factory", new_factory)
    async with new_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield


@pytest.mark.asyncio
async def test_health():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_create_project():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/projects", json={
            "name": "班费管理系统",
            "requirement": "支持班级成员、收入、支出、余额统计、账单查询",
        })
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "班费管理系统"
    assert data["status"] == "planning"
    assert data["id"]


@pytest.mark.asyncio
async def test_list_projects():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post("/api/projects", json={"name": "P1", "requirement": "req1"})
        await client.post("/api/projects", json={"name": "P2", "requirement": "req2"})
        resp = await client.get("/api/projects")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


@pytest.mark.asyncio
async def test_get_project_detail():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create_resp = await client.post("/api/projects", json={
            "name": "Test", "requirement": "Test requirement"
        })
        project_id = create_resp.json()["id"]
        resp = await client.get(f"/api/projects/{project_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == project_id
    assert len(data["tasks"]) == 1
    assert data["tasks"][0]["agent_role"] == "pm"


@pytest.mark.asyncio
async def test_list_tasks():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create_resp = await client.post("/api/projects", json={
            "name": "Test", "requirement": "Test requirement"
        })
        project_id = create_resp.json()["id"]
        resp = await client.get(f"/api/projects/{project_id}/tasks")
    assert resp.status_code == 200
    tasks = resp.json()
    assert len(tasks) == 1
    assert tasks[0]["status"] == "pending"


@pytest.mark.asyncio
async def test_create_project_validation():
    """name 和 requirement 不能为空。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp1 = await client.post("/api/projects", json={"name": "", "requirement": "req"})
        assert resp1.status_code == 422

        resp2 = await client.post("/api/projects", json={"name": "test", "requirement": ""})
        assert resp2.status_code == 422


@pytest.mark.asyncio
async def test_get_nonexistent_project():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/projects/nonexistent")
    assert resp.status_code == 404
