from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import tempfile


class Error(Exception):
    """An actionable user-facing failure."""


CPUS = {"x86-64-v1": "x86-64", "x86-64-v3": "x86-64-v3"}


def cpu_flags(cpu: str) -> str:
    if cpu not in CPUS:
        raise Error(f"unsupported CPU profile: {cpu}")
    return f"-O2 -march={CPUS[cpu]} -mtune=generic -fstack-protector-strong -D_FORTIFY_SOURCE=3"


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def identity(value) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def atomic_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=".vfos-")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(canonical(value) + b"\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
        sync_dir(path.parent)
    finally:
        Path(name).unlink(missing_ok=True)


def sync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def relative_path(name: str) -> PurePosixPath:
    p = PurePosixPath(name)
    if not name or p.is_absolute() or ".." in p.parts or str(p) != name or name == ".":
        raise Error(f"unsafe package path: {name!r}")
    return p


def under(root: Path, name: str) -> Path:
    p = relative_path(name)
    current = root
    for part in p.parts[:-1]:
        current = current / part
        if current.is_symlink():
            raise Error(f"symlink ancestor is forbidden: {current}")
        if current.exists() and not current.is_dir():
            raise Error(f"non-directory ancestor: {current}")
    return root / p


def resolve_target(root: Path, name: str) -> Path:
    """Resolve target-root symlinks without following absolute links on the host."""
    pending = list(relative_path(name).parts)
    current, links = root, 0
    while pending:
        part = pending.pop(0)
        if part in ("", "."):
            continue
        if part == "..":
            if current == root:
                raise Error("symlink escapes target root")
            current = current.parent
            continue
        candidate = current / part
        if candidate.is_symlink():
            links += 1
            if links > 40:
                raise Error("too many target symlinks")
            target = PurePosixPath(os.readlink(candidate))
            if target.is_absolute():
                current = root
            pending = [p for p in target.parts if p != "/"] + pending
        else:
            current = candidate
    return current
