"""Read-only project deliverables. Never follow workspace symlinks."""
import io
import os
import re
import stat
import zipfile
from contextlib import contextmanager
from pathlib import Path

from fastapi import HTTPException

MAX_FILES = 1000
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 32 * 1024 * 1024
MAX_PREVIEW_BYTES = 256 * 1024
EXCLUDED = {"node_modules", "__pycache__", "venv", "dist", "build"}


def allowed(parts):
    return all(p and not p.startswith(".") and p not in EXCLUDED
               and not p.lower().endswith((".pem", ".key", ".pyc")) for p in parts)


@contextmanager
def project_root(workspace_root: str, project_id: str, workspace_path: str):
    if not re.fullmatch(r"[A-Za-z0-9_-]+", project_id):
        raise HTTPException(403, "Invalid project workspace")
    base = Path(workspace_root).resolve()
    expected = base / "projects" / project_id
    # The DB is not authority to expose arbitrary host paths.
    if Path(os.path.abspath(workspace_path)) != expected:
        raise HTTPException(403, "Project workspace is outside configured location")
    fds = []
    try:
        fd = os.open(base, os.O_RDONLY | os.O_DIRECTORY)
        fds.append(fd)
        for part in ("projects", project_id):
            fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            fds.append(fd)
        yield fd
    except FileNotFoundError:
        raise HTTPException(404, "Project workspace or file not found")
    except OSError:
        raise HTTPException(403, "Workspace entry is not accessible")
    finally:
        for fd in reversed(fds):
            os.close(fd)


@contextmanager
def open_file(root, path):
    parts = path.split("/")
    if (not allowed(parts) or any(p in {".", ".."} for p in parts)
            or "\\" in path or "\x00" in path):
        raise HTTPException(403, "Invalid or excluded artifact path")
    fds = []
    try:
        fd = root
        for part in parts[:-1]:
            fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            fds.append(fd)
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        fds.append(fd)
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise HTTPException(403, "Only regular files are available")
        yield fd
    finally:
        for fd in reversed(fds):
            os.close(fd)


def inventory(root):
    files = []
    total = 0

    def walk(fd, prefix="", depth=0):
        nonlocal total
        if depth > 32:
            raise HTTPException(413, "Artifact tree is too deep")
        for name in sorted(os.listdir(fd)):
            if not allowed([name]):
                continue
            path = prefix + name
            info = os.stat(name, dir_fd=fd, follow_symlinks=False)
            if stat.S_ISDIR(info.st_mode):
                child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                try:
                    walk(child, path + "/", depth + 1)
                finally:
                    os.close(child)
            elif stat.S_ISREG(info.st_mode):
                total += info.st_size
                if len(files) >= MAX_FILES or info.st_size > MAX_FILE_BYTES or total > MAX_TOTAL_BYTES:
                    raise HTTPException(413, "Artifact size or file count limit exceeded")
                files.append({"path": path, "size": info.st_size})
    walk(root)
    return files


def artifacts(workspace_root, project_id, workspace_path, mode, path=""):
    with project_root(workspace_root, project_id, workspace_path) as root:
        if mode == "preview":
            with open_file(root, path) as fd:
                data = os.read(fd, MAX_PREVIEW_BYTES + 1)
            if len(data) > MAX_PREVIEW_BYTES:
                raise HTTPException(413, "Preview exceeds 256 KiB")
            try:
                content = data.decode("utf-8")
                if "\x00" in content:
                    raise ValueError()
            except (UnicodeDecodeError, ValueError):
                raise HTTPException(415, "Only UTF-8 text can be previewed")
            return {"path": path, "content": content, "size": len(data)}
        files = inventory(root)
        if mode == "list":
            return {"files": files}
        output = io.BytesIO()
        total = 0
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            for item in files:
                with open_file(root, item["path"]) as fd:
                    data = bytearray()
                    while chunk := os.read(fd, 65536):
                        data.extend(chunk)
                        if len(data) > MAX_FILE_BYTES:
                            raise HTTPException(413, "Artifact file limit exceeded")
                total += len(data)
                if total > MAX_TOTAL_BYTES:
                    raise HTTPException(413, "Artifact total limit exceeded")
                archive.writestr(item["path"], data)
        return output.getvalue()
