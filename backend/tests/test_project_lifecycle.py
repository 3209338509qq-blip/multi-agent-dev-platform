import asyncio

from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import database
from app.agents import AgentResult, BaseAgent, ScriptedAgent
from app.agents import registry as registry_module
from app.config import get_settings
from app.main import app
from app.models import AgentRole, AgentRun, Event as StoredEvent, RunStatus, TaskStatus
from app.orchestrator import AgentRegistry
from app.services.event_bus import event_bus


@pytest.fixture
def isolated_project_db(monkeypatch, tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/new/data/review.db")
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(
        database, "async_session_factory", async_sessionmaker(engine, expire_on_commit=False),
    )
    monkeypatch.setattr(get_settings(), "workspace_root", str(tmp_path / "projects-root"))
    monkeypatch.setattr(get_settings(), "task_max_retries", 0)
    active_registry = AgentRegistry()
    monkeypatch.setattr(registry_module, "_registry", active_registry)
    yield active_registry
    asyncio.run(engine.dispose())


@pytest.fixture
async def client(isolated_project_db):
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
            yield http


async def project_path(client):
    response = await client.post("/api/projects", json={"name": "fixture", "requirement": "fixture"})
    assert response.status_code == 201, response.text
    return f"/api/projects/{response.json()['id']}"


async def wait_for_status(client, path, expected):
    async with asyncio.timeout(3):
        while True:
            project = (await client.get(path)).json()
            if project["status"] == expected:
                return project
            await asyncio.sleep(0.02)


class PausedPM(BaseAgent):
    role = AgentRole.PM

    def __init__(self):
        self.started = asyncio.Event()
        self.stopped = asyncio.Event()

    async def run(self, ctx):
        self.started.set()
        try:
            await asyncio.Event().wait()
        finally:
            self.stopped.set()


async def test_duplicate_run_and_cancellation(client, isolated_project_db):
    agent = PausedPM()
    isolated_project_db.register(agent)
    path = await project_path(client)
    responses = await asyncio.gather(*(client.post(path + "/run") for _ in range(2)))
    assert sorted(response.status_code for response in responses) == [200, 409]
    await asyncio.wait_for(agent.started.wait(), timeout=2)

    project = (await client.get(path)).json()
    assert project["status"] == "architecting"
    assert project["tasks"][0]["status"] == "running"

    response = await client.post(path + "/cancel")
    assert response.status_code == 200
    assert agent.stopped.is_set()
    project = (await client.get(path)).json()
    assert project["status"] == "cancelled"
    assert project["tasks"][0]["status"] == "cancelled"
    async with database.async_session_factory() as db:
        runs = list(await db.scalars(select(AgentRun)))
        assert [run.status for run in runs] == [RunStatus.CANCELLED]

    history = (await client.get(path + "/events")).json()
    assert history[-1]["type"] == "project_cancelled"
    assert "project_completed" not in {event["type"] for event in history}


async def test_failed_project_rerun_preserves_completed_tasks(client, isolated_project_db):
    pm = ScriptedAgent(AgentRole.PM, {"output": {"tasks": [
        {"role": "architect", "depends_on": ["pm"]},
        {"role": "backend", "depends_on": ["architect"]},
    ]}})
    architect = ScriptedAgent(AgentRole.ARCHITECT, {"behavior": "fail"})
    backend = ScriptedAgent(AgentRole.BACKEND)
    for agent in [pm, architect, backend]:
        isolated_project_db.register(agent)
    path = await project_path(client)

    assert (await client.post(path + "/run")).status_code == 200
    project = await wait_for_status(client, path, "failed")
    tasks = {task["agent_role"]: task for task in project["tasks"]}
    assert {role: task["status"] for role, task in tasks.items()} == {
        "pm": "success", "architect": "failed", "backend": "blocked",
    }
    assert all(len(task["id"]) == 32 for task in tasks.values())
    run = app.state.project_runs.get(project["id"])
    if run is not None:
        await asyncio.wait_for(asyncio.shield(run[1]), timeout=3)
    history = (await client.get(path + "/events")).json()
    blocked = next(event for event in history if event["type"] == "task_blocked")
    assert blocked["task_id"] == tasks["backend"]["id"]
    suffix = (await client.get(path + f"/events?after_seq={blocked['seq']}")).json()
    assert suffix == history[history.index(blocked):]

    architect = ScriptedAgent(AgentRole.ARCHITECT)
    isolated_project_db.register(architect)
    assert (await client.post(path + "/run")).status_code == 200
    project = await wait_for_status(client, path, "completed")
    assert (pm.run_count, architect.run_count, backend.run_count) == (1, 1, 1)
    assert all(task["status"] == "success" and task["error"] is None for task in project["tasks"])
    assert {task["id"] for task in project["tasks"]} == {task["id"] for task in tasks.values()}


async def test_task_timeout_does_not_report_completion(client, isolated_project_db, monkeypatch):
    monkeypatch.setattr(get_settings(), "agent_timeout_seconds", 0.1)
    agent = PausedPM()
    isolated_project_db.register(agent)
    path = await project_path(client)
    assert (await client.post(path + "/run")).status_code == 200
    project = await wait_for_status(client, path, "failed")
    assert agent.stopped.is_set()
    assert project["tasks"][0]["error"] == "agent timeout"
    async with database.async_session_factory() as db:
        assert (await db.scalar(select(AgentRun.status))) == RunStatus.TIMEOUT


def test_websocket_replays_old_rows_and_unsubscribes(isolated_project_db):
    before = len(event_bus._subscribers)
    with TestClient(app) as client:
        first = client.post("/api/projects", json={"name": "fixture", "requirement": "old project"})
        assert first.status_code == 201
        project_id = first.json()["id"]

        async def insert_legacy_event():
            async with database.async_session_factory() as db:
                event = StoredEvent(project_id=project_id, type="legacy", seq=0, payload={"seq": 0})
                db.add(event)
                await db.commit()
                return event.id

        legacy_id = client.portal.call(insert_legacy_event)
        path = f"/ws/projects/{project_id}?after_seq={legacy_id}"
        with client.websocket_connect(path) as websocket:
            event = websocket.receive_json()
            assert (event["type"], event["seq"], event["payload"]["seq"]) == ("legacy", legacy_id, legacy_id)
            websocket.send_json({"type": "ping"})
            assert websocket.receive_json() == {"type": "pong"}
            assert len(event_bus._subscribers) == before + 1

            cancelled = client.post(f"/api/projects/{project_id}/cancel")
            assert cancelled.status_code == 200
            task_event = websocket.receive_json()
            project_event = websocket.receive_json()
            assert [task_event["type"], project_event["type"]] == ["task_cancelled", "project_cancelled"]
            assert legacy_id < task_event["seq"] < project_event["seq"]

        assert len(event_bus._subscribers) == before
        with client.websocket_connect(f"/ws/projects/{project_id}?after_seq={task_event['seq'] + 1}") as websocket:
            assert websocket.receive_json()["seq"] == project_event["seq"]
        assert len(event_bus._subscribers) == before


def test_documented_sqlite_url_is_relative_to_repository():
    url = database.resolve_database_url("sqlite+aiosqlite:///./backend/data/platform.db")
    assert url.database == str(database.BASE_DIR / "data" / "platform.db")
    memory = database.resolve_database_url("sqlite+aiosqlite:///:memory:")
    assert memory.database == ":memory:"
