from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request

from .common import Error, atomic_json, cpu_flags, digest, identity
from .packages import Database, Package, pack


ENGINE = Path(__file__).parent


def fetch(source, cache: Path, offline=False):
    cache.mkdir(parents=True, exist_ok=True)
    dest = cache / (source["sha256"] + "-" + source["filename"])
    with (cache / (source["sha256"] + ".lock")).open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if dest.exists():
            if digest(dest) != source["sha256"]:
                raise Error(f"corrupt cached source: {dest}; remove it and retry")
            return dest
        if offline:
            raise Error(f"source is not cached: {source['filename']}")
        fd, name = tempfile.mkstemp(dir=cache)
        tmp = Path(name)
        try:
            with os.fdopen(fd, "wb") as output, urllib.request.urlopen(source["url"], timeout=60) as response:
                if not response.url.startswith("https://"):
                    raise Error("source redirected to an insecure URL")
                shutil.copyfileobj(response, output)
            if digest(tmp) != source["sha256"]:
                raise Error(f"source checksum mismatch: {source['url']}")
            os.replace(tmp, dest)
        finally:
            tmp.unlink(missing_ok=True)
    return dest


def unpack(source, dest):
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(source) as archive:
        # Python's data filter rejects path escapes, escaping links and devices.
        archive.extractall(dest, filter="data")


class Builder:
    def __init__(self, repo, cpu, cache, output, builder_root=None, host_tools=False, jobs=2, offline=False):
        self.repo, self.cpu = repo, cpu
        self.cache, self.output = cache.resolve(), output.resolve() / cpu
        self.builder_root = builder_root.resolve() if builder_root else None
        self.host_tools, self.jobs, self.offline = host_tools, jobs, offline
        if os.geteuid() == 0:
            raise Error("source builds must run as an unprivileged user")
        if not shutil.which("bwrap"):
            raise Error("bubblewrap is required for isolated builds")
        if bool(self.builder_root) == bool(host_tools):
            raise Error("select a VFOS --builder-root or development-only --host-tools")
        if jobs < 1:
            raise Error("jobs must be positive")
        self.flags = cpu_flags(cpu)
        if self.builder_root:
            state = Database(self.builder_root).query()
            if state["cpu"] != cpu or state["rebuild"] or Database(self.builder_root).verify(strict=True):
                raise Error("builder profile mismatch, pending ABI rebuilds or modified builder files")
            self.builder_identity = identity(state)
        else:
            # Host tools are explicitly a development seed, never release provenance.
            self.builder_identity = identity({"host": os.uname().release,
                "tools": {t: digest(Path(shutil.which(t))) for t in ("bash", "gcc", "ld", "make") if shutil.which(t)}})
        self.output.mkdir(parents=True, exist_ok=True)

    def build(self, names):
        artifacts = {}
        for recipe in self.repo.plan(names):
            artifacts[recipe.name] = self.one(recipe, artifacts)
        return artifacts

    def one(self, recipe, artifacts):
        dependency_order = [r.name for r in self.repo.plan(recipe.dependencies)]
        dependencies = {n: digest(artifacts[n]) for n in dependency_order}
        inputs = {"recipe": recipe.fingerprint, "recipe_metadata": recipe.meta, "cpu": self.cpu, "flags": self.flags,
                  "ldflags": "-Wl,-z,relro,-z,now", "builder": self.builder_identity,
                  "dependencies": dependencies, "jobs": self.jobs, "epoch": 0,
                  "development_only": self.host_tools,
                  "engine": {p.name: digest(p) for p in sorted(ENGINE.glob("*.py"))}}
        build_id = identity(inputs)
        output = self.output / f"{recipe.name}-{recipe.meta['version']}-{build_id}.pkg.tar.xz"
        with (self.output / (build_id + ".lock")).open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if output.exists():
                receipt = output.with_suffix(output.suffix + ".sha256.json")
                if not receipt.exists():
                    raise Error(f"cached package has no checksum receipt: {output}")
                with Package(output, json.loads(receipt.read_text())["sha256"]) as package:
                    if package.meta.get("build_id") != build_id:
                        raise Error("cached build identity mismatch")
                return output
            sources = [fetch(s, self.cache / "sources", self.offline) for s in recipe.meta.get("sources", [])]
            with tempfile.TemporaryDirectory(prefix="vfos-build-") as td:
                work = Path(td)
                for d in ("source", "stage", "recipe", "home", "root"):
                    (work / d).mkdir()
                shutil.copytree(recipe.path.parent, work / "recipe", dirs_exist_ok=True)
                for destination, source in recipe.local_files.items():
                    target = work / "recipe" / destination
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, target)
                for source in sources:
                    unpack(source, work / "source")
                roots = list((work / "source").iterdir())
                srcdir = f"/build/source/{roots[0].name}" if len(roots) == 1 and roots[0].is_dir() else "/build/source"
                env = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "HOME": "/build/home", "LC_ALL": "C",
                       "SOURCE_DATE_EPOCH": "0", "TZ": "UTC", "CPU": self.cpu, "CFLAGS": self.flags,
                       "CXXFLAGS": self.flags, "LDFLAGS": inputs["ldflags"], "JOBS": str(self.jobs),
                       "SRCDIR": srcdir, "DESTDIR": "/build/stage", "RECIPE_DIR": "/build/recipe"}
                command = ["bwrap", "--unshare-all", "--die-with-parent", "--new-session"]
                if self.host_tools:
                    if dependencies:
                        raise Error("--host-tools is limited to dependency-free development recipes")
                    command += ["--tmpfs", "/"]
                    for p in ("/usr", "/bin", "/sbin", "/lib", "/lib64"):
                        if Path(p).exists():
                            command += ["--ro-bind", p, p]
                    command += ["--dir", "/etc"]
                    if Path("/etc/ld.so.cache").is_file():
                        command += ["--ro-bind", "/etc/ld.so.cache", "/etc/ld.so.cache"]
                else:
                    # Copy the declared builder closure, then install exact dependency artifacts.
                    shutil.copytree(self.builder_root, work / "root", symlinks=True, dirs_exist_ok=True)
                    db = Database(work / "root")
                    for dep in dependency_order:
                        with Package(artifacts[dep], dependencies[dep]) as package:
                            if package.meta.get("development_only"):
                                raise Error("development artifact in release dependency closure")
                            db.install(package, upgrade=True)
                    command += ["--ro-bind", str(work / "root"), "/"]
                command += ["--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp",
                            "--bind", str(work), "/build",
                            "--ro-bind", str(work / "recipe"), "/build/recipe",
                            "--tmpfs", "/build/root", "--chdir", srcdir, "--clearenv"]
                for key, value in env.items():
                    command += ["--setenv", key, value]
                phases = 'set -euo pipefail; umask 022; source /build/recipe/recipe.sh; prepare; build; check; stage'
                log = self.output / f"{build_id}.log"
                with log.open("w") as f:
                    result = subprocess.run(command + ["/bin/bash", "-c", phases], stdout=f, stderr=subprocess.STDOUT)
                if result.returncode:
                    raise Error(f"{recipe.name} build failed ({result.returncode}); see {log}")
                metadata = {"name": recipe.name, "version": recipe.meta["version"], "abi": recipe.meta["abi"],
                            "cpu": self.cpu, "build_id": build_id, "inputs": inputs,
                            "development_only": self.host_tools,
                            "dependencies": {n: self.repo.get(n).meta["abi"] for n in recipe.meta.get("depends", [])}}
                pack(work / "stage", metadata, output)
            atomic_json(self.output / f"{build_id}.inputs.json", inputs)
        return output
