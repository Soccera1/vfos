"""Deterministic packages and rollback-journalled filesystem transactions.

Archives are verified before writes. No install hooks or archive extraction run as
root. Mutations are serialized and an interrupted transaction rolls back at the
next opening of the database. Callers must keep the target tree private while
installing (as with other system package managers).
"""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import io
import json
import os
from pathlib import Path
import shutil
import stat
import tarfile
import tempfile

from .common import CPUS, Error, atomic_json, canonical, digest, identity, relative_path, sync_dir, under
from .recipes import NAME


def file_info(path):
    mode = stat.S_IMODE(path.lstat().st_mode)
    if path.is_symlink():
        return {"type": "symlink", "target": os.readlink(path), "mode": mode}
    if path.is_file():
        return {"type": "file", "sha256": digest(path), "mode": mode}
    raise Error(f"unsupported payload node: {path}")


def same(path, info):
    if not path.exists() and not path.is_symlink():
        return False
    try:
        return file_info(path) == info
    except Error:
        return False


def pack(stage: Path, metadata: dict, output: Path):
    files = {}
    for path in sorted(stage.rglob("*")):
        name = path.relative_to(stage).as_posix()
        relative_path(name)
        if name == "var/lib/vfos" or name.startswith("var/lib/vfos/"):
            raise Error("package payload may not overwrite the database")
        if path.is_dir() and not path.is_symlink():
            continue
        info = file_info(path)
        if info["mode"] & 0o6000:
            raise Error(f"setuid/setgid package payload is forbidden: {name}")
        files[name] = info
    manifest = {**metadata, "format": 1, "files": files}
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=output.parent, delete=False) as f:
        temporary = Path(f.name)
    try:
        with tarfile.open(temporary, "w:xz", format=tarfile.PAX_FORMAT) as tar:
            data = canonical(manifest)
            entry = tarfile.TarInfo("manifest.json")
            entry.size, entry.mode = len(data), 0o644
            tar.addfile(entry, io.BytesIO(data))
            for name, info in files.items():
                entry = tarfile.TarInfo("root/" + name)
                entry.mode = info["mode"]
                if info["type"] == "symlink":
                    entry.type, entry.linkname = tarfile.SYMTYPE, info["target"]
                    tar.addfile(entry)
                else:
                    entry.size = (stage / name).stat().st_size
                    with (stage / name).open("rb") as f:
                        tar.addfile(entry, f)
        with temporary.open("rb") as f:
            os.fsync(f.fileno())
        os.replace(temporary, output)
        atomic_json(output.with_suffix(output.suffix + ".sha256.json"), {"sha256": digest(output)})
    finally:
        temporary.unlink(missing_ok=True)
    return manifest


class Package:
    def __init__(self, path: Path, expected_hash: str | None = None):
        self.path = path
        self.sha256 = digest(path)
        if expected_hash is not None and self.sha256 != expected_hash:
            raise Error(f"package checksum mismatch: {path}")
        self.temporary = tempfile.TemporaryDirectory(prefix="vfos-package-")
        self.stage = Path(self.temporary.name)
        try:
            with tarfile.open(path, "r:xz") as tar:
                members = tar.getmembers()
                names = [m.name for m in members]
                if len(set(names)) != len(names) or "manifest.json" not in names:
                    raise Error("duplicate archive members or missing manifest")
                member = tar.getmember("manifest.json")
                if not member.isfile() or member.size > 16 * 1024 * 1024:
                    raise Error("invalid package manifest")
                self.meta = json.load(tar.extractfile(member))
                if self.meta.get("format") != 1 or self.meta.get("cpu") not in CPUS:
                    raise Error("unsupported package format or CPU")
                for field in ("name", "version", "abi"):
                    if not NAME.fullmatch(self.meta.get(field, "")):
                        raise Error(f"invalid package {field}")
                files = self.meta.get("files")
                if not isinstance(files, dict) or set(names) != {"manifest.json"} | {"root/" + n for n in files}:
                    raise Error("archive payload differs from manifest")
                for name in files:
                    relative_path(name)
                    if name == "var/lib/vfos" or name.startswith("var/lib/vfos/"):
                        raise Error("package payload may not overwrite the database")
                    # Payload ancestors may never themselves be a file/symlink.
                    if any(str(p) in files for p in Path(name).parents if str(p) != "."):
                        raise Error(f"payload ancestor conflict: {name}")
                for name, info in files.items():
                    m = tar.getmember("root/" + name)
                    if m.mode & 0o6000 or m.mode != info["mode"]:
                        raise Error(f"invalid payload permissions: {name}")
                    p = under(self.stage, name)
                    p.parent.mkdir(parents=True, exist_ok=True)
                    if m.isfile() and info["type"] == "file":
                        with tar.extractfile(m) as src, p.open("wb") as dest:
                            shutil.copyfileobj(src, dest)
                        p.chmod(m.mode)
                    elif m.issym() and info["type"] == "symlink" and m.linkname == info["target"]:
                        # Absolute links are valid *inside* a future chroot; never follow them here.
                        p.symlink_to(m.linkname)
                    else:
                        raise Error(f"unsupported archive entry: {name}")
                    if file_info(p) != info:
                        raise Error(f"payload checksum mismatch: {name}")
        except BaseException:
            self.temporary.cleanup()
            raise

    def close(self):
        self.temporary.cleanup()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


class Database:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.state = under(self.root, "var/lib/vfos/state")
        if self.state.is_symlink():
            raise Error("database path is a symlink")
        self.state.mkdir(parents=True, exist_ok=True)
        self.dbfile = self.state / "packages.json"
        self.journal = self.state / "transaction"

    @contextmanager
    def locked(self):
        with (self.state / "lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            self.recover()
            self.data = json.loads(self.dbfile.read_text()) if self.dbfile.exists() else {"format": 1, "cpu": None, "packages": {}, "rebuild": []}
            yield

    def recover(self):
        record = self.journal / "journal.json"
        if not record.exists():
            if self.journal.exists():
                shutil.rmtree(self.journal)
            return
        journal = json.loads(record.read_text())
        if not (self.journal / "committed").exists():
            for name, backup in reversed(list(journal["paths"].items())):
                p = under(self.root, name)
                if p.is_dir() and not p.is_symlink():
                    raise Error(f"cannot recover over directory {p}; restore it manually")
                p.unlink(missing_ok=True)
                if backup is not None:
                    self.copy(self.journal / backup, p)
            if journal["database"] is None:
                self.dbfile.unlink(missing_ok=True)
            else:
                atomic_json(self.dbfile, journal["database"])
        shutil.rmtree(self.journal)
        sync_dir(self.state)

    @staticmethod
    def copy(src, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        if src.is_symlink():
            dest.symlink_to(os.readlink(src))
        else:
            shutil.copyfile(src, dest)
            dest.chmod(stat.S_IMODE(src.stat().st_mode))
            with dest.open("rb") as f:
                os.fsync(f.fileno())
        sync_dir(dest.parent)

    def transaction(self, writes, deletes, data):
        paths = list(dict.fromkeys(list(writes) + list(deletes)))
        for name in paths:
            p = under(self.root, name)
            if p.exists() and p.is_dir() and not p.is_symlink():
                raise Error(f"refusing to replace directory: {p}")
        self.journal.mkdir()
        backups = {}
        for i, name in enumerate(paths):
            p = under(self.root, name)
            backup = f"backup-{i}" if p.exists() or p.is_symlink() else None
            if backup:
                self.copy(p, self.journal / backup)
            backups[name] = backup
        atomic_json(self.journal / "journal.json", {"paths": backups, "database": self.data if self.dbfile.exists() else None})
        sync_dir(self.state)
        try:
            for name in paths:
                p = under(self.root, name)
                p.unlink(missing_ok=True)
                if name in writes:
                    self.copy(writes[name], p)
                elif p.parent.exists():
                    sync_dir(p.parent)
            atomic_json(self.dbfile, data)
            atomic_json(self.journal / "committed", True)
        except BaseException:
            self.recover()
            raise
        self.recover()
        self.data = data

    def install(self, package: Package, upgrade=False):
        with self.locked():
            meta = package.meta
            name = meta["name"]
            if self.data["cpu"] not in (None, meta["cpu"]):
                raise Error("cannot mix CPU profiles in one system")
            installed = self.data["packages"]
            old = installed.get(name)
            if old and not upgrade:
                raise Error(f"{name} is already installed; use upgrade")
            for dep, abi in meta.get("dependencies", {}).items():
                if dep not in installed or installed[dep]["abi"] != abi:
                    raise Error(f"{name} needs {dep} ABI {abi}")
            owners = {p: n for n, pkg in installed.items() for p in pkg["files"]}
            writes, deletes, files = {}, [], dict(meta["files"])
            for p, info in meta["files"].items():
                dest = under(self.root, p)
                owner = owners.get(p)
                if owner and owner != name:
                    raise Error(f"file conflict: {p} belongs to {owner}")
                exists = dest.exists() or dest.is_symlink()
                if exists and not owner:
                    raise Error(f"unowned file conflict: {p}")
                previous = old["files"].get(p) if old else None
                if previous and p.startswith("etc/") and exists and not same(dest, previous):
                    if info != previous:
                        candidate = p + ".vfos-new"
                        cpath = under(self.root, candidate)
                        if cpath.exists() or cpath.is_symlink() or candidate in owners or candidate in files:
                            raise Error(f"resolve existing configuration candidate: {candidate}")
                        writes[candidate] = package.stage / p
                        files[candidate] = info
                    files[p] = previous  # retain baseline, so verification reports local edits
                else:
                    writes[p] = package.stage / p
            for p, info in (old or {}).get("files", {}).items():
                if p not in files:
                    dest = under(self.root, p)
                    if same(dest, info) or not p.startswith("etc/"):
                        deletes.append(p)
            data = json.loads(json.dumps(self.data))
            data["cpu"] = meta["cpu"]
            data["packages"][name] = {**meta, "files": files, "archive_sha256": package.sha256}
            data["rebuild"] = [n for n in data["rebuild"] if n != name]
            if old and old["abi"] != meta["abi"]:
                affected = {name}
                while True:
                    more = {n for n, p in installed.items() if affected.intersection(p.get("dependencies", {}))} - affected
                    if not more:
                        break
                    affected |= more
                data["rebuild"] = sorted(set(data["rebuild"]) | (affected - {name}))
            self.transaction(writes, deletes, data)
            return data["rebuild"]

    def remove(self, name):
        with self.locked():
            if name not in self.data["packages"]:
                raise Error(f"package is not installed: {name}")
            dependents = [n for n, p in self.data["packages"].items() if name in p.get("dependencies", {})]
            if dependents:
                raise Error(f"{name} is required by: {', '.join(dependents)}")
            old = self.data["packages"][name]
            deletes = [p for p, info in old["files"].items() if not p.startswith("etc/") or same(under(self.root, p), info)]
            data = json.loads(json.dumps(self.data))
            del data["packages"][name]
            data["rebuild"] = [n for n in data["rebuild"] if n != name]
            self.transaction({}, deletes, data)

    def query(self):
        with self.locked():
            return self.data

    def verify(self, strict=False):
        with self.locked():
            result = [{"package": n, "path": p, "configuration": p.startswith("etc/")}
                      for n, pkg in self.data["packages"].items() for p, info in pkg["files"].items()
                      if not same(under(self.root, p), info)]
            if strict:
                owned = {p for pkg in self.data["packages"].values() for p in pkg["files"]}
                for path in self.root.rglob("*"):
                    name = path.relative_to(self.root).as_posix()
                    if name.startswith("var/lib/vfos/") or (path.is_dir() and not path.is_symlink()):
                        continue
                    if name not in owned:
                        result.append({"package": None, "path": name, "unowned": True})
            return result
