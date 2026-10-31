"""Artifact API integration tests with real SQLite and workspace files."""
import io
import os
import zipfile

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

import app.database as db_mod
from app.api import projects
from app.config import Settings
from app.main import app
from app.models import Base, Project
from app.services import artifacts


@pytest.fixture
async def client(tmp_path, monkeypatch):
    engine = db_mod.create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/test.db")
    factory = db_mod.async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(db_mod, "async_session_factory", factory)
    monkeypatch.setattr(projects, "_get_settings", lambda: Settings(workspace_root=str(tmp_path)))
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.post("/api/projects", json={"name": "artifact", "requirement": "demo"})
        project = response.json()
        root = tmp_path / "projects" / project["id"]
        yield c, f'/api/projects/{project["id"]}/artifacts', root, factory
    await engine.dispose()


async def test_list_preview_zip(client):
    c, url, root, _ = client
    (root / "src").mkdir()
    (root / "src" / "你好.py").write_text('print("<script>你好</script>")', encoding="utf-8")
    (root / "image.bin").write_bytes(b"\x00\xff")
    (root / ".env").write_text("SECRET=hidden")
    (root / "private.key").write_text("hidden")
    (root / "node_modules").mkdir()
    (root / "node_modules" / "dep.js").write_text("hidden")
    listing = await c.get(url)
    assert listing.status_code == 200
    assert [f["path"] for f in listing.json()["files"]] == ["image.bin", "src/你好.py"]
    preview = await c.get(url + "/file", params={"path": "src/你好.py"})
    assert preview.status_code == 200
    assert preview.json()["content"] == 'print("<script>你好</script>")'
    assert (await c.get(url + "/file", params={"path": "image.bin"})).status_code == 415
    download = await c.get(url + "/download")
    assert download.status_code == 200
    assert download.headers["content-type"] == "application/zip"
    assert "attachment" in download.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(download.content)) as z:
        assert sorted(z.namelist()) == ["image.bin", "src/你好.py"]
        assert z.read("src/你好.py").decode() == preview.json()["content"]


@pytest.mark.parametrize("path", ["../secret", "/etc/passwd", "src/../../secret", "src\\file", ".env", ".agent/memory.json", "private.key", "a//b", "a\x00b"])
async def test_reject_paths(client, path):
    c, url, _, _ = client
    assert (await c.get(url + "/file", params={"path": path})).status_code == 403


async def test_symlinks_and_special_files(client, tmp_path):
    c, url, root, _ = client
    (tmp_path / "secret").write_text("hidden")
    (root / "link").symlink_to(tmp_path / "secret")
    (root / "folder").symlink_to(tmp_path, target_is_directory=True)
    os.mkfifo(root / "pipe")
    assert (await c.get(url)).json() == {"files": []}
    for path in ["link", "folder/secret", "pipe"]:
        assert (await c.get(url + "/file", params={"path": path})).status_code == 403
    assert zipfile.ZipFile(io.BytesIO((await c.get(url + "/download")).content)).namelist() == []


async def test_missing_and_workspace_boundaries(client, tmp_path):
    c, url, root, factory = client
    assert (await c.get("/api/projects/absent/artifacts")).status_code == 404
    assert (await c.get(url + "/file", params={"path": "absent"})).status_code == 404
    assert (await c.get(url)).json() == {"files": []}
    async with factory() as db:
        project = await db.get(Project, root.name)
        project.workspace_path = str(tmp_path)
        await db.commit()
    assert (await c.get(url)).status_code == 403
    async with factory() as db:
        project = await db.get(Project, root.name)
        project.workspace_path = str(root)
        await db.commit()
    import shutil
    shutil.rmtree(root)
    assert (await c.get(url)).status_code == 404
    root.symlink_to(tmp_path, target_is_directory=True)
    assert (await c.get(url)).status_code == 403


async def test_limits(client, monkeypatch):
    c, url, root, _ = client
    (root / "large.txt").write_bytes(b"a" * (artifacts.MAX_PREVIEW_BYTES + 1))
    assert (await c.get(url + "/file", params={"path": "large.txt"})).status_code == 413
    monkeypatch.setattr(artifacts, "MAX_FILE_BYTES", 10)
    for suffix in ["", "/download"]:
        assert (await c.get(url + suffix)).status_code == 413
    (root / "large.txt").write_text("ok")
    monkeypatch.setattr(artifacts, "MAX_TOTAL_BYTES", 1)
    assert (await c.get(url + "/download")).status_code == 413
    monkeypatch.setattr(artifacts, "MAX_TOTAL_BYTES", 100)
    monkeypatch.setattr(artifacts, "MAX_FILES", 0)
    assert (await c.get(url)).status_code == 413
